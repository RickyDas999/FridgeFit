# FridgeFit — Domain Rules

Durable product and domain invariants. These decisions have already been made. Do not change them,
and do not add new rules, without the developer's explicit approval.

For architecture, see `docs/architecture.md`. For what is currently built, see
`docs/current-milestone.md`.

---

## Ingredient

- An Ingredient represents canonical food/nutrition reference data.
- It is separate from physical kitchen inventory.
- Nutrition data consists of:
  - calories, protein, carbohydrates, fat (per base unit);
  - canonical unit;
  - nutrition base quantity;
  - source URL;
  - nutrition updated timestamp.
- Canonical units: grams, milliliters, count.
- Nutrition data is retrieved once and persisted.

## Inventory

- Inventory is represented by separate purchase batches. One Ingredient may have many
  InventoryBatch records.
- A batch preserves: initial quantity, remaining quantity, purchase date, optional use-by date,
  optional depleted timestamp.
- Separate batches exist so expiration/freshness information is not lost.
- Normal inventory views aggregate batches by Ingredient.
- Inventory consumption follows FEFO:
  - first-expire, first-out;
  - fall back to oldest purchase date when needed.
- Manual inventory corrections must NOT create MealLogs or change nutrition consumption.
- Inventory state and personal nutrition consumption are separate concepts.
- Kitchen inventory is an estimate. Confirming a meal whose recipe needs more of an ingredient
  than inventory holds:
  - must detect and report the shortfall by default, writing nothing;
  - may proceed only when the user explicitly confirms anyway;
  - when confirmed anyway, consumes only what inventory actually holds — inventory never goes
    negative, and emptied batches are marked depleted.

## Recipes

- Recipe metadata is relational. Recipes may save a source URL.
- Recipe instructions may use JSON.
- Recipe ingredients are normalized relationally because the system must:
  - compare them against inventory;
  - calculate nutrition;
  - calculate missing ingredients.
- Recipe macros are NOT stored. They are derived from RecipeIngredient quantities and Ingredient
  nutrition.
- RecipeIngredient classifies each ingredient as PRIMARY, SUPPORTING, or OPTIONAL.

## Meal History

- A MealLog represents a historical consumption event.
- A MealLog stores an immutable snapshot of calories, protein, carbohydrates, and fat.
- Historical meal macros must not change later if Ingredient nutrition data changes.
- MealLogIngredient stores the Ingredient and the actual quantity used. It exists for
  ingredient-level traceability.
- A recipe will not always be followed exactly. When the quantity actually used differs from the
  recipe's stated quantity (including an explicitly confirmed inventory shortfall), both the
  MealLogIngredient quantity and the MealLog macros reflect the amount actually consumed, not the
  recipe amount. The difference from the recipe is derived by comparing RecipeIngredient
  quantities with MealLogIngredient quantities; it is not stored separately.
- Manual macro-only meals may create a MealLog without MealLogIngredients.

## Nutrition Goals

- Nutrition goals are historically preserved using an effective date.
- Remaining macros are derived: `remaining = applicable goal - consumed MealLogs`.
- The applicable goal for a date is the goal with the latest effective date on or before that
  date.
- Consumption is counted per calendar day: only MealLogs consumed on the same calendar day as the
  requested date count toward that day's remaining macros.
- Remaining values may become negative when a target has been exceeded.
- Changing inventory must never automatically change nutrition goals or consumption.

## Recommendations

Primary question:

> What can I make right now?

Ranking order:

1. Availability
2. Freshness
3. Macro fit
4. Enjoyment

Eligibility and availability:

- Meals missing more than one required ingredient are excluded.
- A meal missing exactly one ingredient may still be recommended.
- Ingredient importance uses PRIMARY, SUPPORTING, OPTIONAL.
- Missing-ingredient importance affects the availability score.

Freshness:

- Freshness prioritizes the most urgent ingredient and may receive a small bonus for additional
  expiring-soon ingredients.
- Past-entered use-by dates should be surfaced as warnings, but FridgeFit must not make the user's
  food-safety decision.

Macro priorities:

1. Stay under calorie target.
2. Hit protein target; moderate excess protein is acceptable.
3. Stay under fat target.
4. Stay under carbohydrate target while still encouraging adequate carbohydrates.

Enjoyment and repetition:

- Enjoyment uses a 1–5 rating scale.
- Meal repetition/frequency does NOT reduce recommendation score in V1.
- Recent frequency may be shown informationally.
- Ranking weights will eventually be configurable per recommendation request.

## AI Trust Boundary

- Claude may later generate optional candidate meals.
- AI generation is explicitly user-triggered.
- Saved meals should work without Claude.
- AI suggestions remain ephemeral unless the user explicitly saves them.
- For ephemeral AI candidates, Claude may provide estimated macros, preparation time, and
  ingredients. These must be identified as estimates.
- When an AI recipe is saved, its ingredients are normalized and trusted macros are recalculated
  deterministically.
- Claude does NOT own:
  - persisted nutrition truth;
  - inventory calculations;
  - freshness calculations;
  - final deterministic recommendation ranking.
