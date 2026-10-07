from typing import Sequence

from app.persistence.models import InventoryBatch


def aggregate_inventory_by_ingredient(batches: Sequence[InventoryBatch]) -> dict[int, float]:
    """Sum remaining quantity across inventory batches, grouped by ingredient.

    Depleted batches need no special handling: their ``quantity_remaining``
    is already zero, so they contribute nothing to the total.

    Args:
        batches: Inventory batches to aggregate, possibly spanning many
            ingredients.

    Returns:
        A mapping of ``ingredient_id`` to total quantity remaining.
    """
    totals: dict[int, float] = {}
    for batch in batches:
        totals[batch.ingredient_id] = totals.get(batch.ingredient_id, 0) + batch.quantity_remaining
    return totals
