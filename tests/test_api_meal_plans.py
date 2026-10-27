import logging

import anthropic
import pytest

from app.api.main import create_app
from app.application.ai_planner import DailyLimit, PlannerConfig
from tests.test_ai_planner import REQUEST, FakeClient, reply, tool_use
from tests.test_api_recommendations import add_batch, add_ingredient, add_recipe

AS_OF = "2026-10-11"
CONFIG = PlannerConfig(model="claude-haiku-5-5")


@pytest.fixture
def kitchen(client):
    """Stock rice (short of one recipe's need) and beans, with one recipe for each.

    Args:
        client: The TestClient.

    Returns:
        ``{"rice_bowl": id, "beans": id, "rice": ingredient id}``.
    """
    rice = add_ingredient(client, "Rice")
    beans = add_ingredient(client, "Beans")
    add_batch(client, rice, 150)
    add_batch(client, beans, 100, use_by_date="2026-10-12")
    return {
        "rice_bowl": add_recipe(client, "Rice bowl", (rice, 200, "primary")),
        "beans": add_recipe(client, "Beans", (beans, 100, "primary")),
        "rice": rice,
    }


def use_planner(app, *script, limit=None):
    """Turn AI planning on for the app with a scripted fake client; no real API calls.

    Args:
        app: The FastAPI application.
        *script: The fake client's responses or errors.
        limit: AI attempts allowed per day, or None for no limit.

    Returns:
        The FakeClient.
    """
    fake = FakeClient(*script)
    app.state.planner_config = CONFIG
    app.state.planner_client = fake
    app.state.planner_limit = DailyLimit(limit)
    return fake


def submit(recipe_ids):
    """Build a model reply that submits a plan.

    Args:
        recipe_ids: The proposed recipe ids.

    Returns:
        The stand-in Message.
    """
    proposal = {"recipe_ids": recipe_ids, "explanation": "Beans first."}
    return reply(tool_use("submit_plan", proposal))


def plan(client, **body):
    """POST a one-meal plan request for AS_OF.

    Args:
        client: The TestClient.
        **body: Fields to add or override.

    Returns:
        The response.
    """
    return client.post("/meal-plans", json={"meal_count": 1, "as_of": AS_OF, **body})


def test_without_ai_the_baseline_plan_is_returned_with_simulated_details(app, client, kitchen):
    """With AI planning off, the baseline plan comes back with its meals' simulated details."""
    app.state.planner_config = None
    response = plan(client, meal_count=2)
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "baseline"
    assert body["explanation"] is None
    assert body["fallback_reason"] == "ai_disabled"
    rice_bowl = next(m for m in body["meals"] if m["recipe_id"] == kitchen["rice_bowl"])
    assert rice_bowl["name"] == "Rice bowl"
    assert rice_bowl["servings"] == 1
    assert rice_bowl["ingredients_used"] == [{
        "ingredient_id": kitchen["rice"], "name": "Rice", "unit": "gram", "quantity": 150,
    }]
    assert rice_bowl["shortages"] == [{
        "ingredient_id": kitchen["rice"], "name": "Rice", "unit": "gram",
        "needed": 200, "available": 150,
    }]
    assert rice_bowl["macros"]["calories"] == pytest.approx(150)
    assert body["remaining_at_end"] is None


def test_a_valid_ai_plan_is_returned_with_its_explanation(app, client, kitchen, caplog):
    """A plan passing FridgeFit's checks is returned as the AI's; usage goes only to the log."""
    app.state.planner_config = None
    baseline_id = plan(client).json()["meals"][0]["recipe_id"]
    ai_id = next(i for i in (kitchen["rice_bowl"], kitchen["beans"]) if i != baseline_id)
    fake = use_planner(app, submit([ai_id]))

    with caplog.at_level(logging.INFO, logger="app.api.meal_plans"):
        body = plan(client, preference="Something light").json()

    assert body["source"] == "ai"
    assert body["explanation"] == "Beans first."
    assert body["fallback_reason"] is None
    assert [m["recipe_id"] for m in body["meals"]] == [ai_id]
    assert "Something light" in fake.requests[0]["messages"][0]["content"]
    assert "input_tokens=100" in caplog.text
    assert "est_cost_usd=" in caplog.text
    assert "tokens" not in str(body)


