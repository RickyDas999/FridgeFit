"""AI meal planning: the bounded Claude loop and the deterministic fallback (Milestone 7).

Claude inspects FridgeFit through the read-only planning tools and proposes a plan by calling
``submit_plan``. The loop is explicit Python control flow with hard limits on model calls, tokens,
and time, and it never raises for model or provider problems: every attempt ends with a recorded
outcome and its usage. Every proposal is validated deterministically. ``plan_day`` returns the
AI's plan only when it passed; otherwise it returns the deterministic baseline plan. Nothing here
writes product state.
"""

import os
import threading
import time
from datetime import date
from typing import Callable, NamedTuple

import anthropic
from pydantic import Field, StrictInt, ValidationError

from app.application.planning_tools import (
    PlanningSnapshot,
    ToolError,
    ToolModel,
    ToolResult,
    invalid_input_result,
    proposal_problems,
    replay_proposal,
    run_tool,
    tool_definitions,
)
from app.domain.meal_planning import MealPlan, plan_meals

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
    # Rejected plans Claude may fix in the same conversation before the attempt fails.
    max_corrections: int = 1


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
    rejected_plans: int
    model_seconds: float
    total_seconds: float


class AIPlanAttempt(NamedTuple):
    """How a planning attempt ended, the proposal if there is one, and its usage.

    ``outcome`` is one of: ``submitted`` (a plan that passed deterministic validation),
    ``invalid_plan`` (still invalid after the allowed corrections), ``refusal``, ``truncated``
    (a reply hit ``max_tokens``), ``no_plan`` (Claude stopped without submitting),
    ``step_limit``, ``time_limit``, or ``provider_error``. ``recipe_ids`` holds the last proposal.
    """

    outcome: str
    recipe_ids: list[int] | None
    explanation: str | None
    detail: str | None
    usage: AttemptUsage


class PlanningResult(NamedTuple):
    """The plan to show, where it came from, and how the AI attempt went.

    ``plan`` is always computed by FridgeFit: the AI's recipes replayed through the deterministic
    simulation when ``source`` is ``ai``, otherwise the deterministic baseline plan.
    """

    plan: MealPlan
    source: str
    # The AI's own words about its plan; model-written, never parsed for numbers.
    explanation: str | None
    fallback_reason: str | None
    attempt: AIPlanAttempt | None


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


class DailyLimit:
    """Counts AI planning attempts per server-local calendar day and refuses past a cap.

    The count lives in memory: it resets at midnight and whenever the server restarts.
    """

    # ponytail: per-process count; with several workers or instances each gets its own cap, so a
    # shared store (e.g. a database row) would be needed before scaling out.

    def __init__(self, limit: int | None):
        """Start with nothing counted.

        Args:
            limit: Attempts allowed per day, or None for no limit.
        """
        self.limit = limit
        self.day: date | None = None
        self.count = 0
        # Sync routes run in FastAPI's thread pool, so two requests can check the count at once.
        self.lock = threading.Lock()

    def try_take(self, today: date) -> bool:
        """Count one attempt for today if the cap allows it.

        Args:
            today: The server's current calendar day.

        Returns:
            True if the attempt may run (and was counted), False if today's cap is reached.
        """
        if self.limit is None:
            return True
        with self.lock:
            if today != self.day:
                self.day, self.count = today, 0
            if self.count >= self.limit:
                return False
            self.count += 1
            return True


