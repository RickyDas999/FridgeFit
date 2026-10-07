import pytest

from app.domain.enjoyment import assess_recipe_enjoyment, group_ratings_by_recipe
from app.errors import InvalidInputError
from app.persistence.models import MealFeedback, MealLog, Recipe


def make_feedback(rating, recipe_id):
    """Build an unsaved MealFeedback for a meal made from the given recipe.

    Args:
        rating: The 1-5 rating.
        recipe_id: Recipe the rated meal came from, or None for a manual meal.

    Returns:
        A new, unpersisted MealFeedback with its MealLog attached.
    """
    return MealFeedback(rating=rating, meal_log=MealLog(recipe_id=recipe_id))


def make_recipe(recipe_id):
    """Build an unsaved Recipe with the given id.

    Args:
        recipe_id: Id to give the recipe, used to match ratings.

    Returns:
        A new, unpersisted Recipe.
    """
    return Recipe(id=recipe_id, name="Test Recipe", instructions=[], prep_minutes=10, servings=1)


def test_ratings_are_grouped_by_recipe():
    """Each rating is filed under the recipe its meal was made from."""
    feedback = [make_feedback(5, 1), make_feedback(3, 1), make_feedback(4, 2)]

    assert group_ratings_by_recipe(feedback) == {1: [5, 3], 2: [4]}


def test_ratings_of_manual_meals_are_ignored():
    """A rated meal with no recipe does not affect any recipe's enjoyment."""
    assert group_ratings_by_recipe([make_feedback(5, None)]) == {}


@pytest.mark.parametrize("rating", [0, 6, 3.5, True])
def test_out_of_range_or_non_integer_ratings_are_rejected(rating):
    """Ratings must be whole numbers from 1 to 5."""
    with pytest.raises(InvalidInputError):
        group_ratings_by_recipe([make_feedback(rating, 1)])


def test_unrated_recipe_scores_neutral():
    """A recipe with no ratings scores 0.5, as if rated 3."""
    enjoyment = assess_recipe_enjoyment(make_recipe(1), {})

    assert enjoyment.score == 0.5
    assert enjoyment.average_rating is None
    assert enjoyment.rating_count == 0


@pytest.mark.parametrize(("rating", "expected"), [(1, 0.0), (3, 0.5), (5, 1.0)])
def test_rating_maps_linearly_onto_zero_to_one(rating, expected):
    """A rating of 1 scores 0, 3 scores 0.5, and 5 scores 1.0."""
    enjoyment = assess_recipe_enjoyment(make_recipe(1), {1: [rating]})

    assert enjoyment.score == pytest.approx(expected)


def test_multiple_ratings_are_averaged():
    """Several ratings of one recipe combine as a simple average."""
    enjoyment = assess_recipe_enjoyment(make_recipe(1), {1: [5, 3, 4]})

    assert enjoyment.average_rating == pytest.approx(4)
    assert enjoyment.score == pytest.approx(0.75)
    assert enjoyment.rating_count == 3


def test_other_recipes_ratings_do_not_count():
    """Only ratings of meals made from this recipe affect its enjoyment."""
    enjoyment = assess_recipe_enjoyment(make_recipe(1), {2: [1, 1]})

    assert enjoyment.score == 0.5
