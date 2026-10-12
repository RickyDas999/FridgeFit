from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.recipes import MacrosResponse
from app.api.session import SessionDep
from app.application.recommendations import get_recommendations
from app.domain.recommendations import Recommendation
from app.persistence.enums import IngredientRole

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class IngredientAvailabilityResponse(BaseModel):
    """How much of one ingredient is on hand for one serving."""

    ingredient_id: int
    name: str
    role: IngredientRole
    quantity_per_serving: float
    quantity_on_hand: float
    fraction_available: float
    is_missing: bool


class AvailabilityResponse(BaseModel):
    """The availability component of a recommendation."""

    score: float
    ingredients: list[IngredientAvailabilityResponse]


class ExpiredBatchResponse(BaseModel):
    """A batch past its use-by date, surfaced as a warning."""

    batch_id: int
    ingredient_id: int
    use_by_date: date


class ExpiryUrgencyResponse(BaseModel):
    """The expiry-urgency component: higher means ingredients need using sooner."""

    score: float
    expired_batches: list[ExpiredBatchResponse]


class MacroFitResponse(BaseModel):
    """The macro-fit component, for one serving."""

    score: float
    per_serving: MacrosResponse


class EnjoymentResponse(BaseModel):
    """The enjoyment component; 0.5 when the recipe has no ratings."""

    score: float
    average_rating: float | None
    rating_count: int


class RecentFrequencyResponse(BaseModel):
    """How often the recipe was eaten lately. Informational; never affects the score."""

    times_eaten_recently: int
    last_eaten_on: date | None


class RecommendationResponse(BaseModel):
    """One ranked recipe with the details behind its score."""

    recipe_id: int
    name: str
    score: float
    availability: AvailabilityResponse
    expiry_urgency: ExpiryUrgencyResponse
    macro_fit: MacroFitResponse | None
    enjoyment: EnjoymentResponse
    recent_frequency: RecentFrequencyResponse


def recommendation_response(recommendation: Recommendation) -> RecommendationResponse:
    """Convert a domain Recommendation into its response body.

    Args:
        recommendation: A ranked recipe from ``recommend_recipes``.

    Returns:
        The response body.
    """
    availability = recommendation.availability
    macro_fit = recommendation.macro_fit
    return RecommendationResponse(
        recipe_id=recommendation.recipe.id,
        name=recommendation.recipe.name,
        score=recommendation.score,
        availability=AvailabilityResponse(
            score=availability.score,
            ingredients=[
                IngredientAvailabilityResponse(
                    ingredient_id=item.recipe_ingredient.ingredient_id,
                    name=item.recipe_ingredient.ingredient.name,
                    role=item.recipe_ingredient.role,
                    quantity_per_serving=item.quantity_per_serving,
                    quantity_on_hand=item.quantity_on_hand,
                    fraction_available=item.fraction_available,
                    is_missing=item.is_missing,
                )
                for item in availability.ingredients
            ],
        ),
        expiry_urgency=ExpiryUrgencyResponse(
            score=recommendation.expiry_urgency.score,
            expired_batches=[
                ExpiredBatchResponse(
                    batch_id=batch.id,
                    ingredient_id=batch.ingredient_id,
                    use_by_date=batch.use_by_date,
                )
                for batch in recommendation.expiry_urgency.expired_batches
            ],
        ),
        macro_fit=MacroFitResponse(
            score=macro_fit.score, per_serving=MacrosResponse(**macro_fit.per_serving._asdict())
        ) if macro_fit else None,
        enjoyment=EnjoymentResponse(**recommendation.enjoyment._asdict()),
        recent_frequency=RecentFrequencyResponse(**recommendation.recent_frequency._asdict()),
    )


@router.get("")
def list_recommendations(
    session: SessionDep, as_of: date | None = None
) -> list[RecommendationResponse]:
    """Rank the recipes that can be made on a calendar day, highest score first.

    Recipes missing more than one PRIMARY ingredient are left out.

    Args:
        session: The request's database session.
        as_of: The calendar day, as ``YYYY-MM-DD``. Defaults to today on the server's clock.

    Returns:
        The ranked recommendations.
    """
    recommendations = get_recommendations(session, as_of or date.today())
    return [recommendation_response(r) for r in recommendations]
