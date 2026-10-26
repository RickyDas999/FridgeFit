"""Evaluate the deterministic meal planner on the fixed scenarios and save the results.

Developer tooling, not application code. Run from the repository root:

    .venv/bin/python scripts/evaluate_planner.py

It needs no database or network: scenarios are built in memory. The validated results are
written as JSON to ``evaluation-results/`` (git-ignored), and a short summary is printed.
"""

import argparse
from datetime import datetime
from pathlib import Path

from app.evaluation.metrics import evaluate_baseline
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
    path = results_dir / f"{run.created_at:%Y%m%d-%H%M%S}-{run.planner}.json"
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
    lines.append(
        f"Compliant {summary.hard_constraint_compliant}/{summary.scenarios}, "
        f"no shortfalls {summary.plans_without_shortfalls}/{summary.scenarios}, "
        f"{summary.total_calories_over:.0f} kcal over in total, "
        f"rubric {summary.rubric_checks_passed}/{summary.rubric_checks}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Run the evaluation, write the results file, and print the summary.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.
    """
    parser = argparse.ArgumentParser(description="Evaluate the meal planner on fixed scenarios.")
    parser.add_argument(
        "--results-dir", type=Path, default=RESULTS_DIR, help="where to write the JSON results"
    )
    args = parser.parse_args(argv)

    run = evaluate_baseline(created_at=datetime.now())
    path = write_run(run, args.results_dir)
    print(format_summary(run))
    print(f"Results: {path}")


if __name__ == "__main__":
    main()
