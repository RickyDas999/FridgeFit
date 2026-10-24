import uuid
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.meal_confirmation import InsufficientInventoryError, confirm_meal
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
    This includes a concurrent request that commits the same new key first: whether this call
    then fails on the unique constraint (rolled back) or on the stock the winner consumed, the
    winner's MealLog is returned.
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
        InsufficientInventoryError: If inventory is short, ``allow_shortfall`` is False, and no
            MealLog with this key exists.
        IntegrityError: If the commit violates a constraint and no MealLog with this key exists.
    """
    if idempotency_key is not None:
        existing = _find_meal_log_by_key(session, idempotency_key)
        if existing is not None:
            return MealConfirmation(meal_log=existing, created=False)

    try:
        meal_log = confirm_meal(
            session,
            recipe,
            servings=servings,
            consumed_at=consumed_at,
            name=name,
            allow_shortfall=allow_shortfall,
            idempotency_key=idempotency_key,
        )
    except InsufficientInventoryError:
        if idempotency_key is None:
            raise
        # The shortfall may be the stock a same-key request just consumed after our lookup
        # above. Nothing was written, so the session needs no rollback before looking again.
        winner = _find_meal_log_by_key(session, idempotency_key)
        if winner is None:
            raise
        return MealConfirmation(meal_log=winner, created=False)
    except IntegrityError:
        if idempotency_key is None:
            raise
        # Possibly another request committed this key after our lookup above. The failed
        # transaction must be rolled back before the session can query again; that also
        # discards this attempt's inventory decrements. If no MealLog holds the key, the
        # violation was something else, so it stays an error.
        session.rollback()
        winner = _find_meal_log_by_key(session, idempotency_key)
        if winner is None:
            raise
        return MealConfirmation(meal_log=winner, created=False)
    return MealConfirmation(meal_log=meal_log, created=True)


def _find_meal_log_by_key(session: Session, idempotency_key: uuid.UUID) -> MealLog | None:
    """Find the MealLog confirmed with an idempotency key.

    Args:
        session: An open database session.
        idempotency_key: The client-generated key to look up.

    Returns:
        The MealLog with that key, or None if the key has not been confirmed.
    """
    return session.scalar(select(MealLog).where(MealLog.idempotency_key == idempotency_key))
