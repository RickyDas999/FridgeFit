"""Reset the local FridgeFit database and fill it with a reproducible demo dataset.

Developer tooling, not application code. Run from the repository root, where the app's default
SQLite file lives:

    .venv/bin/python scripts/seed_demo.py

Every table is dropped and recreated, so each run produces the same known state (and picks up
the current schema). All dates are relative to when the script runs, so the demo never goes
stale: something always expires today, a meal was eaten yesterday, and so on.

Historical meals are written directly with macros derived by the domain's own
``calculate_recipe_macros``. They do not consume current inventory: the batches below describe
what is in the kitchen now.
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy.engine import make_url

from app.domain.recipe_macros import calculate_recipe_macros
from app.persistence.database import DATABASE_URL, Base, get_engine, get_session_factory
from app.persistence.enums import CanonicalUnit, IngredientRole
from app.persistence.models import (
    Ingredient,
    InventoryBatch,
    MealFeedback,
    MealLog,
    MealLogIngredient,
    NutritionGoal,
    Recipe,
    RecipeIngredient,
)

GRAM, MILLILITER, COUNT = CanonicalUnit.GRAM, CanonicalUnit.MILLILITER, CanonicalUnit.COUNT
PRIMARY, SUPPORTING, OPTIONAL = (
    IngredientRole.PRIMARY,
    IngredientRole.SUPPORTING,
    IngredientRole.OPTIONAL,
)

# name: (unit, base quantity, calories, protein, carbs, fat) per base quantity.
INGREDIENTS = {
    "Chicken breast": (GRAM, 100, 165, 31, 0, 3.6),
    "Cooked rice": (GRAM, 100, 130, 2.7, 28, 0.3),
    "Broccoli": (GRAM, 100, 34, 2.8, 7, 0.4),
    "Eggs": (COUNT, 1, 72, 6.3, 0.4, 4.8),
    "Spinach": (GRAM, 100, 23, 2.9, 3.6, 0.4),
    "Salmon": (GRAM, 100, 208, 20, 0, 13),
    "Rolled oats": (GRAM, 100, 389, 16.9, 66, 6.9),
    "Milk": (MILLILITER, 100, 42, 3.4, 5, 1),
    "Bell pepper": (GRAM, 100, 31, 1, 6, 0.3),
    "Black beans": (GRAM, 100, 132, 8.9, 23.7, 0.5),
    "Tortillas": (COUNT, 1, 140, 4, 24, 3.5),
    "Greek yogurt": (GRAM, 100, 59, 10, 3.6, 0.4),
    "Banana": (COUNT, 1, 105, 1.3, 27, 0.4),
}

# (ingredient, quantity, use-by in days from today or None, purchased days ago).
# Salmon has no batch, so the salmon plate is missing one PRIMARY ingredient; black beans are
# short, so the burrito is only partly available; one spinach batch is already expired.
BATCHES = [
    ("Chicken breast", 600, 1, 2),
    ("Chicken breast", 400, 5, 1),
    ("Cooked rice", 2000, None, 3),
    ("Broccoli", 300, 2, 2),
    ("Eggs", 12, 14, 4),
    ("Spinach", 150, 0, 3),
    ("Spinach", 100, -2, 8),
    ("Rolled oats", 1000, None, 20),
    ("Milk", 1000, 4, 2),
    ("Bell pepper", 300, 3, 2),
    ("Black beans", 100, 30, 10),
    ("Tortillas", 6, 10, 5),
    ("Greek yogurt", 500, 6, 2),
    ("Banana", 3, 3, 2),
]

# name: (servings, prep minutes, instructions, [(ingredient, quantity, role)]).
RECIPES = {
    "Chicken & broccoli rice bowl": (2, 25, ["Cook rice", "Sear chicken", "Steam broccoli"], [
        ("Chicken breast", 300, PRIMARY),
        ("Cooked rice", 300, PRIMARY),
        ("Broccoli", 200, SUPPORTING),
    ]),
    "Spinach omelette": (1, 10, ["Whisk eggs with milk", "Wilt spinach", "Fold and serve"], [
        ("Eggs", 3, PRIMARY),
        ("Spinach", 60, SUPPORTING),
        ("Milk", 30, OPTIONAL),
    ]),
    "Overnight oats": (1, 5, ["Combine oats and milk", "Refrigerate overnight", "Top"], [
        ("Rolled oats", 60, PRIMARY),
        ("Milk", 200, SUPPORTING),
        ("Banana", 1, SUPPORTING),
        ("Greek yogurt", 100, OPTIONAL),
    ]),
    "Chicken pepper stir fry": (2, 20, ["Slice chicken and peppers", "Stir fry", "Serve"], [
        ("Chicken breast", 250, PRIMARY),
        ("Bell pepper", 200, SUPPORTING),
        ("Cooked rice", 250, SUPPORTING),
        ("Broccoli", 100, OPTIONAL),
    ]),
    "Salmon rice plate": (2, 20, ["Roast salmon", "Warm rice", "Wilt spinach"], [
        ("Salmon", 300, PRIMARY),
        ("Cooked rice", 300, PRIMARY),
        ("Spinach", 100, SUPPORTING),
    ]),
    "Bean burrito": (2, 15, ["Warm beans and peppers", "Fill tortillas", "Roll"], [
        ("Tortillas", 2, PRIMARY),
        ("Black beans", 250, PRIMARY),
        ("Bell pepper", 150, SUPPORTING),
    ]),
}

# Starts well before today so it is in effect for every demo date.
GOAL = {"calories": 2200, "protein": 160, "carbs": 220, "fat": 70, "days_ago": 30}

# (recipe, days ago, hour, servings, rating or None). Today's breakfast is left unrated so the
# rating flow can be demonstrated; the rice bowl is eaten twice in the recent window.
MEALS = [
    ("Overnight oats", 0, 8, 1, None),
    ("Spinach omelette", 1, 8, 1, 4),
    ("Chicken & broccoli rice bowl", 1, 19, 1, 5),
    ("Chicken & broccoli rice bowl", 3, 19, 1, 4),
    ("Chicken pepper stir fry", 5, 19, 1, 3),
    ("Salmon rice plate", 12, 19, 1, 5),
    ("Bean burrito", 20, 13, 1, 2),
]


def at(day: date, hour: int) -> datetime:
    """Return a naive local datetime on a given day and hour.

    Args:
        day: The calendar day.
        hour: The hour of day, 0-23.

    Returns:
        The datetime at the start of that hour.
    """
    return datetime.combine(day, time(hour))


def historical_meal(recipe: Recipe, servings: float, consumed_at: datetime) -> MealLog:
    """Build a past MealLog for a recipe without touching current inventory.

    Quantities are scaled by ``servings / recipe.servings`` and macros come from
    ``calculate_recipe_macros``, so the meal matches what confirming it would have logged.

    Args:
        recipe: The recipe that was eaten, with its ingredients loaded.
        servings: How many servings were eaten.
        consumed_at: When it was eaten.

    Returns:
        An unsaved MealLog with its MealLogIngredient rows.
    """
    scale = servings / recipe.servings
    quantities = {line.id: line.quantity * scale for line in recipe.recipe_ingredients}
    macros = calculate_recipe_macros(recipe, quantity_overrides=quantities)
    return MealLog(
        recipe=recipe,
        name=recipe.name,
        consumed_at=consumed_at,
        calories=macros.calories,
        protein=macros.protein,
        carbs=macros.carbs,
        fat=macros.fat,
        meal_log_ingredients=[
            MealLogIngredient(ingredient_id=line.ingredient_id, quantity=quantities[line.id])
            for line in recipe.recipe_ingredients
        ],
    )


def seed() -> None:
    """Drop and recreate every table, then insert the demo dataset relative to now."""
    engine = get_engine(DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    now = datetime.now()
    today = now.date()

    with get_session_factory(engine)() as session:
        ingredients = {
            name: Ingredient(
                name=name,
                canonical_unit=unit,
                nutrition_base_quantity=base,
                calories_per_base_unit=calories,
                protein_per_base_unit=protein,
                carbs_per_base_unit=carbs,
                fat_per_base_unit=fat,
                nutrition_updated_at=now,
            )
            for name, (unit, base, calories, protein, carbs, fat) in INGREDIENTS.items()
        }
        session.add_all(ingredients.values())

        session.add_all(
            InventoryBatch(
                ingredient=ingredients[name],
                quantity_initial=quantity,
                quantity_remaining=quantity,
                purchased_at=at(today - timedelta(days=bought_days_ago), 10),
                use_by_date=None if use_by is None else today + timedelta(days=use_by),
            )
            for name, quantity, use_by, bought_days_ago in BATCHES
        )

        recipes = {
            name: Recipe(
                name=name,
                servings=servings,
                prep_minutes=prep,
                instructions=steps,
                recipe_ingredients=[
                    RecipeIngredient(ingredient=ingredients[i], quantity=q, role=role)
                    for i, q, role in lines
                ],
            )
            for name, (servings, prep, steps, lines) in RECIPES.items()
        }
        session.add_all(recipes.values())

        session.add(NutritionGoal(
            calories=GOAL["calories"],
            protein=GOAL["protein"],
            carbs=GOAL["carbs"],
            fat=GOAL["fat"],
            effective_date=today - timedelta(days=GOAL["days_ago"]),
        ))
        # Flush so RecipeIngredient ids exist for the macro quantity overrides below.
        session.flush()

        for recipe_name, days_ago, hour, servings, rating in MEALS:
            meal = historical_meal(
                recipes[recipe_name], servings, at(today - timedelta(days=days_ago), hour)
            )
            session.add(meal)
            if rating is not None:
                session.add(MealFeedback(meal_log=meal, rating=rating))

        session.commit()

    path = make_url(DATABASE_URL).database
    rated = sum(1 for *_, rating in MEALS if rating is not None)
    print(
        f"Seeded {path} for {today}: {len(INGREDIENTS)} ingredients, {len(BATCHES)} batches, "
        f"{len(RECIPES)} recipes, 1 nutrition goal, {len(MEALS)} past meals ({rated} rated)."
    )


if __name__ == "__main__":
    seed()
