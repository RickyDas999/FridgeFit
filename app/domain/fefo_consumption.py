from datetime import date
from typing import NamedTuple, Sequence

from app.persistence.models import InventoryBatch


class BatchConsumption(NamedTuple):
    batch: InventoryBatch
    quantity: float


def plan_fefo_consumption(batches: Sequence[InventoryBatch], quantity_needed: float) -> list[BatchConsumption]:
    ordered = sorted(
        (batch for batch in batches if batch.quantity_remaining > 0),
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
