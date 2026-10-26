"""The bounded Claude planning loop (Milestone 7 Slice 4).

Claude inspects FridgeFit through the read-only planning tools and proposes a plan by calling
``submit_plan``. The loop is explicit Python control flow with hard limits on model calls, tokens,
and time, and it never raises for model or provider problems: every attempt ends with a recorded
outcome and its usage. Nothing here validates the proposal or writes product state; validation
and the deterministic fallback are Slice 5.
"""

import os
import time
from typing import Callable, NamedTuple

import anthropic
from pydantic import Field, StrictInt, ValidationError

from app.application.planning_tools import (
    PlanningSnapshot,
    ToolModel,
    invalid_input_result,
    run_tool,
    tool_definitions,
)

PROVIDER = "anthropic"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

SYSTEM_PROMPT = """\
You plan the rest of a user's day of meals in FridgeFit, a kitchen and nutrition tracker.

Use the tools to look at the request, today's remaining calories and macros, what is in stock and
when it must be used, and the ranked recipes. Choose only recipes the tools show you, in the order
they would be eaten, one per meal, and no more meals than requested. Prefer food that is due
soon, keep the day close to its calorie and macro goal, respect the prep-time limit, and follow
the user's preference where you can. Check a candidate plan with simulate_plan before proposing
it.

When you are done, call submit_plan once with the recipe ids and a short explanation of the
tradeoffs, in two or three sentences addressed to the user. Every number you see comes from
FridgeFit; do not invent recipes, quantities, or nutrition values.
"""


class PlannerConfig(NamedTuple):
    """Which model to use and the loop's hard limits."""

    model: str
    effort: str = "low"
    max_model_calls: int = 6
    max_tokens: int = 4096
    time_budget_seconds: float = 60.0


class AttemptUsage(NamedTuple):
    """What one planning attempt cost and how it ran; raw token counts are authoritative."""

    provider: str
    model: str
    effort: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    model_calls: int
    tool_calls: int
    invalid_tool_calls: int
    model_seconds: float
    total_seconds: float


class AIPlanAttempt(NamedTuple):
    """How a planning attempt ended, the proposal if there is one, and its usage.

    ``outcome`` is one of: ``submitted`` (a proposal arrived), ``refusal``, ``truncated`` (a
    reply hit ``max_tokens``), ``no_plan`` (Claude stopped without submitting), ``step_limit``,
    ``time_limit``, or ``provider_error``. The proposal is not validated here.
    """

    outcome: str
    recipe_ids: list[int] | None
    explanation: str | None
    detail: str | None
    usage: AttemptUsage


class SubmitPlanInput(ToolModel):
    """Input for submit_plan: the proposed plan."""

    recipe_ids: list[StrictInt] = Field(
        min_length=1, description="Recipe ids in the order they would be eaten, one per meal."
    )
    explanation: str = Field(
        min_length=1,
        max_length=800,
        description="Two or three sentences for the user on why this plan and its tradeoffs.",
    )


SUBMIT_PLAN_TOOL = {
    "name": "submit_plan",
    "description": "Propose the final plan: recipe ids in eating order and a short explanation. "
    "Call this once, when you are done.",
    "input_schema": SubmitPlanInput.model_json_schema(),
}


def planner_config_from_env() -> PlannerConfig | None:
    """Read the planner's configuration from the environment.

    ``PLANNER_MODEL`` chooses the model and has no default: without it, AI planning is off.
    ``PLANNER_EFFORT`` defaults to ``low``.

    Returns:
        The configuration, or None when ``PLANNER_MODEL`` is unset or empty.

    Raises:
        ValueError: If ``PLANNER_EFFORT`` is not a known effort level.
    """
    model = (os.environ.get("PLANNER_MODEL") or "").strip()
    if not model:
        return None
    effort = (os.environ.get("PLANNER_EFFORT") or "low").strip()
    if effort not in EFFORT_LEVELS:
        allowed = ", ".join(EFFORT_LEVELS)
        raise ValueError(f"PLANNER_EFFORT must be one of {allowed}, got {effort!r}")
    return PlannerConfig(model=model, effort=effort)


