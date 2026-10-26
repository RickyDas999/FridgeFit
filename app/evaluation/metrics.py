"""Score meal plans against scenarios, and evaluate planners (deterministic and AI) on them."""

import math
import time
from datetime import datetime, timedelta
from typing import Callable

from app.application.ai_planner import PlannerConfig, PlanningResult, plan_day
from app.application.planning_tools import PlanningRequest, PlanningSnapshot
from app.domain.expiry_urgency import EXPIRING_SOON_DAYS
from app.domain.macro_fit import PROTEIN_ACCEPTABLE_EXCESS
from app.domain.meal_planning import MealPlan, plan_meals, plan_violations
from app.evaluation.pricing import PRICES, estimate_cost
from app.evaluation.results import (
    AISummary,
    AttemptResult,
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
                scenario.servings_per_meal,
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


class SpendingCap:
    """A running estimate of evaluation spend, shared across configurations of one run."""

    def __init__(self, max_usd: float):
        """Start with nothing spent.

        Args:
            max_usd: No new attempt starts once the estimate reaches this many US dollars.
        """
        self.max_usd = max_usd
        self.spent_usd = 0.0

    def reached(self) -> bool:
        """Whether the estimated spend has reached the cap.

        Returns:
            True once no further attempt may start.
        """
        return self.spent_usd >= self.max_usd


def evaluate_ai(
    config: PlannerConfig,
    client,
    runs: int,
    cap: SpendingCap,
    scenarios: list[Scenario] | None = None,
    created_at: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> EvaluationRun:
    """Plan every scenario ``runs`` times with ``plan_day`` and score what it returns.

    Each attempt's plan, AI or fallback, is scored with ``score_plan`` like the baseline's, and
    its outcome, usage, and estimated cost are recorded. Repeats go scenario set by scenario set,
    so a run stopped by the cap still covers whole sets first. The cap is checked before each
    attempt, so it can be exceeded by at most one attempt.

    Args:
        config: The Claude configuration to evaluate.
        client: An Anthropic client (or a stand-in).
        runs: How many times to plan each scenario; at least 1.
        cap: The shared spending cap; its spend is updated as attempts finish.
        scenarios: Scenarios to run; defaults to ``build_scenarios()``.
        created_at: Timestamp recorded on the run; defaults to now.
        clock: Seconds from a monotonic clock, passed to the planner.

    Returns:
        The evaluation run, with ``stopped_early`` set if the cap ended it.

    Raises:
        ValueError: If ``runs`` is not positive or the model has no listed price (the cap could
            not be enforced).
    """
    if runs < 1:
        raise ValueError(f"runs must be at least 1, got {runs}")
    if ("anthropic", config.model) not in PRICES:
        raise ValueError(f"No price listed for {config.model}; the spending cap needs one.")
    scenarios = build_scenarios() if scenarios is None else scenarios
    results = []
    stopped_early = None
    for run in range(1, runs + 1):
        for scenario in scenarios:
            if cap.reached():
                stopped_early = (
                    f"spending cap ${cap.max_usd:.2f} reached after {len(results)} attempts"
                )
                break
            planned = plan_day(scenario_snapshot(scenario), config, client, clock)
            attempt = attempt_result(planned)
            cap.spent_usd += attempt.estimated_cost_usd or 0.0
            results.append(score_plan(scenario, planned.plan).model_copy(
                update={"run": run, "ai": attempt}
            ))
        if stopped_early:
            break
    summary = summarize(results).model_copy(update={"ai": ai_summary(results)})
    return EvaluationRun(
        planner=f"{config.model}:{config.effort}",
        created_at=created_at or datetime.now(),
        scenario_date=SCENARIO_DATE,
        results=results,
        summary=summary,
        stopped_early=stopped_early,
    )


def scenario_snapshot(scenario: Scenario) -> PlanningSnapshot:
    """Turn a scenario into the snapshot the AI planner and its tools read.

    Args:
        scenario: The scenario.

    Returns:
        The PlanningSnapshot, with the scenario's preference text.
    """
    return PlanningSnapshot(
        request=PlanningRequest(
            as_of=SCENARIO_DATE,
            meal_count=scenario.meal_count,
            max_prep_minutes=scenario.max_prep_minutes,
            servings_per_meal=scenario.servings_per_meal,
            preference=scenario.preference,
        ),
        recipes_by_id={recipe.id: recipe for recipe in scenario.recipes},
        batches=scenario.batches,
        remaining=scenario.remaining,
        rating_summaries=scenario.rating_summaries,
    )


def attempt_result(planned: PlanningResult) -> AttemptResult:
    """Record how an AI planning attempt went, from ``plan_day``'s result.

    Args:
        planned: The result of ``plan_day`` with an attempt.

    Returns:
        The AttemptResult, with the estimated cost.
    """
    attempt = planned.attempt
    usage = attempt.usage
    return AttemptResult(
        source=planned.source,
        outcome=attempt.outcome,
        fallback_reason=planned.fallback_reason,
        rejected_plans=usage.rejected_plans,
        model_calls=usage.model_calls,
        tool_calls=usage.tool_calls,
        invalid_tool_calls=usage.invalid_tool_calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_input_tokens=usage.cache_read_input_tokens,
        cache_creation_input_tokens=usage.cache_creation_input_tokens,
        model_seconds=usage.model_seconds,
        total_seconds=usage.total_seconds,
        estimated_cost_usd=estimate_cost(usage),
    )


def ai_summary(results: list[ScenarioResult]) -> AISummary:
    """Aggregate the AI attempts of one configuration.

    Args:
        results: Scenario results that each carry an ``ai`` attempt.

    Returns:
        The AISummary.
    """
    attempts = [r.ai for r in results]
    seconds = [a.total_seconds for a in attempts]
    costs = [a.estimated_cost_usd for a in attempts]
    return AISummary(
        attempts=len(attempts),
        ai_plans_used=sum(1 for a in attempts if a.source == "ai"),
        fallbacks=sum(1 for a in attempts if a.source == "baseline"),
        corrected_plans_used=sum(1 for a in attempts if a.source == "ai" and a.rejected_plans),
        invalid_tool_calls=sum(a.invalid_tool_calls for a in attempts),
        input_tokens=sum(a.input_tokens for a in attempts),
        output_tokens=sum(a.output_tokens for a in attempts),
        mean_total_seconds=sum(seconds) / len(seconds) if seconds else None,
        max_total_seconds=max(seconds) if seconds else None,
        estimated_cost_usd=None if None in costs else sum(costs),
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
    """List every hard constraint the plan breaks, using the domain's ``plan_violations``.

    Args:
        scenario: The scenario, holding the request and the known recipes.
        plan: The plan to check.

    Returns:
        One readable message per violation; an empty list means it complies.
    """
    return plan_violations(
        [meal.recommendation.recipe for meal in plan.meals],
        {recipe.id for recipe in scenario.recipes},
        scenario.meal_count,
        scenario.max_prep_minutes,
    )


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
