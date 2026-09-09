"""Accumulate finished batches into the two published CSVs.

The runner writes heavy per-attempt artifacts that stay out of git.  This turns
one batch of them into rows anyone can recompute from, and is safe to rerun: a
batch that was collected halfway gets finished rather than doubled.
"""

import csv
import json
from pathlib import Path

from benchmark.reports.comparison import COMPARISON_COLUMNS, comparison_rows
from benchmark.reports.activity_log import (
    ACTIVITY_COLUMNS, activity_rows, extract_turns, is_measurable, reconcile,
    with_context_tax,
)
from benchmark.runner.usage import parse_usage
from benchmark.runner.contracts import is_acceptable_result
from benchmark.runner.scheduler import classify_failure


def aux_model_tokens(result, main_model):
    """Tokens billed to models other than the one under test.

    Claude Code runs a helper model for side work (naming the conversation, for
    one).  Those calls never appear as turns, so the per-turn decomposition
    cannot see them and its total sits below the provider's.  Recording the
    difference keeps that gap checkable once the raw transcripts are gone.
    """
    raw = result.get("modelUsage") or result.get("model_usage") or {}
    total = 0
    for model, usage in raw.items():
        if model == main_model:
            continue
        total += sum(int(usage.get(key, usage.get(snake, 0)) or 0) for key, snake in (
            ("inputTokens", "input_tokens"),
            ("cacheCreationInputTokens", "cache_creation_input_tokens"),
            ("cacheReadInputTokens", "cache_read_input_tokens"),
            ("outputTokens", "output_tokens"),
        ))
    return total


def washout_gaps(runs):
    """Seconds between one run finishing its last request and the next starting.

    The cache-isolation rule is the reason a batch takes eight hours; published
    data has to let a reader check it was actually honoured.
    """
    ordered = sorted(runs, key=lambda r: r["started_epoch"])
    gaps = {ordered[0]["run_id"]: ""} if ordered else {}
    for previous, current in zip(ordered, ordered[1:]):
        gaps[current["run_id"]] = round(
            current["started_epoch"] - previous["last_request_epoch"])
    return gaps


SUMMARY_COLUMNS = (
    "run_date", "run_id", "condition", "cost_usd", "quality_score",
    "critical_pass", "turns", "measurable", "invalid_reason",
    # Stored, not left for the page to re-derive: a second copy of the formula
    # is a second place for it to drift from what was published.
    "reconcile_observed", "reconcile_opening", "reconcile_output",
    "reconcile_tool_result", "reconcile_discarded",
    # Kept because the raw transcripts are not retained: without these the
    # cache-isolation and auxiliary-model claims stop being checkable.
    "model", "duration_seconds", "terminal_reason", "changed_files", "tool_calls",
    "first_turn_cache_read_tokens", "washout_gap_seconds", "aux_model_tokens",
    # The overview needs only these two from the turn log. Publishing them lets
    # that screen stay independent of the largest file as batches accumulate.
    "processed_tokens", "context_tax_tokens",
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


def invalid_reason(result, turns):
    """Say why a run is excluded from ``comparable``, not just that it is.

    A run can fail more than one of these at once - the 2026-09-08 C-BRIEF
    attempt both hit a Claude session quota limit *and* compacted mid-run -
    so every applicable cause is reported, joined with ``+``, rather than
    only the first one a bool check happens to trip on.
    """
    if is_acceptable_result(result) and is_measurable(turns):
        return ""
    reasons = []
    transcript = result.get("transcript_summary") or {}
    first_read = transcript.get("first_turn_cache_read_tokens")
    if first_read is None or int(first_read) < 0:
        reasons.append("cache_evidence_missing")
    if result.get("terminal_reason", "completed") == "max_turns":
        reasons.append("max_turns")
    elif result.get("returncode") != 0 or result.get("is_error"):
        failure = classify_failure(json.dumps(result))
        reasons.append("quota_interrupted" if failure.invalidate_attempt else "execution_error")
    if not result.get("changed_files"):
        reasons.append("no_changed_files")
    if not (result.get("final_text") or "").strip():
        reasons.append("empty_response")
    if turns and not reconcile(turns)["balanced"]:
        reasons.append("reconcile_unbalanced")
    if any(turn.compacted for turn in turns):
        reasons.append("compacted")
    if not turns:
        reasons.append("no_turns")
    return "+".join(reasons) or "unknown"


def critical_pass(quality):
    """Report passed-of-total.  The grader also writes a bare boolean, which
    loses how close a run came and does not match the published column."""
    total = quality.get("critical_total")
    if total is None:
        return quality.get("critical_pass", "")
    return f"{quality.get('critical_passed', 0)}/{total}"


def collect_batch(run_root, activity_path, summary_path, comparison_path=None):
    """Read one batch of attempts and append them to the published CSVs."""
    run_root = Path(run_root)
    run_date = run_root.name
    activity = []
    summary = []
    comparable = []
    timing = []
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
        transcript_summary = result.get("transcript_summary") or {}
        # The main model is whichever one produced the turns being decomposed.
        # modelUsage is keyed in billing order, so its first entry is often
        # the helper model instead of the one whose context we are measuring.
        model = turns[0].model if turns else ""
        timing.append({
            "run_id": run_id,
            "started_epoch": float(result.get("started_epoch", 0) or 0),
            "last_request_epoch": float(result.get("last_request_epoch", 0) or 0),
        })
        measurable = is_acceptable_result(result) and is_measurable(turns)
        if measurable:
            comparable.append({
                "condition": condition,
                # The same totals the page shows, so a published percentage can be
                # rederived from the published per-turn rows.
                "processed": sum(t.context_tokens + t.output_tokens for t in turns),
                "tax": sum(t.context_tax_tokens for t in turns),
                "cost": parse_usage(result).cost_usd,
                "quality": quality.get("score", 0) or 0,
            })
        summary.append([
            run_date, run_id, condition,
            parse_usage(result).cost_usd,
            quality.get("score", ""),
            critical_pass(quality),
            len(turns),
            int(measurable),
            "" if measurable else invalid_reason(result, turns),
            shares["observed"], shares["opening"], shares["output"],
            shares["tool_result"], shares["discarded"],
            model,
            round(float(result.get("duration_ms", 0) or 0) / 1000, 1),
            result.get("terminal_reason", ""),
            len(result.get("changed_files") or []),
            transcript_summary.get("tool_calls", ""),
            transcript_summary.get("first_turn_cache_read_tokens", ""),
            run_id,   # replaced below with the gap once every run is known
            aux_model_tokens(result, model),
            sum(turn.context_tokens + turn.output_tokens for turn in turns),
            sum(turn.context_tax_tokens for turn in turns),
        ])
    if not summary:
        # The raw run directories are not retained, so a batch that yields
        # nothing means the originals are gone - not that the batch was empty.
        # Rewriting here would replace published rows with nothing, and there
        # would be no way back.
        return {"run_date": run_date, "runs": 0, "turns": 0, "wrote": False}

    # The gap needs every run's timing, so it is filled in after the walk.
    gaps = washout_gaps(timing)
    slot = SUMMARY_COLUMNS.index("washout_gap_seconds")
    for row in summary:
        row[slot] = gaps.get(row[slot], "")

    _rewrite(activity_path, ACTIVITY_COLUMNS, run_date, activity)
    _rewrite(summary_path, SUMMARY_COLUMNS, run_date, summary)
    if comparison_path is not None:
        _rewrite(comparison_path, COMPARISON_COLUMNS, run_date,
                 comparison_rows(run_date, comparable))
    return {"run_date": run_date, "runs": len(summary), "turns": len(activity),
            "wrote": True}
