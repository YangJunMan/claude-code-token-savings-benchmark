import csv
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/published-measurements.csv"
OUTPUT = ROOT / "docs/GENERATED_RESULTS.md"


def mean(rows, field):
    return sum(float(row[field]) for row in rows) / len(rows)


def saving(reference, treatment):
    return 100 * (reference - treatment) / reference


def relative_range(values):
    average = sum(values) / len(values)
    return 100 * (max(values) - min(values)) / average


def format_optional(value):
    return value if value else "not scored"


def format_mean(value, digits=0):
    quantum = Decimal("1").scaleb(-digits)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{rounded:,.{digits}f}"


def main():
    rows = list(csv.DictReader(SOURCE.open()))
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["condition"]].append(row)

    base = grouped["BASE"]
    headroom = grouped["H-ON"]
    base_cost = mean(base, "cost_usd")
    base_tokens = mean(base, "total_processed_tokens")
    base_output = mean(base, "output_tokens")
    headroom_cost = mean(headroom, "cost_usd")
    headroom_tokens = mean(headroom, "total_processed_tokens")
    headroom_output = mean(headroom, "output_tokens")

    lines = [
        "# Generated benchmark table", "",
        "> Source: `data/published-measurements.csv`. The tables are reproducible from sanitized aggregates; raw private transcripts are not published.", "",
        "## Individual runs", "",
        "| Run | Condition | Cost | Processed tokens | Output tokens | Quality | Critical | Turns | Validation |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['run_id']} | {row['condition']} | ${float(row['cost_usd']):.3f} | "
            f"{int(row['total_processed_tokens']):,} | {int(row['output_tokens']):,} | "
            f"{format_optional(row['quality_score'])} | {format_optional(row['critical_pass'])} | "
            f"{row['turns']} | {row['validation']} |"
        )

    lines.extend([
        "", "## Condition means", "",
        "| Condition | Cost | Processed tokens | Output tokens | Observations |",
        "|---|---:|---:|---:|---:|",
        f"| BASE mean (n=2) | ${format_mean(base_cost, 3)} | {format_mean(base_tokens)} | {format_mean(base_output)} | 2 |",
        f"| H-ON mean (n=2) | ${format_mean(headroom_cost, 3)} | {format_mean(headroom_tokens)} | {format_mean(headroom_output)} | 2 |",
    ])
    for condition in ("C-FULL", "C-BRIEF", "R-ON"):
        group = grouped[condition]
        lines.append(
            f"| {condition} (n={len(group)}) | ${format_mean(mean(group, 'cost_usd'), 3)} | "
            f"{format_mean(mean(group, 'total_processed_tokens'))} | "
            f"{format_mean(mean(group, 'output_tokens'))} | {len(group)} |"
        )

    lines.extend([
        "", "## Relative to the two-run baseline mean", "",
        "| Condition | Cost saving | Processed-token saving | Output-token saving |",
        "|---|---:|---:|---:|",
        f"| H-ON | +{saving(base_cost, headroom_cost):.1f}% | +{saving(base_tokens, headroom_tokens):.1f}% | +{saving(base_output, headroom_output):.1f}% |",
    ])
    for condition in ("C-FULL", "C-BRIEF", "R-ON"):
        group = grouped[condition]
        lines.append(
            f"| {condition} | {saving(base_cost, mean(group, 'cost_usd')):+.1f}% | "
            f"{saving(base_tokens, mean(group, 'total_processed_tokens')):+.1f}% | "
            f"{saving(base_output, mean(group, 'output_tokens')):+.1f}% |"
        )

    base_context = [float(row["cache_read_tokens"]) / int(row["turns"]) for row in base]
    headroom_context = [float(row["cache_read_tokens"]) / int(row["turns"]) for row in headroom]
    base_cost_per_turn = [float(row["cost_usd"]) / int(row["turns"]) for row in base]
    headroom_cost_per_turn = [float(row["cost_usd"]) / int(row["turns"]) for row in headroom]
    diagnostics = [
        ("Total cost", [float(row["cost_usd"]) for row in base], [float(row["cost_usd"]) for row in headroom], "Borderline"),
        ("Cost per turn", base_cost_per_turn, headroom_cost_per_turn, "Borderline"),
        ("Context per turn", base_context, headroom_context, "Robust"),
        ("Output tokens", [float(row["output_tokens"]) for row in base], [float(row["output_tokens"]) for row in headroom], "Within noise"),
    ]
    lines.extend([
        "", "## Headroom repeat diagnostics", "",
        "| Metric | H-ON vs BASE | H-ON spread | BASE spread | Ranges overlap | Assessment |",
        "|---|---:|---:|---:|---|---|",
    ])
    for label, base_values, headroom_values, assessment in diagnostics:
        overlap = not (max(headroom_values) < min(base_values) or max(base_values) < min(headroom_values))
        lines.append(
            f"| {label} | {-saving(sum(base_values) / 2, sum(headroom_values) / 2):+.1f}% | "
            f"{relative_range(headroom_values):.1f}% | {relative_range(base_values):.1f}% | "
            f"{'Yes' if overlap else 'No'} | {assessment} |"
        )

    lines.extend([
        "", "The original single H-ON observation overstated cost saving as 35.6%. With two H-ON runs, the mean cost saving is 26.4% and the within-condition spread is 25.1%, so cost is a borderline signal.", "",
        "Context per turn is the more stable mechanism metric: H-ON reduced it by 41.4%, the H-ON spread was 10.6%, and neither H-ON value overlapped the BASE range.", "",
        "H-ON-02 passed the public test suite but was not run through the held-out grader. Quality 98 and critical 6/6 therefore describe H-ON-01 only, not the two-run mean.",
    ])
    OUTPUT.write_text("\n".join(lines) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
