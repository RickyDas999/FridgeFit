"""Score meal plans against scenarios, and evaluate the deterministic planner on all of them."""

import math
from datetime import datetime, timedelta

from app.domain.expiry_urgency import EXPIRING_SOON_DAYS
from app.domain.macro_fit import PROTEIN_ACCEPTABLE_EXCESS
from app.domain.meal_planning import MealPlan, plan_meals
from app.evaluation.results import (
    EvaluationRun,
    ExpiringFoodResult,
    MacroAmounts,
    MacroResult,
    PreferenceResult,
    RubricCheck,
    RunSummary,
    ScenarioResult,
    Shortfall,
)
from app.evaluation.scenarios import (
    SCENARIO_DATE,
    ExcludeRecipe,
    MinPlannedMacro,
    Scenario,
    build_scenarios,
)

BASELINE_PLANNER = "deterministic-greedy"


def evaluate_baseline(
    scenarios: list[Scenario] | None = None, created_at: datetime | None = None
) -> EvaluationRun:
    """Run the deterministic greedy planner on every scenario and score each plan.

    Args:
        scenarios: Scenarios to run; defaults to ``build_scenarios()``.
        created_at: Timestamp recorded on the run; defaults to now.

    Returns:
        The validated evaluation run: one result per scenario plus a summary.
    """
    scenarios = build_scenarios() if scenarios is None else scenarios
    results = [
        score_plan(
            scenario,
            plan_meals(
                scenario.recipes,
                scenario.batches,
                SCENARIO_DATE,
                scenario.remaining,
                scenario.rating_summaries,
                scenario.meal_count,
                scenario.max_prep_minutes,
            ),
        )
        for scenario in scenarios
    ]
    return EvaluationRun(
        planner=BASELINE_PLANNER,
        created_at=created_at or datetime.now(),
        scenario_date=SCENARIO_DATE,
        results=results,
        summary=summarize(results),
    )


def score_plan(scenario: Scenario, plan: MealPlan) -> ScenarioResult:
    """Measure one plan against its scenario. Uses only the scenario and the plan.

    Args:
        scenario: The scenario the plan was made for.
        plan: The plan to score.

    Returns:
        Every metric for this plan.
    """
    ingredient_names = {
        line.ingredient_id: line.ingredient.name
        for recipe in scenario.recipes
        for line in recipe.recipe_ingredients
    }
    shortfalls = [
        Shortfall(
            meal_index=index,
            ingredient=ingredient_names[ingredient_id],
            quantity_needed=needed,
            quantity_available=available,
        )
        for index, meal in enumerate(plan.meals)
        for ingredient_id, (needed, available) in meal.shortfalls.items()
    ]
    planned_names = [meal.recommendation.recipe.name for meal in plan.meals]
    return ScenarioResult(
        scenario_id=scenario.id,
        description=scenario.description,
        meals_requested=scenario.meal_count,
        meals_planned=len(plan.meals),
        planned_recipes=planned_names,
        hard_constraint_violations=hard_constraint_violations(scenario, plan),
        meals_with_shortfalls=sum(1 for meal in plan.meals if meal.shortfalls),
        shortfalls=shortfalls,
        macros=macro_result(scenario, plan),
        expiring_food=expiring_food_result(scenario, plan),
        preference=PreferenceResult(
            text=scenario.preference,
            checks=[rubric_check(rule, plan) for rule in scenario.rubric],
        ),
    )


def hard_constraint_violations(scenario: Scenario, plan: MealPlan) -> list[str]:
    """List every hard constraint the plan breaks; an empty list means it complies.

    Args:
        scenario: The scenario, holding the request and the known recipes.
        plan: The plan to check.

    Returns:
        One readable message per violation.
    """
    violations = []
    if len(plan.meals) > scenario.meal_count:
        violations.append(f"{len(plan.meals)} meals planned, {scenario.meal_count} requested")
    known = {recipe.id for recipe in scenario.recipes}
    seen = set()
    for meal in plan.meals:
        recipe = meal.recommendation.recipe
        if recipe.id not in known:
            violations.append(f"{recipe.name!r} is not one of the kitchen's recipes")
        if recipe.id in seen:
            violations.append(f"{recipe.name!r} is planned more than once")
        seen.add(recipe.id)
        limit = scenario.max_prep_minutes
        if limit is not None and recipe.prep_minutes > limit:
            violations.append(
                f"{recipe.name!r} takes {recipe.prep_minutes} min, over the {limit}-min limit"
            )
    return violations


