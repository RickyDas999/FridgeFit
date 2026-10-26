import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import anthropic
import pytest
from pydantic import ValidationError

from app.application.ai_planner import AttemptUsage, PlannerConfig
from app.domain.meal_planning import MealPlan
from app.domain.nutrition_state import RemainingMacros
from app.domain.recipe_macros import RecipeMacros
from app.evaluation.metrics import (
    SpendingCap,
    evaluate_ai,
    evaluate_baseline,
    expiring_food_result,
    hard_constraint_violations,
    macro_result,
    rubric_check,
    score_plan,
)
from app.evaluation.pricing import estimate_cost
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
from tests.test_ai_planner import REQUEST, SUBMIT, FakeClient, reply

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
        meals=list(meals),
        meals_requested=requested or len(meals),
        servings_per_meal=1,
        remaining_at_end=None,
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


def ai_config(model="claude-haiku-5-5"):
    """A planner configuration for evaluation tests.

    Args:
        model: The model id.

    Returns:
        The PlannerConfig.
    """
    return PlannerConfig(model=model)


def test_estimated_cost_comes_from_raw_tokens_and_the_price_table():
    """Cost is tokens times the listed price per million; an unpriced model has none."""
    usage = AttemptUsage("anthropic", "claude-sonnet-5-5", "low", 10_000, 1_000, 0, 0,
                         3, 3, 0, 0, 5.0, 5.0)

    assert estimate_cost(usage) == pytest.approx(10_000 * 2 / 1e6 + 1_000 * 10 / 1e6)
    assert estimate_cost(usage._replace(model="claude-unknown")) is None


def test_ai_evaluation_records_each_attempt_and_scores_the_plan_it_returns():
    """Every repeat is scored like the baseline and carries its outcome, usage, and cost."""
    expiring = [s for s in build_scenarios() if s.id == "expiring-today"]
    client = FakeClient(reply(SUBMIT), reply(SUBMIT))

    run = evaluate_ai(ai_config(), client, runs=2, cap=SpendingCap(1.0), scenarios=expiring)

    assert run.planner == "claude-haiku-5-5:low"
    assert [(r.scenario_id, r.run, r.ai.source) for r in run.results] == [
        ("expiring-today", 1, "ai"), ("expiring-today", 2, "ai"),
    ]
    assert run.results[0].planned_recipes == ["Spinach omelette", "Salmon rice plate"]
    assert run.results[0].ai.estimated_cost_usd == pytest.approx(
        100 * 0.10 / 1e6 + 20 * 0.50 / 1e6
    )
    assert (run.summary.ai.attempts, run.summary.ai.ai_plans_used) == (2, 2)
    assert run.stopped_early is None


def test_a_failed_attempt_is_scored_on_the_baseline_plan_it_fell_back_to():
    """A provider error is recorded as a fallback; the plan scored is the baseline's."""
    expiring = [s for s in build_scenarios() if s.id == "expiring-today"]
    client = FakeClient(anthropic.APIConnectionError(request=REQUEST))

    run = evaluate_ai(ai_config(), client, runs=1, cap=SpendingCap(1.0), scenarios=expiring)

    [result] = run.results
    assert result.ai.source == "baseline"
    assert result.ai.fallback_reason.startswith("provider_error")
    baseline = evaluate_baseline(scenarios=expiring).results[0]
    assert result.planned_recipes == baseline.planned_recipes
    assert run.summary.ai.fallbacks == 1


def test_the_spending_cap_stops_new_attempts():
    """Once the estimate reaches the cap, no further attempt starts and the run says why."""
    expiring = [s for s in build_scenarios() if s.id == "expiring-today"]
    cap = SpendingCap(0.000001)

    run = evaluate_ai(ai_config(), FakeClient(reply(SUBMIT)), runs=3, cap=cap,
                      scenarios=expiring)

    assert len(run.results) == 1
    assert run.stopped_early == "spending cap $0.00 reached after 1 attempts"
    assert cap.spent_usd > cap.max_usd


def test_an_unpriced_model_cannot_be_evaluated():
    """Without a price the cap could not be enforced, so the run refuses to start."""
    with pytest.raises(ValueError, match="No price listed"):
        evaluate_ai(ai_config("claude-unknown"), FakeClient(), runs=1, cap=SpendingCap(1.0))


def test_the_script_refuses_api_calls_without_live(tmp_path, capsys):
    """--config without --live stops before anything runs or is written."""
    with pytest.raises(SystemExit):
        main(["--results-dir", str(tmp_path), "--config", "claude-haiku-5-5:1"])

    assert "add --live" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_the_script_needs_an_api_key_for_live_runs(tmp_path, monkeypatch, capsys):
    """--live without ANTHROPIC_API_KEY stops before anything runs."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(SystemExit):
        main(["--results-dir", str(tmp_path), "--live", "--config", "claude-haiku-5-5:1"])

    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_a_live_run_writes_one_results_file_per_planner(tmp_path, capsys):
    """Baseline plus one AI configuration: two validated files and a spend summary."""
    failures = [anthropic.APIConnectionError(request=REQUEST)] * len(build_scenarios())

    main(["--results-dir", str(tmp_path), "--live", "--config", "claude-haiku-5-5:1"],
         client=FakeClient(*failures))

    names = sorted(path.name.split("-", 2)[-1] for path in tmp_path.glob("*.json"))
    assert names == ["claude-haiku-5-5_low.json", "deterministic-greedy.json"]
    output = capsys.readouterr().out
    assert "AI: 0/7 AI plans used" in output
    assert "Estimated spend: $0.0000 of a $1.00 cap" in output
