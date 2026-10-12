from pathlib import Path
from types import SimpleNamespace

from scripts.ai_review import (
    DOC_SECTIONS,
    MAX_REPAIR_ATTEMPTS,
    doc_section,
    review,
    validate_review,
)

PASS_REVIEW = """## AI Review

Status: PASS
Findings: 0
Highest Severity: NONE

### Findings

None.

### Summary

No material issues found. Deterministic CI remains the source of truth for lint and test status."""

# A real response (PR #17): a FINDINGS review, then a "correction" and a second, PASS review.
CONTRADICTORY_REVIEW = """## AI Review

Status: FINDINGS
Findings: 1
Highest Severity: LOW

### Findings

1. [LOW] Typo in docs: "httpx2" should be "httpx"
   File: docs/current-milestone.md:50
   Rule: Documentation accuracy
   Issue: The dependency is listed as "httpx2" but should be "httpx".
   Verify: Check PyPI for the correct package name; httpx2 is indeed the v2 series package name.

### Summary

No material issues found. API layer initialization, session management, and error handling are \
correctly implemented with appropriate test coverage.

---

**Correction:** Upon closer inspection, "httpx2" is the correct package name, so the docs entry \
is accurate. Disregarding the finding above.

```text
""" + PASS_REVIEW + "\n```"


def test_contract_pass_review_is_accepted():
    """The exact no-findings review from AGENTS.md is well-formed."""
    assert validate_review(PASS_REVIEW) == []


def test_second_review_block_is_rejected():
    """A response containing two review blocks with different verdicts is rejected."""
    problems = validate_review(CONTRADICTORY_REVIEW)

    assert "'## AI Review' appears more than once" in problems
    assert "'Status:' appears more than once" in problems


def test_multi_line_summary_is_rejected():
    """A Summary section longer than one line is rejected."""
    problems = validate_review(PASS_REVIEW + "\nA second summary line.")

    assert problems == ["Summary is longer than one line"]


class FakeClient:
    """Stands in for `anthropic.Anthropic`, replaying scripted responses in order."""

    def __init__(self, *replies):
        """Script the responses.

        Args:
            *replies: ``(stop_reason, text)`` tuples, one per expected call.
        """
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def create(self, *, model, max_tokens, system, messages):
        """Record one request and return the next scripted response.

        The keyword-only signature matches the arguments the real call uses, so passing an
        unexpected argument fails here instead of only in CI.

        Args:
            model: The model name.
            max_tokens: The output-token limit.
            system: The system prompt.
            messages: The conversation; FridgeFit always sends one user message.

        Returns:
            A response with the fields `review` reads.
        """
        self.calls.append({"system": system, "content": messages[0]["content"]})
        stop_reason, text = self.replies.pop(0)
        return SimpleNamespace(
            stop_reason=stop_reason,
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=10),
        )


def test_malformed_review_is_repaired_with_only_its_problems_and_response():
    """A rejected review triggers one repair request carrying the problems, not the bundle."""
    client = FakeClient(("end_turn", CONTRADICTORY_REVIEW), ("end_turn", PASS_REVIEW))

    comment = review(client, "model", "CONTRACT", "BUNDLE")

    assert comment.startswith(PASS_REVIEW)
    assert "2 calls · 200 input / 20 output tokens" in comment
    repair = client.calls[1]
    assert repair["system"] == "CONTRACT"
    assert "BUNDLE" not in repair["content"]
    assert f'attempt="1" max_attempts="{MAX_REPAIR_ATTEMPTS}"' in repair["content"]
    assert "- 'Status:' appears more than once" in repair["content"]
    assert CONTRADICTORY_REVIEW in repair["content"]


def test_repairs_stop_at_the_bound_and_post_the_error_comment():
    """A review still malformed after every repair attempt falls back to Status: ERROR."""
    client = FakeClient(*[("end_turn", CONTRADICTORY_REVIEW)] * (MAX_REPAIR_ATTEMPTS + 1))

    comment = review(client, "model", "CONTRACT", "BUNDLE")

    assert len(client.calls) == MAX_REPAIR_ATTEMPTS + 1
    assert "Status: ERROR" in comment


def test_refusal_is_not_retried():
    """A refusal goes straight to the error comment without a repair request."""
    client = FakeClient(("refusal", ""))

    comment = review(client, "model", "CONTRACT", "BUNDLE")

    assert len(client.calls) == 1
    assert "Status: ERROR" in comment


def test_every_mapped_doc_section_exists(monkeypatch):
    """Each DOC_SECTIONS heading exists, so a renamed heading cannot silently drop context."""
    monkeypatch.chdir(Path(__file__).resolve().parents[1])

    missing = [(doc, heading) for _, doc, heading in DOC_SECTIONS if not doc_section(doc, heading)]

    assert missing == []
