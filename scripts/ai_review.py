"""Single-call Claude semantic review of a FridgeFit pull request.

CI-only tooling for `.github/workflows/ai-review.yml`. It gathers a bounded review bundle
deterministically, makes exactly one Anthropic API request, validates the response's structure,
and writes the comment to a file for the workflow to post. It never writes to the repository or
the pull request itself.

It runs from the trusted default branch: `AGENTS.md`, docs, and unchanged test files are read
from that checkout, while all pull request content is fetched with `gh` and treated as text.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

# Hard ceiling on the bundle sent to the model (instructions + PR + diff + context), in
# characters. Roughly 4 characters per token, so about 15k input tokens at most.
MAX_CONTEXT_CHARS = 60_000
# Enough for the fixed structure with 3 findings; prevents long, expensive reviews.
MAX_OUTPUT_TOKENS = 800
# A docs-only change at or under this many changed lines is treated as a trivial edit.
TRIVIAL_DOC_LINES = 4
MAX_FINDINGS = 3
SEVERITY_PATTERN = "LOW|MEDIUM|HIGH|BLOCKER|TEST GAP"

# Posted instead of the model's text when it does not follow the required structure. It must
# never read as a passing review.
INVALID_RESPONSE_COMMENT = """## AI Review

Status: ERROR
Findings: 0
Highest Severity: NONE

### Findings

None.

### Summary

