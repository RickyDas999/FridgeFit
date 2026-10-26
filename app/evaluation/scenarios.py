"""Reproducible planning scenarios: in-memory kitchens with a planning request.

Every scenario is built from the same small catalog of ingredients and recipes, with explicit
ids and a fixed date, so a planner sees exactly the same inputs on every run. Nothing here
touches a database.
"""

from datetime import date, datetime, timedelta
from typing import NamedTuple

from app.domain.enjoyment import RatingSummary
from app.domain.meal_planning import SimulatedBatch
from app.domain.nutrition_state import RemainingMacros
from app.persistence.enums import CanonicalUnit, IngredientRole
from app.persistence.models import Ingredient, Recipe, RecipeIngredient

SCENARIO_DATE = date(2026, 3, 10)
DAILY_GOAL = RemainingMacros(calories=2200, protein=160, carbs=220, fat=70)
NOTHING_EATEN = RemainingMacros(calories=0, protein=0, carbs=0, fat=0)

GRAM, COUNT = CanonicalUnit.GRAM, CanonicalUnit.COUNT
PRIMARY, SUPPORTING = IngredientRole.PRIMARY, IngredientRole.SUPPORTING

# id: (name, unit, base quantity, calories, protein, carbs, fat) per base quantity.
INGREDIENTS = {
    1: ("Chicken breast", GRAM, 100, 165, 31, 0, 3.6),
    2: ("Cooked rice", GRAM, 100, 130, 2.7, 28, 0.3),
    3: ("Broccoli", GRAM, 100, 34, 2.8, 7, 0.4),
    4: ("Eggs", COUNT, 1, 72, 6.3, 0.4, 4.8),
    5: ("Spinach", GRAM, 100, 23, 2.9, 3.6, 0.4),
    6: ("Salmon", GRAM, 100, 208, 20, 0, 13),
    7: ("Rolled oats", GRAM, 100, 389, 16.9, 66, 6.9),
    8: ("Greek yogurt", GRAM, 100, 59, 10, 3.6, 0.4),
    9: ("Black beans", GRAM, 100, 132, 8.9, 23.7, 0.5),
    10: ("Tortillas", COUNT, 1, 140, 4, 24, 3.5),
}

# id: (name, servings, prep minutes, [(ingredient id, quantity, role)]).
RECIPES = {
    1: ("Chicken rice bowl", 2, 25, [(1, 300, PRIMARY), (2, 300, PRIMARY), (3, 200, SUPPORTING)]),
    2: ("Spinach omelette", 1, 10, [(4, 3, PRIMARY), (5, 60, SUPPORTING)]),
    3: ("Overnight oats", 1, 5, [(7, 60, PRIMARY), (8, 150, SUPPORTING)]),
    4: ("Salmon rice plate", 2, 30, [(6, 300, PRIMARY), (2, 300, PRIMARY), (5, 100, SUPPORTING)]),
    5: ("Bean burrito", 2, 15, [(10, 2, PRIMARY), (9, 250, PRIMARY)]),
    6: ("Yogurt bowl", 1, 5, [(8, 200, PRIMARY), (7, 30, SUPPORTING)]),
}

RATINGS = {
    1: RatingSummary(average=4.5, count=4),
    2: RatingSummary(average=4.0, count=2),
    5: RatingSummary(average=2.0, count=1),
}

# Plenty of every ingredient, nothing due soon.
FULL_STOCK = {1: 1000, 2: 2000, 3: 500, 4: 12, 5: 300, 6: 600, 7: 1000, 8: 1000, 9: 800, 10: 8}


class MinPlannedMacro(NamedTuple):
    """Rubric rule: the plan's meals together supply at least ``amount`` of one macro."""

    macro: str
    amount: float


class ExcludeRecipe(NamedTuple):
    """Rubric rule: the plan does not include the named recipe."""

    recipe_name: str


class Scenario(NamedTuple):
    """One kitchen state and planning request, with the rubric for its soft preference."""

    id: str
    description: str
    recipes: list[Recipe]
    batches: list[SimulatedBatch]
    goal: RemainingMacros | None
    eaten_today: RemainingMacros
    rating_summaries: dict[int, RatingSummary]
    meal_count: int
    max_prep_minutes: int | None
    preference: str | None
    rubric: list[MinPlannedMacro | ExcludeRecipe]

    @property
    def remaining(self) -> RemainingMacros | None:
        """Today's remaining macros (goal minus eaten), or None without a goal.

        Returns:
            The remaining macros the planner starts from.
        """
        if self.goal is None:
            return None
        return RemainingMacros(*(goal - eaten for goal, eaten in zip(self.goal, self.eaten_today)))


