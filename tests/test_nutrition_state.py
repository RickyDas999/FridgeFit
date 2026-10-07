from datetime import date, datetime

import pytest

from app.domain.nutrition_state import calculate_remaining_macros, select_applicable_goal
from app.errors import InvalidInputError
from app.persistence.models import MealLog, NutritionGoal


def make_goal(**overrides):
    """Build an unsaved NutritionGoal with valid defaults.

    Args:
        **overrides: NutritionGoal field values that replace the defaults.

    Returns:
        A new, unpersisted NutritionGoal.
    """
    defaults = dict(calories=2200, protein=160, carbs=220, fat=70, effective_date=date(2026, 1, 1))
    defaults.update(overrides)
    return NutritionGoal(**defaults)


def make_meal_log(**overrides):
    """Build an unsaved MealLog with valid defaults.

    Args:
        **overrides: MealLog field values that replace the defaults.

    Returns:
        A new, unpersisted MealLog.
    """
    defaults = dict(
        name="Test Meal",
        calories=450,
        protein=35,
        carbs=20,
        fat=15,
        consumed_at=datetime(2026, 1, 1, 12, 30),
    )
    defaults.update(overrides)
    return MealLog(**defaults)


def test_select_applicable_goal_picks_latest_goal_on_or_before_date():
    """The most recent goal effective by the given date is selected."""
    early = make_goal(effective_date=date(2026, 1, 1), calories=2200)
    later = make_goal(effective_date=date(2026, 3, 1), calories=2000)

    goal = select_applicable_goal([early, later], as_of=date(2026, 3, 15))

    assert goal.calories == 2000


def test_select_applicable_goal_ignores_future_goals():
    """Goals dated after the given date are not selected."""
    early = make_goal(effective_date=date(2026, 1, 1), calories=2200)
    future = make_goal(effective_date=date(2026, 6, 1), calories=1800)

    goal = select_applicable_goal([early, future], as_of=date(2026, 3, 15))

    assert goal.calories == 2200


def test_select_applicable_goal_returns_none_when_no_goal_applies():
    """None is returned when every goal is in the future."""
    future = make_goal(effective_date=date(2026, 6, 1))

    goal = select_applicable_goal([future], as_of=date(2026, 1, 1))

    assert goal is None


def test_remaining_macros_subtracts_same_day_consumption():
    """Remaining macros equal the goal minus that day's consumption."""
    goal = make_goal(calories=2200, protein=160, carbs=220, fat=70)
    meal = make_meal_log(
        calories=450, protein=35, carbs=20, fat=15, consumed_at=datetime(2026, 1, 1, 12, 30)
    )

    remaining = calculate_remaining_macros([goal], [meal], as_of=date(2026, 1, 1))

    assert remaining.calories == pytest.approx(1750)
    assert remaining.protein == pytest.approx(125)
    assert remaining.carbs == pytest.approx(200)
    assert remaining.fat == pytest.approx(55)


def test_remaining_macros_ignores_meal_logs_from_other_days():
    """Meals from other days do not reduce remaining macros."""
    goal = make_goal(calories=2200)
    yesterday_meal = make_meal_log(calories=450, consumed_at=datetime(2025, 12, 31, 20, 0))

    remaining = calculate_remaining_macros([goal], [yesterday_meal], as_of=date(2026, 1, 1))

    assert remaining.calories == pytest.approx(2200)


def test_remaining_macros_can_go_negative_when_exceeded():
    """Remaining macros go negative when the target is exceeded."""
    goal = make_goal(calories=2200)
    meal = make_meal_log(calories=3000, consumed_at=datetime(2026, 1, 1, 12, 30))

    remaining = calculate_remaining_macros([goal], [meal], as_of=date(2026, 1, 1))

    assert remaining.calories == pytest.approx(-800)


def test_remaining_macros_raises_when_no_goal_applies():
    """A ValueError is raised when no goal is effective yet."""
    future_goal = make_goal(effective_date=date(2026, 6, 1))

    with pytest.raises(ValueError):
        calculate_remaining_macros([future_goal], [], as_of=date(2026, 1, 1))


def test_datetime_as_of_is_rejected_by_remaining_macros():
    """A datetime would match no meal logs and silently return the full goal, so it raises."""
    with pytest.raises(InvalidInputError):
        calculate_remaining_macros([make_goal()], [make_meal_log()], as_of=datetime(2026, 1, 1))


def test_datetime_as_of_is_rejected_by_goal_selection():
    """Goal selection also requires a calendar date."""
    with pytest.raises(InvalidInputError):
        select_applicable_goal([make_goal()], as_of=datetime(2026, 1, 1))
