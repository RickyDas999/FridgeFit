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
- A recipe must have at least one ingredient. A recipe with no ingredients is invalid: it must
  never be persisted, and domain logic rejects it with an error rather than scoring it.
- A valid recipe lists each ingredient at most once.
- A recipe makes a positive number of servings.

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
- Confirming a meal from a recipe states how many servings were made and eaten: any positive
  number, including fractions and more than the recipe's base serving count. Only that much is
  made: each ingredient is scaled by `servings / recipe servings`, and both inventory consumption
  and the logged macros reflect the scaled amount. Leftovers are never created or tracked.

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

Recommendations describe cooking **one serving**. Availability and macro fit are both judged
for a single serving: each recipe ingredient's per-serving quantity is its recipe quantity
divided by the recipe's servings.

Ranking order:

1. Availability
2. Freshness
3. Macro fit
4. Enjoyment

Eligibility and availability:

- An ingredient is **missing** only when none of it is on hand. A partial amount counts as
  available; the shortfall is reported to the user (e.g. 68% of the needed amount on hand) and
  lowers the availability score proportionally.
- Only PRIMARY ingredients are required. Meals missing more than one PRIMARY ingredient are
  excluded.
- A meal missing exactly one PRIMARY ingredient may still be recommended. Missing SUPPORTING or
  OPTIONAL ingredients never exclude a meal.
- Ingredient importance uses PRIMARY, SUPPORTING, OPTIONAL.
- Missing-ingredient importance affects the availability score: each ingredient's fraction of
  its per-serving quantity on hand (capped at 1) is averaged with role weights PRIMARY 3,
  SUPPORTING 2, OPTIONAL 1.

Combining scores:

- Each component score is on a 0–1 scale and they are combined as a weighted sum.
- Default weights follow the ranking order: availability 0.4, freshness 0.3, macro fit 0.2,
  enjoyment 0.1.

Freshness:

- Freshness is scored as **expiry urgency** (`expiry_urgency` in code): a higher score means a
  recipe's ingredients need using sooner, and 1.0 means one must be used today. It does not
  measure how fresh the food is.
- Freshness prioritizes the most urgent ingredient and may receive a small bonus for additional
  expiring-soon ingredients.
- An ingredient is **expiring soon** when its use-by date is within 2 days. That is when using it
  should become a priority.
- An ingredient's urgency comes from its earliest-dated batch that still has stock and is not
  past its use-by date. A batch is usable through its use-by date; it is expired only after it.
- The expiry urgency score (0–1) starts from the most urgent ingredient: 1.0 when it must be used
  today, falling linearly to 0 at 7 days out. Each other ingredient expiring soon adds 0.1. The
  score is capped at 1.0. A recipe with no dated ingredients scores 0.
- Past-entered use-by dates should be surfaced as warnings, but FridgeFit must not make the user's
  food-safety decision. Batches past their use-by date therefore still count as available
  inventory, and never raise a recipe's expiry urgency score.

Macro priorities:

1. Stay under calorie target.
2. Hit protein target; moderate excess protein is acceptable.
3. Stay under fat target.
4. Stay under carbohydrate target while still encouraging adequate carbohydrates.

Macro fit compares **one serving** of a recipe (its total macros divided by its servings) with
what is left of today's goal. With *s* the serving's amount and *r* the amount remaining:

- Calories and fat score 1.0 when *s* fits within *r*, otherwise the share that fits, *r* / *s*
  (0 once the target is used up).
- Protein scores its coverage, *s* / *r*, capped at 1.0. Excess up to 1.5× *r* is not penalized;
  beyond that the score falls linearly to 0 at 3× *r*. Protein scores 1.0 once today's target is
  met.
- Carbohydrates score 1.0 from 25% to 100% of *r*. Below 25% the score falls linearly to 0.5 at
  zero carbohydrates; above *r* they score like calories.
- The four scores combine with weights calories 0.4, protein 0.3, fat 0.2, carbohydrates 0.1.
- When no nutrition goal is in effect yet, macro fit is left out of the ranking and the other
  component weights rescale.

Enjoyment and repetition:

- Enjoyment uses a 1–5 rating scale.
- A recipe's enjoyment is the simple average of the user's ratings of meals made from it, mapped
  linearly onto 0–1 (1 → 0.0, 3 → 0.5, 5 → 1.0). Ratings of manual meals with no recipe do not
  count toward any recipe.
- A recipe with no ratings scores a neutral 0.5, so new recipes are neither helped nor hurt.
- Meal repetition/frequency does NOT reduce recommendation score in V1.
- Recent frequency may be shown informationally. For each recipe it reports how many times it
  was eaten in the last 7 days (the reporting date and the 6 days before it) and the date it was
  last eaten, from full history. Meals logged after the reporting date and meals not made from a
  recipe do not count.
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
