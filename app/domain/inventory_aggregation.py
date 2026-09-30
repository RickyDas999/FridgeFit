from typing import Sequence

from app.persistence.models import InventoryBatch


def aggregate_inventory_by_ingredient(batches: Sequence[InventoryBatch]) -> dict[int, float]:
    totals: dict[int, float] = {}
    for batch in batches:
        totals[batch.ingredient_id] = totals.get(batch.ingredient_id, 0) + batch.quantity_remaining
    return totals
