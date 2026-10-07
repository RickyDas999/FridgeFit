from collections import defaultdict
from typing import NamedTuple, Sequence

from app.domain.validation import validate_ratings
from app.persistence.models import MealFeedback, Recipe

MIN_RATING = 1
MAX_RATING = 5
UNRATED_SCORE = 0.5


class RecipeEnjoyment(NamedTuple):
    """How much the user has enjoyed a recipe, from their meal ratings."""

    score: float
    average_rating: float | None
    rating_count: int


def group_ratings_by_recipe(meal_feedback: Sequence[MealFeedback]) -> dict[int, list[int]]:
    """Group 1-5 ratings by the recipe each rated meal was made from.

    Ratings of manual meals that did not come from a recipe are ignored.

    Args:
        meal_feedback: MealFeedback rows; each one's ``meal_log`` must be loadable.

    Returns:
        Mapping of ``recipe_id`` to that recipe's ratings.

    Raises:
        InvalidInputError: If any rating is outside 1-5.
    """
    validate_ratings([feedback.rating for feedback in meal_feedback])

    ratings = defaultdict(list)
    for feedback in meal_feedback:
        recipe_id = feedback.meal_log.recipe_id
        if recipe_id is not None:
            ratings[recipe_id].append(feedback.rating)
    return ratings


def assess_recipe_enjoyment(
    recipe: Recipe, ratings_by_recipe: dict[int, list[int]]
) -> RecipeEnjoyment:
    """Score a recipe by the average of the user's ratings of meals made from it.

    The average 1-5 rating maps linearly onto 0-1 (1 is 0.0, 3 is 0.5, 5 is 1.0). A recipe
    with no ratings scores ``UNRATED_SCORE``, so new recipes are neither helped nor hurt.

    Args:
        recipe: The recipe to score.
        ratings_by_recipe: Mapping of ``recipe_id`` to ratings, as returned by
            ``group_ratings_by_recipe``.

    Returns:
        The 0-1 enjoyment score, the average rating (None if unrated), and the rating count.
    """
    ratings = ratings_by_recipe.get(recipe.id, [])
    if not ratings:
        return RecipeEnjoyment(score=UNRATED_SCORE, average_rating=None, rating_count=0)

    average = sum(ratings) / len(ratings)
    score = (average - MIN_RATING) / (MAX_RATING - MIN_RATING)
    return RecipeEnjoyment(score=score, average_rating=average, rating_count=len(ratings))
