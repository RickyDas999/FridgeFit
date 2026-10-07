from datetime import date
from typing import NamedTuple, Sequence

from app.domain.validation import validate_quantity_needed, validate_single_ingredient_batches
from app.persistence.models import InventoryBatch


class BatchConsumption(NamedTuple):
    """A planned draw of a specific quantity from a single inventory batch."""

    batch: InventoryBatch
    quantity: float


def plan_fefo_consumption(
    batches: Sequence[InventoryBatch], quantity_needed: float
) -> list[BatchConsumption]:
    """Plan which batches to consume from using first-expire, first-out ordering.

    Batches are ordered by ``use_by_date`` ascending, then by ``purchased_at``
    ascending as a tiebreaker. This function only plans; it never mutates
    the batches.

    Args:
        batches: Candidate batches, all for the same ingredient. Batches with no
            remaining quantity are skipped.
        quantity_needed: Total quantity to draw.

    Returns:
        Planned draws in consumption order. If inventory is insufficient, the
        plan covers only what is available; callers detect the shortfall by
        comparing the summed quantities against ``quantity_needed``.

    Raises:
        InvalidInputError: If ``quantity_needed`` is not positive or the batches span more
            than one ingredient.
    """
    validate_quantity_needed(quantity_needed)
    validate_single_ingredient_batches(batches)

    ordered = sorted(
        (batch for batch in batches if batch.quantity_remaining > 0),
        # date.max stands in for a missing use_by_date: undated batches sort
        # last, and None is never compared directly (which would raise).
        key=lambda batch: (batch.use_by_date or date.max, batch.purchased_at),
    )

    plan = []
    remaining_needed = quantity_needed
    for batch in ordered:
        if remaining_needed <= 0:
            break
        take = min(batch.quantity_remaining, remaining_needed)
        plan.append(BatchConsumption(batch=batch, quantity=take))
        remaining_needed -= take

    return plan
