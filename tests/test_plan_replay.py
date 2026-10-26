import pytest

from app.domain.meal_planning import plan_meals, replay_plan
from app.evaluation.scenarios import SCENARIO_DATE, build_scenarios

BOWL, OMELETTE, OATS, SALMON_PLATE, BURRITO, YOGURT = 1, 2, 3, 4, 5, 6


def scenario(scenario_id):
    """Return one evaluation scenario.

    Args:
        scenario_id: Which scenario.

    Returns:
        The Scenario.
    """
    return next(s for s in build_scenarios() if s.id == scenario_id)


def replay(s, recipe_ids, **overrides):
    """Replay recipe ids on a scenario's kitchen and request.

    Args:
        s: The scenario.
        recipe_ids: The proposed recipes, in order.
        **overrides: replay_plan arguments that replace the scenario's.

    Returns:
        The ReplayedPlan.
    """
    by_id = {recipe.id: recipe for recipe in s.recipes}
    arguments = dict(
        batches=s.batches, as_of=SCENARIO_DATE, remaining_macros=s.remaining,
        rating_summaries=s.rating_summaries, meal_count=s.meal_count,
        max_prep_minutes=s.max_prep_minutes, servings_per_meal=s.servings_per_meal,
    )
    arguments.update(overrides)
    return replay_plan([by_id[i] for i in recipe_ids], s.recipes, **arguments)


@pytest.mark.parametrize("s", build_scenarios(), ids=lambda s: s.id)
def test_replaying_the_baselines_choices_reproduces_the_baseline_plan(s):
    """The validator agrees with the planner: the same choices give the same plan, no problems."""
    baseline = plan_meals(
        s.recipes, s.batches, SCENARIO_DATE, s.remaining, s.rating_summaries,
        s.meal_count, s.max_prep_minutes, s.servings_per_meal,
    )

    replayed = replay(s, [meal.recommendation.recipe.id for meal in baseline.meals])

    assert replayed.problems == []
    assert replayed.plan == baseline


def test_hard_constraint_violations_are_problems():
    """Repeats and recipes over the prep limit make the sequence invalid."""
    replayed = replay(scenario("tight-prep-limit"), [OMELETTE, OMELETTE, BOWL])

    assert replayed.problems == [
        "'Spinach omelette' is planned more than once",
        "'Chicken rice bowl' takes 25 min, over the 10-min limit",
    ]


def test_a_recipe_ineligible_at_its_point_in_the_plan_is_a_problem():
    """With no salmon and no rice, the salmon plate cannot be replayed."""
    s = scenario("short-inventory")
    without_rice = [b for b in s.batches if b.ingredient_id != 2]

    replayed = replay(s, [OMELETTE, SALMON_PLATE], batches=without_rice)

    assert replayed.plan is None
    assert replayed.problems == [
        "'Salmon rice plate' is ineligible at that point in the plan: more than one primary "
        "ingredient is missing"
    ]


def test_shortages_are_allowed_and_reported():
    """A partly stocked recipe is valid; its meal reports the shortage, as in the baseline."""
    replayed = replay(scenario("short-inventory"), [BOWL, OMELETTE, OATS])

    assert replayed.problems == []
    assert replayed.plan.meals[0].shortfalls == {1: (150, 120)}


def test_fewer_meals_than_requested_is_a_problem_while_eligible_recipes_remain():
    """Two meals for a three-meal request, with recipes left that could fill the third."""
    replayed = replay(scenario("well-stocked"), [BOWL, OMELETTE])

    assert replayed.problems == ["only 2 of 3 meals planned while eligible recipes remain"]
    assert len(replayed.plan.meals) == 2


def test_fewer_meals_than_requested_is_valid_when_nothing_eligible_is_left():
    """Within a 10-minute limit only three recipes qualify; planning all three for four is fine."""
    replayed = replay(scenario("tight-prep-limit"), [OMELETTE, OATS, YOGURT], meal_count=4)

    assert replayed.problems == []
    assert replayed.plan.meals_requested == 4
