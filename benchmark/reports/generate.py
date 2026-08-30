import csv
import json
from pathlib import Path

from benchmark.runner.usage import parse_usage


BASELINE = "BASE"

TREATMENTS = (
    ("Headroom optimized vs baseline", "H-ON"),
    ("Caveman full vs baseline", "C-FULL"),
    ("Be brief vs baseline", "C-BRIEF"),
    ("RTK on vs baseline", "R-ON"),
)


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def baseline_noise(rows):
    """Spread between repeated untreated runs: the floor an effect must clear.

    Identical BASE attempts differ only by model nondeterminism and service
    conditions, so a treatment effect smaller than this spread is not
    distinguishable from noise.
    """
    base_rows = [row for row in rows if row["condition"] == BASELINE]
    if len(base_rows) < 2:
        return None
    tokens = [row["total_processed_tokens"] for row in base_rows]
    costs = [row["cost_usd"] for row in base_rows]
    scores = [row["quality_score"] for row in base_rows]
    return {
        "attempts": len(base_rows),
        "token_spread_pct": 100 * (max(tokens) - min(tokens)) / _mean(tokens) if _mean(tokens) else 0.0,
        "cost_spread_pct": 100 * (max(costs) - min(costs)) / _mean(costs) if _mean(costs) else 0.0,
        "quality_spread": max(scores) - min(scores),
        "mean_tokens": _mean(tokens),
        "mean_cost": _mean(costs),
        "mean_quality": _mean(scores),
    }


def paired_comparisons(rows):
    """Compare every treatment against the pooled untreated baseline."""
    base_rows = [row for row in rows if row["condition"] == BASELINE]
    if not base_rows:
        return []
    token_base = _mean([row["total_processed_tokens"] for row in base_rows])
    cost_base = _mean([row["cost_usd"] for row in base_rows])
    quality_base = _mean([row["quality_score"] for row in base_rows])
    base_critical = _mean([row.get("critical_passed", 0) for row in base_rows])
    noise = baseline_noise(rows)
    by_condition = {}
    for row in rows:
        if row["condition"] != BASELINE:
            by_condition.setdefault(row["condition"], []).append(row)
    comparisons = []
    for label, treatment_name in TREATMENTS:
        group = by_condition.get(treatment_name)
        if not group or not token_base or not cost_base:
            continue
        treatment_tokens = _mean([row["total_processed_tokens"] for row in group])
        treatment_cost = _mean([row["cost_usd"] for row in group])
        treatment_quality = _mean([row["quality_score"] for row in group])
        treatment_critical = _mean([row.get("critical_passed", 0) for row in group])
        token_pct = 100 * (token_base - treatment_tokens) / token_base
        cost_pct = 100 * (cost_base - treatment_cost) / cost_base
        quality_delta = treatment_quality - quality_base
        # A relative gate: the treatment must not lose a critical invariant the
        # untreated run held, and must not drop more than five points overall.
        # Requiring the baseline itself to be perfect would fail every comparison
        # whenever the untreated run missed one test, which says nothing about
        # the treatment.
        quality_gate = treatment_critical >= base_critical and quality_delta >= -5
        # Report the two metrics separately.  The token total sums input, cache
        # writes and cache reads at equal weight even though a cache read costs a
        # tenth of an input token, so its spread is the noisier of the two.  Cost
        # is the decision-relevant metric and the one the recommendation gates on.
        token_above = cost_above = None
        own_costs = [row["cost_usd"] for row in group]
        own_spread = (100 * (max(own_costs) - min(own_costs)) / _mean(own_costs)
                      if len(group) > 1 and _mean(own_costs) else 0.0)
        if noise:
            floor = max(noise["cost_spread_pct"], own_spread)
            token_above = abs(token_pct) > noise["token_spread_pct"]
            cost_above = abs(cost_pct) > floor
        comparisons.append({
            "comparison": label,
            "treatment": treatment_name,
            "baseline": BASELINE,
            "observations": len(group),
            "baseline_attempts": len(base_rows),
            "own_cost_spread_pct": own_spread,
            "token_saving_pct": token_pct,
            "cost_saving_pct": cost_pct,
            "quality_delta": quality_delta,
            "quality_gate_pass": quality_gate,
            "token_above_noise": token_above,
            "cost_above_noise": cost_above,
            "recommended": bool(token_pct > 0 and cost_pct > 0 and quality_gate and cost_above),
        })
    return comparisons


def invalid_reason(result):
    """Name why an attempt cannot be measured, not just how it ended."""
    if result.get("terminal_reason") == "max_turns":
        return "max_turns: truncated before the final response"
    if not result.get("changed_files"):
        return "no work performed: the run changed no file"
    if not (result.get("final_text") or "").strip():
        return "no final response"
    if result.get("returncode") != 0:
        return f"returncode {result.get('returncode')}"
    return "unknown"


