from typing import NamedTuple, Sequence

from app.domain.availability import RecipeAvailability, assess_recipe_availability
from app.domain.inventory_aggregation import aggregate_inventory_by_ingredient
from app.persistence.models import InventoryBatch, Recipe

DEFAULT_WEIGHTS = {
    "availability": 0.4,
    "freshness": 0.3,
    "macro_fit": 0.2,
    "enjoyment": 0.1,
}


class Recommendation(NamedTuple):
    """A ranked recipe with its combined score and the details behind it."""

    recipe: Recipe
    score: float
    availability: RecipeAvailability


def combine_scores(scores: dict[str, float]) -> float:
    """Combine component scores into one 0-1 score using the default weights.

    Only the components present in ``scores`` are weighted; their weights are rescaled to sum
    to 1, so the result stays on a 0-1 scale while some components are not yet implemented.

    Args:
        scores: Mapping of component name (a key of ``DEFAULT_WEIGHTS``) to a 0-1 score.

    Returns:
        The weighted combined score.
    """
    total_weight = sum(DEFAULT_WEIGHTS[name] for name in scores)
    return sum(DEFAULT_WEIGHTS[name] * score for name, score in scores.items()) / total_weight


def recommend_recipes(
    recipes: Sequence[Recipe], batches: Sequence[InventoryBatch]
) -> list[Recommendation]:
    """Rank recipes by how well they can be made right now.

    Recipes that are ineligible (more than one PRIMARY ingredient missing) are excluded.

    Args:
        recipes: Candidate recipes. Their ``recipe_ingredients`` must be loadable.
        batches: Current inventory batches across all ingredients.

    Returns:
        Eligible recipes as Recommendations, highest score first.
    """
    inventory_totals = aggregate_inventory_by_ingredient(batches)

    recommendations = []
    for recipe in recipes:
        availability = assess_recipe_availability(recipe, inventory_totals)
        if not availability.is_eligible:
            continue
        score = combine_scores({"availability": availability.score})
        recommendations.append(Recommendation(recipe, score, availability))

    return sorted(recommendations, key=lambda r: r.score, reverse=True)
