import enum


class CanonicalUnit(enum.Enum):
    GRAM = "gram"
    MILLILITER = "milliliter"
    COUNT = "count"


class IngredientRole(enum.Enum):
    PRIMARY = "primary"
    SUPPORTING = "supporting"
    OPTIONAL = "optional"