The AI reviewer returned an invalid response format. No AI findings were accepted from this run.
"""

GENERATED_PATTERNS = (
    ".github/workflows/*.lock.yml",
    ".github/aw/*",
    "*.egg-info/*",
)

# Authoritative doc sections worth including when files under these paths change.
DOC_SECTIONS = (
    (
        (
            "app/domain/availability.py",
            "app/domain/expiry_urgency.py",
            "app/domain/macro_fit.py",
            "app/domain/enjoyment.py",
            "app/domain/recent_frequency.py",
            "app/domain/recommendations.py",
        ),
        "docs/domain-rules.md",
        "Recommendations",
    ),
    (
        (
            "app/domain/fefo_consumption.py",
            "app/domain/inventory_aggregation.py",
            "app/domain/meal_confirmation.py",
        ),
        "docs/domain-rules.md",
        "Inventory",
    ),
    (("app/domain/meal_confirmation.py",), "docs/domain-rules.md", "Meal History"),
    (("app/domain/nutrition_state.py",), "docs/domain-rules.md", "Nutrition Goals"),
    (("app/domain/recipe_macros.py",), "docs/domain-rules.md", "Recipes"),
    (("app/persistence/",), "docs/architecture.md", "Persistence Conventions"),
    (("app/domain/validation.py", "app/errors.py"), "docs/architecture.md", "Code Layout"),
)


def run_gh(*args: str) -> str:
    """Run a read-only GitHub CLI command and return its output.

    Args:
        *args: Arguments passed to `gh`.

    Returns:
        The command's standard output.

    Raises:
        RuntimeError: If the command fails.
    """
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def is_generated(path: str) -> bool:
    """Return whether a path is a generated artifact that is never sent for review.

    Args:
        path: Repository-relative file path.

    Returns:
        True if the path matches a generated-file pattern.
    """
    return any(fnmatch(path, pattern) for pattern in GENERATED_PATTERNS)


def split_diff(diff: str) -> dict[str, str]:
    """Split a unified diff into per-file sections.

    Args:
        diff: The full unified diff of the pull request.

    Returns:
        Mapping of file path to that file's diff section.
    """
    sections: dict[str, str] = {}
    current = None
    for line in diff.splitlines(keepends=True):
        header = re.match(r"diff --git a/.+ b/(.+)$", line.rstrip("\n"))
        if header:
            current = header.group(1)
            sections[current] = ""
        if current is not None:
            sections[current] += line
    return sections


def corresponding_test(path: str) -> str | None:
    """Return the test file that directly corresponds to a production module, if it exists.

    Uses the project convention `app/<package>/<name>.py` → `tests/test_<name>.py`.

    Args:
        path: Repository-relative path of a changed file.

    Returns:
        The test file path, or None if the file is not a production module or has no test.
    """
    file = Path(path)
    if file.parts[:1] != ("app",) or file.suffix != ".py" or file.name == "__init__.py":
        return None
    test = Path("tests") / f"test_{file.stem}.py"
    return str(test) if test.exists() else None


def doc_section(doc: str, heading: str) -> str:
    """Extract one `## ` section from a Markdown document.

    Args:
        doc: Path of the Markdown file.
        heading: Text of the `## ` heading to extract.

    Returns:
        The section, from its heading up to the next `## ` heading, or an empty string if the
        document or heading is missing.
    """
    path = Path(doc)
    if not path.exists():
        return ""
    lines = path.read_text().splitlines()
    try:
        start = lines.index(f"## {heading}")
    except ValueError:
        return ""
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines)
    )
    return "\n".join(lines[start:end]).strip()


def build_bundle(pr: dict, diff: str, instructions: str) -> tuple[str | None, str]:
    """Assemble the bounded review bundle, or decide to skip the paid review.

    Args:
        pr: PR metadata from `gh pr view` (`title`, `body`, `files`).
        diff: The PR's unified diff.
        instructions: The reviewer contract (`AGENTS.md`), sent as the system prompt.

    Returns:
        A `(bundle, reason)` pair. `bundle` is the user message to send, or None when the review
        is skipped; `reason` explains the skip or summarizes what was included.
    """
    files = pr["files"]
    semantic = [f for f in files if not is_generated(f["path"])]
    if not semantic:
        return None, "the PR changes only generated files"

    changed_lines = sum(f["additions"] + f["deletions"] for f in semantic)
    if all(f["path"].endswith(".md") for f in semantic) and changed_lines <= TRIVIAL_DOC_LINES:
        return None, f"the PR is a trivial documentation edit ({changed_lines} changed lines)"

    sections = split_diff(diff)
    file_list = "\n".join(
        f"- {f['path']} (+{f['additions']}/-{f['deletions']})"
        + (" [generated, excluded]" if is_generated(f["path"]) else "")
        for f in files
    )
    required = (
        "<pull_request>\n"
        f"<title>{pr['title']}</title>\n"
        f"<description>\n{pr['body'] or '(none)'}\n</description>\n"
        f"<changed_files>\n{file_list}\n</changed_files>\n"
        "</pull_request>\n\n"
        "<diff>\n"
        + "".join(sections.get(f["path"], "") for f in semantic)
        + "</diff>\n"
    )
    footer = (
        "\nReview this pull request according to your instructions. "
        "Return only the required structure.\n"
    )
    budget = MAX_CONTEXT_CHARS - len(instructions) - len(footer)
    if len(required) > budget:
        return None, (
            f"the PR's reviewable diff ({len(required):,} characters) exceeds the AI-review limit "
            f"({budget:,} characters); split the PR or review it manually"
        )

    optional = []
    changed_paths = {f["path"] for f in semantic}
    # A test file changed by the PR is already in the diff; attach the full file only when the
    # tests did not change, so the reviewer can judge coverage of the changed module.
    tests = {t for p in changed_paths if (t := corresponding_test(p))} - changed_paths
    for path in sorted(tests):
        content = Path(path).read_text()
        optional.append((path, f'<test_file path="{path}">\n{content}</test_file>\n'))
    for prefixes, doc, heading in DOC_SECTIONS:
        if any(p.startswith(prefixes) for p in changed_paths):
            text = doc_section(doc, heading)
            if text:
                label = f"{doc} § {heading}"
                tag = f'<doc_excerpt source="{doc}" section="{heading}">\n{text}\n</doc_excerpt>\n'
                optional.append((label, tag))

    bundle, included, omitted = required, [], []
    for label, text in optional:
        if len(bundle) + len(text) <= budget:
            bundle += "\n" + text
            included.append(label)
        else:
            omitted.append(label)
    if omitted:
        bundle += "\n<note>Omitted for size: " + ", ".join(omitted) + "</note>\n"
    summary = f"{len(semantic)} reviewable files; context: {', '.join(included) or 'diff only'}"
    if omitted:
        summary += f"; omitted for size: {', '.join(omitted)}"
    return bundle + footer, summary


def strip_code_fence(text: str) -> str:
    """Remove a single code fence wrapping the whole response, if present.

    `AGENTS.md` shows the required structure inside a ```text block, so the model sometimes
    echoes the fence. Only a fence around the entire response is removed.

    Args:
        text: The model's response text.

    Returns:
        The text without the surrounding fence.
    """
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text.strip()


def validate_review(text: str) -> list[str]:
    """Check a review against the fixed structure required by `AGENTS.md`.

    Args:
        text: The model's response, without a surrounding code fence.

    Returns:
        Every problem found; an empty list means the review is well-formed.
    """
    problems = []
    if not text.startswith("## AI Review\n"):
        problems.append("does not start with '## AI Review'")

    status = re.search(r"^Status: (PASS|FINDINGS)$", text, re.MULTILINE)
    count = re.search(r"^Findings: ([0-3])$", text, re.MULTILINE)
    severity = re.search(rf"^Highest Severity: (NONE|{SEVERITY_PATTERN})$", text, re.MULTILINE)
    for name, match in (("Status", status), ("Findings", count), ("Highest Severity", severity)):
        if not match:
            problems.append(f"missing or invalid '{name}' line")

    findings_heading = re.search(r"^### Findings$", text, re.MULTILINE)
    summary_heading = re.search(r"^### Summary$", text, re.MULTILINE)
    in_order = (
        findings_heading and summary_heading and findings_heading.end() < summary_heading.start()
    )
    if not in_order:
        problems.append("missing '### Findings' or '### Summary' section, or out of order")
        return problems
    findings = text[findings_heading.end():summary_heading.start()].strip()
    if not text[summary_heading.end():].strip():
        problems.append("empty Summary section")

    starts = list(re.finditer(rf"^\d+\. \[({SEVERITY_PATTERN})\] \S", findings, re.MULTILINE))
    if len(starts) > MAX_FINDINGS:
        problems.append(f"{len(starts)} findings exceeds the maximum of {MAX_FINDINGS}")
    for i, start in enumerate(starts):
        entry = findings[start.start():starts[i + 1].start() if i + 1 < len(starts) else None]
        for field in ("File", "Rule", "Issue", "Verify"):
            if not re.search(rf"^\s+{field}: \S", entry, re.MULTILINE):
                problems.append(f"finding {i + 1} is missing '{field}'")

    if status and count and severity:
        declared = int(count.group(1))
        if declared != len(starts):
            problems.append(f"'Findings: {declared}' does not match {len(starts)} listed findings")
        if declared == 0 and (
            status.group(1) != "PASS" or severity.group(1) != "NONE" or findings != "None."
        ):
            problems.append("zero findings must be 'Status: PASS', severity NONE, and 'None.'")
        listed = {m.group(1) for m in starts}
        if declared > 0 and (status.group(1) != "FINDINGS" or severity.group(1) not in listed):
            problems.append("findings require 'Status: FINDINGS' and a listed highest severity")
    return problems


def review(instructions: str, bundle: str) -> str:
    """Make the single Anthropic API request and return the comment to post.

    The response is validated locally against the required structure. A malformed, truncated,
    or refused response is replaced by a fixed error comment; no second request is made.

    Args:
        instructions: The reviewer contract, sent as the system prompt.
        bundle: The bounded review bundle, sent as the only user message.

    Returns:
        The validated review, or the fixed error comment, followed by a one-line usage footer.

    Raises:
        RuntimeError: If the model is not configured.
    """
    import anthropic  # CI-only dependency; not needed for --dry-run

    model = os.environ.get("AI_REVIEW_MODEL")
    if not model:
        raise RuntimeError("AI_REVIEW_MODEL is not set")

    # The only model request. max_retries=1 only re-sends a request that failed at the network
    # or server; it never re-runs a completed review.
    client = anthropic.Anthropic(max_retries=1)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=instructions,
        messages=[{"role": "user", "content": bundle}],
    )

    text = strip_code_fence(
        "".join(block.text for block in response.content if block.type == "text")
    )
    if response.stop_reason == "refusal":
        problems = ["the model declined to review"]
    elif response.stop_reason == "max_tokens":
        problems = ["the response hit the output-token limit"]
    else:
        problems = validate_review(text)

    usage = (
        f"{model} · {response.usage.input_tokens:,} input / "
        f"{response.usage.output_tokens:,} output tokens"
    )
    if problems:
        print("AI review response rejected: " + "; ".join(problems))
        print("Rejected response:\n" + text)
        return (
            f"{INVALID_RESPONSE_COMMENT}\n<sub>Advisory AI review · {usage} · response rejected "
            f"by local format validation.</sub>\n"
        )
    return (
        f"{text}\n\n<sub>Advisory AI review · {usage} · findings are hypotheses for the "
        f"developer to verify.</sub>\n"
    )


def main() -> int:
    """Gather the bundle for a pull request, review it once, and write the result.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pr", type=int, required=True, help="pull request number")
    parser.add_argument("--output", type=Path, help="file to write the review comment to")
    parser.add_argument(
        "--dry-run", action="store_true", help="report the bundle size without calling the API"
    )
    args = parser.parse_args()

    instructions = Path("AGENTS.md").read_text()
    pr = json.loads(run_gh("pr", "view", str(args.pr), "--json", "title,body,files"))
    diff = run_gh("pr", "diff", str(args.pr))
    bundle, reason = build_bundle(pr, diff, instructions)

    if bundle is None:
        print(f"Skipping AI review: {reason}.")
        comment = f"## AI Review\n\nStatus: SKIPPED\n\nNo model call was made: {reason}.\n"
    else:
        size = len(instructions) + len(bundle)
        print(f"Review bundle: {size:,} characters (~{size // 4:,} input tokens). {reason}.")
        if args.dry_run:
            return 0
        comment = review(instructions, bundle)

    if args.output:
        args.output.write_text(comment)
    else:
        print(comment)
    return 0


if __name__ == "__main__":
    sys.exit(main())
