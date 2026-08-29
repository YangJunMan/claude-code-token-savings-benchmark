import csv
import json
from pathlib import Path

from benchmark.runner.usage import parse_usage


PAIR_DEFINITIONS = (
    ("Headroom ON vs OFF", "H-ON", "H-OFF"),
    ("Caveman full vs non", "C-FULL", "C-NON"),
    ("Caveman brief vs non", "C-BRIEF", "C-NON"),
    ("RTK ON vs OFF", "R-ON", "R-OFF"),
)


def paired_comparisons(rows):
    by_condition = {row["condition"]: row for row in rows}
    comparisons = []
    for label, treatment_name, baseline_name in PAIR_DEFINITIONS:
        if treatment_name not in by_condition or baseline_name not in by_condition:
            continue
        treatment = by_condition[treatment_name]
        baseline = by_condition[baseline_name]
        token_base = baseline["total_processed_tokens"]
        cost_base = baseline["cost_usd"]
        token_pct = 100 * (token_base - treatment["total_processed_tokens"]) / token_base
        cost_pct = 100 * (cost_base - treatment["cost_usd"]) / cost_base
        quality_delta = treatment["quality_score"] - baseline["quality_score"]
        quality_gate = (
            bool(treatment["critical_pass"])
            and bool(baseline["critical_pass"])
            and quality_delta >= -5
        )
        comparisons.append({
            "comparison": label,
            "treatment": treatment_name,
            "baseline": baseline_name,
            "token_saving_pct": token_pct,
            "cost_saving_pct": cost_pct,
            "quality_delta": quality_delta,
            "quality_gate_pass": quality_gate,
            "recommended": token_pct > 0 and cost_pct > 0 and quality_gate,
        })
    return comparisons


def _acceptable(result):
    cleared = bool(result.get("clear_succeeded"))
    completed = result.get("returncode") == 0
    budget_exhausted = (
        result.get("terminal_reason") == "max_turns"
        and result.get("public_returncode") == 0
    )
    return cleared and (completed or budget_exhausted)


def _row_for(result_path):
    result = json.loads(result_path.read_text())
    usage = parse_usage(result)
    quality_path = result_path.parent / "quality.json"
    manifest_path = result_path.parent / "manifest.json"
    quality = json.loads(quality_path.read_text()) if quality_path.exists() else {}
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    transcript = manifest.get("transcript", result.get("transcript_summary", {}))
    lines = manifest.get("changed_lines", {})
    return {
        "condition": result_path.parts[-3],
        "attempt": result_path.parts[-2],
        "valid": _acceptable(result),
        "input_tokens": usage.input_tokens,
        "cache_creation_tokens": usage.cache_creation_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "input_related_tokens": usage.input_related_tokens,
        "output_tokens": usage.output_tokens,
        "total_processed_tokens": usage.total_processed_tokens,
        "cost_usd": usage.cost_usd,
        "quality_score": int(quality.get("score", 0)),
        "critical_pass": bool(quality.get("critical_pass", False)),
        "turns": int(transcript.get("turns", result.get("num_turns", 0)) or 0),
        "tool_calls": int(transcript.get("tool_calls", 0) or 0),
        "first_turn_cache_read_tokens": int(transcript.get("first_turn_cache_read_tokens", -1)),
        "changed_lines": int(lines.get("changed", 0) or 0),
        "started_epoch": float(result.get("started_epoch", 0) or 0),
        "last_request_epoch": float(result.get("last_request_epoch", 0) or 0),
        "duration_seconds": float(result.get("duration_ms", 0) or 0) / 1000,
        "terminal_reason": result.get("terminal_reason", "completed"),
    }


def collect_rows(run_root):
    all_rows = [_row_for(path) for path in sorted(run_root.glob("*/*/result.json"))]
    valid = []
    for condition in ("H-ON", "H-OFF", "C-FULL", "C-NON", "C-BRIEF", "R-ON", "R-OFF"):
        candidates = [row for row in all_rows if row["condition"] == condition and row["valid"]]
        if candidates:
            valid.append(candidates[-1])
    invalid = [row for row in all_rows if not row["valid"]]
    return valid, invalid