def make_client() -> anthropic.Anthropic | None:
    """Create the Anthropic client from the server's ``ANTHROPIC_API_KEY``.

    Retries are off: the loop's time budget bounds every attempt, and a failed call falls back to
    the deterministic plan instead of waiting.

    Returns:
        The client, or None when no API key is configured.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return anthropic.Anthropic(max_retries=0)


def run_ai_planner(
    snapshot: PlanningSnapshot,
    config: PlannerConfig,
    client,
    clock: Callable[[], float] = time.monotonic,
) -> AIPlanAttempt:
    """Let Claude inspect the snapshot through the tools and propose a plan, within hard limits.

    Args:
        snapshot: The planning request's data; the tools read only this.
        config: The model and the loop's limits.
        client: An Anthropic client (or a stand-in with the same ``messages.create``).
        clock: Seconds from a monotonic clock; injectable for tests.

    Returns:
        The attempt: its outcome, the proposal if one was submitted, and its usage.
    """
    started = clock()
    deadline = started + config.time_budget_seconds
    tools = [{**t, "strict": True} for t in [*tool_definitions(), SUBMIT_PLAN_TOOL]]
    messages = [{"role": "user", "content": _request_text(snapshot)}]
    tally = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
             "calls": 0, "tools": 0, "invalid": 0, "model_seconds": 0.0}

    def finish(outcome, detail=None, recipe_ids=None, explanation=None):
        """Close the attempt with its outcome and the usage so far.

        Args:
            outcome: How the attempt ended.
            detail: A short reason for an unsuccessful outcome.
            recipe_ids: The proposed recipe ids, when submitted.
            explanation: Claude's explanation, when submitted.

        Returns:
            The AIPlanAttempt.
        """
        usage = AttemptUsage(
            provider=PROVIDER, model=config.model, effort=config.effort,
            input_tokens=tally["input"], output_tokens=tally["output"],
            cache_read_input_tokens=tally["cache_read"],
            cache_creation_input_tokens=tally["cache_creation"],
            model_calls=tally["calls"], tool_calls=tally["tools"],
            invalid_tool_calls=tally["invalid"],
            model_seconds=round(tally["model_seconds"], 3),
            total_seconds=round(clock() - started, 3),
        )
        return AIPlanAttempt(outcome, recipe_ids, explanation, detail, usage)

    for _ in range(config.max_model_calls):
        time_left = deadline - clock()
        if time_left <= 0:
            return finish("time_limit", f"over the {config.time_budget_seconds:g} s budget")
        call_started = clock()
        try:
            response = client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": config.effort},
                timeout=time_left,
            )
        except anthropic.APITimeoutError:
            tally["model_seconds"] += clock() - call_started
            return finish("time_limit", "the model call timed out")
        except anthropic.APIError as exc:
            tally["model_seconds"] += clock() - call_started
            return finish("provider_error", f"{type(exc).__name__}: {exc}")
        tally["model_seconds"] += clock() - call_started
        tally["calls"] += 1
        _add_usage(tally, response.usage)

        if response.stop_reason == "refusal":
            return finish("refusal", "the model declined the request")
        if response.stop_reason == "max_tokens":
            return finish("truncated", f"a reply reached max_tokens ({config.max_tokens})")
        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if not tool_uses:
            return finish("no_plan", "the model stopped without calling submit_plan")

        # Append the reply unchanged (thinking blocks included) before the tool results.
        messages.append({"role": "assistant", "content": response.content})
        results = []
        submitted = None
        for block in tool_uses:
            if block.name == "submit_plan":
                try:
                    submitted = SubmitPlanInput.model_validate(block.input)
                    content, is_error = '{"status": "received"}', False
                except ValidationError as exc:
                    tally["invalid"] += 1
                    content, is_error = invalid_input_result("submit_plan", exc)
            else:
                tally["tools"] += 1
                result = run_tool(snapshot, block.name, block.input)
                tally["invalid"] += result.is_error
                content, is_error = result.content, result.is_error
            results.append({
                "type": "tool_result", "tool_use_id": block.id,
                "content": content, "is_error": is_error,
            })
        if submitted is not None:
            return finish(
                "submitted", recipe_ids=submitted.recipe_ids, explanation=submitted.explanation
            )
        messages.append({"role": "user", "content": results})

    return finish("step_limit", f"no plan after {config.max_model_calls} model calls")


def _request_text(snapshot: PlanningSnapshot) -> str:
    """Describe the planning request to the model; the tools hold all the data.

    Args:
        snapshot: The planning request's data.

    Returns:
        The user message.
    """
    request = snapshot.request
    limit = (
        "no prep-time limit" if request.max_prep_minutes is None
        else f"at most {request.max_prep_minutes} minutes of prep each"
    )
    text = (
        f"Plan {request.meal_count} more meal(s) for {request.as_of.isoformat()}, "
        f"{request.servings_per_meal:g} serving(s) each, {limit}."
    )
    if request.preference:
        text += f"\n\nThe user's preference, in their words:\n{request.preference}"
    return text


def _add_usage(tally: dict, usage) -> None:
    """Add one response's token usage to the running totals.

    Args:
        tally: The running totals.
        usage: The response's ``usage``.
    """
    tally["input"] += usage.input_tokens
    tally["output"] += usage.output_tokens
    tally["cache_read"] += usage.cache_read_input_tokens or 0
    tally["cache_creation"] += usage.cache_creation_input_tokens or 0

