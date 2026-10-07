# FridgeFit — Architecture

Durable architectural decisions. Changes to anything here are architecture decisions and must be
approved by the developer before implementation.

For product/domain invariants, see `docs/domain-rules.md`. For what is currently built, see
`docs/current-milestone.md`.

---

## Shape of the System

- FridgeFit should initially be a **modular monolith**.
- The architecture must remain simple enough to understand and explain end-to-end.

## Workload Assumptions

FridgeFit is a single-user application in V1:

- approximately 1 daily active user;
- low concurrency;
- small dataset.

Concurrent writes are not currently a meaningful concern.

## Stack

- Python 3.11+
- SQLAlchemy 2.x
- SQLite as the V1 relational database
- pytest
- Ruff for linting, pinned to an exact version and configured in `pyproject.toml`
- GitHub Actions for CI: lint and tests on every pull request and every push to `main`

PostgreSQL is a possible future migration only if multi-user deployment or concurrency genuinely
requires it.

## Infrastructure Not Used

Do not add any of the following unless a future requirement actually needs it:

- Redis;
- message queues;
- microservices;
- distributed infrastructure;
- multi-agent or agent-to-agent (A2A) architecture.

## External Boundaries

External services are allowed when they solve a real problem. They are **boundaries, not sources of
internal truth**: data crossing into FridgeFit is normalized and persisted or recalculated
deterministically before it is trusted.

Expected future external boundaries:

- a nutrition-data API;
- the Claude API, for optional meal generation.

Neither is implemented. Neither may be implemented until explicitly requested.

## Code Layout

```text
app/
├── errors.py      InvalidInputError, shared by both layers
├── persistence/   database setup, enums, SQLAlchemy models
└── domain/        deterministic business logic and its input validators
tests/             pytest suite; tests/conftest.py provides an in-memory SQLite session
.github/workflows/ CI workflow
```

- Deterministic domain logic stays separate from persistence concerns where practical.
- Dependencies point one way: `domain` may import `persistence`, never the reverse. Anything both
  layers need, such as `InvalidInputError`, lives outside them in `app/errors.py`.
- Domain functions validate their inputs through `app/domain/validation.py` and raise
  `InvalidInputError`, rather than failing deep inside a calculation or returning a wrong result.
- Domain calculations are written as pure functions over already-loaded objects (no `Session`, no
  queries) where practical. A domain operation that must be atomic may take a `Session` and own the
  transaction boundary; `confirm_meal` is the current example.

## Persistence Conventions

- SQLite foreign-key enforcement is enabled on every connection (`PRAGMA foreign_keys=ON` via a
  SQLAlchemy connect-event hook). SQLite leaves foreign keys unenforced by default.
- Clearly invalid values (negative quantities or macros, ratings outside 1–5, non-positive
  servings) are rejected by database `CheckConstraint`s.
- Rules a database constraint cannot express are enforced before each save with a SQLAlchemy
  `before_flush` hook in `models.py`. The current one rejects a Recipe with no ingredients, which
  a constraint cannot check because the Recipe row must exist before its ingredient rows.
- Recipe instructions are stored in a JSON column.
- There are no migrations (Alembic is not set up). The test fixture creates the schema with
  `Base.metadata.create_all`; no application entry point creates it yet.
