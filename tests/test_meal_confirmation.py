from datetime import date, datetime

import pytest

from app.domain.meal_confirmation import InsufficientInventoryError, confirm_meal
from app.persistence.enums import CanonicalUnit, IngredientRole
from app.persistence.models import (
    Ingredient,
    InventoryBatch,
    MealLog,
    MealLogIngredient,
    Recipe,
    RecipeIngredient,
)


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


def make_recipe(**overrides):
    """Build an unsaved Recipe with valid defaults.

    Args:
        **overrides: Recipe field values that replace the defaults.

    Returns:
        A new, unpersisted Recipe.
    """
    defaults = dict(
        name="Grilled Chicken Bowl",
        instructions=["Season chicken", "Grill 6 minutes per side"],
        prep_minutes=20,
        servings=2,
    )
    defaults.update(overrides)
    return Recipe(**defaults)


def test_confirming_a_meal_creates_a_linked_meal_log_with_derived_macros(session):
    """Confirmation creates a recipe-linked MealLog with calculated macros."""
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    session.add(RecipeIngredient(
        recipe_id=recipe.id,
        ingredient_id=ingredient.id,
        quantity=200,
        role=IngredientRole.PRIMARY,
    ))
    session.add(InventoryBatch(
        ingredient_id=ingredient.id,
        quantity_initial=500,
        quantity_remaining=500,
        purchased_at=datetime(2026, 1, 1),
    ))
    session.commit()
    session.refresh(recipe)

    meal_log = confirm_meal(session, recipe, consumed_at=datetime(2026, 1, 15, 12, 0))

    assert meal_log.recipe_id == recipe.id
    assert meal_log.calories == pytest.approx(330)
    assert meal_log.protein == pytest.approx(62)
    assert session.query(MealLog).count() == 1


def test_confirming_a_meal_records_meal_log_ingredients(session):
    """Confirmation records a MealLogIngredient per consumed ingredient."""
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    session.add(RecipeIngredient(
        recipe_id=recipe.id,
        ingredient_id=ingredient.id,
        quantity=200,
        role=IngredientRole.PRIMARY,
    ))
    session.add(InventoryBatch(
        ingredient_id=ingredient.id,
        quantity_initial=500,
        quantity_remaining=500,
        purchased_at=datetime(2026, 1, 1),
    ))
    session.commit()
    session.refresh(recipe)

    meal_log = confirm_meal(session, recipe, consumed_at=datetime(2026, 1, 15, 12, 0))

    logged = session.query(MealLogIngredient).filter_by(meal_log_id=meal_log.id).one()
    assert logged.ingredient_id == ingredient.id
    assert logged.quantity == 200


def test_confirming_a_meal_consumes_earliest_expiring_batch_first(session):
    """Confirmation consumes inventory in FEFO order and marks emptied batches depleted."""
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    session.add(RecipeIngredient(
        recipe_id=recipe.id,
        ingredient_id=ingredient.id,
        quantity=150,
        role=IngredientRole.PRIMARY,
    ))
    expiring_soon = InventoryBatch(
        ingredient_id=ingredient.id,
        quantity_initial=100,
        quantity_remaining=100,
        purchased_at=datetime(2026, 1, 1),
        use_by_date=date(2026, 1, 20),
    )
    expiring_later = InventoryBatch(
        ingredient_id=ingredient.id,
        quantity_initial=200,
        quantity_remaining=200,
        purchased_at=datetime(2026, 1, 5),
        use_by_date=date(2026, 2, 20),
    )
    session.add_all([expiring_soon, expiring_later])
    session.commit()
    session.refresh(recipe)

    confirm_meal(session, recipe, consumed_at=datetime(2026, 1, 15, 12, 0))

    assert expiring_soon.quantity_remaining == 0
    assert expiring_soon.depleted_at is not None
    assert expiring_later.quantity_remaining == 150


def test_insufficient_inventory_raises_and_writes_nothing(session):
    """Without an override, a shortfall raises and leaves the database untouched."""
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    session.add(RecipeIngredient(
        recipe_id=recipe.id,
        ingredient_id=ingredient.id,
        quantity=500,
        role=IngredientRole.PRIMARY,
    ))
    batch = InventoryBatch(
        ingredient_id=ingredient.id,
        quantity_initial=100,
        quantity_remaining=100,
        purchased_at=datetime(2026, 1, 1),
    )
    session.add(batch)
    session.commit()
    session.refresh(recipe)

    with pytest.raises(InsufficientInventoryError):
        confirm_meal(session, recipe, consumed_at=datetime(2026, 1, 15, 12, 0))

    assert session.query(MealLog).count() == 0
    assert batch.quantity_remaining == 100


