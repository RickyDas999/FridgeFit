import pytest

from app.domain.enjoyment import RatingSummary, assess_recipe_enjoyment
from app.errors import InvalidInputError
from app.persistence.models import Recipe


def make_recipe(recipe_id):
    """Build an unsaved Recipe with the given id.

    Args:
        recipe_id: Id to give the recipe, used to match rating summaries.

    Returns:
        A new, unpersisted Recipe.
    """
    return Recipe(id=recipe_id, name="Test Recipe", instructions=[], prep_minutes=10, servings=1)


def test_unrated_recipe_scores_neutral():
    """A recipe with no ratings scores 0.5, as if rated 3."""
    enjoyment = assess_recipe_enjoyment(make_recipe(1), {})

    assert enjoyment.score == 0.5
    assert enjoyment.average_rating is None
    assert enjoyment.rating_count == 0


@pytest.mark.parametrize(("average", "expected"), [(1, 0.0), (3, 0.5), (5, 1.0)])
def test_average_rating_maps_linearly_onto_zero_to_one(average, expected):
    """An average of 1 scores 0, 3 scores 0.5, and 5 scores 1.0."""
    enjoyment = assess_recipe_enjoyment(make_recipe(1), {1: RatingSummary(average, 1)})

    assert enjoyment.score == pytest.approx(expected)


def test_summary_average_and_count_are_reported():
    """The recipe's average and rating count come straight from its summary."""
    enjoyment = assess_recipe_enjoyment(make_recipe(1), {1: RatingSummary(4.0, 3)})

    assert enjoyment.average_rating == pytest.approx(4)
    assert enjoyment.score == pytest.approx(0.75)
    assert enjoyment.rating_count == 3


def test_other_recipes_ratings_do_not_count():
    """Only this recipe's summary affects its enjoyment."""
    enjoyment = assess_recipe_enjoyment(make_recipe(1), {2: RatingSummary(1.0, 2)})

    assert enjoyment.score == 0.5


@pytest.mark.parametrize(
    "summary",
    [
        RatingSummary(0.5, 1),
        RatingSummary(5.5, 1),
        RatingSummary(3.0, 0),
        RatingSummary(3.0, True),
    ],
)
def test_impossible_rating_summaries_are_rejected(summary):
    """An average outside 1-5, or a summary of no ratings, cannot come from 1-5 ratings."""
    with pytest.raises(InvalidInputError):
        assess_recipe_enjoyment(make_recipe(1), {1: summary})
