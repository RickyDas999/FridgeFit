# FridgeFit — Claude Code Instructions

## Project Purpose

FridgeFit is a personal meal-planning backend that helps a user answer:

> Given the groceries I currently have, my remaining nutrition goals, food freshness, and meal preferences, what should I make?

The project is intentionally small and will be developed incrementally.

The primary goals are:

1. Build a genuinely useful application.
2. Keep the architecture understandable end-to-end.
3. Strengthen the developer's backend engineering, debugging, testing, and system-design skills.
4. Use AI as an engineering assistant without allowing AI to take ownership of the system.
5. Produce a codebase where the developer can explain every meaningful file, function, model, algorithm, and tradeoff.

This is NOT a code-generation exercise.

---

## Development Philosophy

Work in very small vertical or conceptual slices.

A good task:

> Add Ingredient and InventoryBatch persistence models.

A bad task:

> Add inventory models, services, API endpoints, recommendation logic, and tests.

Do not implement functionality that has not been explicitly requested in the current prompt.

Do not anticipate future checkpoints by adding abstractions, services, interfaces, files, endpoints, or dependencies "for later."

Prefer the simplest implementation that satisfies the current requirement.

---

## Critical Rules

### Never Commit or Push

Never run:

- `git commit`
- `git push`
- commands that create commits

The developer will inspect all changes and commit manually.

You may inspect Git status/diffs when useful.

---

### Do Not Build Ahead

Only implement the current requested slice.

If the requested task is:

> Add Ingredient model

do not also add:

- inventory services
- FastAPI routes
- recommendation logic
- nutrition API integration
- Claude integration
- repository abstractions
- unrelated models

Future architecture has already been planned and will be introduced incrementally.

---

### Explain Before Expanding

When a task requires a meaningful engineering decision that was not specified:

1. Do not silently choose a sophisticated solution.
2. State the decision briefly.
3. Explain the simplest viable options.
4. Use the least complex option unless explicitly instructed otherwise.

If a decision could materially affect architecture, stop and surface it rather than implementing broadly.

Do not ask questions about trivial implementation details that can safely follow existing project conventions.

---

### Keep Responses Token-Efficient

Be concise.

Before implementation:
- inspect only the files relevant to the task;
- summarize what matters;
- avoid repeating the entire project specification.

After implementation report only:

1. Files changed.
2. What was implemented.
3. Important design choices.
4. Tests run and results.
5. Anything the developer should inspect or understand.

Do not produce long tutorials unless explicitly asked.

---

## Learning-Oriented Development

The developer is intentionally using this project to improve as a software engineer.

Do not hide complexity behind generated code.

Favor code that a new-grad backend engineer can understand and explain.

When introducing an unfamiliar construct, briefly explain:
- what it does;
- why it is being used here;
- what simpler alternative exists, if relevant.

Examples:
- SQLAlchemy relationships
- transactions
- eager loading
- constraints
- idempotency
- dependency injection
- async behavior
- external API boundaries

Do not introduce advanced patterns purely because they are "best practice."

---

## Debugging Rules

When something fails:

1. Read the actual error.
2. Form a specific hypothesis.
3. Investigate the smallest relevant area.
4. Prefer reproducing the failure with a focused test.
5. Fix the root cause rather than rewriting large sections.
6. Explain what caused the bug.

Do not respond to a failing test by replacing large amounts of working code unless necessary.

Do not repeatedly make speculative changes until tests pass.

The developer should be able to follow the debugging process.

---

## Testing Rules

Every meaningful behavior should eventually have tests.

For each slice:
- add only tests relevant to that slice;
- prefer focused unit/model tests before broad integration tests;
- test important edge cases;
- do not add huge generic test suites.

Do not trust generated code merely because it imports or compiles.

Run the relevant tests before reporting completion.

---

## Architecture Principles

FridgeFit is currently a single-user application.

Current expected workload:
- approximately 1 daily active user;
- low concurrency;
- small dataset.

Therefore:

- SQLite is the V1 relational database.
- Concurrent writes are not currently a meaningful concern.
- PostgreSQL is a possible future migration if multi-user deployment or concurrency justifies it.
- Do not add Redis.
- Do not add message queues.
- Do not add microservices.
- Do not add distributed infrastructure unless a future requirement actually needs it.

FridgeFit should initially be a modular monolith.

External services are allowed when they solve a real problem.

Expected future external boundaries:
- nutrition-data API;
- Claude API for optional meal generation.

Do not implement either until explicitly requested.

---

## Important Domain Decisions

These decisions have already been made.

### Ingredient

An Ingredient represents canonical food/nutrition reference data.

It is separate from physical kitchen inventory.

Nutrition data will eventually include:
- calories;
- protein;
- carbohydrates;
- fat;
- canonical unit;
- nutrition base quantity;
- source URL;
- nutrition updated timestamp.

Canonical units:
- grams;
- milliliters;
- count.

Nutrition data is retrieved once and persisted.

---

### Inventory

Inventory is represented by separate purchase batches.

One Ingredient may have many InventoryBatch records.

A batch preserves:
- initial quantity;
- remaining quantity;
- purchase date;
- optional use-by date;
- optional depleted timestamp.

Separate batches exist so expiration/freshness information is not lost.

Normal inventory views will later aggregate batches by Ingredient.

Inventory consumption will eventually follow FEFO:
- first-expire, first-out;
- fall back to oldest purchase date when needed.

