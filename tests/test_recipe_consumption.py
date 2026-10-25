from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.domain.recipe_consumption import plan_recipe_consumption
from app.errors import InvalidInputError
from app.persistence.enums import IngredientRole
from app.persistence.models import InventoryBatch, Recipe, RecipeIngredient

CHICKEN, RICE = 1, 2
PRIMARY = IngredientRole.PRIMARY


def make_recipe():
    """Build an unsaved 2-serving recipe: 200 chicken and 300 rice, with fixed line ids.

    Returns:
        A Recipe whose lines have ids 10 (chicken) and 20 (rice).
    """
    return Recipe(
        name="Bowl",
        instructions=["Cook"],
        prep_minutes=20,
        servings=2,
        recipe_ingredients=[
            RecipeIngredient(id=10, ingredient_id=CHICKEN, quantity=200, role=PRIMARY),
            RecipeIngredient(id=20, ingredient_id=RICE, quantity=300, role=PRIMARY),
        ],
    )


def make_batch(ingredient_id, quantity, use_by):
    """Build an unsaved batch.

    Args:
        ingredient_id: The batch's ingredient.
        quantity: Quantity remaining.
        use_by: Use-by date, or None.

    Returns:
        An InventoryBatch not attached to any session.
    """
    return InventoryBatch(
        ingredient_id=ingredient_id,
        quantity_initial=quantity,
        quantity_remaining=quantity,
        purchased_at=datetime(2026, 1, 1),
        use_by_date=use_by,
    )


def test_one_serving_draws_the_scaled_quantity_first_expiring_first():
    """One of two servings needs half of each line, drawn from the earliest use-by first."""
    soon = make_batch(CHICKEN, 60, date(2026, 1, 3))
    later = make_batch(CHICKEN, 500, date(2026, 1, 9))

    plan = plan_recipe_consumption(
        make_recipe(), 1, {CHICKEN: [later, soon], RICE: [make_batch(RICE, 1000, None)]}
    )

    chicken = plan.lines[0]
    assert chicken.quantity_needed == 100
    assert [(draw.batch, draw.quantity) for draw in chicken.draws] == [(soon, 60), (later, 40)]
    assert plan.fulfilled_quantities == {10: 100, 20: 150}
    assert plan.shortfalls == {}


def test_short_stock_is_drawn_as_far_as_it_goes_and_reported():
    """A short ingredient draws everything available and records needed vs. available."""
    plan = plan_recipe_consumption(make_recipe(), 1, {CHICKEN: [make_batch(CHICKEN, 30, None)]})

    assert plan.fulfilled_quantities == {10: 30, 20: 0}
    assert plan.shortfalls == {CHICKEN: (100, 30), RICE: (150, 0)}


def test_planning_never_changes_the_batches():
    """The plan only describes draws; batch quantities stay as they were."""
    batch = make_batch(CHICKEN, 500, None)

    plan_recipe_consumption(make_recipe(), 2, {CHICKEN: [batch]})

    assert batch.quantity_remaining == 500


def test_any_object_with_the_batch_fields_can_stand_in_for_a_batch():
    """Plain in-memory copies work as batches, so callers can plan without database objects."""
    chicken, rice = (
        SimpleNamespace(
            ingredient_id=ingredient_id,
            quantity_remaining=500,
            use_by_date=None,
            purchased_at=datetime(2026, 1, 1),
        )
        for ingredient_id in (CHICKEN, RICE)
    )

    plan = plan_recipe_consumption(make_recipe(), 1, {CHICKEN: [chicken], RICE: [rice]})

    assert plan.lines[0].draws[0].batch is chicken
    assert plan.shortfalls == {}


def test_non_positive_servings_are_rejected():
    """Servings must be positive, as in meal confirmation."""
    with pytest.raises(InvalidInputError):
        plan_recipe_consumption(make_recipe(), 0, {})
