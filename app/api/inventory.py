from datetime import date, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, NaiveDatetime
from sqlalchemy import select

from app.api.session import SessionDep
from app.domain.inventory_aggregation import aggregate_inventory_by_ingredient
from app.persistence.enums import CanonicalUnit
from app.persistence.models import Ingredient, InventoryBatch

router = APIRouter(prefix="/inventory", tags=["inventory"])


class BatchCreate(BaseModel):
    """Request body for recording one grocery purchase."""

    # Python's JSON parser accepts Infinity and NaN; neither is a real quantity.
    model_config = ConfigDict(allow_inf_nan=False)

    ingredient_id: int
    quantity: float = Field(gt=0, description="Amount bought, in the ingredient's unit.")
    # Naive local time, like every stored datetime: calendar-day logic compares local dates.
    purchased_at: NaiveDatetime | None = Field(
        default=None,
        description="Local time, without a timezone. Defaults to now.",
        # Without this, the generated docs example ends in "Z" (UTC), which is rejected.
        examples=["2026-10-11T18:30:00"],
    )
    use_by_date: date | None = None


class BatchResponse(BaseModel):
    """One stored inventory batch."""

    # Lets model_validate read attributes from an InventoryBatch ORM object.
    model_config = ConfigDict(from_attributes=True)

    id: int
    ingredient_id: int
    quantity_initial: float
    quantity_remaining: float
    purchased_at: datetime
    use_by_date: date | None
    depleted_at: datetime | None


class InventoryItem(BaseModel):
    """The total quantity on hand of one ingredient, across all its batches."""

    ingredient_id: int
    name: str
    canonical_unit: CanonicalUnit
    quantity_on_hand: float


@router.post("/batches", status_code=201)
def add_batch(body: BatchCreate, session: SessionDep) -> BatchResponse:
    """Record a grocery purchase as a new inventory batch.

    Args:
        body: The purchase details.
        session: The request's database session.

    Returns:
        The stored batch, with its full quantity remaining.

    Raises:
        HTTPException: 404 if the ingredient does not exist.
    """
    if session.get(Ingredient, body.ingredient_id) is None:
        raise HTTPException(
            status_code=404, detail=f"Ingredient {body.ingredient_id} not found"
        )

    batch = InventoryBatch(
        ingredient_id=body.ingredient_id,
        quantity_initial=body.quantity,
        quantity_remaining=body.quantity,
        purchased_at=body.purchased_at or datetime.now(),
        use_by_date=body.use_by_date,
    )
    session.add(batch)
    session.commit()
    return BatchResponse.model_validate(batch)


@router.get("")
def get_inventory(session: SessionDep) -> list[InventoryItem]:
    """List the total quantity on hand per ingredient, alphabetically by name.

    Ingredients with nothing left are omitted.

    Args:
        session: The request's database session.

    Returns:
        One item per ingredient with stock.
    """
    batches = session.scalars(
        select(InventoryBatch).where(InventoryBatch.quantity_remaining > 0)
    ).all()
    totals = aggregate_inventory_by_ingredient(batches)

    ingredients = session.scalars(
        select(Ingredient).where(Ingredient.id.in_(totals)).order_by(Ingredient.name)
    )
    return [
        InventoryItem(
            ingredient_id=ingredient.id,
            name=ingredient.name,
            canonical_unit=ingredient.canonical_unit,
            quantity_on_hand=totals[ingredient.id],
        )
        for ingredient in ingredients
    ]
