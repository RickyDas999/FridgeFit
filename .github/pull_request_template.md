## Requirement

What behavior or repository change does this PR implement?

<!--
Be specific and bounded.
Example:
"Add freshness scoring to recipe recommendations using ingredient use-by dates."
-->

## Domain / Architecture Invariants

What existing FridgeFit rules must remain true?

<!--
Examples:
- MealLog macros remain immutable historical snapshots.
- Inventory consumption follows FEFO.
- Recent frequency must not affect recommendation score.
- SQLite remains the V1 database.
- This change must not introduce LLM-owned nutrition or ranking logic.
-->

## Verification

What proves this change works?

<!--
Include:
- targeted tests added or updated;
- relevant full test-suite result;
- lint/static checks;
- any manual verification performed.

Example:
- Added 6 tests in tests/test_freshness.py
- pytest: 132 passed
- ruff check .: passed
-->

## AI Assistance

How was AI used for this change?

<!--
Record meaningful assistance only.

Examples:
- Claude Code implemented the initial scoring function and tests from the approved requirements.
- Claude helped debug a failing expiration-boundary test.
- No AI assistance beyond implementation.
-->

## Human Verification

What did the developer personally inspect, test, reason about, or change?

<!--
Examples:
- Reviewed the full diff.
- Verified score boundaries by hand.
- Rejected an unnecessary abstraction suggested by Claude.
- Reproduced the failing test locally before accepting the fix.
-->

## Out of Scope

What is intentionally NOT included in this PR?

<!--
This prevents scope creep.

Examples:
- No macro-fit scoring.
- No API endpoints.
- No database schema changes.
- No Claude API integration.
-->

## Notes for Review

Anything a reviewer should pay special attention to?

<!--
Optional.
Use this for tricky tradeoffs, assumptions, or areas where independent review is especially valuable.
-->