def macro_result(scenario: Scenario, plan: MealPlan) -> MacroResult | None:
    """Compare the day's total (eaten plus planned) with its goal, directionally.

    Args:
        scenario: The scenario, holding the goal and what was eaten before planning.
        plan: The plan to measure.

    Returns:
        The macro metrics, or None when the scenario has no nutrition goal.
    """
    if scenario.goal is None:
        return None
    totals = {
        macro: getattr(scenario.eaten_today, macro)
        + sum(getattr(meal.macros, macro) for meal in plan.meals)
        for macro in ("calories", "protein", "carbs", "fat")
    }
    goal = scenario.goal._asdict()
    remaining = {macro: goal[macro] - totals[macro] for macro in totals}
    return MacroResult(
        goal=MacroAmounts(**goal),
        end_of_day_remaining=MacroAmounts(**remaining),
        calories_over=max(-remaining["calories"], 0.0),
        carbs_over=max(-remaining["carbs"], 0.0),
        fat_over=max(-remaining["fat"], 0.0),
        protein_short=max(remaining["protein"], 0.0),
        protein_excess=max(totals["protein"] - PROTEIN_ACCEPTABLE_EXCESS * goal["protein"], 0.0),
    )


def expiring_food_result(scenario: Scenario, plan: MealPlan) -> ExpiringFoodResult:
    """Measure how much stock due within ``EXPIRING_SOON_DAYS`` the plan uses.

    Already-expired stock is not counted: the goal is using food before it goes off.

    Args:
        scenario: The scenario, holding the stock.
        plan: The plan to measure.

    Returns:
        The expiring-food metrics.
    """
    window_end = SCENARIO_DATE + timedelta(days=EXPIRING_SOON_DAYS)
    expiring = [
        batch for batch in scenario.batches
        if batch.use_by_date is not None and SCENARIO_DATE <= batch.use_by_date <= window_end
    ]
    shares = []
    used_up = 0
    for batch in expiring:
        used = sum(meal.batch_draws.get(batch.id, 0.0) for meal in plan.meals)
        shares.append(used / batch.quantity_remaining)
        if math.isclose(used, batch.quantity_remaining):
            used_up += 1
    return ExpiringFoodResult(
        expiring_batches=len(expiring),
        expiring_batches_used_up=used_up,
        share_used=sum(shares) / len(shares) if shares else None,
    )


def rubric_check(rule: MinPlannedMacro | ExcludeRecipe, plan: MealPlan) -> RubricCheck:
    """Check one soft-preference rule against the plan.

    Args:
        rule: The rule.
        plan: The plan to check.

    Returns:
        Whether the plan passes, with the measured value.
    """
    if isinstance(rule, MinPlannedMacro):
        total = sum(getattr(meal.macros, rule.macro) for meal in plan.meals)
        return RubricCheck(
            rule=f"planned {rule.macro} >= {rule.amount:g}",
            passed=total >= rule.amount,
            detail=f"planned {rule.macro}: {total:.1f}",
        )
    planned = [meal.recommendation.recipe.name for meal in plan.meals]
    return RubricCheck(
        rule=f"no {rule.recipe_name}",
        passed=rule.recipe_name not in planned,
        detail=f"planned: {', '.join(planned) or 'nothing'}",
    )


def summarize(results: list[ScenarioResult]) -> RunSummary:
    """Aggregate scenario results into one run summary.

    Args:
        results: One result per scenario.

    Returns:
        The summary.
    """
    shares = [
        r.expiring_food.share_used for r in results if r.expiring_food.share_used is not None
    ]
    checks = [check for r in results for check in r.preference.checks]
    return RunSummary(
        scenarios=len(results),
        complete_plans=sum(1 for r in results if r.meals_planned == r.meals_requested),
        hard_constraint_compliant=sum(1 for r in results if not r.hard_constraint_violations),
        plans_without_shortfalls=sum(1 for r in results if r.meals_with_shortfalls == 0),
        total_calories_over=sum(r.macros.calories_over for r in results if r.macros),
        total_protein_short=sum(r.macros.protein_short for r in results if r.macros),
        mean_expiring_share_used=sum(shares) / len(shares) if shares else None,
        rubric_checks_passed=sum(1 for check in checks if check.passed),
        rubric_checks=len(checks),
    )
