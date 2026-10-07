# FridgeFit — Current Milestone

Snapshot of the repository's actual state. Update this file whenever a slice or milestone lands.
If it disagrees with the code, the code is correct and this file is stale.

Last updated: 2026-10-07

---

## Status

**Completed: Core Deterministic Domain Logic.** All five planned slices are implemented and tested.

**Next milestone: Recommendations.** Approved by the developer as the next milestone. Its scope
and slice plan have not been defined yet. Do not begin implementing it until the developer
approves a slice plan; the governing rules are in the Recommendations section of
`docs/domain-rules.md`.

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

55 tests across `tests/test_models.py` and one test module per domain module. Run with:

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
