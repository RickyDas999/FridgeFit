from typing import NamedTuple

from app.domain.validation import validate_rating_summary
from app.persistence.models import Recipe

MIN_RATING = 1
MAX_RATING = 5
UNRATED_SCORE = 0.5


class RecipeEnjoyment(NamedTuple):
    """How much the user has enjoyed a recipe, from their meal ratings."""

    score: float
    average_rating: float | None
    rating_count: int


class RatingSummary(NamedTuple):
    """A recipe's ratings, summarized: their average and how many there are."""

    average: float
    count: int


def assess_recipe_enjoyment(
    recipe: Recipe, rating_summaries: dict[int, RatingSummary]
) -> RecipeEnjoyment:
    """Score a recipe by the average of the user's ratings of meals made from it.

    The average 1-5 rating maps linearly onto 0-1 (1 is 0.0, 3 is 0.5, 5 is 1.0). A recipe
    with no ratings scores ``UNRATED_SCORE``, so new recipes are neither helped nor hurt.

    Args:
        recipe: The recipe to score.
        rating_summaries: Mapping of ``recipe_id`` to its ratings' average and count, covering
            only meals made from a recipe (ratings of manual meals count toward none). Recipes
            with no ratings are simply absent.

    Returns:
        The 0-1 enjoyment score, the average rating (None if unrated), and the rating count.

    Raises:
        InvalidInputError: If the recipe's summary has an average outside 1-5 or no ratings.
    """
    summary = rating_summaries.get(recipe.id)
    if summary is None:
        return RecipeEnjoyment(score=UNRATED_SCORE, average_rating=None, rating_count=0)

    validate_rating_summary(summary.average, summary.count)
    score = (summary.average - MIN_RATING) / (MAX_RATING - MIN_RATING)
    return RecipeEnjoyment(
        score=score, average_rating=summary.average, rating_count=summary.count
    )
