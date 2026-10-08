# FridgeFit

[![CI](https://github.com/RickyDas999/FridgeFit/actions/workflows/ci.yml/badge.svg)](https://github.com/RickyDas999/FridgeFit/actions/workflows/ci.yml)

A personal meal-planning backend that answers one question:

> Given the groceries I currently have, my remaining nutrition goals, food freshness, and meal
> preferences, what should I make?

FridgeFit is a single-user project, built in small reviewed slices with an emphasis on a
codebase that can be explained end to end.

## Status

FridgeFit is currently a **tested Python library**, with no API or app to run yet. Implemented:

- **Persistence**: SQLAlchemy models for ingredients, inventory batches, recipes, meal history,
  nutrition goals, and meal feedback, on SQLite.
- **Core domain logic**: recipe macros, remaining daily macros, inventory aggregation,
  first-expire-first-out (FEFO) consumption, and atomic meal confirmation.
- **Recommendations**: recipes ranked by availability, freshness, macro fit, and enjoyment, with
  recent eating frequency reported for information.

Not built yet: an API layer, nutrition-data and Claude integrations, and migrations. See
[`docs/current-milestone.md`](docs/current-milestone.md) for exactly what is implemented and
what comes next.

## Getting Started

Requires Python 3.11 or newer.

```bash
git clone https://github.com/RickyDas999/FridgeFit.git
cd FridgeFit
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Run the same checks CI runs:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests/ -v
```

The tests are the best place to see the library in use: each domain module has a matching
`tests/test_<module>.py`.

## Project Layout

```text
app/
├── errors.py       shared InvalidInputError
├── persistence/    database setup, enums, SQLAlchemy models
└── domain/         deterministic business logic and input validation
tests/              pytest suite, run against an in-memory SQLite database
scripts/            CI-only tooling (the AI review helper)
docs/               architecture, domain rules, and current status
```

## Documentation

| Document | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Stack, infrastructure limits, layering, persistence conventions |
| [`docs/domain-rules.md`](docs/domain-rules.md) | Product rules: inventory, recipes, meal history, goals, recommendation scoring |
| [`docs/current-milestone.md`](docs/current-milestone.md) | What is implemented, what is not, and what is next |
| [`CLAUDE.md`](CLAUDE.md) | How the AI implementation assistant works in this repository |
| [`AGENTS.md`](AGENTS.md) | The contract for the AI pull-request reviewer |

## Development Workflow

- Changes go through feature branches and pull requests into `main`, using the
  [pull request template](.github/pull_request_template.md).
- **CI** runs Ruff and pytest on Python 3.11 and 3.12 for every pull request. Both checks must
  pass to merge.
- **AI review** is optional and advisory. Adding the `ai-review` label to a pull request runs a
  single Claude request that posts one structured review comment, typically costing about a
  cent. It never blocks merging; its findings are hypotheses for the developer to accept or
  reject. To preview a pull request's review size without calling the API:

  ```bash
  .venv/bin/python scripts/ai_review.py --pr <number> --dry-run
  ```
