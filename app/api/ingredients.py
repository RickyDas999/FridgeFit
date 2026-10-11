from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.session import SessionDep
from app.persistence.enums import CanonicalUnit
from app.persistence.models import Ingredient

router = APIRouter(prefix="/ingredients", tags=["ingredients"])


class IngredientCreate(BaseModel):
    """Request body for adding an ingredient's nutrition reference data.

    Macro values are per ``nutrition_base_quantity`` of ``canonical_unit`` (e.g. per 100 g).
    """

    # Python's JSON parser accepts Infinity and NaN; neither is a real nutrition value.
    model_config = ConfigDict(allow_inf_nan=False, str_strip_whitespace=True)

    name: str = Field(min_length=1)
    canonical_unit: CanonicalUnit
    nutrition_base_quantity: float = Field(gt=0)
    calories_per_base_unit: float = Field(ge=0)
    protein_per_base_unit: float = Field(ge=0)
    carbs_per_base_unit: float = Field(ge=0)
    fat_per_base_unit: float = Field(ge=0)
    source_url: str | None = None


class IngredientResponse(BaseModel):
    """An ingredient's stored nutrition reference data."""

    # Lets model_validate read attributes from an Ingredient ORM object.
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    canonical_unit: CanonicalUnit
    nutrition_base_quantity: float
    calories_per_base_unit: float
    protein_per_base_unit: float
    carbs_per_base_unit: float
    fat_per_base_unit: float
    source_url: str | None
    nutrition_updated_at: datetime


@router.post("", status_code=201)
def create_ingredient(body: IngredientCreate, session: SessionDep) -> IngredientResponse:
    """Add an ingredient, stamping its nutrition data as updated now.

    Args:
        body: The ingredient's nutrition reference data.
        session: The request's database session.

    Returns:
        The stored ingredient.

    Raises:
        HTTPException: 409 if an ingredient with the same name already exists.
    """
    existing = session.scalar(select(Ingredient).where(Ingredient.name == body.name))
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Ingredient {body.name!r} already exists")

    ingredient = Ingredient(**body.model_dump(), nutrition_updated_at=datetime.now())
    session.add(ingredient)
    session.commit()
    return IngredientResponse.model_validate(ingredient)


@router.get("")
def list_ingredients(session: SessionDep) -> list[IngredientResponse]:
    """List every ingredient, alphabetically by name.

    Args:
        session: The request's database session.

    Returns:
        All stored ingredients.
    """
    ingredients = session.scalars(select(Ingredient).order_by(Ingredient.name))
    return [IngredientResponse.model_validate(ingredient) for ingredient in ingredients]
