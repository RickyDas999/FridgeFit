import enum


class CanonicalUnit(enum.Enum):
    """Unit in which an Ingredient's quantities and nutrition are expressed."""

    GRAM = "gram"
    MILLILITER = "milliliter"
    COUNT = "count"


class IngredientRole(enum.Enum):
    """How important an ingredient is to a recipe, used for availability scoring."""

    PRIMARY = "primary"
    SUPPORTING = "supporting"
    OPTIONAL = "optional"