def daily_limit_from_env() -> DailyLimit:
    """Read ``PLANNER_DAILY_LIMIT``, the most AI planning attempts allowed per day.

    Returns:
        The DailyLimit; unset or empty means no limit, and 0 turns AI planning off.

    Raises:
        ValueError: If the value is not a whole number of zero or more.
    """
    raw = (os.environ.get("PLANNER_DAILY_LIMIT") or "").strip()
    if not raw:
        return DailyLimit(None)
    if not raw.isdigit():
        raise ValueError(f"PLANNER_DAILY_LIMIT must be a whole number >= 0, got {raw!r}")
    return DailyLimit(int(raw))


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

    Each submitted plan is checked with ``proposal_problems``. A rejected plan's tool result
    lists every problem and Claude may resubmit, up to ``max_corrections`` times, within the same
    call and time limits; another rejection ends the attempt as ``invalid_plan``.

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
             "calls": 0, "tools": 0, "invalid": 0, "rejected": 0, "model_seconds": 0.0}

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
            rejected_plans=tally["rejected"],
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
        accepted = None
        for block in tool_uses:
            if block.name == "submit_plan":
                try:
                    proposal = SubmitPlanInput.model_validate(block.input)
                except ValidationError as exc:
                    tally["invalid"] += 1
                    content, is_error = invalid_input_result("submit_plan", exc)
                else:
                    problems = proposal_problems(snapshot, proposal.recipe_ids)
                    if not problems:
                        accepted = proposal
                        content, is_error = '{"status": "accepted"}', False
                    elif tally["rejected"] < config.max_corrections:
                        tally["rejected"] += 1
                        content, is_error = _rejection(problems)
                    else:
                        tally["rejected"] += 1
                        return finish(
                            "invalid_plan", "; ".join(problems),
                            recipe_ids=proposal.recipe_ids, explanation=proposal.explanation,
                        )
            else:
                tally["tools"] += 1
                result = run_tool(snapshot, block.name, block.input)
                tally["invalid"] += result.is_error
                content, is_error = result.content, result.is_error
            results.append({
                "type": "tool_result", "tool_use_id": block.id,
                "content": content, "is_error": is_error,
            })
        if accepted is not None:
            return finish(
                "submitted", recipe_ids=accepted.recipe_ids, explanation=accepted.explanation
            )
        messages.append({"role": "user", "content": results})

    return finish("step_limit", f"no plan after {config.max_model_calls} model calls")


def plan_day(
    snapshot: PlanningSnapshot,
    config: PlannerConfig | None,
    client,
    clock: Callable[[], float] = time.monotonic,
) -> PlanningResult:
    """Plan the rest of the day with Claude when possible, and the deterministic baseline if not.

    The AI's plan is used only when its attempt ends ``submitted`` and replaying it still passes
    validation; any other outcome, or AI planning being off, returns the baseline plan with the
    reason. Unexpected errors in FridgeFit's own code are not caught.

    Args:
        snapshot: The planning request's data.
        config: The planner configuration, or None when ``PLANNER_MODEL`` is not set.
        client: An Anthropic client, or None when no API key is configured.
        clock: Seconds from a monotonic clock; injectable for tests.

    Returns:
        The PlanningResult.
    """
    if config is None:
        return baseline_result(snapshot, "AI planning is off: PLANNER_MODEL is not set", None)
    if client is None:
        return baseline_result(snapshot, "AI planning is off: ANTHROPIC_API_KEY is not set", None)
    attempt = run_ai_planner(snapshot, config, client, clock)
    if attempt.outcome != "submitted":
        return baseline_result(snapshot, f"{attempt.outcome}: {attempt.detail}", attempt)
    # The loop already validated this plan; replaying it again yields the numbers to return and
    # guarantees nothing unvalidated is ever shown as valid.
    replayed = replay_proposal(snapshot, attempt.recipe_ids)
    if replayed.problems:
        return baseline_result(snapshot, "invalid_plan: " + "; ".join(replayed.problems), attempt)
    return PlanningResult(replayed.plan, "ai", attempt.explanation, None, attempt)


def baseline_result(
    snapshot: PlanningSnapshot, reason: str, attempt: AIPlanAttempt | None
) -> PlanningResult:
    """Return the deterministic greedy plan, with why the AI plan is not used.

    Args:
        snapshot: The planning request's data.
        reason: Why the AI plan is not used.
        attempt: The AI attempt, if one ran.

    Returns:
        The PlanningResult with the baseline plan.
    """
    request = snapshot.request
    plan = plan_meals(
        list(snapshot.recipes_by_id.values()),
        snapshot.batches,
        request.as_of,
        snapshot.remaining,
        snapshot.rating_summaries,
        request.meal_count,
        request.max_prep_minutes,
        request.servings_per_meal,
    )
    return PlanningResult(plan, "baseline", None, reason, attempt)


def _rejection(problems: list[str]) -> ToolResult:
    """Tell Claude why its plan was rejected, so it can fix it once.

    Args:
        problems: Every reason the plan is invalid.

    Returns:
        An error ToolResult listing the problems.
    """
    listed = "; ".join(problems)
    message = (
        f"Plan rejected by FridgeFit's checks: {listed}. Fix these and call submit_plan again."
    )
    return ToolResult(ToolError(error=message).model_dump_json(), is_error=True)


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

