"""The arithmetic that turns runs into a comparison, in one place.

The page used to compute this in JavaScript while ``reports.generate`` computed
it in Python.  Two implementations of the same formula are two chances to
disagree about a published number, so the numbers are produced here, written to
``data/comparison.csv``, and merely read by the page.

Every figure is a ratio of published totals.  Comparisons are made *inside* a
batch: each batch has its own baseline, and averaging totals across batches
would let a batch that only ran BASE move the yardstick for every other one.
"""

from benchmark.runner.conditions import conditions as declared_conditions


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def baseline_id(conditions=None):
    """The declared condition that applies no treatment."""
    conditions = declared_conditions() if conditions is None else conditions
    for item in conditions.values():
        if item.mechanism == "none":
            return item.value
    return next(iter(conditions))


def spread_pct(values):
    """Gap between repeated observations, as a share of their mean.

    Undefined below two observations: a single run has no spread, and reporting
    0.0 would read as "perfectly repeatable" instead of "not measured".
    """
    values = list(values)
    if len(values) < 2:
        return None
    average = _mean(values)
    return 100 * (max(values) - min(values)) / average if average else 0.0


def delta_pct(treatment, base):
    """Signed difference, increase-positive.  ``None`` when there is no base."""
    if not base:
        return None
    return 100 * (treatment - base) / base


def batch_comparison(runs, conditions=None):
    """Compare one batch's treatments against that batch's own baseline."""
    baseline = baseline_id(conditions)
    base_runs = [run for run in runs if run["condition"] == baseline]
    noise = {
        "processed": spread_pct(run["processed"] for run in base_runs),
        "cost": spread_pct(run["cost"] for run in base_runs),
        "baseline_runs": len(base_runs),
    }
    if not base_runs:
        return {"noise": noise, "conditions": []}

    base = {field: _mean(run[field] for run in base_runs)
            for field in ("processed", "cost", "tax", "quality")}
    grouped = {}
    for run in runs:
        if run["condition"] != baseline:
            grouped.setdefault(run["condition"], []).append(run)

    rows = []
    for condition in sorted(grouped):
        group = grouped[condition]
        rows.append({
            "condition": condition,
            "runs": len(group),
            "processed": delta_pct(_mean(r["processed"] for r in group), base["processed"]),
            "cost": delta_pct(_mean(r["cost"] for r in group), base["cost"]),
            "tax": delta_pct(_mean(r["tax"] for r in group), base["tax"]),
            "quality": _mean(r["quality"] for r in group) - base["quality"],
        })
    return {"noise": noise, "conditions": rows}


COMPARISON_COLUMNS = (
    "run_date", "condition", "runs", "baseline_runs",
    "processed_delta_pct", "cost_delta_pct", "tax_delta_pct", "quality_delta",
    "noise_processed_pct", "noise_cost_pct",
)


def _round(value, digits=4):
    return "" if value is None else round(value, digits)


def comparison_rows(run_date, runs, conditions=None):
    """One published row per treatment condition in this batch."""
    result = batch_comparison(runs, conditions)
    noise = result["noise"]
    return [[
        run_date, row["condition"], row["runs"], noise["baseline_runs"],
        _round(row["processed"]), _round(row["cost"]), _round(row["tax"]),
        _round(row["quality"]),
        _round(noise["processed"]), _round(noise["cost"]),
    ] for row in result["conditions"]]
