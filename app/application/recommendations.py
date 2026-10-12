from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.nutrition import get_nutrition_state
from app.domain.recent_frequency import recent_window_start
from app.domain.recommendations import Recommendation, recommend_recipes
from app.persistence.models import InventoryBatch, MealFeedback, MealLog, Recipe


def get_recommendations(session: Session, as_of: date) -> list[Recommendation]:
    """Load what the recommender needs for one calendar day and rank the recipes.

    Meal history is never loaded in full: only the recent-frequency window's meals and each
    recipe's last-eaten date (one grouped query) are read.

    Args:
        session: An open database session; nothing is written.
        as_of: The calendar day to recommend for.

    Returns:
        Eligible recipes as Recommendations, highest score first.

    Raises:
        InvalidInputError: If ``as_of`` is a datetime rather than a calendar date.
    """
    remaining = get_nutrition_state(session, as_of).remaining
    recipes = session.scalars(select(Recipe)).all()
    # Empty batches contribute nothing to availability or expiry urgency.
    batches = session.scalars(
        select(InventoryBatch).where(InventoryBatch.quantity_remaining > 0)
    ).all()
    # ponytail: loads every rating; compute per-recipe averages in SQL when it grows.
    meal_feedback = session.scalars(select(MealFeedback)).all()

    day_after = datetime.combine(as_of + timedelta(days=1), time.min)
    recent_meal_logs = session.scalars(
        select(MealLog).where(
            MealLog.recipe_id.is_not(None),
            MealLog.consumed_at >= datetime.combine(recent_window_start(as_of), time.min),
            MealLog.consumed_at < day_after,
        )
    ).all()
    last_eaten_rows = session.execute(
        select(MealLog.recipe_id, func.max(MealLog.consumed_at))
        .where(MealLog.recipe_id.is_not(None), MealLog.consumed_at < day_after)
        .group_by(MealLog.recipe_id)
    )
    last_eaten_by_recipe = {recipe_id: eaten_at.date() for recipe_id, eaten_at in last_eaten_rows}

    return recommend_recipes(
        recipes, batches, as_of, remaining, meal_feedback, recent_meal_logs, last_eaten_by_recipe
    )
