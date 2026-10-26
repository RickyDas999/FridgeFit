from datetime import date

from sqlalchemy.orm import Session

from app.application.recommendations import load_recommendation_inputs
from app.domain.meal_planning import MealPlan, SimulatedBatch, plan_meals


def get_meal_plan(
    session: Session, as_of: date, meal_count: int, max_prep_minutes: int | None = None
) -> MealPlan:
    """Plan the rest of a day's meals with the deterministic greedy planner.

    The inventory is copied into plain ``SimulatedBatch`` values before planning, so the
    simulation never changes the session's objects and nothing is written.

    Args:
        session: An open database session; nothing is written.
        as_of: The calendar day to plan.
        meal_count: How many meals to plan; at least 1.
        max_prep_minutes: Only plan recipes that take at most this long, or None for no limit.

    Returns:
        The plan, possibly with fewer meals than requested.

    Raises:
        InvalidInputError: If ``as_of`` is not a calendar date, ``meal_count`` is not a positive
            whole number, or ``max_prep_minutes`` is negative.
    """
    inputs = load_recommendation_inputs(session, as_of)
    batches = [
        SimulatedBatch(
            id=batch.id,
            ingredient_id=batch.ingredient_id,
            quantity_remaining=batch.quantity_remaining,
            use_by_date=batch.use_by_date,
            purchased_at=batch.purchased_at,
        )
        for batch in inputs.batches
    ]
    return plan_meals(
        inputs.recipes,
        batches,
        as_of,
        inputs.remaining,
        inputs.rating_summaries,
        meal_count,
        max_prep_minutes,
    )
