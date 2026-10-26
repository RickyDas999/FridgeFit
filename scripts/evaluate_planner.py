"""Evaluate meal planners on the fixed scenarios and save the results.

Developer tooling, not application code. Run from the repository root:

    .venv/bin/python scripts/evaluate_planner.py

evaluates the deterministic baseline only: no database, no network, no cost. To also evaluate
Claude configurations, which calls the Anthropic API and costs money, pass ``--live`` and one
``--config MODEL:RUNS`` per model, with ``ANTHROPIC_API_KEY`` set:

    .venv/bin/python scripts/evaluate_planner.py --live \
        --config claude-haiku-5-5:3 --config claude-sonnet-5-5:1 --config claude-opus-5-5:1

Estimated spend is capped (``--max-cost-usd``, default 1.00): no attempt starts once the
estimate reaches it. Each run's validated results are written as JSON to
``evaluation-results/`` (git-ignored), and a summary is printed.
"""

import argparse
from datetime import datetime
from pathlib import Path

from app.application.ai_planner import EFFORT_LEVELS, PlannerConfig, make_client
from app.evaluation.metrics import SpendingCap, evaluate_ai, evaluate_baseline
from app.evaluation.pricing import PRICES
from app.evaluation.results import EvaluationRun

RESULTS_DIR = Path(__file__).resolve().parent.parent / "evaluation-results"


def write_run(run: EvaluationRun, results_dir: Path) -> Path:
    """Write an evaluation run as JSON, named by planner and time.

    Args:
        run: The validated run.
        results_dir: Directory for result files; created if missing.

    Returns:
        The path written.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    # Planner names such as "claude-haiku-5-5:low" hold a colon, which some file systems reject.
    safe_name = run.planner.replace(":", "_")
    path = results_dir / f"{run.created_at:%Y%m%d-%H%M%S}-{safe_name}.json"
    path.write_text(run.model_dump_json(indent=2) + "\n")
    return path


def format_summary(run: EvaluationRun) -> str:
    """Describe a run in a few readable lines.

    Args:
        run: The run to describe.

    Returns:
        The summary text.
    """
    lines = [f"Planner: {run.planner}, {len(run.results)} scenarios"]
    for result in run.results:
        flags = []
        if result.hard_constraint_violations:
            flags.append(f"{len(result.hard_constraint_violations)} violations")
        if result.meals_with_shortfalls:
            flags.append(f"{result.meals_with_shortfalls} meal(s) short")
        if result.macros and result.macros.calories_over:
            flags.append(f"{result.macros.calories_over:.0f} kcal over")
        if result.expiring_food.share_used is not None:
            flags.append(f"{result.expiring_food.share_used:.0%} of expiring food used")
        failed = [check.rule for check in result.preference.checks if not check.passed]
        if failed:
            flags.append(f"preference missed: {'; '.join(failed)}")
        lines.append(
            f"  {result.scenario_id}: {result.meals_planned}/{result.meals_requested} meals"
            + (f" ({', '.join(flags)})" if flags else "")
        )
    summary = run.summary
    if summary.ai:
        ai = summary.ai
        cost = "unknown" if ai.estimated_cost_usd is None else f"${ai.estimated_cost_usd:.4f}"
        lines.append(
            f"AI: {ai.ai_plans_used}/{ai.attempts} AI plans used ({ai.corrected_plans_used} after "
            f"a correction), {ai.fallbacks} fallbacks, {ai.invalid_tool_calls} invalid tool "
            f"calls, {ai.input_tokens} in / {ai.output_tokens} out tokens, "
            f"mean {ai.mean_total_seconds or 0:.1f} s (max {ai.max_total_seconds or 0:.1f} s), "
            f"est. {cost}"
        )
        fallbacks = sorted({r.ai.fallback_reason for r in run.results if r.ai.fallback_reason})
        lines.extend(f"  fallback: {reason}" for reason in fallbacks)
    if run.stopped_early:
        lines.append(f"Stopped early: {run.stopped_early}")
    lines.append(
        f"Compliant {summary.hard_constraint_compliant}/{summary.scenarios}, "
        f"no shortfalls {summary.plans_without_shortfalls}/{summary.scenarios}, "
        f"{summary.total_calories_over:.0f} kcal over in total, "
        f"rubric {summary.rubric_checks_passed}/{summary.rubric_checks}"
    )
    return "\n".join(lines)


def parse_config(value: str) -> tuple[str, int]:
    """Parse a ``MODEL:RUNS`` command-line value.

    Args:
        value: e.g. ``claude-haiku-5-5:3``.

    Returns:
        The model and the number of runs per scenario.

    Raises:
        argparse.ArgumentTypeError: If the value is malformed, runs is not positive, or the model
            has no listed price (the spending cap needs one).
    """
    model, _, runs = value.rpartition(":")
    if not model or not runs.isdigit() or int(runs) < 1:
        raise argparse.ArgumentTypeError(f"expected MODEL:RUNS with RUNS >= 1, got {value!r}")
    if ("anthropic", model) not in PRICES:
        priced = ", ".join(name for _, name in PRICES)
        raise argparse.ArgumentTypeError(f"no listed price for {model!r}; priced: {priced}")
    return model, int(runs)


def main(argv: list[str] | None = None, client=None) -> None:
    """Run the evaluation, write a results file per planner, and print each summary.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.
        client: An Anthropic client to use instead of one made from ``ANTHROPIC_API_KEY``
            (tests pass a stand-in).

    Raises:
        SystemExit: On bad arguments, ``--config`` without ``--live``, or ``--live`` without an
            API key; nothing is called or spent.
    """
    parser = argparse.ArgumentParser(description="Evaluate meal planners on fixed scenarios.")
    parser.add_argument(
        "--results-dir", type=Path, default=RESULTS_DIR, help="where to write the JSON results"
    )
    parser.add_argument(
        "--live", action="store_true", help="allow calls to the Anthropic API (costs money)"
    )
    parser.add_argument(
        "--config", type=parse_config, action="append", default=[], metavar="MODEL:RUNS",
        help="a Claude model to evaluate and how many runs per scenario; repeatable",
    )
    parser.add_argument("--effort", choices=EFFORT_LEVELS, default="low")
    parser.add_argument("--max-cost-usd", type=float, default=1.00)
    args = parser.parse_args(argv)
    if args.config and not args.live:
        parser.error("--config calls the Anthropic API and costs money; add --live to allow it")
    if args.config:
        client = client or make_client()
        if client is None:
            parser.error("--live needs ANTHROPIC_API_KEY in the environment")

    runs = [evaluate_baseline(created_at=datetime.now())]
    cap = SpendingCap(args.max_cost_usd)
    for model, repeats in args.config:
        config = PlannerConfig(model=model, effort=args.effort)
        runs.append(evaluate_ai(config, client, repeats, cap, created_at=datetime.now()))
    for run in runs:
        path = write_run(run, args.results_dir)
        print(format_summary(run))
        print(f"Results: {path}\n")
    if args.config:
        print(f"Estimated spend: ${cap.spent_usd:.4f} of a ${cap.max_usd:.2f} cap")


if __name__ == "__main__":
    main()
