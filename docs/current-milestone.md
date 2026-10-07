# FridgeFit — Current Milestone

Snapshot of the repository's actual state. Update this file whenever a slice or milestone lands.
If it disagrees with the code, the code is correct and this file is stale.

Last updated: 2026-10-07

---

## Status

**Completed milestones:**

1. **Core Deterministic Domain Logic**: recipe macros, nutrition state, inventory aggregation,
   FEFO consumption, and atomic meal confirmation.
2. **Recommendations**: availability, freshness, macro fit, and enjoyment scoring combined into a
   weighted ranking, plus informational recent frequency. Includes the input-validation slice and
   CI setup completed during the milestone.

**Next step: add Codex to the CI pipeline** as an additional review layer, as approved by the
developer. This is pipeline work, not a feature milestone.

**No feature milestone is active.** Do not start new feature work until the developer approves
the next milestone and its scope.

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
- `Recipe.servings` must be positive, enforced by a database check constraint.
- A SQLAlchemy `before_flush` hook in `models.py` rejects saving a Recipe with no ingredients: a
  new empty recipe, emptying a saved recipe, or deleting its last ingredient.

### Core domain logic (`app/domain/`)

| Area | Module | Entry point |
|---|---|---|
| Recipe macro calculation | `recipe_macros.py` | `calculate_recipe_macros(recipe, quantity_overrides=None)` |
| Current nutrition state | `nutrition_state.py` | `select_applicable_goal`, `calculate_remaining_macros` |
| Inventory aggregation | `inventory_aggregation.py` | `aggregate_inventory_by_ingredient(batches)` |
| FEFO consumption | `fefo_consumption.py` | `plan_fefo_consumption(batches, quantity_needed)` |
| Meal confirmation | `meal_confirmation.py` | `confirm_meal(session, recipe, *, consumed_at, name=None, allow_shortfall=False)` |

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

### Recommendations (`app/domain/`)

| Module | Entry point |
|---|---|
| `availability.py` | `assess_recipe_availability(recipe, inventory_totals)` |
| `freshness.py` | `assess_recipe_freshness(recipe, batches_by_ingredient, as_of)` |
| `macro_fit.py` | `assess_macro_fit(recipe, remaining)` |
| `enjoyment.py` | `group_ratings_by_recipe(meal_feedback)`, `assess_recipe_enjoyment(recipe, ratings_by_recipe)` |
| `recent_frequency.py` | `group_meal_dates_by_recipe(meal_logs, as_of)`, `assess_recent_frequency(recipe, meal_dates_by_recipe, as_of)` |
| `recommendations.py` | `recommend_recipes(recipes, batches, as_of, remaining_macros, meal_feedback, meal_logs)`, `combine_scores(scores)` |

- `recommend_recipes` drops ineligible recipes, scores the rest, and returns `Recommendation`s
  (recipe, combined score, availability, freshness, macro-fit, enjoyment, and recent-frequency
  details) highest score first.
- `remaining_macros` is required but may be None (no nutrition goal in effect yet). Macro fit is
  then skipped, `Recommendation.macro_fit` is None, and `combine_scores` rescales the remaining
  default weights to sum to 1. This is the only case where weights are rescaled.
- `meal_feedback` is required; pass an empty sequence when nothing has been rated. Enjoyment is
  always scored (0.5 when unrated), so with a nutrition goal all four weights apply unscaled.
- `meal_logs` is required and used only for `Recommendation.recent_frequency`; it never affects
  the score.
- Each `Recommendation.freshness.expired_batches` lists batches past their use-by date, as
  warnings.

### Input validation

- `app/errors.py` defines `InvalidInputError(ValueError)`, raised by all input validation, in
  both layers.
- `app/domain/validation.py` holds the domain input validators; each domain function calls the
  ones it needs at its top. They reject:
  - a recipe with no ingredients or non-positive servings;
  - non-positive recipe-ingredient quantities, nutrition base quantities, and FEFO
    `quantity_needed`; negative quantity overrides;
  - quantity overrides keyed by a RecipeIngredient that is not part of the recipe;
  - FEFO batch lists that mix ingredients;
  - a `datetime` passed as `as_of` (nutrition state, freshness, recent frequency,
    recommendations);
  - ratings that are not whole numbers from 1 to 5.
- Persistence never imports from `app/domain/`.

### Tests

150 tests across `tests/test_models.py` and one test module per domain module. Run with:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests/ -v
```

### CI

- `.github/workflows/ci.yml` runs `ruff check .` and `pytest` on Python 3.11 and 3.12 for every
  pull request and every push to `main`.
- Ruff is pinned (`ruff==0.16.10`) and configured in `pyproject.toml`.
- `main` is protected: changes merge only through a pull request with both CI checks passing; no
  approval is required, and the admin can bypass in an emergency.

## Intentionally Unimplemented

- FastAPI / API layer
- Nutrition-data API integration
- Claude API integration
- Use of `MealLog.idempotency_key` in meal confirmation
- Ranking weights configurable per recommendation request (the defaults are fixed in
  `DEFAULT_WEIGHTS`)
- Grocery addition and manual inventory correction operations
- Alembic migrations
- Docker
- Agent (Codex) review in CI
