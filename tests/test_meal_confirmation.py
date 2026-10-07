from datetime import date, datetime

import pytest

from app.domain.meal_confirmation import InsufficientInventoryError, confirm_meal
from app.errors import InvalidInputError
from app.persistence.enums import CanonicalUnit, IngredientRole
from app.persistence.models import (
    Ingredient,
    InventoryBatch,
    MealLog,
    MealLogIngredient,
    Recipe,
    RecipeIngredient,
)

CONSUMED_AT = datetime(2026, 1, 15, 12, 0)


def make_ingredient(**overrides):
    """Build an unsaved Ingredient with chicken-breast defaults.

    Args:
        **overrides: Ingredient field values that replace the defaults.

    Returns:
        A new, unpersisted Ingredient.
    """
    defaults = dict(
        name="Chicken Breast",
        canonical_unit=CanonicalUnit.GRAM,
        nutrition_base_quantity=100,
        calories_per_base_unit=165,
        protein_per_base_unit=31,
        carbs_per_base_unit=0,
        fat_per_base_unit=3.6,
        nutrition_updated_at=datetime(2026, 1, 1),
    )
    defaults.update(overrides)
    return Ingredient(**defaults)


def make_rice():
    """Build an unsaved rice Ingredient.

    Returns:
        A new, unpersisted Ingredient with rice nutrition data.
    """
    return make_ingredient(
        name="Rice",
        calories_per_base_unit=130,
        protein_per_base_unit=2.7,
        carbs_per_base_unit=28,
        fat_per_base_unit=0.3,
    )


def make_recipe(*ingredients):
    """Build an unsaved Recipe from ingredient specs.

    Args:
        *ingredients: ``(ingredient, quantity, role)`` tuples, one per RecipeIngredient.

    Returns:
        A new, unpersisted Recipe with its RecipeIngredients attached.
    """
    return Recipe(
        name="Grilled Chicken Bowl",
        instructions=["Season chicken", "Grill 6 minutes per side"],
        prep_minutes=20,
        servings=2,
        recipe_ingredients=[
            RecipeIngredient(ingredient=ingredient, quantity=quantity, role=role)
            for ingredient, quantity, role in ingredients
        ],
    )


def make_batch(ingredient, quantity, **overrides):
    """Build an unsaved InventoryBatch for an ingredient, full to the given quantity.

    Args:
        ingredient: The Ingredient the batch belongs to.
        quantity: Initial and remaining quantity of the batch.
        **overrides: InventoryBatch field values that replace the defaults.

    Returns:
        A new, unpersisted InventoryBatch.
    """
    defaults = dict(
        ingredient=ingredient,
        quantity_initial=quantity,
        quantity_remaining=quantity,
        purchased_at=datetime(2026, 1, 1),
    )
    defaults.update(overrides)
    return InventoryBatch(**defaults)


def test_confirming_a_meal_creates_a_linked_meal_log_with_derived_macros(session):
    """Confirmation creates a recipe-linked MealLog with calculated macros."""
    chicken = make_ingredient()
    recipe = make_recipe((chicken, 200, IngredientRole.PRIMARY))
    session.add_all([recipe, make_batch(chicken, 500)])
    session.commit()

    meal_log = confirm_meal(session, recipe, consumed_at=CONSUMED_AT)

    assert meal_log.recipe_id == recipe.id
    assert meal_log.calories == pytest.approx(330)
    assert meal_log.protein == pytest.approx(62)
    assert session.query(MealLog).count() == 1


def test_confirming_a_meal_records_meal_log_ingredients(session):
    """Confirmation records a MealLogIngredient per consumed ingredient."""
    chicken = make_ingredient()
    recipe = make_recipe((chicken, 200, IngredientRole.PRIMARY))
    session.add_all([recipe, make_batch(chicken, 500)])
    session.commit()

    meal_log = confirm_meal(session, recipe, consumed_at=CONSUMED_AT)

    logged = session.query(MealLogIngredient).filter_by(meal_log_id=meal_log.id).one()
    assert logged.ingredient_id == chicken.id
    assert logged.quantity == 200


