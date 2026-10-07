from datetime import date
from typing import NamedTuple, Sequence

from app.persistence.models import MealLog, NutritionGoal


class RemainingMacros(NamedTuple):
    """Macros left in the day's budget; negative values mean the target was exceeded."""

    calories: float
    protein: float
    carbs: float
    fat: float


def select_applicable_goal(
    goals: Sequence[NutritionGoal], as_of: date
) -> NutritionGoal | None:
    """Return the nutrition goal in effect on a given date.

    The applicable goal is the one with the latest ``effective_date`` that is
    on or before ``as_of``; goals dated in the future are ignored.

    Args:
        goals: The full nutrition goal history to choose from.
        as_of: The date to evaluate.

    Returns:
        The applicable NutritionGoal, or None if no goal is effective yet.
    """
    applicable = [goal for goal in goals if goal.effective_date <= as_of]
    if not applicable:
        return None
    return max(applicable, key=lambda goal: goal.effective_date)


def calculate_remaining_macros(
    goals: Sequence[NutritionGoal], meal_logs: Sequence[MealLog], as_of: date
) -> RemainingMacros:
    """Calculate remaining macros for a day as the applicable goal minus consumption.

    Only meal logs consumed on the same calendar day as ``as_of`` count
    toward consumption.

    Args:
        goals: The full nutrition goal history.
        meal_logs: Candidate meal logs; those from other days are ignored.
        as_of: The day to calculate remaining macros for.

    Returns:
        The remaining macros as a RemainingMacros tuple. Values may be negative.

    Raises:
        ValueError: If no nutrition goal is effective on or before ``as_of``.
    """
    goal = select_applicable_goal(goals, as_of)
    if goal is None:
        raise ValueError(f"No nutrition goal is effective on or before {as_of}")

    consumed_today = [
        meal_log for meal_log in meal_logs if meal_log.consumed_at.date() == as_of
    ]

    return RemainingMacros(
        calories=goal.calories - sum(meal_log.calories for meal_log in consumed_today),
        protein=goal.protein - sum(meal_log.protein for meal_log in consumed_today),
        carbs=goal.carbs - sum(meal_log.carbs for meal_log in consumed_today),
        fat=goal.fat - sum(meal_log.fat for meal_log in consumed_today),
    )
