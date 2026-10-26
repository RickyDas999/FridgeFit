from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from app.application import planning_tools
from app.application.planning_tools import (
    PlanningRequest,
    PlanningSnapshot,
    load_planning_snapshot,
    run_tool,
    tool_definitions,
    tool_result_json,
)
from app.domain.meal_planning import simulate_meal
from app.errors import InvalidInputError
from app.evaluation.scenarios import SCENARIO_DATE, build_scenarios
from app.persistence.enums import CanonicalUnit, IngredientRole
from app.persistence.models import Ingredient, InventoryBatch, MealLog, Recipe, RecipeIngredient

SALMON_PLATE, OMELETTE, BOWL = 4, 2, 1


def snapshot_for(scenario_id, **request_overrides):
    """Build a tool snapshot from one evaluation scenario (in memory, no database).

    Args:
        scenario_id: Which scenario.
        **request_overrides: PlanningRequest fields to replace.

    Returns:
        The PlanningSnapshot.
    """
    scenario = next(s for s in build_scenarios() if s.id == scenario_id)
    request = PlanningRequest(
        as_of=SCENARIO_DATE,
        meal_count=scenario.meal_count,
        max_prep_minutes=scenario.max_prep_minutes,
        servings_per_meal=scenario.servings_per_meal,
        preference=scenario.preference,
    )._replace(**request_overrides)
    return PlanningSnapshot(
        request=request,
        recipes_by_id={recipe.id: recipe for recipe in scenario.recipes},
        batches=scenario.batches,
        remaining=scenario.remaining,
        rating_summaries=scenario.rating_summaries,
    )


def call(snapshot, name, tool_input):
    """Run a tool that must succeed and return its decoded JSON.

    Args:
        snapshot: The snapshot.
        name: Tool name.
        tool_input: The model's input.

    Returns:
        The decoded result.
    """
    result = run_tool(snapshot, name, tool_input)
    assert not result.is_error, result.content
    return tool_result_json(result)


def test_tool_definitions_match_the_input_models():
    """Three tools, each schema closed to unknown fields, with required inputs declared."""
    definitions = {d["name"]: d for d in tool_definitions()}

    assert set(definitions) == {"get_planning_context", "get_recipe", "simulate_plan"}
    for definition in definitions.values():
        assert definition["description"]
        assert definition["input_schema"]["additionalProperties"] is False
    assert definitions["get_recipe"]["input_schema"]["required"] == ["recipe_id"]
    assert definitions["simulate_plan"]["input_schema"]["required"] == ["recipe_ids"]


def test_planning_context_describes_the_request_stock_and_ranked_candidates():
    """Remaining macros, stock due soon per ingredient, and candidates best first."""
    context = call(snapshot_for("expiring-today"), "get_planning_context", {})

    assert (context["date"], context["meal_count"]) == ("2026-03-10", 2)
    assert context["remaining_macros"]["calories"] == 2200
    spinach = next(item for item in context["stock"] if item["ingredient"] == "Spinach")
    assert spinach == {
        "ingredient_id": 5, "ingredient": "Spinach", "unit": "gram", "on_hand": 300,
        "earliest_use_by": "2026-03-10", "due_soon": 300,
    }
    scores = [c["score"] for c in context["candidates"]]
    assert scores == sorted(scores, reverse=True)
    assert context["candidates"][0]["name"] == "Spinach omelette"


def test_candidates_respect_the_prep_limit():
    """Recipes over the request's prep limit are not offered as candidates."""
    context = call(snapshot_for("tight-prep-limit"), "get_planning_context", {})

    assert context["candidates"]
    assert all(c["prep_minutes"] <= 10 for c in context["candidates"])


def test_candidates_are_capped(monkeypatch):
    """No more than MAX_CANDIDATES go to the model; the total eligible is still reported."""
    monkeypatch.setattr(planning_tools, "MAX_CANDIDATES", 2)

    context = call(snapshot_for("well-stocked"), "get_planning_context", {})

    assert len(context["candidates"]) == 2
    assert context["eligible_recipes"] == 6


def test_recipe_details_show_lines_against_stock():
    """A recipe's lines are per serving, next to what is on hand."""
    details = call(snapshot_for("short-inventory"), "get_recipe", {"recipe_id": SALMON_PLATE})

    salmon = next(line for line in details["ingredients"] if line["ingredient"] == "Salmon")
    assert salmon == {
        "ingredient": "Salmon", "unit": "gram", "role": "primary", "per_serving": 150,
        "on_hand": 0,
    }
    assert details["within_prep_limit"] is True


def test_simulation_matches_the_domain_simulation_meal_by_meal():
    """simulate_plan reports what simulate_meal computes, chaining stock between meals."""
    snapshot = snapshot_for("expiring-today")

    result = call(snapshot, "simulate_plan", {"recipe_ids": [SALMON_PLATE, OMELETTE]})

    first = simulate_meal(snapshot.recipes_by_id[SALMON_PLATE], snapshot.batches,
                          snapshot.remaining, 1)
    second = simulate_meal(snapshot.recipes_by_id[OMELETTE], first.batches_after,
                           first.remaining_after, 1)
    assert result["meals"][0]["macros"]["calories"] == round(first.macros.calories, 1)
    assert result["remaining_at_end"]["calories"] == round(second.remaining_after.calories, 1)
    assert (result["violations"], result["within_constraints"]) == ([], True)