def test_confirming_a_meal_consumes_earliest_expiring_batch_first(session):
    """Confirmation consumes inventory in FEFO order and marks emptied batches depleted."""
    chicken = make_ingredient()
    recipe = make_recipe((chicken, 150, IngredientRole.PRIMARY))
    expiring_soon = make_batch(chicken, 100, use_by_date=date(2026, 1, 20))
    expiring_later = make_batch(
        chicken, 200, purchased_at=datetime(2026, 1, 5), use_by_date=date(2026, 2, 20)
    )
    session.add_all([recipe, expiring_soon, expiring_later])
    session.commit()

    confirm_meal(session, recipe, consumed_at=CONSUMED_AT)

    assert expiring_soon.quantity_remaining == 0
    assert expiring_soon.depleted_at is not None
    assert expiring_later.quantity_remaining == 150


def test_insufficient_inventory_raises_and_writes_nothing(session):
    """Without an override, a shortfall raises and leaves the database untouched."""
    chicken = make_ingredient()
    recipe = make_recipe((chicken, 500, IngredientRole.PRIMARY))
    batch = make_batch(chicken, 100)
    session.add_all([recipe, batch])
    session.commit()

    with pytest.raises(InsufficientInventoryError):
        confirm_meal(session, recipe, consumed_at=CONSUMED_AT)

    assert session.query(MealLog).count() == 0
    assert batch.quantity_remaining == 100


def test_explicit_override_consumes_only_available_inventory_and_scales_macros(session):
    """With an override, only available inventory is consumed and macros reflect it."""
    chicken = make_ingredient()
    recipe = make_recipe((chicken, 220, IngredientRole.PRIMARY))
    batch = make_batch(chicken, 150)
    session.add_all([recipe, batch])
    session.commit()

    meal_log = confirm_meal(session, recipe, consumed_at=CONSUMED_AT, allow_shortfall=True)

    logged = session.query(MealLogIngredient).filter_by(meal_log_id=meal_log.id).one()
    assert logged.quantity == 150
    assert batch.quantity_remaining == 0
    assert batch.depleted_at is not None
    # 150g of chicken (165 cal/100g), not the recipe's full 220g
    assert meal_log.calories == pytest.approx(165 * 1.5)


def test_explicit_override_with_zero_available_skips_meal_log_ingredient(session):
    """With an override and no inventory, no MealLogIngredient row is created."""
    recipe = make_recipe((make_ingredient(), 200, IngredientRole.PRIMARY))
    session.add(recipe)
    session.commit()

    meal_log = confirm_meal(session, recipe, consumed_at=CONSUMED_AT, allow_shortfall=True)

    assert session.query(MealLogIngredient).filter_by(meal_log_id=meal_log.id).count() == 0
    assert meal_log.calories == pytest.approx(0)


def test_explicit_override_with_mixed_sufficient_and_short_ingredients(session):
    """With an override, each ingredient is logged at the amount actually consumed."""
    chicken = make_ingredient()
    rice = make_rice()
    recipe = make_recipe(
        (chicken, 220, IngredientRole.PRIMARY), (rice, 150, IngredientRole.SUPPORTING)
    )
    session.add_all([recipe, make_batch(chicken, 150), make_batch(rice, 500)])
    session.commit()

    meal_log = confirm_meal(session, recipe, consumed_at=CONSUMED_AT, allow_shortfall=True)

    logged = {
        mli.ingredient_id: mli.quantity
        for mli in session.query(MealLogIngredient).filter_by(meal_log_id=meal_log.id).all()
    }
    assert logged == {chicken.id: 150, rice.id: 150}


def test_confirming_a_meal_with_multiple_ingredients(session):
    """Confirmation logs every ingredient of a multi-ingredient recipe."""
    chicken = make_ingredient()
    rice = make_rice()
    recipe = make_recipe(
        (chicken, 200, IngredientRole.PRIMARY), (rice, 150, IngredientRole.SUPPORTING)
    )
    session.add_all([recipe, make_batch(chicken, 500), make_batch(rice, 500)])
    session.commit()

    meal_log = confirm_meal(session, recipe, consumed_at=CONSUMED_AT)

    logged_ingredient_ids = {
        mli.ingredient_id
        for mli in session.query(MealLogIngredient).filter_by(meal_log_id=meal_log.id).all()
    }
    assert logged_ingredient_ids == {chicken.id, rice.id}


def test_recipe_with_no_ingredients_is_rejected_and_writes_nothing(session):
    """Confirming a recipe with no ingredients raises before anything is written."""
    with pytest.raises(InvalidInputError):
        confirm_meal(session, make_recipe(), consumed_at=CONSUMED_AT)

    assert session.query(MealLog).count() == 0