def _acceptable(result, attempt_dir=None):
    """Mirror ``runner.cli.is_acceptable_result``: only self-terminated runs count."""
    transcript = result.get("transcript_summary")
    if transcript is not None:
        first_read = transcript.get("first_turn_cache_read_tokens")
        if first_read is None or int(first_read) < 0:
            return False
    if result.get("terminal_reason", "completed") != "completed":
        return False
    if result.get("returncode") != 0 or result.get("is_error"):
        return False
    if not result.get("changed_files"):
        return False
    return bool((result.get("final_text") or "").strip())


def uniform_first_turn_cache_read(rows):
    """Cross-run contamination shows up as an asymmetric first-turn cache read.

    Identical values mean every condition reused the same fixed prefix - the
    Claude Code system prompt and tool definitions - which is symmetric and
    cancels out of a comparison.  Differing values mean one condition started
    from a prefix the others did not have.
    """
    values = {int(row["first_turn_cache_read_tokens"]) for row in rows}
    return len(values) <= 1


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
    cache_phases = cache_phase_counts(usage, transcript)
    if "disable_prompt_caching" in result:
        cache_policy = "disabled" if result["disable_prompt_caching"] else "natural"
    else:
        cache_policy = "unknown"
    return {
        # The run directory may be a per-run label such as "BASE-01"; the condition
        # itself is recorded in the result, and grouping must use that or every
        # repeated run lands in a group of its own.
        "condition": result.get("condition") or result_path.parts[-3],
        "run_label": result_path.parts[-3],
        "attempt": result_path.parts[-2],
        "api_mode": bool(result.get("api_mode", False)),
        "max_turns": int(result.get("max_turns", 0) or 0),
        "cache_policy": cache_policy,
        "valid": _acceptable(result, result_path.parent),
        "input_tokens": usage.input_tokens,
        "cache_creation_tokens": usage.cache_creation_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "input_related_tokens": usage.input_related_tokens,
        "output_tokens": usage.output_tokens,
        "total_processed_tokens": usage.total_processed_tokens,
        "cost_usd": usage.cost_usd,
        "quality_score": int(quality.get("score", 0)),
        "critical_passed": int(quality.get("critical_passed", 0) or 0),
        "critical_total": int(quality.get("critical_total", 0) or 0),
        "flaky_tests": quality.get("flaky_tests", []),
        "invalid_reason": invalid_reason(result),
        "prompt_sha256": (manifest.get("base_prompt_sha256") or "")[:12],
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
    for condition in (BASELINE, "H-ON", "C-FULL", "C-BRIEF", "R-ON"):
        valid.extend(row for row in all_rows
                     if row["condition"] == condition and row["valid"])
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
        "api_mode", "cache_policy", "prompt_sha256", "critical_passed", "critical_total", "hidden_score", "public_score", "code_score", "documentation_score", "evidence_score",
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
        f"Valid runs: {len(rows)} · Invalid attempts: {len(invalid)} · Valid API-equivalent cost: ${total_cost:.6f} · All attempts: ${all_attempt_cost:.6f}",
        f"Prompt-cache policy observed: {policy_label}", "",
        "## Condition measurements", "",
    ]
    lines.extend(_markdown_table(
        ["Run", "Input", "Cache create", "Cache read", "Output", "Total", "Cost USD", "Quality", "Breakdown", "Critical tests", "Cache policy", "Turns", "Tools", "Changed lines"],
        [[
            f"{row['condition']} {row['attempt']}", f"{row['input_tokens']:,}", f"{row['cache_creation_tokens']:,}",
            f"{row['cache_read_tokens']:,}", f"{row['output_tokens']:,}",
            f"{row['total_processed_tokens']:,}", f"${row['cost_usd']:.6f}",
            f"{row['quality_score']}/100",
            f"H{row['hidden_score']} P{row['public_score']} C{row['code_score']} D{row['documentation_score']} E{row['evidence_score']}",
            f"{row['critical_passed']}/{row['critical_total']}",
            row["cache_policy"],
            row["turns"], row["tool_calls"], row["changed_lines"],
        ] for row in rows],
    ))
    prompt_variants = sorted({row["prompt_sha256"] for row in rows if row["prompt_sha256"]})
    lines.extend(["", "## Paired comparisons", ""])
    if len(prompt_variants) > 1:
        lines.extend([
            f"**Warning: these runs used different master prompts ({', '.join(prompt_variants)}).** "
            "A prompt difference lands in the same column as the condition effect, so a "
            "condition run under the looser prompt that shows larger output cannot be "
            "separated from the prompt change; treat it as undecided. A condition that "
            "shows smaller output despite the looser prompt is the conservative direction.",
            "",
        ])
    lines.extend(_markdown_table(
        ["Comparison", "Runs", "Token saving", "Cost saving", "Quality delta",
         "Quality gate", "Token > noise", "Cost > noise", "Recommendation"],
        [[
            item["comparison"], item["observations"],
            _pct(item["token_saving_pct"]), _pct(item["cost_saving_pct"]),
            f"{item['quality_delta']:+.1f}", "PASS" if item["quality_gate_pass"] else "FAIL",
            {True: "YES", False: "NO", None: "UNKNOWN"}[item["token_above_noise"]],
            {True: "YES", False: "NO", None: "UNKNOWN"}[item["cost_above_noise"]],
            "YES" if item["recommended"] else "NO",
        ] for item in comparisons],
    ))
    noise = baseline_noise(rows)
    lines.extend(["", "## Baseline noise floor", ""])
    if noise:
        lines.extend(_markdown_table(
            ["Baseline runs", "Token spread", "Cost spread", "Quality spread",
             "Mean tokens", "Mean cost", "Mean quality"],
            [[noise["attempts"], f"{noise['token_spread_pct']:.2f}%",
              f"{noise['cost_spread_pct']:.2f}%", noise["quality_spread"],
              f"{noise['mean_tokens']:,.0f}", f"${noise['mean_cost']:.6f}",
              f"{noise['mean_quality']:.1f}"]],
        ))
        lines.extend([
            "",
            "This is the difference between repeated runs of the identical setup. "
            "A saving smaller than this cannot be told apart from run-to-run variation. "
            "It is a lower bound, not a variance estimate: with only a few repeats it also "
            "carries whatever service-load difference separated those runs.",
        ])
    else:
        lines.append("Fewer than two valid BASE runs, so no noise floor could be computed. "
                     "Every percentage below is one observation against one observation.")
    api_mode = any(row["api_mode"] for row in rows)
    uniform = uniform_first_turn_cache_read(rows) if rows else True
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
            cache_gate = "SHARED PREFIX" if uniform else "ASYMMETRIC"
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
            f"- {row['condition']}/{row['attempt']}: {row['invalid_reason']}"
            f"; turns={row['turns']}; changed lines={row['changed_lines']}"
            f"; cost=${row['cost_usd']:.6f}"
            for row in invalid
        )
        lines.extend([
            "",
            "These figures are diagnostic only. A run truncated at max_turns measures the "
            "turn cap rather than the condition, so its tokens and cost are excluded from "
            "every saving above. They are kept because the pattern of invalid runs is often "
            "what reveals the real cause.",
        ])
    max_turn_values = sorted({row["max_turns"] for row in rows if row["max_turns"]})
    max_turn_label = ", ".join(str(value) for value in max_turn_values) or "unknown"
    counts = {}
    for row in rows:
        counts[row["condition"]] = counts.get(row["condition"], 0) + 1
    single = sorted(name for name, count in counts.items() if count < 2)
    lines.extend([
        "", "## Interpretation limits", "",
        f"- Observations per condition: "
        + ", ".join(f"{name} x{count}" for name, count in sorted(counts.items())) + ".",
    ])
    if single:
        lines.append(
            "- " + ", ".join(single) + " have a single observation, so their percentages "
            "cannot be checked against a noise floor of their own and may move substantially "
            "if repeated. No statistical significance is claimed for any condition.")
    lines.extend([
        f"- Valid runs are only those that Claude ended on its own within max_turns={max_turn_label}, "
        "with a non-empty final response and at least one changed file. A truncated run never "
        "reaches the documentation and reporting phase, so it is excluded.",
        "- BASE is a plain run: no proxy, no plugin, no hook. `headroom proxy --no-optimize` is not "
        "used as a control because its request log shows it still applies tool-schema compaction "
        "and tool-search deferral, so H-ON is 'proxy versus no proxy'.",
        "- C-BRIEF loads no plugin; it isolates whether a plain brevity instruction is enough.",
        "- total_processed_tokens sums input, cache writes and cache reads at equal weight even "
        "though a cache read costs about a tenth of an input token, so judge savings by cost.",
        "- Total cost is dominated by `turns x context per turn`, and turn count varies widely "
        "between identical runs. An effect stated per turn reproduces better than one stated as "
        "a total cost percentage.",
        "- Recommendation=YES requires positive token and cost savings, a passing quality gate, "
        "and a cost saving larger than the noise floor.",
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
