from datetime import date, datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import CanonicalUnit, IngredientRole


class Ingredient(Base):
    """Canonical food/nutrition reference data — not a record of what's in stock."""

    __tablename__ = "ingredients"
    __table_args__ = (
        CheckConstraint("nutrition_base_quantity > 0", name="ck_ingredient_base_quantity_positive"),
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

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    instructions: Mapped[list] = mapped_column(JSON)
    source_url: Mapped[str | None] = mapped_column(String, default=None)

    recipe_ingredients: Mapped[list["RecipeIngredient"]] = relationship(back_populates="recipe")


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
