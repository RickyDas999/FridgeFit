from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.session import SessionDep
from app.domain.recipe_macros import calculate_recipe_macros
from app.persistence.enums import CanonicalUnit, IngredientRole
from app.persistence.models import Ingredient, Recipe, RecipeIngredient

router = APIRouter(prefix="/recipes", tags=["recipes"])


class RecipeIngredientCreate(BaseModel):
    """One ingredient line in a new recipe."""

    # Python's JSON parser accepts Infinity and NaN; neither is a real quantity.
    model_config = ConfigDict(allow_inf_nan=False)

    ingredient_id: int
    quantity: float = Field(
        gt=0, description="Amount for the whole recipe, in the ingredient's unit."
    )
    role: IngredientRole


class RecipeCreate(BaseModel):
    """Request body for adding a recipe with its ingredients.

    Macros are not accepted: they are always derived from the ingredients.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    instructions: list[str] = Field(default_factory=list, description="Steps, in order.")
    source_url: str | None = None
    prep_minutes: int = Field(ge=0)
    servings: int = Field(gt=0)
    ingredients: list[RecipeIngredientCreate] = Field(min_length=1)

    @field_validator("ingredients")
    @classmethod
    def reject_repeated_ingredients(
        cls, ingredients: list[RecipeIngredientCreate]
    ) -> list[RecipeIngredientCreate]:
        """Enforce the domain rule that a recipe lists each ingredient at most once.

        Args:
            ingredients: The recipe's ingredient lines.

        Returns:
            The ingredient lines, unchanged.

        Raises:
            ValueError: If an ingredient appears more than once.
        """
        ids = [line.ingredient_id for line in ingredients]
        if len(ids) != len(set(ids)):
            raise ValueError("each ingredient may appear at most once in a recipe")
        return ingredients


class RecipeIngredientResponse(BaseModel):
    """One ingredient line in a stored recipe."""

    ingredient_id: int
    name: str
    canonical_unit: CanonicalUnit
    quantity: float
    role: IngredientRole


class MacrosResponse(BaseModel):
    """Calories, protein, carbs, and fat."""

    calories: float
    protein: float
    carbs: float
    fat: float


class RecipeResponse(BaseModel):
    """A stored recipe with its ingredients and derived macros."""

    id: int
    name: str
    instructions: list[str]
    source_url: str | None
    prep_minutes: int
    servings: int
    ingredients: list[RecipeIngredientResponse]
    macros: MacrosResponse = Field(description="For the whole recipe (all servings).")
    macros_per_serving: MacrosResponse = Field(description="For one serving: macros / servings.")


def recipe_response(recipe: Recipe) -> RecipeResponse:
    """Build the response for a recipe, deriving its macros from its ingredients.

    Args:
        recipe: A stored recipe whose ingredients can be loaded.

    Returns:
        The recipe's response body.
    """
    macros = calculate_recipe_macros(recipe)
    return RecipeResponse(
        id=recipe.id,
        name=recipe.name,
        instructions=recipe.instructions,
        source_url=recipe.source_url,
        prep_minutes=recipe.prep_minutes,
        servings=recipe.servings,
        ingredients=[
            RecipeIngredientResponse(
                ingredient_id=line.ingredient_id,
                name=line.ingredient.name,
                canonical_unit=line.ingredient.canonical_unit,
                quantity=line.quantity,
                role=line.role,
            )
            for line in recipe.recipe_ingredients
        ],
        macros=MacrosResponse(**macros._asdict()),
        macros_per_serving=MacrosResponse(
            **{name: value / recipe.servings for name, value in macros._asdict().items()}
        ),
    )


@router.post("", status_code=201)
def create_recipe(body: RecipeCreate, session: SessionDep) -> RecipeResponse:
    """Add a recipe and its ingredient lines in one transaction.

    Args:
        body: The recipe and its ingredient lines.
        session: The request's database session.

    Returns:
        The stored recipe with its derived macros.

    Raises:
        HTTPException: 409 if a recipe with the same name already exists, or 404 if any
            referenced ingredient does not exist.
    """
    duplicate = HTTPException(status_code=409, detail=f"Recipe {body.name!r} already exists")
    if _recipe_named(session, body.name) is not None:
        raise duplicate

    ids = {line.ingredient_id for line in body.ingredients}
    found = set(session.scalars(select(Ingredient.id).where(Ingredient.id.in_(ids))))
    missing = sorted(ids - found)
    if missing:
        raise HTTPException(status_code=404, detail=f"Ingredients not found: {missing}")

    recipe = Recipe(
        name=body.name,
        instructions=body.instructions,
        source_url=body.source_url,
        prep_minutes=body.prep_minutes,
        servings=body.servings,
        recipe_ingredients=[
            RecipeIngredient(
                ingredient_id=line.ingredient_id, quantity=line.quantity, role=line.role
            )
            for line in body.ingredients
        ],
    )
    session.add(recipe)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent request may have committed this name after the check above.
        # The failed transaction must be rolled back before the session can query again. If no
        # recipe has the name, the violation was something else, so it stays an error.
        session.rollback()
        if _recipe_named(session, body.name) is None:
            raise
        raise duplicate from None
    return recipe_response(recipe)


def _recipe_named(session: Session, name: str) -> Recipe | None:
    """Find the recipe with a name.

    Args:
        session: An open database session.
        name: The exact name to look up.

    Returns:
        The recipe with that name, or None if there is none.
    """
    return session.scalar(select(Recipe).where(Recipe.name == name))


@router.get("")
def list_recipes(session: SessionDep) -> list[RecipeResponse]:
    """List every recipe with its derived macros, alphabetically by name.

    Args:
        session: The request's database session.

    Returns:
        All stored recipes.
    """
    # Eager-load lines and their ingredients in one query each, instead of one per recipe/line.
    recipes = session.scalars(
        select(Recipe)
        .options(selectinload(Recipe.recipe_ingredients).selectinload(RecipeIngredient.ingredient))
        .order_by(Recipe.name, Recipe.id)
    )
    return [recipe_response(recipe) for recipe in recipes]


@router.get("/{recipe_id}")
def get_recipe(recipe_id: int, session: SessionDep) -> RecipeResponse:
    """Return one recipe with its derived macros.

    Args:
        recipe_id: The recipe's id.
        session: The request's database session.

    Returns:
        The recipe.

    Raises:
        HTTPException: 404 if the recipe does not exist.
    """
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id} not found")
    return recipe_response(recipe)
