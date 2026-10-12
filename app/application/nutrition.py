from datetime import date, datetime, time, timedelta
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.nutrition_state import (
    RemainingMacros,
    calculate_remaining_macros,
    select_applicable_goal,
)
from app.persistence.models import MealLog, NutritionGoal


class NutritionState(NamedTuple):
    """The goal in effect on a day and what is left of it; both None when no goal applies."""

    goal: NutritionGoal | None
    remaining: RemainingMacros | None


def get_nutrition_state(session: Session, as_of: date) -> NutritionState:
    """Load goals and the day's meals, then derive the nutrition state for one calendar day.

    Args:
        session: An open database session; nothing is written.
        as_of: The calendar day to evaluate.

    Returns:
        The applicable goal and remaining macros, or ``(None, None)`` if no goal is effective.

    Raises:
        InvalidInputError: If ``as_of`` is a datetime rather than a calendar date.
    """
    goals = session.scalars(select(NutritionGoal)).all()
    goal = select_applicable_goal(goals, as_of)
    if goal is None:
        return NutritionState(goal=None, remaining=None)

    # Only load the requested day's meals; the domain still applies the calendar-day rule itself.
    day_start = datetime.combine(as_of, time.min)
    meal_logs = session.scalars(
        select(MealLog).where(
            MealLog.consumed_at >= day_start,
            MealLog.consumed_at < day_start + timedelta(days=1),
        )
    ).all()
    return NutritionState(goal=goal, remaining=calculate_remaining_macros(goals, meal_logs, as_of))
