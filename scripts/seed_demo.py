"""Fill a FridgeFit database with a reproducible demo dataset.

Developer and deployment tooling, not application code. Run from the repository root. It uses
the same database as the API (``DATABASE_URL``, or the local SQLite file). Two modes:

    .venv/bin/python scripts/seed_demo.py                # reset, local SQLite only
    .venv/bin/python scripts/seed_demo.py --insert-only  # add to an empty database, any kind

The default resets: every table is dropped and rebuilt by the Alembic migrations, so each run
produces the same known state. It refuses any non-SQLite database, so it cannot wipe a deployed
PostgreSQL database.

``--insert-only`` never drops or changes anything: it adds the dataset only to a database that
is already at the latest migration and holds no rows at all, and refuses otherwise. This is how
a deployed database gets its demo data, once.

All dates are relative to when the data is inserted: something expires today, a meal was eaten
yesterday, and so on. A reset keeps the local demo current; inserted-once data ages.

Historical meals are written directly with macros derived by the domain's own
``calculate_recipe_macros``. They do not consume current inventory: the batches below describe
what is in the kitchen now.
"""

import argparse
from datetime import date, datetime, time, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.domain.recipe_macros import calculate_recipe_macros
from app.persistence.database import Base, get_database_url, get_engine, get_session_factory
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

# Absolute, so the seed finds the migrations however it is launched.
ALEMBIC_INI = str(Path(__file__).resolve().parent.parent / "alembic.ini")

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


def insert_demo_data(session: Session, now: datetime) -> None:
    """Add the demo dataset, dated relative to ``now``, and commit it.

    Args:
        session: A session on a migrated database whose tables are empty.
        now: The moment the demo treats as the present.
    """
    today = now.date()
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


def summary(database_url: str, today: date) -> str:
    """Describe what was seeded, naming the database but never its credentials.

    Args:
        database_url: The database that was seeded.
        today: The day the demo dates are relative to.

    Returns:
        A one-line summary.
    """
    rated = sum(1 for *_, rating in MEALS if rating is not None)
    return (
        f"Seeded {make_url(database_url).database} for {today}: {len(INGREDIENTS)} ingredients, "
        f"{len(BATCHES)} batches, {len(RECIPES)} recipes, 1 nutrition goal, {len(MEALS)} past "
        f"meals ({rated} rated)."
    )


def reset_and_seed() -> None:
    """Drop every table, rebuild them with the migrations, then insert the demo dataset.

    Raises:
        SystemExit: If the configured database is not SQLite; nothing is touched.
    """
    database_url = get_database_url()
    if make_url(database_url).get_backend_name() != "sqlite":
        raise SystemExit("Refusing to reset a non-SQLite database; use --insert-only instead.")
    engine = get_engine(database_url)
    Base.metadata.drop_all(engine)
    # drop_all only knows the models' tables. Alembic's version table must go too, or the
    # upgrade below would think the (now empty) database is already migrated.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    command.upgrade(Config(ALEMBIC_INI), "head")

    now = datetime.now()
    with get_session_factory(engine)() as session:
        insert_demo_data(session, now)
    engine.dispose()
    print(summary(database_url, now.date()))


def seed_empty_database() -> None:
    """Insert the demo dataset into a migrated, empty database, without changing anything else.

    Raises:
        SystemExit: If the database is not at the latest migration or already holds any rows;
            nothing is written.
    """
    database_url = get_database_url()
    engine = get_engine(database_url)
    head = ScriptDirectory.from_config(Config(ALEMBIC_INI)).get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    if current != head:
        engine.dispose()
        raise SystemExit(
            f"Refusing to insert: database is at migration {current}, not {head}. "
            "Run `alembic upgrade head` first."
        )

    now = datetime.now()
    with get_session_factory(engine)() as session:
        occupied = [
            table.name
            for table in Base.metadata.sorted_tables
            if session.scalar(select(func.count()).select_from(table))
        ]
        if occupied:
            engine.dispose()
            raise SystemExit(f"Refusing to insert: database is not empty ({', '.join(occupied)}).")
        insert_demo_data(session, now)
    engine.dispose()
    print(summary(database_url, now.date()))


def main(argv: list[str] | None = None) -> None:
    """Run the reset (default) or ``--insert-only``, as chosen on the command line.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.

    Raises:
        SystemExit: On an unknown argument (before anything runs), or when the chosen mode
            refuses the database.
    """
    parser = argparse.ArgumentParser(description="Fill a FridgeFit database with demo data.")
    parser.add_argument(
        "--insert-only",
        action="store_true",
        help="add the dataset to a migrated, empty database (any kind) without resetting it",
    )
    if parser.parse_args(argv).insert_only:
        seed_empty_database()
    else:
        reset_and_seed()


if __name__ == "__main__":
    main()
