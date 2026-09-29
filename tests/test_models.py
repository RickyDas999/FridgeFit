from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.enums import CanonicalUnit, IngredientRole
from app.models import Ingredient, InventoryBatch, Recipe, RecipeIngredient


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def make_ingredient(**overrides):
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


def test_ingredient_persists_and_retrieves(session):
    session.add(make_ingredient())
    session.commit()

    fetched = session.query(Ingredient).filter_by(name="Chicken Breast").one()
    assert fetched.canonical_unit == CanonicalUnit.GRAM
    assert fetched.calories_per_base_unit == 165


def test_ingredient_has_many_batches(session):
    ingredient = make_ingredient()
    session.add(ingredient)
    session.commit()

    session.add_all([
        InventoryBatch(
            ingredient_id=ingredient.id,
            quantity_initial=500,
            quantity_remaining=500,
            purchased_at=datetime(2026, 1, 1),
        ),
        InventoryBatch(
            ingredient_id=ingredient.id,
            quantity_initial=500,
            quantity_remaining=200,
            purchased_at=datetime(2026, 1, 8),
        ),
    ])
    session.commit()

    session.refresh(ingredient)
    assert len(ingredient.batches) == 2


def test_batches_do_not_duplicate_nutrition_data(session):
    ingredient = make_ingredient()
    session.add(ingredient)
    session.commit()

    batch = InventoryBatch(
        ingredient_id=ingredient.id,
        quantity_initial=500,
        quantity_remaining=500,
        purchased_at=datetime(2026, 1, 1),
    )
    session.add(batch)
    session.commit()

    assert not hasattr(batch, "calories_per_base_unit")
    assert batch.ingredient.calories_per_base_unit == 165


def test_use_by_date_is_nullable(session):
    ingredient = make_ingredient()
    session.add(ingredient)
    session.commit()

    batch = InventoryBatch(
        ingredient_id=ingredient.id,
        quantity_initial=500,
        quantity_remaining=500,
        purchased_at=datetime(2026, 1, 1),
        use_by_date=None,
    )
    session.add(batch)
    session.commit()

    assert batch.use_by_date is None


def test_negative_quantity_remaining_rejected(session):
    ingredient = make_ingredient()
    session.add(ingredient)
    session.commit()

    session.add(InventoryBatch(
        ingredient_id=ingredient.id,
        quantity_initial=500,
        quantity_remaining=-10,
        purchased_at=datetime(2026, 1, 1),
    ))
    with pytest.raises(IntegrityError):
        session.commit()


def test_negative_calories_rejected(session):
    session.add(make_ingredient(calories_per_base_unit=-1))
    with pytest.raises(IntegrityError):
        session.commit()


def make_recipe(**overrides):
    defaults = dict(
        name="Grilled Chicken Bowl",
        instructions=["Season chicken", "Grill 6 minutes per side", "Slice and serve"],
    )
    defaults.update(overrides)
    return Recipe(**defaults)


def test_recipe_persists_and_retrieves(session):
    session.add(make_recipe())
    session.commit()

    fetched = session.query(Recipe).filter_by(name="Grilled Chicken Bowl").one()
    assert fetched.instructions[1] == "Grill 6 minutes per side"


def test_recipe_source_url_is_nullable(session):
    session.add(make_recipe())
    session.commit()

    fetched = session.query(Recipe).filter_by(name="Grilled Chicken Bowl").one()
    assert fetched.source_url is None


def test_recipe_has_many_recipe_ingredients(session):
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    session.add_all([
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=ingredient.id,
            quantity=200,
            role=IngredientRole.PRIMARY,
        ),
        RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=ingredient.id,
            quantity=5,
            role=IngredientRole.SUPPORTING,
        ),
    ])
    session.commit()

    session.refresh(recipe)
    assert len(recipe.recipe_ingredients) == 2


def test_recipe_ingredient_does_not_duplicate_nutrition_data(session):
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    recipe_ingredient = RecipeIngredient(
        recipe_id=recipe.id,
        ingredient_id=ingredient.id,
        quantity=200,
        role=IngredientRole.PRIMARY,
    )
    session.add(recipe_ingredient)
    session.commit()

    assert not hasattr(recipe_ingredient, "calories_per_base_unit")
    assert recipe_ingredient.ingredient.calories_per_base_unit == 165


def test_negative_recipe_ingredient_quantity_rejected(session):
    ingredient = make_ingredient()
    recipe = make_recipe()
    session.add_all([ingredient, recipe])
    session.commit()

    session.add(RecipeIngredient(
        recipe_id=recipe.id,
        ingredient_id=ingredient.id,
        quantity=-1,
        role=IngredientRole.PRIMARY,
    ))
    with pytest.raises(IntegrityError):
        session.commit()

def test_recipe_ingredient_requires_real_recipe(session):
    ingredient = make_ingredient()
    session.add(ingredient)
    session.commit()

    session.add(RecipeIngredient(
        recipe_id=9999,
        ingredient_id=ingredient.id,
        quantity=100,
        role=IngredientRole.PRIMARY,
    ))
    with pytest.raises(IntegrityError):
        session.commit()