# FridgeFit — Current Milestone

Snapshot of the repository's actual state. Update this file whenever a slice or milestone lands.
If it disagrees with the code, the code is correct and this file is stale.

Last updated: 2026-10-07

---

## Status

**Completed: Core Deterministic Domain Logic.** All five planned slices are implemented and tested.

**Active milestone: Recommendations.** Governing rules are in the Recommendations section of
`docs/domain-rules.md`. Every slice is a pure function in `app/domain/` and adds to a working
ranker, so each slice ends with runnable recommendations.

| # | Slice | Status |
|---|---|---|
| 1 | Availability, eligibility, and a weighted-sum ranker (`availability.py`, `recommendations.py`) | Implemented, not yet committed |
| 2 | Freshness score and past-use-by warnings | Not started |
| 3 | Macro fit score | Not started |
| 4 | Enjoyment score | Not started |
| 5 | Recent frequency shown informationally | Not started |

**Input validation (between slices 1 and 2): implemented, not yet committed.**

- `app/errors.py` defines `InvalidInputError(ValueError)`, raised by all input validation.
- `app/domain/validation.py` holds the domain input validators; each domain function calls the
  ones it needs at its top. They reject:
  - a recipe with no ingredients (`calculate_recipe_macros`, `assess_recipe_availability`,
    `confirm_meal`);
  - non-positive recipe-ingredient quantities, nutrition base quantities, and FEFO
    `quantity_needed`; negative quantity overrides;
  - quantity overrides keyed by a RecipeIngredient that is not part of the recipe;
  - FEFO batch lists that mix ingredients;
  - a `datetime` passed as `as_of` to the nutrition-state functions.
- `app/persistence/models.py` registers a SQLAlchemy `before_flush` hook that rejects saving a
  Recipe with no ingredients: a new empty recipe, emptying a saved recipe, or deleting its last
  ingredient. Persistence never imports from `app/domain/`.

Open decisions, to settle when their slice starts: the "expiring soon" threshold (2), whole recipe
vs. per-serving macro fit (3), the score for a recipe with no ratings (4).

Until a component's slice lands, `combine_scores` leaves it out and rescales the remaining default
weights to sum to 1.

## Implemented

### Persistence (`app/persistence/`)

Models: Ingredient, InventoryBatch, Recipe, RecipeIngredient, MealLog, MealLogIngredient,
NutritionGoal, MealFeedback.

Schema details beyond the core domain rules:

- `Recipe.prep_minutes` and `Recipe.servings` (both required).
- `MealLog.name` (required).
- `MealLog.recipe_id`: nullable foreign key to the Recipe the meal came from.
- `MealLog.idempotency_key`: nullable, unique UUID. Present in the schema but not yet used by any
  domain logic.
- `MealFeedback`: one 1–5 rating per MealLog, enforced by a unique foreign key.

### Domain logic (`app/domain/`)

| Slice | Module | Entry point |
|---|---|---|
| 1. Recipe macro calculation | `recipe_macros.py` | `calculate_recipe_macros(recipe, quantity_overrides=None)` |
| 2. Current nutrition state | `nutrition_state.py` | `select_applicable_goal`, `calculate_remaining_macros` |
| 3. Inventory aggregation | `inventory_aggregation.py` | `aggregate_inventory_by_ingredient(batches)` |
| 4. FEFO consumption | `fefo_consumption.py` | `plan_fefo_consumption(batches, quantity_needed)` |
| 5. Meal confirmation | `meal_confirmation.py` | `confirm_meal(session, recipe, *, consumed_at, name=None, allow_shortfall=False)` |

Implementation behavior worth knowing:

- **Recipe macros** accept optional per-ingredient quantity overrides keyed by
  `RecipeIngredient.id`. With no overrides, the recipe's stated quantities are used.
- **Remaining macros** subtract only MealLogs whose `consumed_at` falls on the same calendar day as
  the requested date. A `ValueError` is raised if no goal is effective yet.
- **Inventory aggregation** sums `quantity_remaining` per ingredient.
- **FEFO planning** is read-only. It returns a plan, and returns a partial plan (not an error) when
  inventory is insufficient.
- **Meal confirmation** plans every ingredient before mutating anything, then commits the MealLog,
  MealLogIngredients, and batch decrements in one transaction.
  - By default, any shortfall raises `InsufficientInventoryError` and nothing is written.
  - With `allow_shortfall=True`, the meal is confirmed anyway because kitchen inventory is an
    estimate. Only available inventory is consumed and batches never go negative. Emptied batches
    get `depleted_at`. `MealLogIngredient.quantity` and the MealLog macros reflect the amount
    actually consumed, not the recipe's stated amount. An ingredient with nothing available gets no
    MealLogIngredient row.
  - Ingredient roles (PRIMARY/SUPPORTING/OPTIONAL) do not affect confirmation; every ingredient is
    consumed.

### Tests

82 tests across `tests/test_models.py` and one test module per domain module. Run with:

```bash
.venv/bin/python -m pytest tests/ -v
```

## Intentionally Unimplemented

- FastAPI / API layer
- Recommendation engine (availability, freshness, macro fit, enjoyment scoring)
- Nutrition-data API integration
- Claude API integration
- Use of `MealLog.idempotency_key` in meal confirmation
- Grocery addition and manual inventory correction operations
- Alembic migrations
- Docker
