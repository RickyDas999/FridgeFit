import uuid
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.meal_confirmation import confirm_meal
from app.persistence.models import MealLog, Recipe


class MealConfirmation(NamedTuple):
    """The MealLog for a confirmation, and whether this call created it."""

    meal_log: MealLog
    created: bool


def confirm_recipe_meal(
    session: Session,
    recipe: Recipe,
    *,
    servings: float,
    consumed_at: datetime,
    name: str | None,
    allow_shortfall: bool,
    idempotency_key: uuid.UUID | None,
) -> MealConfirmation:
    """Confirm a meal made from a recipe, unless this idempotency key was already confirmed.

    The first successful confirmation for a key is authoritative: a retry with the same key
    returns that MealLog without consuming inventory again, even if the retried request differs.
    Without a key, every call confirms a new meal.

    Args:
        session: An open database session; ``confirm_meal`` commits it.
        recipe: The recipe that was made.
        servings: How many servings were made and eaten.
        consumed_at: When the meal was eaten.
        name: Optional meal name; defaults to the recipe's name.
        allow_shortfall: Whether to confirm even when inventory is short.
        idempotency_key: Optional client-generated key identifying this confirmation.

    Returns:
        The MealLog, with ``created`` False when it came from an earlier confirmation.

    Raises:
        InvalidInputError: If the recipe or servings are invalid.
        InsufficientInventoryError: If inventory is short and ``allow_shortfall`` is False.
    """
    if idempotency_key is not None:
        existing = session.scalar(
            select(MealLog).where(MealLog.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return MealConfirmation(meal_log=existing, created=False)

    meal_log = confirm_meal(
        session,
        recipe,
        servings=servings,
        consumed_at=consumed_at,
        name=name,
        allow_shortfall=allow_shortfall,
        idempotency_key=idempotency_key,
    )
    return MealConfirmation(meal_log=meal_log, created=True)
