import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, NaiveDatetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.session import SessionDep
from app.application.meals import confirm_recipe_meal
from app.domain.meal_confirmation import InsufficientInventoryError
from app.persistence.models import MealFeedback, MealLog, MealLogIngredient, Recipe

router = APIRouter(tags=["meals"])


class MealConfirm(BaseModel):
    """Request body for confirming a meal made from a recipe."""

    # Python's JSON parser accepts Infinity and NaN; neither is a real number of servings.
    model_config = ConfigDict(allow_inf_nan=False, str_strip_whitespace=True)

    servings: float = Field(gt=0, description="Servings made and eaten; fractions allowed.")
    # Naive local time, like every stored datetime: calendar-day logic compares local dates.
    consumed_at: NaiveDatetime | None = Field(
        default=None,
        description="Local time, without a timezone. Defaults to now.",
        # Without this, the generated docs example ends in "Z" (UTC), which is rejected.
        examples=["2026-10-11T19:00:00"],
    )
    name: str | None = Field(
        default=None, min_length=1, description="Defaults to the recipe name."
    )
    allow_shortfall: bool = Field(
        default=False, description="Confirm anyway when inventory is short."
    )


class MealLogIngredientResponse(BaseModel):
    """The amount of one ingredient actually used in a meal."""

    ingredient_id: int
    name: str
    quantity: float


class MealLogResponse(BaseModel):
    """A logged meal with its macro snapshot and the ingredients it used."""

    id: int
    recipe_id: int | None
    name: str
    consumed_at: datetime
    calories: float
    protein: float
    carbs: float
    fat: float
    idempotency_key: uuid.UUID | None
    ingredients: list[MealLogIngredientResponse]
    rating: int | None = Field(description="The meal's 1-5 rating; None until it is rated.")


class FeedbackCreate(BaseModel):
    """Request body for rating a meal."""

    # Strict: reject true, "4", and 4.0 rather than coercing them into a rating.
    rating: int = Field(ge=1, le=5, strict=True, description="Whole number from 1 to 5.")


class FeedbackResponse(BaseModel):
    """A stored meal rating."""

    # Lets model_validate read attributes from a MealFeedback ORM object.
    model_config = ConfigDict(from_attributes=True)

    id: int
    meal_log_id: int
    rating: int


def meal_log_response(meal_log: MealLog) -> MealLogResponse:
    """Build the response for a MealLog, naming each ingredient it used.

    Args:
        meal_log: A stored MealLog whose ingredients can be loaded.

    Returns:
        The meal's response body.
    """
    return MealLogResponse(
        id=meal_log.id,
        recipe_id=meal_log.recipe_id,
        name=meal_log.name,
        consumed_at=meal_log.consumed_at,
        calories=meal_log.calories,
        protein=meal_log.protein,
        carbs=meal_log.carbs,
        fat=meal_log.fat,
        idempotency_key=meal_log.idempotency_key,
        ingredients=[
            MealLogIngredientResponse(
                ingredient_id=line.ingredient_id,
                name=line.ingredient.name,
                quantity=line.quantity,
            )
            for line in meal_log.meal_log_ingredients
        ],
        rating=meal_log.feedback.rating if meal_log.feedback else None,
    )


@router.post("/recipes/{recipe_id}/confirm", status_code=201)
def confirm_recipe(
    recipe_id: int,
    body: MealConfirm,
    session: SessionDep,
    response: Response,
    idempotency_key: Annotated[
        uuid.UUID | None,
        Header(
            alias="Idempotency-Key",
            description="Client-generated UUID; retrying with it returns the original meal.",
        ),
    ] = None,
) -> MealLogResponse:
    """Log a meal made from a recipe and consume its ingredients from inventory.

    Returns 201 for a new meal, or 200 with the original meal when the ``Idempotency-Key``
    header was already confirmed.

    Args:
        recipe_id: The recipe that was made.
        body: Servings, time, and confirmation options.
        session: The request's database session.
        response: Used to switch the status code to 200 for a replayed key.
        idempotency_key: The optional ``Idempotency-Key`` header, parsed as a UUID.

    Returns:
        The logged meal.

    Raises:
        HTTPException: 404 if the recipe does not exist; 409 with per-ingredient shortfalls if
            inventory is short and ``allow_shortfall`` is false.
    """
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id} not found")

    try:
        confirmation = confirm_recipe_meal(
            session,
            recipe,
            servings=body.servings,
            consumed_at=body.consumed_at or datetime.now(),
            name=body.name,
            allow_shortfall=body.allow_shortfall,
            idempotency_key=idempotency_key,
        )
    except InsufficientInventoryError as exc:
        names = {line.ingredient_id: line.ingredient.name for line in recipe.recipe_ingredients}
        raise HTTPException(status_code=409, detail={
            "message": "Insufficient inventory",
            "shortfalls": [
                {
                    "ingredient_id": ingredient_id,
                    "name": names[ingredient_id],
                    "quantity_needed": needed,
                    "quantity_available": available,
                }
                for ingredient_id, (needed, available) in exc.shortfalls.items()
            ],
        }) from exc

    if not confirmation.created:
        response.status_code = 200
    return meal_log_response(confirmation.meal_log)


@router.get("/meal-logs")
def list_meal_logs(session: SessionDep, consumed_on: date | None = None) -> list[MealLogResponse]:
    """List the meals eaten on one calendar day, in the order they were eaten.

    Args:
        session: The request's database session.
        consumed_on: The calendar day, as ``YYYY-MM-DD``. Defaults to today on the server's
            clock.

    Returns:
        That day's meals.
    """
    day_start = datetime.combine(consumed_on or date.today(), time.min)
    # Eager-load each meal's lines, their ingredients, and its rating: fixed queries per request.
    meal_logs = session.scalars(
        select(MealLog)
        .options(
            selectinload(MealLog.meal_log_ingredients).selectinload(MealLogIngredient.ingredient),
            selectinload(MealLog.feedback),
        )
        .where(
            MealLog.consumed_at >= day_start,
            MealLog.consumed_at < day_start + timedelta(days=1),
        )
        .order_by(MealLog.consumed_at, MealLog.id)
    )
    return [meal_log_response(meal_log) for meal_log in meal_logs]


@router.post("/meal-logs/{meal_log_id}/feedback", status_code=201)
def rate_meal(meal_log_id: int, body: FeedbackCreate, session: SessionDep) -> FeedbackResponse:
    """Rate a logged meal from 1 to 5. Each meal can be rated once.

    Ratings of meals made from a recipe feed that recipe's enjoyment score; ratings of manual
    meals are stored but count toward no recipe.

    Args:
        meal_log_id: The meal being rated.
        body: The rating.
        session: The request's database session.

    Returns:
        The stored rating.

    Raises:
        HTTPException: 404 if the meal does not exist; 409 if it is already rated.
    """
    meal_log = session.get(MealLog, meal_log_id)
    if meal_log is None:
        raise HTTPException(status_code=404, detail=f"Meal log {meal_log_id} not found")
    already_rated = HTTPException(
        status_code=409, detail=f"Meal log {meal_log_id} is already rated"
    )
    if meal_log.feedback is not None:
        raise already_rated

    feedback = MealFeedback(meal_log=meal_log, rating=body.rating)
    session.add(feedback)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent request may have rated this meal after the check above.
        # The failed transaction must be rolled back before the session can query again; that
        # also expires meal_log, so .feedback is read fresh. If the meal still has no rating,
        # the violation was something else, so it stays an error.
        session.rollback()
        if meal_log.feedback is None:
            raise
        raise already_rated from None
    return FeedbackResponse.model_validate(feedback)