def _pct(value):
    return f"{value:+.2f}%"


def _markdown_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def generate_report(run_root: Path, report_dir: Path):
    report_dir.mkdir(parents=True, exist_ok=True)
    rows, invalid = collect_rows(run_root)
    csv_path = report_dir / "measurements.csv"
    csv_fields = [
        "condition", "attempt", "input_tokens", "cache_creation_tokens", "cache_read_tokens",
        "input_related_tokens", "output_tokens", "total_processed_tokens", "cost_usd",
        "quality_score", "critical_pass", "turns", "tool_calls",
        "first_turn_cache_read_tokens", "changed_lines", "duration_seconds", "terminal_reason",
    ]
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    comparisons = paired_comparisons(rows)
    total_cost = sum(row["cost_usd"] for row in rows)
    lines = [
        "# Token Optimizer Benchmark Results", "",
        "이 보고서의 비용은 provider가 반환한 API-equivalent estimated cost이며 Claude Pro 구독료에 추가 청구된 금액이 아니다.", "",
        f"Valid conditions: {len(rows)}/7 · Invalid attempts: {len(invalid)} · Total API-equivalent cost: ${total_cost:.6f}", "",
        "## Condition measurements", "",
    ]
    lines.extend(_markdown_table(
        ["Condition", "Input", "Cache create", "Cache read", "Output", "Total", "Cost USD", "Quality", "Critical", "Turns", "Tools"],
        [[
            row["condition"], f"{row['input_tokens']:,}", f"{row['cache_creation_tokens']:,}",
            f"{row['cache_read_tokens']:,}", f"{row['output_tokens']:,}",
            f"{row['total_processed_tokens']:,}", f"${row['cost_usd']:.6f}",
            f"{row['quality_score']}/100", "PASS" if row["critical_pass"] else "FAIL",
            row["turns"], row["tool_calls"],
        ] for row in rows],
    ))
    lines.extend(["", "## Paired comparisons", ""])
    lines.extend(_markdown_table(
        ["Comparison", "Token saving", "Cost saving", "Quality delta", "Quality gate", "Recommendation"],
        [[
            item["comparison"], _pct(item["token_saving_pct"]), _pct(item["cost_saving_pct"]),
            f"{item['quality_delta']:+d}", "PASS" if item["quality_gate_pass"] else "FAIL",
            "YES" if item["recommended"] else "NO",
        ] for item in comparisons],
    ))
    lines.extend(["", "## Cache isolation and washout", ""])
    if rows:
        isolation_rows = []
        for index, row in enumerate(rows):
            if index == 0:
                gap = "N/A"
                washout = "N/A"
            else:
                seconds = row["started_epoch"] - rows[index - 1]["last_request_epoch"]
                gap = f"{seconds:.1f}s"
                washout = "PASS" if seconds >= 4200 else "FAIL"
            first_cache = row["first_turn_cache_read_tokens"]
            cache_gate = "PASS" if first_cache == 0 else ("UNKNOWN" if first_cache < 0 else "FAIL")
            isolation_rows.append([row["condition"], gap, washout, first_cache, cache_gate])
        lines.extend(_markdown_table(
            ["Condition", "Gap from previous", "70m washout", "First-turn cache read", "Cache gate"],
            isolation_rows,
        ))
    if invalid:
        lines.extend(["", "## Invalid attempts", ""])
        lines.extend(f"- {row['condition']}/{row['attempt']}: {row['terminal_reason']}" for row in invalid)
    lines.extend([
        "", "## Interpretation limits", "",
        "- 각 조건은 유효 관측치 1회이므로 통계적 유의성을 주장할 수 없다.",
        "- 고정 실행 순서 때문에 시간대별 service load와 subscription quota drift가 조건 효과에 섞일 수 있다.",
        "- Claude의 비결정성과 28-turn 상한은 구현 범위와 최종 응답 완성도에 영향을 줄 수 있다.",
        "- 양의 token/cost 절감과 quality gate 통과가 동시에 확인된 비교에만 Recommendation=YES를 부여한다.",
    ])
    (report_dir / "final-report.md").write_text("\n".join(lines) + "\n")
    return rows
