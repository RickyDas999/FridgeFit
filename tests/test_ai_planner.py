import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.application.ai_planner import (
    PlannerConfig,
    make_client,
    planner_config_from_env,
    run_ai_planner,
)
from app.application.planning_tools import PlanningRequest, PlanningSnapshot
from app.evaluation.scenarios import SCENARIO_DATE, build_scenarios

CONFIG = PlannerConfig(model="claude-test-model")
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def snapshot():
    """Build a snapshot from the expiring-today scenario, with a preference.

    Returns:
        The PlanningSnapshot.
    """
    s = next(s for s in build_scenarios() if s.id == "expiring-today")
    return PlanningSnapshot(
        request=PlanningRequest(SCENARIO_DATE, 2, 30, 1, "Something light, please."),
        recipes_by_id={recipe.id: recipe for recipe in s.recipes},
        batches=s.batches,
        remaining=s.remaining,
        rating_summaries=s.rating_summaries,
    )


def tool_use(name, tool_input, block_id=None):
    """Build a tool_use content block.

    Args:
        name: Tool name.
        tool_input: The tool's input.
        block_id: The block id; defaults to one derived from the name.

    Returns:
        A stand-in ToolUseBlock.
    """
    return SimpleNamespace(type="tool_use", id=block_id or f"toolu_{name}", name=name,
                           input=tool_input)


def reply(*content, stop_reason="tool_use", input_tokens=100, output_tokens=20):
    """Build a model response.

    Args:
        *content: Content blocks.
        stop_reason: Why the model stopped.
        input_tokens: Input tokens billed.
        output_tokens: Output tokens billed.

    Returns:
        A stand-in Message.
    """
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                            cache_read_input_tokens=0, cache_creation_input_tokens=None)
    return SimpleNamespace(content=list(content), stop_reason=stop_reason, usage=usage)


class FakeClient:
    """Returns scripted responses (or raises scripted errors) and records every request."""

    def __init__(self, *script):
        """Store the script.

        Args:
            *script: Responses or exceptions, one per expected model call.
        """
        self.script = list(script)
        self.requests = []
        self.messages = self

    def create(self, **request):
        """Record the request and play the next scripted step.

        Args:
            **request: The messages.create arguments.

        Returns:
            The next scripted response.

        Raises:
            Exception: The next scripted error, if it is one.
        """
        # Copy the history: the loop keeps appending to the same list after this call.
        self.requests.append({**request, "messages": list(request["messages"])})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


SUBMIT = tool_use("submit_plan", {"recipe_ids": [2, 4], "explanation": "Uses spinach first."})


def test_a_plan_is_submitted_after_inspecting_with_tools():
    """Claude inspects, simulates, submits; the attempt carries the proposal and the usage."""
    client = FakeClient(
        reply(tool_use("get_planning_context", {})),
        reply(tool_use("simulate_plan", {"recipe_ids": [2, 4]})),
        reply(SUBMIT, input_tokens=300, output_tokens=60),
    )

    attempt = run_ai_planner(snapshot(), CONFIG, client)

    assert attempt.outcome == "submitted"
    assert (attempt.recipe_ids, attempt.explanation) == ([2, 4], "Uses spinach first.")
    assert attempt.usage._replace(model_seconds=0, total_seconds=0)._asdict() == {
        "provider": "anthropic", "model": "claude-test-model", "effort": "low",
        "input_tokens": 500, "output_tokens": 100, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0, "model_calls": 3, "tool_calls": 2,
        "invalid_tool_calls": 0, "model_seconds": 0, "total_seconds": 0,
    }


def test_requests_use_the_configured_limits_and_strict_tools():
    """Model, max_tokens, effort, adaptive thinking, and strict tools including submit_plan."""
    client = FakeClient(reply(SUBMIT))

    run_ai_planner(snapshot(), CONFIG._replace(effort="medium"), client)

    [request] = client.requests
    assert (request["model"], request["max_tokens"]) == ("claude-test-model", 4096)
    assert request["output_config"] == {"effort": "medium"}
    assert request["thinking"] == {"type": "adaptive"}
    assert [t["name"] for t in request["tools"]] == [
        "get_planning_context", "get_recipe", "simulate_plan", "submit_plan",
    ]
    assert all(t["strict"] is True for t in request["tools"])
    first_message = request["messages"][0]["content"]
    assert "Plan 2 more meal(s) for 2026-03-10" in first_message
    assert "Something light, please." in first_message
    assert "temperature" not in request


