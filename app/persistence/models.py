import uuid
from datetime import date, datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, event
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.errors import InvalidInputError
from app.persistence.database import Base
from app.persistence.enums import CanonicalUnit, IngredientRole


class Ingredient(Base):
    """Canonical food/nutrition reference data — not a record of what's in stock."""

    __tablename__ = "ingredients"
    __table_args__ = (
        CheckConstraint(
            "nutrition_base_quantity > 0", name="ck_ingredient_base_quantity_positive"
        ),
        CheckConstraint("calories_per_base_unit >= 0", name="ck_ingredient_calories_nonneg"),
        CheckConstraint("protein_per_base_unit >= 0", name="ck_ingredient_protein_nonneg"),
        CheckConstraint("carbs_per_base_unit >= 0", name="ck_ingredient_carbs_nonneg"),
        CheckConstraint("fat_per_base_unit >= 0", name="ck_ingredient_fat_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    canonical_unit: Mapped[CanonicalUnit]
    nutrition_base_quantity: Mapped[float]
    calories_per_base_unit: Mapped[float]
    protein_per_base_unit: Mapped[float]
    carbs_per_base_unit: Mapped[float]
    fat_per_base_unit: Mapped[float]
    source_url: Mapped[str | None] = mapped_column(String, default=None)
    nutrition_updated_at: Mapped[datetime]
    batches: Mapped[list["InventoryBatch"]] = relationship(back_populates="ingredient")


class InventoryBatch(Base):
    """One physical grocery purchase of an ingredient."""

    __tablename__ = "inventory_batches"
    __table_args__ = (
        CheckConstraint("quantity_initial > 0", name="ck_batch_quantity_initial_positive"),
        CheckConstraint("quantity_remaining >= 0", name="ck_batch_quantity_remaining_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    quantity_initial: Mapped[float]
    quantity_remaining: Mapped[float]
    purchased_at: Mapped[datetime]
    use_by_date: Mapped[date | None] = mapped_column(default=None)
    depleted_at: Mapped[datetime | None] = mapped_column(default=None)

    ingredient: Mapped["Ingredient"] = relationship(back_populates="batches")


class Recipe(Base):
    """A recipe's metadata and instructions. Macros are derived, not stored."""

    __tablename__ = "recipes"
    __table_args__ = (
        CheckConstraint("servings > 0", name="ck_recipe_servings_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    instructions: Mapped[list] = mapped_column(JSON)
    source_url: Mapped[str | None] = mapped_column(String, default=None)
    prep_minutes: Mapped[int]
    servings: Mapped[int]

    recipe_ingredients: Mapped[list["RecipeIngredient"]] = relationship(back_populates="recipe")
    meal_logs: Mapped[list["MealLog"]] = relationship(back_populates="recipe")


class RecipeIngredient(Base):
    """One ingredient's role and quantity within a recipe."""

    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_recipe_ingredient_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    quantity: Mapped[float]
    role: Mapped[IngredientRole]

    recipe: Mapped["Recipe"] = relationship(back_populates="recipe_ingredients")
    ingredient: Mapped["Ingredient"] = relationship()


class MealLog(Base):
    """An immutable historical consumption event.

    Macros are snapshotted at consumption time, not derived, so editing an
    Ingredient's nutrition data later cannot rewrite past meal history.
    """

    __tablename__ = "meal_logs"
    __table_args__ = (
        CheckConstraint("calories >= 0", name="ck_meal_log_calories_nonneg"),
        CheckConstraint("protein >= 0", name="ck_meal_log_protein_nonneg"),
        CheckConstraint("carbs >= 0", name="ck_meal_log_carbs_nonneg"),
        CheckConstraint("fat >= 0", name="ck_meal_log_fat_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id"))
    name: Mapped[str]
    calories: Mapped[float]
    protein: Mapped[float]
    carbs: Mapped[float]
    fat: Mapped[float]
    consumed_at: Mapped[datetime]
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(unique=True)

    meal_log_ingredients: Mapped[list["MealLogIngredient"]] = relationship(
        back_populates="meal_log"
    )
    recipe: Mapped["Recipe"] = relationship(back_populates="meal_logs")


class MealLogIngredient(Base):
    """Traces the actual quantity of one Ingredient used within a MealLog."""

    __tablename__ = "meal_log_ingredients"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_meal_log_ingredient_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_log_id: Mapped[int] = mapped_column(ForeignKey("meal_logs.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    quantity: Mapped[float]

    meal_log: Mapped["MealLog"] = relationship(back_populates="meal_log_ingredients")
    ingredient: Mapped["Ingredient"] = relationship()


class NutritionGoal(Base):
    """A nutrition target, effective starting a given date.

    Changing goals creates a new row rather than overwriting the old one, so
    past goals remain intact for historical "what was my goal on date X" checks.
    """

    __tablename__ = "nutrition_goals"
    __table_args__ = (
        CheckConstraint("calories >= 0", name="ck_nutrition_goal_calories_nonneg"),
        CheckConstraint("protein >= 0", name="ck_nutrition_goal_protein_nonneg"),
        CheckConstraint("carbs >= 0", name="ck_nutrition_goal_carbs_nonneg"),
        CheckConstraint("fat >= 0", name="ck_nutrition_goal_fat_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    calories: Mapped[float]
    protein: Mapped[float]
    carbs: Mapped[float]
    fat: Mapped[float]
    effective_date: Mapped[date]


class MealFeedback(Base):
    """A 1-5 enjoyment rating for one MealLog. At most one per MealLog."""

    __tablename__ = "meal_feedback"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_meal_feedback_rating_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_log_id: Mapped[int] = mapped_column(ForeignKey("meal_logs.id"), unique=True)
    rating: Mapped[int]

    meal_log: Mapped["MealLog"] = relationship()


@event.listens_for(Session, "before_flush")
def _reject_recipes_without_ingredients(session, _flush_context, _instances):
    """Prevent any Recipe from being saved without at least one ingredient.

    A database constraint cannot enforce this: a Recipe row must exist before its
    RecipeIngredient rows can reference it. Checking pending session state before each flush
    covers new recipes, recipes whose ingredient list was emptied, and deleting a recipe's
    last ingredient.

    Args:
        session: The session about to flush.
        _flush_context: SQLAlchemy's internal flush context; unused.
        _instances: Deprecated SQLAlchemy argument; unused.

    Raises:
        InvalidInputError: If a Recipe would be left with no ingredients.
    """
    recipes = {obj for obj in session.new | session.dirty if isinstance(obj, Recipe)}
    recipes |= {
        obj.recipe
        for obj in session.deleted
        if isinstance(obj, RecipeIngredient) and obj.recipe is not None
    }

    # Reading recipe_ingredients may lazy-load; autoflush here would re-enter this hook.
    with session.no_autoflush:
        for recipe in recipes:
            if recipe in session.deleted:
                continue
            remaining = [ri for ri in recipe.recipe_ingredients if ri not in session.deleted]
            if not remaining:
                raise InvalidInputError(
                    f"Recipe {recipe.name!r} must have at least one ingredient"
                )