def test_a_provider_failure_returns_the_baseline_without_the_error_text(
    app, client, kitchen, caplog
):
    """A provider error falls back with ai_failed; its message goes only to the server log."""
    error = anthropic.APIConnectionError(message="secret upstream detail", request=REQUEST)
    use_planner(app, error)

    with caplog.at_level(logging.INFO, logger="app.api.meal_plans"):
        response = plan(client)

    assert response.status_code == 200
    assert response.json()["source"] == "baseline"
    assert response.json()["fallback_reason"] == "ai_failed"
    assert "secret upstream detail" not in response.text
    assert "secret upstream detail" in caplog.text


def test_a_plan_still_invalid_after_the_correction_returns_ai_plan_invalid(app, client, kitchen):
    """Two invalid submissions fall back to the baseline with ai_plan_invalid."""
    # Two meals requested while both recipes are eligible, so one meal is too few.
    use_planner(app, submit([kitchen["beans"]]), submit([kitchen["beans"]]))

    body = plan(client, meal_count=2).json()

    assert body["source"] == "baseline"
    assert body["fallback_reason"] == "ai_plan_invalid"
    assert len(body["meals"]) == 2


def test_past_the_daily_limit_the_baseline_is_returned_without_calling_claude(
    app, client, kitchen
):
    """Once today's AI attempts reach the cap, requests get the baseline with ai_limit."""
    fake = use_planner(app, submit([kitchen["beans"]]), limit=1)

    first = plan(client).json()
    # A different as_of does not reset the cap: the count is per server day.
    second = plan(client, as_of="2026-10-12").json()

    assert first["source"] == "ai"
    assert second["source"] == "baseline"
    assert second["fallback_reason"] == "ai_limit"
    assert len(second["meals"]) == 1
    assert len(fake.requests) == 1


def test_requests_without_ai_do_not_use_up_the_daily_limit(app, client, kitchen):
    """With AI planning off, requests are not counted against the cap."""
    use_planner(app, submit([kitchen["beans"]]), limit=1)
    app.state.planner_config = None
    assert plan(client).json()["fallback_reason"] == "ai_disabled"

    app.state.planner_config = CONFIG
    assert plan(client).json()["source"] == "ai"


def test_the_baseline_can_be_requested_without_calling_claude(app, client, kitchen):
    """planner=baseline returns the deterministic plan with no fallback reason and no AI call."""
    app.state.planner_config = None
    expected = plan(client).json()["meals"]
    fake = use_planner(app, submit([kitchen["beans"]]))

    body = plan(client, planner="baseline").json()

    assert body["source"] == "baseline"
    assert body["fallback_reason"] is None
    assert body["explanation"] is None
    assert body["meals"] == expected
    assert fake.requests == []


def test_requesting_the_baseline_does_not_use_up_the_daily_limit(app, client, kitchen):
    """Baseline requests are not counted against the AI cap."""
    use_planner(app, submit([kitchen["beans"]]), limit=1)
    plan(client, planner="baseline")
    assert plan(client).json()["source"] == "ai"


@pytest.mark.parametrize("body", [
    {"meal_count": 0},
    {"meal_count": 6},
    {"meal_count": 1, "max_prep_minutes": 241},
    {"meal_count": 1, "servings_per_meal": 0},
    {"meal_count": 1, "preference": "x" * 301},
    {"meal_count": 1, "budget": 5},
    {"meal_count": 1, "planner": "claude"},
    {},
])
def test_invalid_requests_are_rejected(app, client, body):
    """Out-of-range, unknown, or missing fields are a 422, before any planning."""
    fake = use_planner(app)
    response = client.post("/meal-plans", json=body)
    assert response.status_code == 422
    assert fake.requests == []


def test_the_planner_is_configured_from_the_environment(monkeypatch, empty_database_url):
    """create_app reads the model and key once; without a key there is no client."""
    monkeypatch.setenv("PLANNER_MODEL", "claude-haiku-5-5")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PLANNER_DAILY_LIMIT", "50")
    app = create_app(empty_database_url)
    assert app.state.planner_config.model == "claude-haiku-5-5"
    assert app.state.planner_client is None
    assert app.state.planner_limit.limit == 50
