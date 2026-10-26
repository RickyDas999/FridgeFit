import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.domain.meal_planning import MealPlan
from app.domain.nutrition_state import RemainingMacros
from app.domain.recipe_macros import RecipeMacros
from app.evaluation.metrics import (
    evaluate_baseline,
    expiring_food_result,
    hard_constraint_violations,
    macro_result,
    rubric_check,
    score_plan,
)
from app.evaluation.results import EvaluationRun, ExpiringFoodResult
from app.evaluation.scenarios import (
    DAILY_GOAL,
    SCENARIO_DATE,
    ExcludeRecipe,
    MinPlannedMacro,
    build_batches,
    build_scenarios,
)
from scripts.evaluate_planner import main

ZERO = RecipeMacros(calories=0, protein=0, carbs=0, fat=0)


def scenario(**overrides):
    """Return the first scenario with some fields replaced.

    Args:
        **overrides: Scenario fields to replace.

    Returns:
        The Scenario.
    """
    return build_scenarios()[0]._replace(**overrides)


def meal(recipe, macros=ZERO, batch_draws=None, shortfalls=None):
    """Build a stand-in planned meal with only the fields the metrics read.

    Args:
        recipe: The planned recipe.
        macros: The meal's macros.
        batch_draws: Batch id to quantity drawn.
        shortfalls: Ingredient id to (needed, available).

    Returns:
        A stand-in PlannedMeal.
    """
    return SimpleNamespace(
        recommendation=SimpleNamespace(recipe=recipe),
        macros=macros,
        batch_draws=batch_draws or {},
        shortfalls=shortfalls or {},
    )


def plan_of(*meals, requested=None):
    """Build a MealPlan from stand-in meals.

    Args:
        *meals: The planned meals.
        requested: Meals requested; defaults to the number given.

    Returns:
        The MealPlan.
    """
    return MealPlan(
        meals=list(meals), meals_requested=requested or len(meals), remaining_at_end=None
    )


def test_a_compliant_plan_has_no_violations():
    """Distinct known recipes within the limits break no hard constraint."""
    s = scenario(meal_count=2, max_prep_minutes=30)
    bowl, omelette = s.recipes[0], s.recipes[1]

    assert hard_constraint_violations(s, plan_of(meal(bowl), meal(omelette))) == []


def test_every_kind_of_hard_constraint_violation_is_reported():
    """Too many meals, a repeat, an unknown recipe, and a slow recipe are each named."""
    s = scenario(meal_count=2, max_prep_minutes=20)
    bowl = s.recipes[0]  # 25 minutes
    stranger = SimpleNamespace(id=999, name="Mystery stew", prep_minutes=5)

    violations = hard_constraint_violations(s, plan_of(meal(bowl), meal(bowl), meal(stranger)))

    assert violations == [
        "3 meals planned, 2 requested",
        "'Chicken rice bowl' takes 25 min, over the 20-min limit",
        "'Chicken rice bowl' is planned more than once",
        "'Chicken rice bowl' takes 25 min, over the 20-min limit",
        "'Mystery stew' is not one of the kitchen's recipes",
    ]


def test_macros_are_judged_directionally():
    """Over the goal counts for calories, carbs, and fat; protein counts when short or far over."""
    eaten = RemainingMacros(calories=2000, protein=100, carbs=100, fat=10)
    s = scenario(eaten_today=eaten)
    dinner = RecipeMacros(calories=500, protein=20, carbs=50, fat=10)

    result = macro_result(s, plan_of(meal(s.recipes[0], macros=dinner)))

    assert result.end_of_day_remaining.calories == pytest.approx(DAILY_GOAL.calories - 2500)
    assert result.calories_over == pytest.approx(300)
    assert result.carbs_over == 0  # 150 of 220 g
    assert result.fat_over == 0
    assert result.protein_short == pytest.approx(40)
    assert result.protein_excess == 0