def test_each_simulated_meal_sees_the_stock_the_previous_ones_left():
    """Two chicken bowls with 120 g of chicken: the first takes it all, the second finds none."""
    snapshot = snapshot_for("short-inventory", meal_count=2)

    first, second = call(snapshot, "simulate_plan", {"recipe_ids": [BOWL, BOWL]})["meals"]

    def chicken_shortage(meal):
        """Return the meal's chicken shortage, or None.

        Args:
            meal: A simulated meal.

        Returns:
            The shortage entry for chicken.
        """
        return next(s for s in meal["shortages"] if s["ingredient"] == "Chicken breast")

    assert chicken_shortage(first) == {
        "ingredient": "Chicken breast", "unit": "gram", "needed": 150, "available": 120,
    }
    assert chicken_shortage(second)["available"] == 0


def test_simulation_reports_hard_constraint_violations():
    """Too many meals, a repeat, and a slow recipe are reported, not refused."""
    snapshot = snapshot_for("tight-prep-limit", meal_count=2)

    result = call(snapshot, "simulate_plan", {"recipe_ids": [OMELETTE, OMELETTE, BOWL]})

    assert result["within_constraints"] is False
    assert result["violations"] == [
        "3 meals planned, 2 requested",
        "'Spinach omelette' is planned more than once",
        "'Chicken rice bowl' takes 25 min, over the 10-min limit",
    ]


def test_simulation_flags_a_recipe_the_recommender_would_exclude():
    """With no salmon and no rice, the salmon plate is simulated but carries a warning."""
    snapshot = snapshot_for("short-inventory")
    snapshot = snapshot._replace(batches=[b for b in snapshot.batches if b.ingredient_id != 2])

    meal = call(snapshot, "simulate_plan", {"recipe_ids": [SALMON_PLATE]})["meals"][0]

    assert meal["warning"] == "ineligible: 2 primary ingredients missing (Salmon, Cooked rice)"
    assert {s["ingredient"] for s in meal["shortages"]} == {"Salmon", "Cooked rice"}


@pytest.mark.parametrize(
    ("name", "tool_input", "message"),
    [
        ("get_recipe", {"recipe_id": "4"}, "recipe_id: Input should be a valid integer"),
        ("get_recipe", {"recipe_id": 4, "extra": 1}, "extra: Extra inputs are not permitted"),
        ("get_recipe", {}, "recipe_id: Field required"),
        ("simulate_plan", {"recipe_ids": []}, "recipe_ids: List should have at least 1 item"),
        ("simulate_plan", {"recipe_ids": [4, 99]}, "Unknown recipe id(s): 99"),
        ("get_recipe", {"recipe_id": 99}, "Unknown recipe id(s): 99"),
        ("delete_everything", {}, "Unknown tool 'delete_everything'"),
    ],
)
def test_bad_tool_calls_return_a_structured_error(name, tool_input, message):
    """Bad input never raises: the model gets an error result it can correct."""
    result = run_tool(snapshot_for("well-stocked"), name, tool_input)

    assert result.is_error is True
    assert message in tool_result_json(result)["error"]


def test_tools_never_change_the_snapshot():
    """Running every tool leaves the snapshot's stock exactly as it was."""
    snapshot = snapshot_for("expiring-today")
    before = list(snapshot.batches)

    call(snapshot, "get_planning_context", {})
    call(snapshot, "get_recipe", {"recipe_id": SALMON_PLATE})
    call(snapshot, "simulate_plan", {"recipe_ids": [SALMON_PLATE, OMELETTE]})

    assert snapshot.batches == before


def test_loading_a_snapshot_reads_the_database_and_writes_nothing(session):
    """The snapshot copies stock into plain values; the session stays clean."""
    chicken = Ingredient(
        name="Chicken", canonical_unit=CanonicalUnit.GRAM, nutrition_base_quantity=100,
        calories_per_base_unit=165, protein_per_base_unit=31, carbs_per_base_unit=0,
        fat_per_base_unit=3.6, nutrition_updated_at=datetime(2026, 1, 1),
    )
    batch = InventoryBatch(
        ingredient=chicken, quantity_initial=300, quantity_remaining=300,
        purchased_at=datetime(2026, 1, 1),
    )
    recipe = Recipe(
        name="Bowl", instructions=["Cook"], prep_minutes=10, servings=1,
        recipe_ingredients=[
            RecipeIngredient(ingredient=chicken, quantity=100, role=IngredientRole.PRIMARY)
        ],
    )
    session.add_all([batch, recipe])
    session.commit()

    snapshot = load_planning_snapshot(
        session, PlanningRequest(date(2026, 3, 10), 1, None, 1, None)
    )
    call(snapshot, "simulate_plan", {"recipe_ids": [recipe.id]})

    assert snapshot.batches[0].quantity_remaining == 300
    assert batch.quantity_remaining == 300
    assert not session.new and not session.dirty
    assert session.scalar(select(func.count()).select_from(MealLog)) == 0


def test_an_invalid_request_is_rejected_before_loading(session):
    """The request's numbers are checked with the same rules the planner uses."""
    with pytest.raises(InvalidInputError, match="meal_count"):
        load_planning_snapshot(session, PlanningRequest(date(2026, 3, 10), 0, None, 1, None))