Manual inventory corrections must NOT create MealLogs or change nutrition consumption.

Inventory state and personal nutrition consumption are separate concepts.

---

### Recipes

Recipe metadata is relational.

Recipe instructions may use JSON.

Recipe ingredients are normalized relationally because the system must:
- compare them against inventory;
- calculate nutrition;
- calculate missing ingredients.

Recipe macros are NOT stored.

Recipe macros are derived from:
- RecipeIngredient quantities;
- Ingredient nutrition.

RecipeIngredient will eventually classify ingredients as:
- PRIMARY;
- SUPPORTING;
- OPTIONAL.

Recipes may save a source URL.

---

### Meal History

MealLog represents a historical consumption event.

MealLog stores an immutable snapshot of:
- calories;
- protein;
- carbohydrates;
- fat.

Historical meal macros must not change later if Ingredient nutrition data changes.

MealLogIngredient stores:
- the Ingredient;
- the actual quantity used.

MealLogIngredient exists for ingredient-level traceability.

Manual macro-only meals may create a MealLog without MealLogIngredients.

---

### Nutrition Goals

Nutrition goals are historically preserved using an effective date.

Remaining macros are derived:

remaining = applicable goal - consumed MealLogs

Remaining values may become negative when a target has been exceeded.

Changing inventory must never automatically change nutrition goals or consumption.

---

### Recommendations

Primary question:

> What can I make right now?

Current ranking philosophy:

1. Availability
2. Freshness
3. Macro fit
4. Enjoyment

Meals missing more than one required ingredient are excluded.

A meal missing exactly one ingredient may still be recommended.

Ingredient importance will use:
- PRIMARY;
- SUPPORTING;
- OPTIONAL.

Missing-ingredient importance affects availability score.

Freshness prioritizes the most urgent ingredient and may receive a small bonus for additional expiring-soon ingredients.

Past-entered use-by dates should be surfaced as warnings, but FridgeFit must not make the user's food-safety decision.

Macro priorities:
1. Stay under calorie target.
2. Hit protein target; moderate excess protein is acceptable.
3. Stay under fat target.
4. Stay under carbohydrate target while still encouraging adequate carbohydrates.

Enjoyment uses a 1–5 rating scale.

Meal repetition/frequency does NOT reduce recommendation score in V1.

Recent frequency may be shown informationally.

Ranking weights will eventually be configurable per recommendation request.

---

### AI

Claude will eventually generate optional candidate meals.

AI generation is explicitly user-triggered.

Saved meals should work without Claude.

AI suggestions remain ephemeral unless the user explicitly saves them.

For ephemeral AI candidates, Claude may provide estimated:
- macros;
- preparation time;
- ingredients.

These estimates must be identified as estimates.

When an AI recipe is saved, ingredients will later be normalized and trusted macros recalculated deterministically.

Claude does NOT own:
- persisted nutrition truth;
- inventory calculations;
- freshness calculations;
- final deterministic ranking logic.

Do not create multi-agent or A2A architecture unless a future requirement genuinely requires it.

---

## Code Quality

Prefer:
- clear names;
- short functions;
- straightforward control flow;
- explicit domain logic;
- small modules with real responsibilities.

Avoid:
- speculative abstractions;
- premature generic repositories;
- unnecessary factories;
- unnecessary inheritance;
- giant utility modules;
- dependency sprawl;
- magic behavior;
- over-commenting obvious code.

Comments should explain WHY when the reason is not obvious.

---

## File Growth

Do not split files simply because they reach an arbitrary line count.

Split when responsibilities become meaningfully separate.

The project should remain small enough that the developer can comfortably navigate and explain it.

---

## Current Status

The repository starts empty.

No implementation exists yet.

Work only on the current task supplied in the active Claude Code prompt.

## Development Workflow

Claude Code is the primary implementation and debugging partner for this repository.

Work continuously within the currently approved milestone, but keep each implementation slice small enough to become one manual Git commit.

A milestone may contain multiple commit-sized slices.

For each slice:

1. State the exact scope in one sentence.
2. Implement only that scope.
3. Run targeted tests.
4. Debug failures incrementally using the actual error output.
5. Show the developer the important changes.
6. Briefly explain any new engineering concepts introduced.
7. Stop before beginning the next slice unless the developer explicitly says to continue.
8. Never commit or push.

Do not require the developer to consult another assistant for routine implementation decisions.

Escalate a decision to the developer when it materially affects:
- architecture;
- data modeling;
- API contracts;
- persistence strategy;
- concurrency;
- transactions;
- external dependencies;
- significant abstractions;
- recommendation behavior;
- correctness or trust boundaries.

Routine coding, testing, debugging, and small refactors should be handled directly in this repository.

Prefer teaching through the actual code and failing tests rather than long theoretical explanations.

## Developer Participation

The developer should actively practice debugging, testing, and running the system.

Do not automatically perform every debugging and verification step.

When a real failure or useful implementation issue appears:

- surface the exact failure;
- explain the relevant context;
- ask the developer to form a hypothesis or try the next debugging step;
- provide hints before giving the full fix.

Do not manufacture fake bugs.

Routine setup or trivial syntax errors should be resolved quickly.

The developer should personally:
- run important test commands;
- inspect meaningful diffs;
- reproduce selected failures;
- debug some issues;
- verify behavior before committing.

Claude should teach through the actual repository state rather than replacing the developer's reasoning.