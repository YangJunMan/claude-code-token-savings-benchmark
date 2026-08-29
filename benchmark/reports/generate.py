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


def _clear_verified(result, attempt_dir=None):
    """Return whether clear evidence is valid, preserving recovery evidence.

    Older API attempts did not echo slash-command input in the TUI, so their
    original result can say ``clear_succeeded=false`` even though the runner
    sent ``/clear`` and captured the resumed-session marker.  A separate
    recovery record keeps that post-run evidence auditable without rewriting
    the model result.
    """
    if result.get("clear_succeeded"):
        return True, False
    if attempt_dir is None:
        return False, False
    recovery_path = attempt_dir / "clear-recovery.json"
    if not recovery_path.exists():
        return False, False
    try:
        recovery = json.loads(recovery_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False, False
    recovered = bool(recovery.get("command_sent") and recovery.get("resume_marker_observed"))
    return recovered, recovered


def _acceptable(result, attempt_dir=None):
    cleared, _ = _clear_verified(result, attempt_dir)
    transcript = result.get("transcript_summary")
    if transcript is not None:
        first_read = transcript.get("first_turn_cache_read_tokens")
        if first_read is None or int(first_read) != 0:
            return False
    completed = result.get("returncode") == 0
    budget_exhausted = (
        result.get("terminal_reason") == "max_turns"
        and result.get("public_returncode") == 0
    )
    return cleared and (completed or budget_exhausted)


def cache_phase_counts(usage, transcript):
    """Split aggregate provider cache usage into first and later turns."""
    first_creation = int(transcript.get("first_turn_cache_creation_tokens", 0) or 0)
    first_read = int(transcript.get("first_turn_cache_read_tokens", 0) or 0)
    return {
        "first_turn_cache_creation_tokens": first_creation,
        "first_turn_cache_read_tokens": first_read,
        "later_turn_cache_creation_tokens": max(0, usage.cache_creation_tokens - first_creation),
        "later_turn_cache_read_tokens": max(0, usage.cache_read_tokens - first_read),
    }


def _row_for(result_path):
    result = json.loads(result_path.read_text())
    usage = parse_usage(result)
    quality_path = result_path.parent / "quality.json"
    manifest_path = result_path.parent / "manifest.json"
    quality = json.loads(quality_path.read_text()) if quality_path.exists() else {}
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    transcript = manifest.get("transcript", result.get("transcript_summary", {}))
    lines = manifest.get("changed_lines", {})
    _, clear_recovered = _clear_verified(result, result_path.parent)
    cache_phases = cache_phase_counts(usage, transcript)
    if "disable_prompt_caching" in result:
        cache_policy = "disabled" if result["disable_prompt_caching"] else "natural"
    else:
        cache_policy = "unknown"
    return {
        "condition": result_path.parts[-3],
        "attempt": result_path.parts[-2],
        "api_mode": bool(result.get("api_mode", False)),
        "max_turns": int(result.get("max_turns", 0) or 0),
        "cache_policy": cache_policy,
        "valid": _acceptable(result, result_path.parent),
        "clear_recovered": clear_recovered,
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
        **cache_phases,
        "changed_lines": int(lines.get("changed", 0) or 0),
        "started_epoch": float(result.get("started_epoch", 0) or 0),
        "last_request_epoch": float(result.get("last_request_epoch", 0) or 0),
        "duration_seconds": float(result.get("duration_ms", 0) or 0) / 1000,
        "terminal_reason": result.get("terminal_reason", "completed"),
        "hidden_score": int(quality.get("hidden_score", 0) or 0),
        "public_score": int(quality.get("public_score", 0) or 0),
        "code_score": int(quality.get("code_score", 0) or 0),
        "documentation_score": int(quality.get("documentation_score", 0) or 0),
        "evidence_score": int(quality.get("evidence", 0) or 0),
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
        "condition", "attempt", "max_turns", "input_tokens", "cache_creation_tokens", "cache_read_tokens",
        "input_related_tokens", "output_tokens", "total_processed_tokens", "cost_usd",
        "quality_score", "critical_pass", "turns", "tool_calls",
        "first_turn_cache_creation_tokens", "first_turn_cache_read_tokens",
        "later_turn_cache_creation_tokens", "later_turn_cache_read_tokens",
        "changed_lines", "duration_seconds", "terminal_reason",
        "api_mode", "cache_policy", "clear_recovered", "hidden_score", "public_score", "code_score", "documentation_score", "evidence_score",
    ]
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    comparisons = paired_comparisons(rows)
    total_cost = sum(row["cost_usd"] for row in rows)
    invalid_cost = sum(row["cost_usd"] for row in invalid)
    all_attempt_cost = total_cost + invalid_cost
    policies = sorted({row["cache_policy"] for row in rows})
    policy_label = ", ".join(policies) if policies else "unknown"
    lines = [
        "# Token Optimizer Benchmark Results", "",
        "이 보고서의 비용은 provider가 반환한 API-equivalent estimated cost이며 Claude Pro 구독료에 추가 청구된 금액이 아니다.", "",
        f"Valid conditions: {len(rows)}/7 · Invalid attempts: {len(invalid)} · Valid API-equivalent cost: ${total_cost:.6f} · All attempts: ${all_attempt_cost:.6f}",
        f"Prompt-cache policy observed: {policy_label}", "",
        "## Condition measurements", "",
    ]
    lines.extend(_markdown_table(
        ["Condition", "Input", "Cache create", "Cache read", "Output", "Total", "Cost USD", "Quality", "Breakdown", "Critical", "Clear", "Cache policy", "Turns", "Tools"],
        [[
            row["condition"], f"{row['input_tokens']:,}", f"{row['cache_creation_tokens']:,}",
            f"{row['cache_read_tokens']:,}", f"{row['output_tokens']:,}",
            f"{row['total_processed_tokens']:,}", f"${row['cost_usd']:.6f}",
            f"{row['quality_score']}/100",
            f"H{row['hidden_score']} P{row['public_score']} C{row['code_score']} D{row['documentation_score']} E{row['evidence_score']}",
            "PASS" if row["critical_pass"] else "FAIL",
            "RECOVERED" if row["clear_recovered"] else "PASS",
            row["cache_policy"],
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
    api_mode = any(row["api_mode"] for row in rows)
    lines.extend(["", "## Cache isolation and scheduling", ""])
    if rows:
        isolation_rows = []
        for index, row in enumerate(rows):
            if api_mode:
                gap = "parallel"
                washout = "not required"
            else:
                if index == 0:
                    gap = "N/A"
                    washout = "N/A"
                else:
                    seconds = row["started_epoch"] - rows[index - 1]["last_request_epoch"]
                    gap = f"{seconds:.1f}s"
                    washout = "PASS" if seconds >= 4200 else "FAIL"
            first_cache = row["first_turn_cache_read_tokens"]
            cache_gate = "PASS" if first_cache == 0 else ("UNKNOWN" if first_cache < 0 else "FAIL")
            isolation_rows.append([
                row["condition"], gap, washout, first_cache, cache_gate,
                row["later_turn_cache_creation_tokens"], row["later_turn_cache_read_tokens"],
            ])
        lines.extend(_markdown_table(
            ["Condition", "Gap from previous", "Washout", "First-turn cache read", "Cache gate",
             "Later-turn cache write", "Later-turn cache read"],
            isolation_rows,
        ))
    if invalid:
        lines.extend(["", "## Invalid attempts", ""])
        lines.extend(
            f"- {row['condition']}/{row['attempt']}: {row['terminal_reason']}"
            f"; first-turn cache read={row['first_turn_cache_read_tokens']}"
            for row in invalid
        )
    max_turn_values = sorted({row["max_turns"] for row in rows if row["max_turns"]})
    max_turn_label = ", ".join(str(value) for value in max_turn_values) or "unknown"
    lines.extend([
        "", "## Interpretation limits", "",
        "- 각 조건은 유효 관측치 1회이므로 통계적 유의성을 주장할 수 없다.",
        f"- 이 API cohort의 유효 관측치는 조건당 max_turns={max_turn_label}로 고정했다. 이전 Pro H-ON 탐색 실행(max_turns=28)과 직접 합산하지 않는다.",
        "- cache_policy=natural cohort에서는 첫 turn isolation과 later-turn cache read를 분리해 기록한다. cache_policy=disabled cohort와 자연-cache 결과를 섞어 해석하지 않는다.",
        "- Headroom proxy가 provider cache marker를 보존하거나 주입하면 환경변수만으로 provider cache 상태를 단정할 수 없으므로, usage의 cache_creation/cache_read를 우선한다.",
        "- 모든 조건의 첫 turn cache read는 0이었지만, nonce가 전체 provider cache 계층의 모든 prefix를 무효화한다고 해석하지 않는다.",
        "- API 병렬 실행으로 같은 시각의 service load·rate limit 경쟁이 조건 효과에 섞일 수 있다.",
        f"- Claude의 비결정성과 max_turns={max_turn_label} 상한은 구현 범위와 최종 응답 완성도에 영향을 줄 수 있다.",
        "- 양의 token/cost 절감과 quality gate 통과가 동시에 확인된 비교에만 Recommendation=YES를 부여한다.",
    ])
    probe_path = report_dir / "api-probe.json"
    if probe_path.exists():
        try:
            probe = json.loads(probe_path.read_text())
            probe_cost = float(probe.get("cost_usd", 0) or 0)
            lines.insert(3, f"별도 API 연결성 probe 비용(조건 합계에 미포함): ${probe_cost:.6f} · probe 포함 실측 합계: ${total_cost + probe_cost:.6f}")
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    (report_dir / "final-report.md").write_text("\n".join(lines) + "\n")
    return rows