def build_recipes() -> list[Recipe]:
    """Build the catalog's recipes, with their ingredients, as unsaved objects with fixed ids.

    Returns:
        A fresh list of Recipes, in id order.
    """
    ingredients = {
        ingredient_id: Ingredient(
            id=ingredient_id,
            name=name,
            canonical_unit=unit,
            nutrition_base_quantity=base,
            calories_per_base_unit=calories,
            protein_per_base_unit=protein,
            carbs_per_base_unit=carbs,
            fat_per_base_unit=fat,
            nutrition_updated_at=datetime(2026, 1, 1),
        )
        for ingredient_id, (name, unit, base, calories, protein, carbs, fat) in INGREDIENTS.items()
    }
    return [
        Recipe(
            id=recipe_id,
            name=name,
            instructions=["Prepare"],
            prep_minutes=prep,
            servings=servings,
            recipe_ingredients=[
                RecipeIngredient(
                    # Unique per line: macro overrides are keyed by recipe-ingredient id.
                    id=recipe_id * 100 + position,
                    ingredient=ingredients[ingredient_id],
                    ingredient_id=ingredient_id,
                    quantity=quantity,
                    role=role,
                )
                for position, (ingredient_id, quantity, role) in enumerate(lines)
            ],
        )
        for recipe_id, (name, servings, prep, lines) in RECIPES.items()
    ]


def build_batches(
    quantities: dict[int, float], use_by_days: dict[int, int] | None = None
) -> list[SimulatedBatch]:
    """Build one batch per ingredient, dated relative to ``SCENARIO_DATE``.

    Args:
        quantities: Mapping of ingredient id to quantity on hand; zero means no batch.
        use_by_days: Mapping of ingredient id to days until use-by (0 is today); others undated.

    Returns:
        The batches; each batch's id is its ingredient's id.
    """
    use_by_days = use_by_days or {}
    return [
        SimulatedBatch(
            id=ingredient_id,
            ingredient_id=ingredient_id,
            quantity_remaining=quantity,
            use_by_date=(
                SCENARIO_DATE + timedelta(days=use_by_days[ingredient_id])
                if ingredient_id in use_by_days else None
            ),
            purchased_at=datetime(2026, 3, 1),
        )
        for ingredient_id, quantity in quantities.items()
        if quantity > 0
    ]


def _scenario(
    scenario_id: str,
    description: str,
    batches: list[SimulatedBatch],
    meal_count: int,
    eaten: RemainingMacros = NOTHING_EATEN,
    max_prep: int | None = None,
    preference: str | None = None,
    rubric: tuple = (),
) -> Scenario:
    """Build a scenario with the shared recipes, daily goal, and ratings.

    Args:
        scenario_id: Short stable identifier, used in results.
        description: What the scenario tests.
        batches: The kitchen's stock.
        meal_count: Meals to plan.
        eaten: Macros already eaten today.
        max_prep: Prep-time limit in minutes, or None.
        preference: The user's soft preference in words, or None.
        rubric: Machine-checkable rules standing in for the preference.

    Returns:
        The Scenario.
    """
    return Scenario(
        id=scenario_id,
        description=description,
        recipes=build_recipes(),
        batches=batches,
        goal=DAILY_GOAL,
        eaten_today=eaten,
        rating_summaries=RATINGS,
        meal_count=meal_count,
        max_prep_minutes=max_prep,
        preference=preference,
        rubric=list(rubric),
    )


def build_scenarios() -> list[Scenario]:
    """Build the evaluation scenarios, each isolating one behavior a planner should handle.

    Returns:
        Fresh Scenario objects, in a fixed order.
    """
    return [
        _scenario(
            "well-stocked",
            "Everything in stock and nothing due soon; plan the day's three meals.",
            build_batches(FULL_STOCK),
            meal_count=3,
        ),
        _scenario(
            "short-inventory",
            "Little chicken, no salmon, few beans: some recipes are only partly available.",
            build_batches({**FULL_STOCK, 1: 120, 6: 0, 9: 60}),
            meal_count=3,
        ),
        _scenario(
            "expiring-today",
            "Spinach and salmon are due today and eggs tomorrow; use them before they spoil.",
            build_batches(FULL_STOCK, use_by_days={5: 0, 6: 0, 4: 1}),
            meal_count=2,
        ),
        _scenario(
            "macros-nearly-used",
            "Most of the day's calories are already eaten; two light meals should stay under.",
            build_batches(FULL_STOCK),
            meal_count=2,
            eaten=RemainingMacros(calories=1800, protein=110, carbs=180, fat=55),
        ),
        _scenario(
            "tight-prep-limit",
            "Only recipes taking 10 minutes or less; plan three meals.",
            build_batches(FULL_STOCK),
            meal_count=3,
            max_prep=10,
        ),
        _scenario(
            "high-protein-preference",
            "The user asks for high-protein meals and does not want the burrito.",
            build_batches(FULL_STOCK),
            meal_count=2,
            preference="I'm training today: high protein please, and no burrito.",
            # 90 g: above what ignoring the request gives, reachable by choosing high-protein
            # recipes, so the check separates following the preference from ignoring it.
            rubric=[MinPlannedMacro("protein", 90), ExcludeRecipe("Bean burrito")],
        ),
    ]