def test_explicit_override_consumes_only_available_inventory_and_scales_macros(session):
    """With an override, only available inventory is consumed and macros reflect it."""
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    session.add(RecipeIngredient(
        recipe_id=recipe.id,
        ingredient_id=ingredient.id,
        quantity=220,
        role=IngredientRole.PRIMARY,
    ))
    batch = InventoryBatch(
        ingredient_id=ingredient.id,
        quantity_initial=150,
        quantity_remaining=150,
        purchased_at=datetime(2026, 1, 1),
    )
    session.add(batch)
    session.commit()
    session.refresh(recipe)

    meal_log = confirm_meal(
        session, recipe, consumed_at=datetime(2026, 1, 15, 12, 0), allow_shortfall=True
    )

    logged = session.query(MealLogIngredient).filter_by(meal_log_id=meal_log.id).one()
    assert logged.quantity == 150
    assert batch.quantity_remaining == 0
    assert batch.depleted_at is not None
    # 150g of chicken (165 cal/100g), not the recipe's full 220g
    assert meal_log.calories == pytest.approx(165 * 1.5)


def test_explicit_override_with_zero_available_skips_meal_log_ingredient(session):
    """With an override and no inventory, no MealLogIngredient row is created."""
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    session.add(RecipeIngredient(
        recipe_id=recipe.id,
        ingredient_id=ingredient.id,
        quantity=200,
        role=IngredientRole.PRIMARY,
    ))
    session.commit()
    session.refresh(recipe)

    meal_log = confirm_meal(
        session, recipe, consumed_at=datetime(2026, 1, 15, 12, 0), allow_shortfall=True
    )

    assert session.query(MealLogIngredient).filter_by(meal_log_id=meal_log.id).count() == 0
    assert meal_log.calories == pytest.approx(0)


def test_explicit_override_with_mixed_sufficient_and_short_ingredients(session):
    """With an override, each ingredient is logged at the amount actually consumed."""
    chicken = make_ingredient()
    rice = make_ingredient(
        name="Rice",
        calories_per_base_unit=130,
        protein_per_base_unit=2.7,
        carbs_per_base_unit=28,
        fat_per_base_unit=0.3,
    )
    recipe = make_recipe()
    session.add_all([chicken, rice, recipe])
    session.commit()

    session.add_all([
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=chicken.id,
            quantity=220,
            role=IngredientRole.PRIMARY,
        ),
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=rice.id,
            quantity=150,
            role=IngredientRole.SUPPORTING,
        ),
        InventoryBatch(
            ingredient_id=chicken.id,
            quantity_initial=150,
            quantity_remaining=150,
            purchased_at=datetime(2026, 1, 1),
        ),
        InventoryBatch(
            ingredient_id=rice.id,
            quantity_initial=500,
            quantity_remaining=500,
            purchased_at=datetime(2026, 1, 1),
        ),
    ])
    session.commit()
    session.refresh(recipe)

    meal_log = confirm_meal(
        session, recipe, consumed_at=datetime(2026, 1, 15, 12, 0), allow_shortfall=True
    )

    logged = {
        mli.ingredient_id: mli.quantity
        for mli in session.query(MealLogIngredient).filter_by(meal_log_id=meal_log.id).all()
    }
    assert logged == {chicken.id: 150, rice.id: 150}


def test_confirming_a_meal_with_multiple_ingredients(session):
    """Confirmation logs every ingredient of a multi-ingredient recipe."""
    chicken = make_ingredient()
    rice = make_ingredient(
        name="Rice",
        calories_per_base_unit=130,
        protein_per_base_unit=2.7,
        carbs_per_base_unit=28,
        fat_per_base_unit=0.3,
    )
    recipe = make_recipe()
    session.add_all([chicken, rice, recipe])
    session.commit()

    session.add_all([
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=chicken.id,
            quantity=200,
            role=IngredientRole.PRIMARY,
        ),
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=rice.id,
            quantity=150,
            role=IngredientRole.SUPPORTING,
        ),
        InventoryBatch(
            ingredient_id=chicken.id,
            quantity_initial=500,
            quantity_remaining=500,
            purchased_at=datetime(2026, 1, 1),
        ),
        InventoryBatch(
            ingredient_id=rice.id,
            quantity_initial=500,
            quantity_remaining=500,
            purchased_at=datetime(2026, 1, 1),
        ),
    ])
    session.commit()
    session.refresh(recipe)

    meal_log = confirm_meal(session, recipe, consumed_at=datetime(2026, 1, 15, 12, 0))

    logged_ingredient_ids = {
        mli.ingredient_id
        for mli in session.query(MealLogIngredient).filter_by(meal_log_id=meal_log.id).all()
    }
    assert logged_ingredient_ids == {chicken.id, rice.id}
