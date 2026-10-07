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

## Sources of Truth

This file describes **how Claude Code should work** in this repository. System facts live in `docs/`:

| Document | Contains |
|---|---|
| `docs/architecture.md` | Durable architecture decisions: stack, infrastructure limits, external boundaries, code layout |
| `docs/domain-rules.md` | Durable product/domain invariants |
| `docs/current-milestone.md` | What is implemented now, what is unimplemented, and which milestone is active |

Before making architecture or domain decisions, read:
- `docs/architecture.md`
- `docs/domain-rules.md`

Before beginning implementation, read:
- `docs/current-milestone.md`

Only implement work that belongs to a milestone the developer has explicitly approved.

If these documents contradict each other or the code, point out the contradiction to the developer rather than guessing which is correct.

Do not change architecture decisions or domain rules without the developer's explicit approval.

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

Do not redesign or replace the persistence layer unless a current requirement exposes a concrete problem.

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
- magic behavior.

---

## Documentation Style

Follow PEP 8 formatting throughout (naming, whitespace, blank lines between top-level definitions, line length).

Maximum line length is 99 characters — the team-agreed extension PEP 8 explicitly permits over its 79-character default.

Ruff enforces this style, import order, and the docstring rules below; its configuration lives in `pyproject.toml`. CI runs the same checks on every pull request. Before reporting a slice complete, run:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests/
```

Every function and class gets a docstring, enterprise-style, regardless of how obvious the function appears:
- one-line summary of what it does;
- `Args:` describing each parameter, when the function takes any;
- `Returns:` describing the return value, when the function returns something other than `None`;
- `Raises:` when the function can raise an intentional exception.

Test functions get a concise one-line docstring describing the behavior under test, without a full Args/Returns block (the `session` fixture parameter and lack of a return value don't need documenting).

Inline comments should still explain WHY when the reason is not obvious — docstrings cover WHAT/HOW; this does not change.

---

## File Growth

Do not split files simply because they reach an arbitrary line count.

Split when responsibilities become meaningfully separate.

The project should remain small enough that the developer can comfortably navigate and explain it.

---

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

---

## Branch and Pull Request Workflow

FridgeFit now uses feature branches and pull requests for meaningful changes.

Claude Code's role remains local implementation and debugging only.

Rules:

- Work only on the branch that is currently checked out.
- Do not create branches.
- Do not switch branches.
- Do not merge branches.
- Do not commit.
- Do not push.
- Do not open or merge pull requests.
- The developer owns branch creation, commits, pushes, pull requests, and merges.
- Keep each implementation task small enough to become one independently reviewable commit or PR slice.
- Do not begin the next slice until the developer explicitly asks.
- When finishing a slice, report:
  1. files changed;
  2. behavior implemented;
  3. important design decisions;
  4. tests run and results;
  5. anything the developer should inspect before committing.

Before making changes, confirm that the currently checked-out branch matches the task being requested. If it appears mismatched, surface that fact instead of switching branches automatically.

---

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