def test_tool_results_follow_the_unchanged_reply_with_matching_ids():
    """The reply is appended as-is, then one user message holds every tool result by id."""
    thinking = SimpleNamespace(type="thinking", thinking="", signature="sig")
    calls = (tool_use("get_recipe", {"recipe_id": 4}, "toolu_a"),
             tool_use("get_recipe", {"recipe_id": 99}, "toolu_b"))
    client = FakeClient(reply(thinking, *calls), reply(SUBMIT))

    attempt = run_ai_planner(snapshot(), CONFIG, client)

    assistant, user = client.requests[1]["messages"][1:]
    assert assistant == {"role": "assistant", "content": [thinking, *calls]}
    assert [(r["tool_use_id"], r["is_error"]) for r in user["content"]] == [
        ("toolu_a", False), ("toolu_b", True),
    ]
    assert json.loads(user["content"][1]["content"])["error"].startswith("Unknown recipe id")
    assert (attempt.usage.tool_calls, attempt.usage.invalid_tool_calls) == (2, 1)


def test_an_invalid_submission_is_returned_to_the_model_to_fix():
    """A malformed submit_plan is an error result, not a plan; a valid one later ends the loop."""
    client = FakeClient(
        reply(tool_use("submit_plan", {"recipe_ids": [], "explanation": "x"})), reply(SUBMIT)
    )

    attempt = run_ai_planner(snapshot(), CONFIG, client)

    error = client.requests[1]["messages"][2]["content"][0]
    assert error["is_error"] is True
    assert "recipe_ids: List should have at least 1 item" in json.loads(error["content"])["error"]
    assert (attempt.outcome, attempt.usage.invalid_tool_calls) == ("submitted", 1)


def test_the_loop_stops_at_the_model_call_limit():
    """With no submission, the attempt ends after max_model_calls calls."""
    client = FakeClient(*[reply(tool_use("get_planning_context", {})) for _ in range(3)])

    attempt = run_ai_planner(snapshot(), CONFIG._replace(max_model_calls=3), client)

    assert attempt.outcome == "step_limit"
    assert attempt.usage.model_calls == 3
    assert client.script == []


@pytest.mark.parametrize(
    ("stop_reason", "content", "outcome"),
    [
        ("refusal", [], "refusal"),
        ("max_tokens", [tool_use("simulate_plan", {})], "truncated"),
        ("end_turn", [SimpleNamespace(type="text", text="Eat the omelette.")], "no_plan"),
    ],
)
def test_replies_that_cannot_continue_end_the_attempt(stop_reason, content, outcome):
    """A refusal, a truncated reply, or plain text without submit_plan ends with no plan."""
    client = FakeClient(reply(*content, stop_reason=stop_reason))

    attempt = run_ai_planner(snapshot(), CONFIG, client)

    assert (attempt.outcome, attempt.recipe_ids) == (outcome, None)


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (anthropic.APIConnectionError(request=REQUEST), "provider_error"),
        (anthropic.RateLimitError("Rate limited", response=httpx2.Response(429, request=REQUEST),
                                  body=None), "provider_error"),
        (anthropic.APITimeoutError(request=REQUEST), "time_limit"),
    ],
)
def test_provider_failures_end_the_attempt_without_raising(error, outcome):
    """Connection errors, rate limits, and timeouts are recorded outcomes, not exceptions."""
    attempt = run_ai_planner(snapshot(), CONFIG, FakeClient(error))

    assert attempt.outcome == outcome
    assert attempt.detail
    assert attempt.usage.model_calls == 0


def test_each_call_gets_only_the_time_left_and_the_budget_ends_the_loop():
    """The per-call timeout shrinks with the budget; once it is spent, no further call is made."""
    now = [0.0]

    def clock():
        """Advance 25 simulated seconds per reading after the first.

        Returns:
            The simulated time.
        """
        value = now[0]
        now[0] += 25.0
        return value

    client = FakeClient(*[reply(tool_use("get_planning_context", {})) for _ in range(2)])

    attempt = run_ai_planner(snapshot(), CONFIG, client, clock=clock)

    # Clock readings: start 0, first check 25 (35 s left), call 50-75, next check 100: over.
    assert attempt.outcome == "time_limit"
    assert [r["timeout"] for r in client.requests] == [35.0]
    assert attempt.usage.model_calls == 1


def test_without_a_model_configured_ai_planning_is_off(monkeypatch):
    """No PLANNER_MODEL means no configuration; effort defaults to low."""
    monkeypatch.delenv("PLANNER_MODEL", raising=False)
    assert planner_config_from_env() is None

    monkeypatch.setenv("PLANNER_MODEL", "claude-haiku-5-5")
    assert planner_config_from_env() == PlannerConfig(model="claude-haiku-5-5", effort="low")


def test_an_unknown_effort_level_is_rejected(monkeypatch):
    """PLANNER_EFFORT must be a real effort level."""
    monkeypatch.setenv("PLANNER_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("PLANNER_EFFORT", "extreme")

    with pytest.raises(ValueError, match="PLANNER_EFFORT"):
        planner_config_from_env()


def test_without_an_api_key_there_is_no_client(monkeypatch):
    """The key comes only from the server's environment; without it, no client is made."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert make_client() is None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = make_client()
    assert client is not None and client.max_retries == 0
