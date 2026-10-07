from datetime import datetime

from app.domain.inventory_aggregation import aggregate_inventory_by_ingredient
from app.persistence.models import InventoryBatch


def make_batch(**overrides):
    """Build an unsaved InventoryBatch with valid defaults.

    Args:
        **overrides: InventoryBatch field values that replace the defaults.

    Returns:
        A new, unpersisted InventoryBatch.
    """
    defaults = dict(
        ingredient_id=1,
        quantity_initial=500,
        quantity_remaining=500,
        purchased_at=datetime(2026, 1, 1),
    )
    defaults.update(overrides)
    return InventoryBatch(**defaults)


def test_sums_multiple_batches_of_the_same_ingredient():
    """Batches of one ingredient are summed into a single total."""
    batches = [
        make_batch(ingredient_id=1, quantity_remaining=500),
        make_batch(ingredient_id=1, quantity_remaining=200),
    ]

    totals = aggregate_inventory_by_ingredient(batches)

    assert totals == {1: 700}


def test_keeps_different_ingredients_separate():
    """Each ingredient gets its own total."""
    batches = [
        make_batch(ingredient_id=1, quantity_remaining=500),
        make_batch(ingredient_id=2, quantity_remaining=300),
    ]

    totals = aggregate_inventory_by_ingredient(batches)

    assert totals == {1: 500, 2: 300}


def test_empty_batch_list_returns_empty_totals():
    """No batches produces an empty mapping."""
    assert aggregate_inventory_by_ingredient([]) == {}


def test_depleted_batch_contributes_zero():
    """A depleted batch adds nothing to its ingredient's total."""
    batches = [
        make_batch(ingredient_id=1, quantity_remaining=0, depleted_at=datetime(2026, 1, 5)),
        make_batch(ingredient_id=1, quantity_remaining=150),
    ]

    totals = aggregate_inventory_by_ingredient(batches)

    assert totals == {1: 150}
