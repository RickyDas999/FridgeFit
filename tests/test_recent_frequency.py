from datetime import date, datetime, time, timedelta

import pytest

from app.domain.recent_frequency import assess_recent_frequency, group_meal_dates_by_recipe
from app.errors import InvalidInputError
from app.persistence.models import MealLog, Recipe

AS_OF = date(2026, 3, 10)


def make_meal(days_ago, recipe_id=1):
    """Build an unsaved MealLog eaten the given number of days before ``AS_OF``.

    Args:
        days_ago: Days before ``AS_OF`` the meal was eaten; negative means after it.
        recipe_id: Recipe the meal came from, or None for a manual meal.

    Returns:
        A new, unpersisted MealLog.
    """
    eaten_at = datetime.combine(AS_OF - timedelta(days=days_ago), time(12))
    return MealLog(recipe_id=recipe_id, consumed_at=eaten_at)


def make_recipe(recipe_id=1):
    """Build an unsaved Recipe with the given id.

    Args:
        recipe_id: Id to give the recipe, used to match meals.

    Returns:
        A new, unpersisted Recipe.
    """
    return Recipe(id=recipe_id, name="Test Recipe", instructions=[], prep_minutes=10, servings=1)


def frequency(*meals):
    """Report recipe 1's recent frequency as of ``AS_OF`` from the given meals.

    Args:
        *meals: The meal history.

    Returns:
        The RecentFrequency for recipe 1.
    """
    meal_dates = group_meal_dates_by_recipe(meals, AS_OF)
    return assess_recent_frequency(make_recipe(1), meal_dates, AS_OF)


def test_never_eaten_recipe_reports_zero_and_no_date():
    """A recipe with no meals reports no recent eating and no last-eaten date."""
    result = frequency()

    assert result.times_eaten_recently == 0
    assert result.last_eaten_on is None


def test_window_covers_today_and_the_six_days_before():
    """Meals from today back to six days ago count; seven days ago does not."""
    result = frequency(make_meal(0), make_meal(6), make_meal(7))

    assert result.times_eaten_recently == 2


def test_last_eaten_date_looks_beyond_the_window():
    """The last-eaten date comes from full history, even when nothing is recent."""
    result = frequency(make_meal(20), make_meal(45))

    assert result.times_eaten_recently == 0
    assert result.last_eaten_on == AS_OF - timedelta(days=20)


def test_meals_after_as_of_are_ignored():
    """Meals dated after the reporting date neither count nor set the last-eaten date."""
    result = frequency(make_meal(-1), make_meal(3))

    assert result.times_eaten_recently == 1
    assert result.last_eaten_on == AS_OF - timedelta(days=3)


def test_manual_and_other_recipe_meals_are_ignored():
    """Only meals made from this recipe count toward its frequency."""
    result = frequency(make_meal(1, recipe_id=None), make_meal(1, recipe_id=2))

    assert result.times_eaten_recently == 0
    assert result.last_eaten_on is None


def test_multiple_meals_on_one_day_each_count():
    """Eating a recipe twice in one day counts as two times eaten."""
    assert frequency(make_meal(2), make_meal(2)).times_eaten_recently == 2


def test_datetime_as_of_is_rejected():
    """Recent frequency requires a calendar date, not a datetime."""
    with pytest.raises(InvalidInputError):
        group_meal_dates_by_recipe([], datetime(2026, 3, 10))
