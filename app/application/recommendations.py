from datetime import date, datetime, time, timedelta

from sqlalchemy import Float, func, select
from sqlalchemy.orm import Session, selectinload

from app.application.nutrition import get_nutrition_state
from app.domain.enjoyment import RatingSummary
from app.domain.recent_frequency import recent_window_start
from app.domain.recommendations import Recommendation, recommend_recipes
from app.persistence.models import (
    InventoryBatch,
    MealFeedback,
    MealLog,
    Recipe,
    RecipeIngredient,
)


def get_recommendations(session: Session, as_of: date) -> list[Recommendation]:
    """Load what the recommender needs for one calendar day and rank the recipes.

    Meal history and ratings are never loaded in full: only the recent-frequency window's meals,
    each recipe's last-eaten date, and each recipe's rating average and count (grouped queries)
    are read.

    Args:
        session: An open database session; nothing is written.
        as_of: The calendar day to recommend for.

    Returns:
        Eligible recipes as Recommendations, highest score first.

    Raises:
        InvalidInputError: If ``as_of`` is a datetime rather than a calendar date.
    """
    remaining = get_nutrition_state(session, as_of).remaining
    # Eager-load what the domain reads per recipe (lines and ingredient nutrition), so scoring
    # runs a fixed number of queries however many recipes exist.
    recipes = session.scalars(
        select(Recipe).options(
            selectinload(Recipe.recipe_ingredients).selectinload(RecipeIngredient.ingredient)
        )
    ).all()
    # Empty batches contribute nothing to availability or expiry urgency.
    batches = session.scalars(
        select(InventoryBatch).where(InventoryBatch.quantity_remaining > 0)
    ).all()
    # One row per rated recipe, not one per rating: SQL averages and counts each recipe's
    # ratings. Manual meals (no recipe) count toward none. The cast keeps AVG a float on
    # PostgreSQL, where AVG over integers returns NUMERIC (a Python Decimal).
    rating_rows = session.execute(
        select(
            MealLog.recipe_id,
            func.avg(MealFeedback.rating).cast(Float),
            func.count(MealFeedback.id),
        )
        .join(MealFeedback.meal_log)
        .where(MealLog.recipe_id.is_not(None))
        .group_by(MealLog.recipe_id)
    )
    rating_summaries = {
        recipe_id: RatingSummary(average=float(average), count=count)
        for recipe_id, average, count in rating_rows
    }

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
        recipes,
        batches,
        as_of,
        remaining,
        rating_summaries,
        recent_meal_logs,
        last_eaten_by_recipe,
    )