def test_protein_counts_as_excess_only_beyond_one_and_a_half_times_the_goal():
    """Up to 1.5x the protein goal is fine; beyond that is excess."""
    s = scenario(eaten_today=RemainingMacros(calories=0, protein=250, carbs=0, fat=0))

    result = macro_result(s, plan_of(meal(s.recipes[0])))

    assert result.protein_short == 0
    assert result.protein_excess == pytest.approx(250 - 1.5 * DAILY_GOAL.protein)
    assert result.calories_over == 0  # the whole calorie goal is still unused: under, not over


def test_no_goal_means_no_macro_result():
    """Without a nutrition goal, macro metrics are absent."""
    s = scenario(goal=None)

    assert macro_result(s, plan_of(meal(s.recipes[0]))) is None


def test_expiring_food_counts_only_stock_due_within_the_window():
    """Stock due today through EXPIRING_SOON_DAYS counts; expired and undated stock do not."""
    batches = build_batches(
        {4: 12, 5: 300, 6: 600, 2: 2000, 9: 100}, use_by_days={4: 1, 5: 0, 6: 2, 9: -1}
    )
    s = scenario(batches=batches)
    plan = plan_of(meal(s.recipes[0], batch_draws={5: 300, 6: 150, 9: 100, 2: 500}))

    result = expiring_food_result(s, plan)

    assert result == ExpiringFoodResult(
        expiring_batches=3, expiring_batches_used_up=1, share_used=(0 + 1 + 0.25) / 3
    )


def test_nothing_expiring_gives_no_share():
    """With no stock in the window, the share used is None rather than 0 or 1."""
    s = scenario(batches=build_batches({2: 1000}))

    assert expiring_food_result(s, plan_of(meal(s.recipes[0]))).share_used is None


def test_rubric_rules_pass_and_fail_on_the_plan():
    """A minimum-macro rule compares the planned total; an exclusion checks the recipe names."""
    s = scenario()
    bowl, burrito = s.recipes[0], s.recipes[4]
    plan = plan_of(meal(bowl, macros=ZERO._replace(protein=45)), meal(burrito))

    protein = rubric_check(MinPlannedMacro("protein", 60), plan)
    no_burrito = rubric_check(ExcludeRecipe("Bean burrito"), plan)

    assert (protein.passed, protein.detail) == (False, "planned protein: 45.0")
    assert no_burrito.passed is False


def test_shortfalls_are_reported_by_meal_and_ingredient_name():
    """Each short ingredient appears once, under the meal that is short."""
    s = scenario()
    result = score_plan(s, plan_of(meal(s.recipes[0]), meal(s.recipes[1], shortfalls={4: (3, 1)})))

    assert result.meals_with_shortfalls == 1
    assert [(x.meal_index, x.ingredient, x.quantity_needed) for x in result.shortfalls] == [
        (1, "Eggs", 3)
    ]


def test_the_baseline_evaluation_is_reproducible():
    """Two runs give identical results; only the timestamp differs."""
    first = evaluate_baseline(created_at=datetime(2026, 1, 1))
    second = evaluate_baseline(created_at=datetime(2026, 1, 2))

    assert first.results == second.results
    assert first.summary.scenarios == len(build_scenarios())


def test_results_are_validated_when_built():
    """A result that breaks its schema (here, a negative count) is rejected."""
    with pytest.raises(ValidationError):
        ExpiringFoodResult(expiring_batches=-1, expiring_batches_used_up=0, share_used=None)


def test_the_script_writes_a_results_file_that_validates(tmp_path, capsys):
    """The evaluation script writes JSON that loads back as a valid EvaluationRun."""
    main(["--results-dir", str(tmp_path)])

    [path] = tmp_path.glob("*-deterministic-greedy.json")
    run = EvaluationRun.model_validate_json(path.read_text())
    assert run.scenario_date == SCENARIO_DATE
    assert json.loads(path.read_text())["summary"]["scenarios"] == len(build_scenarios())
    assert "Planner: deterministic-greedy" in capsys.readouterr().out


def test_scenario_dates_are_relative_to_the_fixed_scenario_date():
    """A batch's use-by is the scenario date plus its offset, so runs never depend on today."""
    [batch] = build_batches({5: 100}, use_by_days={5: 2})

    assert batch.use_by_date == SCENARIO_DATE + timedelta(days=2)
