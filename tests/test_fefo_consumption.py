from datetime import date, datetime

from app.domain.fefo_consumption import plan_fefo_consumption
from app.persistence.models import InventoryBatch


def make_batch(**overrides):
    defaults = dict(
        ingredient_id=1,
        quantity_initial=500,
        quantity_remaining=500,
        purchased_at=datetime(2026, 1, 1),
    )
    defaults.update(overrides)
    return InventoryBatch(**defaults)


def test_single_batch_covers_the_need():
    batch = make_batch(quantity_remaining=500)

    plan = plan_fefo_consumption([batch], quantity_needed=200)

    assert len(plan) == 1
    assert plan[0].batch is batch
    assert plan[0].quantity == 200


def test_draws_from_next_batch_once_first_is_exhausted():
    first = make_batch(quantity_remaining=100, use_by_date=date(2026, 1, 10))
    second = make_batch(quantity_remaining=500, use_by_date=date(2026, 1, 20))

    plan = plan_fefo_consumption([first, second], quantity_needed=300)

    assert [(p.batch, p.quantity) for p in plan] == [(first, 100), (second, 200)]


def test_earliest_use_by_date_is_drawn_first_regardless_of_purchase_date():
    expires_soon = make_batch(purchased_at=datetime(2026, 1, 10), use_by_date=date(2026, 2, 1), quantity_remaining=100)
    expires_later = make_batch(purchased_at=datetime(2026, 1, 1), use_by_date=date(2026, 3, 1), quantity_remaining=100)

    plan = plan_fefo_consumption([expires_later, expires_soon], quantity_needed=50)

    assert plan[0].batch is expires_soon


def test_batches_without_use_by_date_are_drawn_last():
    no_expiry = make_batch(use_by_date=None, purchased_at=datetime(2026, 1, 1), quantity_remaining=100)
    has_expiry = make_batch(use_by_date=date(2026, 6, 1), purchased_at=datetime(2026, 5, 1), quantity_remaining=100)

    plan = plan_fefo_consumption([no_expiry, has_expiry], quantity_needed=150)

    assert plan[0].batch is has_expiry
    assert plan[1].batch is no_expiry


def test_falls_back_to_oldest_purchase_date_when_no_use_by_date():
    older = make_batch(use_by_date=None, purchased_at=datetime(2026, 1, 1), quantity_remaining=100)
    newer = make_batch(use_by_date=None, purchased_at=datetime(2026, 3, 1), quantity_remaining=100)

    plan = plan_fefo_consumption([newer, older], quantity_needed=50)

    assert plan[0].batch is older


def test_depleted_batches_are_skipped():
    depleted = make_batch(quantity_remaining=0, depleted_at=datetime(2026, 1, 5))
    available = make_batch(quantity_remaining=100)

    plan = plan_fefo_consumption([depleted, available], quantity_needed=50)

    assert len(plan) == 1
    assert plan[0].batch is available


def test_partial_fulfillment_when_inventory_is_insufficient():
    only_batch = make_batch(quantity_remaining=100)

    plan = plan_fefo_consumption([only_batch], quantity_needed=300)

    assert len(plan) == 1
    assert plan[0].quantity == 100
    assert sum(p.quantity for p in plan) < 300
