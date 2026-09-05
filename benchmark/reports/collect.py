"""Accumulate finished batches into the two published CSVs.

The runner writes heavy per-attempt artifacts that stay out of git.  This turns
one batch of them into rows anyone can recompute from, and is safe to rerun: a
batch that was collected halfway gets finished rather than doubled.
"""

import csv
import json
from pathlib import Path

from benchmark.reports.activity_log import (
    ACTIVITY_COLUMNS, activity_rows, extract_turns, is_measurable, reconcile,
    with_context_tax,
)
from benchmark.runner.usage import parse_usage


SUMMARY_COLUMNS = (
    "run_date", "run_id", "condition", "cost_usd", "quality_score",
    "critical_pass", "turns", "measurable",
    # Stored, not left for the page to re-derive: a second copy of the formula
    # is a second place for it to drift from what was published.
    "reconcile_observed", "reconcile_opening", "reconcile_output",
    "reconcile_tool_result", "reconcile_discarded",
)


def _rewrite(destination, columns, run_date, rows):
    """Replace this batch's rows in place, keeping every other batch untouched."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    kept = []
    if destination.exists():
        with destination.open() as stream:
            reader = csv.DictReader(stream)
            kept = [row for row in reader if row.get("run_date") != run_date]
    with destination.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row in kept:
            writer.writerow([row.get(name, "") for name in columns])
        writer.writerows(rows)
    return destination


def run_identity(attempt_dir, condition):
    """Name one attempt uniquely.

    The weekly runner groups repeats under the condition's own directory
    (``BASE/attempt-01``, ``BASE/attempt-02``), so the directory name repeats and
    the attempt number is what separates them.  The API path already labels
    directories per run (``BASE-01/attempt-01``), where appending the attempt
    again would read as ``BASE-01-01``.
    """
    label = attempt_dir.parent.name
    if label != condition:
        return label
    return f"{condition}-{attempt_dir.name.split('-')[-1]}"


def critical_pass(quality):
    """Report passed-of-total.  The grader also writes a bare boolean, which
    loses how close a run came and does not match the published column."""
    total = quality.get("critical_total")
    if total is None:
        return quality.get("critical_pass", "")
    return f"{quality.get('critical_passed', 0)}/{total}"


def collect_batch(run_root, activity_path, summary_path):
    """Read one batch of attempts and append them to the published CSVs."""
    run_root = Path(run_root)
    run_date = run_root.name
    activity = []
    summary = []
    for result_path in sorted(run_root.glob("*/*/result.json")):
        attempt_dir = result_path.parent
        transcript = attempt_dir / "transcript.jsonl"
        if not transcript.exists():
            continue
        result = json.loads(result_path.read_text())
        condition = result.get("condition", attempt_dir.parent.name)
        run_id = run_identity(attempt_dir, condition)
        turns = with_context_tax(extract_turns(transcript))
        activity.extend(activity_rows(run_date, run_id, condition, turns))
        quality_path = attempt_dir / "quality.json"
        quality = json.loads(quality_path.read_text()) if quality_path.exists() else {}
        shares = reconcile(turns)
        summary.append([
            run_date, run_id, condition,
            parse_usage(result).cost_usd,
            quality.get("score", ""),
            critical_pass(quality),
            len(turns),
            int(is_measurable(turns)),
            shares["observed"], shares["opening"], shares["output"],
            shares["tool_result"], shares["discarded"],
        ])
    _rewrite(activity_path, ACTIVITY_COLUMNS, run_date, activity)
    _rewrite(summary_path, SUMMARY_COLUMNS, run_date, summary)
    return {"run_date": run_date, "runs": len(summary), "turns": len(activity)}
