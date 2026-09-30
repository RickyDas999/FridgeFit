from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.enums import CanonicalUnit, IngredientRole
from app.models import (
    Ingredient,
    InventoryBatch,
    MealFeedback,
    MealLog,
    MealLogIngredient,
    NutritionGoal,
    Recipe,
    RecipeIngredient,
)


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
        prep_minutes=20,
        servings=2,
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


def make_meal_log(**overrides):
    defaults = dict(
        name="Chicken and Rice",
        calories=450,
        protein=35,
        carbs=20,
        fat=15,
        consumed_at=datetime(2026, 1, 1, 12, 30),
    )
    defaults.update(overrides)
    return MealLog(**defaults)


def test_meal_log_persists_and_retrieves(session):
    session.add(make_meal_log())
    session.commit()

    fetched = session.query(MealLog).one()
    assert fetched.calories == 450
    assert fetched.consumed_at == datetime(2026, 1, 1, 12, 30)


def test_meal_log_has_many_meal_log_ingredients(session):
    ingredient = make_ingredient()
    meal_log = make_meal_log()
    session.add_all([ingredient, meal_log])
    session.commit()

    session.add_all([
        MealLogIngredient(meal_log_id=meal_log.id, ingredient_id=ingredient.id, quantity=150),
        MealLogIngredient(meal_log_id=meal_log.id, ingredient_id=ingredient.id, quantity=10),
    ])
    session.commit()

    session.refresh(meal_log)
    assert len(meal_log.meal_log_ingredients) == 2


def test_meal_log_macros_do_not_change_if_ingredient_nutrition_changes(session):
    ingredient = make_ingredient()
    meal_log = make_meal_log(calories=450)
    session.add_all([ingredient, meal_log])
    session.commit()

    session.add(MealLogIngredient(meal_log_id=meal_log.id, ingredient_id=ingredient.id, quantity=150))
    session.commit()

    ingredient.calories_per_base_unit = 999
    session.commit()

    session.refresh(meal_log)
    assert meal_log.calories == 450


def test_negative_meal_log_calories_rejected(session):
    session.add(make_meal_log(calories=-1))
    with pytest.raises(IntegrityError):
        session.commit()

def test_macro_only_meal_saves_no_meal_ingredients(session):
    session.add(make_meal_log())
    session.commit()
    meal_log = session.query(MealLog).one()

    assert meal_log.meal_log_ingredients == []


def make_nutrition_goal(**overrides):
    defaults = dict(
        calories=2200,
        protein=160,
        carbs=220,
        fat=70,
        effective_date=date(2026, 1, 1),
    )
    defaults.update(overrides)
    return NutritionGoal(**defaults)


def test_nutrition_goal_persists_and_retrieves(session):
    session.add(make_nutrition_goal())
    session.commit()

    fetched = session.query(NutritionGoal).one()
    assert fetched.calories == 2200
    assert fetched.effective_date == date(2026, 1, 1)


def test_changing_goal_preserves_prior_goal_history(session):
    session.add(make_nutrition_goal(effective_date=date(2026, 1, 1), calories=2200))
    session.commit()

    session.add(make_nutrition_goal(effective_date=date(2026, 3, 1), calories=2000))
    session.commit()

    goals = session.query(NutritionGoal).order_by(NutritionGoal.effective_date).all()
    assert [g.calories for g in goals] == [2200, 2000]


def test_negative_nutrition_goal_calories_rejected(session):
    session.add(make_nutrition_goal(calories=-1))
    with pytest.raises(IntegrityError):
        session.commit()


def test_meal_feedback_persists_and_retrieves(session):
    meal_log = make_meal_log()
    session.add(meal_log)
    session.commit()

    session.add(MealFeedback(meal_log_id=meal_log.id, rating=4))
    session.commit()

    fetched = session.query(MealFeedback).one()
    assert fetched.rating == 4
    assert fetched.meal_log.calories == 450


def test_second_feedback_for_same_meal_log_rejected(session):
    meal_log = make_meal_log()
    session.add(meal_log)
    session.commit()

    session.add(MealFeedback(meal_log_id=meal_log.id, rating=4))
    session.commit()

    session.add(MealFeedback(meal_log_id=meal_log.id, rating=2))
    with pytest.raises(IntegrityError):
        session.commit()

def test_higher_than_range_meal_feedback(session):
    meal_log = make_meal_log()
    session.add(meal_log)
    session.commit()

    session.add(MealFeedback(meal_log_id=meal_log.id, rating=6))
    with pytest.raises(IntegrityError):
        session.commit()

def test_lower_than_range_meal_feedback(session):
    meal_log = make_meal_log()
    session.add(meal_log)
    session.commit()

    session.add(MealFeedback(meal_log_id=meal_log.id, rating=0))
    with pytest.raises(IntegrityError):
        session.commit()