"""완료된 token_bench 실행을 레거시 CSV(`data/activity-log.csv`,
`data/run-summary.csv`)에 턴 단위로 append한다.

사용자가 옛 벤치마크 방식(턴별 context tax 누적)을 유지하길 원해서, 옛
`benchmark/reports/activity_log.py`의 턴 추출 로직을 `token_bench/activity_log.py`로
그대로 옮겨 왔고, 이 모듈은 그걸 token_bench의 job 기록(`result.json` +
`stdout.jsonl`)에 연결한다. 이미 게시된 run_id는 다시 쓰지 않는다(append-only,
과거 행은 건드리지 않는다) — 레거시 `collect_batch`처럼 batch 전체를 재작성하지
않는 이유는, token_bench 실행이 옛 주간 배치 디렉터리 구조를 따르지 않기
때문이다.

`quality_score`는 token_bench의 pass/fail(`evaluation_passed`)을 100/0으로
옮겨 쓴다(숫자 grader가 없다 — 사용자 결정: 옛 grader를 복원하지 않고
pass/fail만 쓴다). 100/0으로 넣으면 여러 실행을 평균 낼 때 자동으로
"pass율(%)"이 되므로, 기존 통계 코드(web/app.js의 평균·delta 계산)를 그대로
쓸 수 있다. 평가를 아예 안 돌린 실행은 빈 문자열로 남긴다.

`data/comparison.csv`는 append하지 않고 매번 `run-summary.csv` 전체에서
다시 계산해 통째로 다시 쓴다 — 100% 파생 데이터라 유실 위험이 없고, 다른
날짜에 조건이 하나씩 늘어나도 그때마다 baseline과 다시 비교해야 하기
때문이다.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from token_bench.activity_log import (
    ACTIVITY_COLUMNS,
    activity_rows,
    extract_turns,
    is_measurable,
    reconcile,
    with_context_tax,
)
from token_bench.diagnostics import update_manifest
from token_bench.job_store import JobRecord, list_jobs
from token_bench.results import ResultsError, load as load_result
from token_bench.workspace import PROMPT_PRESETS

DEFAULT_DIAGNOSTICS_PATH = Path("data/run-diagnostics.json")

DEFAULT_ACTIVITY_PATH = Path("data/activity-log.csv")
DEFAULT_SUMMARY_PATH = Path("data/run-summary.csv")
DEFAULT_COMPARISON_PATH = Path("data/comparison.csv")

PUBLISHABLE_STATUSES = frozenset({"succeeded", "failed"})
BASELINE_CONDITION = "BASE"

# 웹의 "실행 상세" 탭은 activity-log.csv의 condition 문자열 그대로로 그룹을
# 나눈다(web/app.js:runsGroupedByCondition). token_bench의 condition_id(소문자,
# 하이픈)가 레거시 라벨(대문자, 밑줄)과 다르면 같은 조건인데도 새 버튼으로
# 따로 뜬다. 레거시 라벨로 맞춰 기존 그룹에 합친다.
CONDITION_LABELS = {
    "base": "BASE",
    "be-brief": "BE_BRIEF",
    "headroom": "HEADROOM",
    "caveman-full": "CAVEMAN-FULL",
    "rtk": "RTK",
}


def _legacy_condition(condition_id: str) -> str:
    return CONDITION_LABELS.get(condition_id, condition_id)


_PRESET_BY_PATH = {str(path): name for name, path in PROMPT_PRESETS.items()}


def _prompt_id(snapshot_path: str) -> str:
    """어떤 프롬프트(내장 프리셋 3종 또는 사용자 지정)로 돈 실행인지 식별한다.

    프리셋이면 이름(`small`/`large`/`very-large`)을 쓰고, 사용자가 `--prompt`로
    직접 지정한 파일이면 절대경로를 그대로 쓰지 않는다 — 다른 기여자의 로컬
    파일 경로(사용자 이름 포함)가 공개 CSV에 그대로 남는 걸 막기 위해서다.
    프롬프트 내용의 sha256(이미 snapshot.json에 있음) 앞 8자만 쓴다.
    """
    try:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    preset = _PRESET_BY_PATH.get(snapshot.get("task_prompt_path", ""))
    if preset:
        return preset
    prompt_sha = snapshot.get("task_prompt_sha256", "")
    return f"custom:{prompt_sha[:8]}" if prompt_sha else "custom:unknown"


SUMMARY_COLUMNS = (
    "run_date", "run_id", "condition", "prompt_id", "cost_usd", "quality_score",
    "critical_pass", "turns", "measurable", "invalid_reason",
    "reconcile_observed", "reconcile_opening", "reconcile_output",
    "reconcile_tool_result", "reconcile_discarded",
    "model", "duration_seconds", "terminal_reason", "changed_files", "tool_calls",
    "first_turn_cache_read_tokens", "washout_gap_seconds", "aux_model_tokens",
    "processed_tokens", "context_tax_tokens",
)


def _read_published_run_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {row["run_id"] for row in reader if row.get("run_id")}


def _final_result_event(stdout_path: str | None) -> dict:
    if not stdout_path or not Path(stdout_path).is_file():
        return {}
    events = []
    for line in Path(stdout_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    for event in reversed(events):
        if event.get("type") == "result":
            return event
    return {}


def _aux_model_tokens(result_event: dict, main_model: str) -> int:
    """레거시 `collect.aux_model_tokens`와 동일: 주 모델 외 model의 토큰 합."""
    raw = result_event.get("modelUsage") or {}
    total = 0
    for model, usage in raw.items():
        if model == main_model:
            continue
        total += sum(int(usage.get(key, 0) or 0) for key in (
            "inputTokens", "outputTokens",
            "cacheCreationInputTokens", "cacheReadInputTokens",
        ))
    return total


def _invalid_reason(status: str, turns: list) -> str:
    if status == "succeeded" and is_measurable(turns):
        return ""
    reasons = []
    if status != "succeeded":
        reasons.append("execution_error")
    if not turns:
        reasons.append("no_turns")
    else:
        if not reconcile(turns)["balanced"]:
            reasons.append("reconcile_unbalanced")
        if any(turn.compacted for turn in turns):
            reasons.append("compacted")
    return "+".join(reasons) or "unknown"


def _washout_gaps(jobs: list[JobRecord]) -> dict[str, str]:
    """같은 batch_id 안에서, 앞 실행이 끝난 시각과 다음 실행이 시작한 시각의 간격(초).

    token_bench는 배치 하나를 여러 조건이 순차 실행하므로, 레거시처럼 하루 전체가
    아니라 batch_id 단위로 washout을 계산한다.
    """
    by_batch: dict[str, list[JobRecord]] = {}
    for job in jobs:
        if job.started_at and job.finished_at:
            by_batch.setdefault(job.batch_id, []).append(job)

    gaps: dict[str, str] = {}
    for batch_jobs in by_batch.values():
        ordered = sorted(batch_jobs, key=lambda j: j.started_at)
        if ordered:
            gaps[ordered[0].run_id] = ""
        for previous, current in zip(ordered, ordered[1:]):
            from datetime import datetime

            prev_end = datetime.fromisoformat(previous.finished_at)
            curr_start = datetime.fromisoformat(current.started_at)
            gaps[current.run_id] = str(round((curr_start - prev_end).total_seconds()))
    return gaps


def _mean(values: list[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _spread_pct(values: list[float]) -> float | None:
    values = list(values)
    if len(values) < 2:
        return None
    average = _mean(values)
    return 100 * (max(values) - min(values)) / average if average else 0.0


def _delta_pct(treatment: float, base: float) -> float | None:
    if not base:
        return None
    return 100 * (treatment - base) / base


COMPARISON_COLUMNS = (
    "run_date", "prompt_id", "condition", "runs", "baseline_runs",
    "processed_delta_pct", "cost_delta_pct", "tax_delta_pct", "quality_delta",
    "noise_processed_pct", "noise_cost_pct",
)


def _round(value: float | None, digits: int = 4):
    return "" if value is None else round(value, digits)


def _comparison_rows_for_date(runs: list[dict]) -> list[list]:
    """레거시 `comparison.batch_comparison`과 동일한 계산, 같은 날짜 안에서만."""
    base_runs = [r for r in runs if r["condition"] == BASELINE_CONDITION]
    noise = {
        "processed": _spread_pct([r["processed"] for r in base_runs]),
        "cost": _spread_pct([r["cost"] for r in base_runs]),
        "baseline_runs": len(base_runs),
    }
    if not base_runs:
        return []

    base = {field: _mean([r[field] for r in base_runs])
            for field in ("processed", "cost", "tax", "quality")}
    grouped: dict[str, list[dict]] = {}
    for run in runs:
        if run["condition"] != BASELINE_CONDITION:
            grouped.setdefault(run["condition"], []).append(run)

    rows = []
    for condition in sorted(grouped):
        group = grouped[condition]
        rows.append([
            condition, len(group), noise["baseline_runs"],
            _round(_delta_pct(_mean([r["processed"] for r in group]), base["processed"])),
            _round(_delta_pct(_mean([r["cost"] for r in group]), base["cost"])),
            _round(_delta_pct(_mean([r["tax"] for r in group]), base["tax"])),
            _round(_mean([r["quality"] for r in group]) - base["quality"]),
            _round(noise["processed"]), _round(noise["cost"]),
        ])
    return rows


def _rebuild_comparison(summary_path: Path, comparison_path: Path) -> None:
    """`(run_date, prompt_id)` 단위로 묶어 비교한다.

    prompt_id별로 묶지 않으면 large preset BASE가 small preset HEADROOM과
    비교되는 식의 잘못된 delta가 나온다 — 프롬프트 크기가 다르면 토큰 수
    자체가 다르므로 같은 preset끼리만 비교해야 한다.
    """
    if not summary_path.is_file():
        return
    with summary_path.open("r", encoding="utf-8", newline="") as stream:
        summary_rows = list(csv.DictReader(stream))

    by_group: dict[tuple[str, str], list[dict]] = {}
    for row in summary_rows:
        if row.get("measurable") != "1":
            continue
        quality = row.get("quality_score")
        if quality in (None, ""):
            continue  # 평가 안 돌린 실행은 quality delta에 넣을 수 없다.
        key = (row["run_date"], row.get("prompt_id", ""))
        by_group.setdefault(key, []).append({
            "condition": row["condition"],
            "processed": float(row["processed_tokens"]),
            "cost": float(row["cost_usd"]),
            "tax": float(row["context_tax_tokens"]),
            "quality": float(quality),
        })

    out_rows = []
    for run_date, prompt_id in sorted(by_group):
        for row in _comparison_rows_for_date(by_group[(run_date, prompt_id)]):
            out_rows.append([run_date, prompt_id, *row])

    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    with comparison_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(COMPARISON_COLUMNS)
        writer.writerows(out_rows)


def collect(
    *, db_path: Path, activity_path: Path = DEFAULT_ACTIVITY_PATH,
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    comparison_path: Path = DEFAULT_COMPARISON_PATH,
    diagnostics_path: Path = DEFAULT_DIAGNOSTICS_PATH,
) -> dict:
    """아직 게시되지 않은 succeeded/failed 작업을 턴 단위로 CSV에 append한다."""

    already_published = _read_published_run_ids(summary_path)
    jobs = list_jobs(db_path=db_path)
    gaps = _washout_gaps(jobs)

    new_activity_rows: list[list] = []
    new_summary_rows: list[list] = []

    for job in jobs:
        if job.run_id in already_published or job.status not in PUBLISHABLE_STATUSES:
            continue

        result_path = Path(job.workdir).parent / "result.json"
        try:
            result = load_result(result_path)
        except ResultsError:
            continue

        turns = with_context_tax(extract_turns(job.stdout_path)) if job.stdout_path else []
        run_date = (job.started_at or job.enqueued_at)[:10]
        condition = _legacy_condition(job.condition_id)

        new_activity_rows.extend(activity_rows(run_date, job.run_id, condition, turns))
        if job.stdout_path:
            update_manifest(job.run_id, job.stdout_path, diagnostics_path)

        measurable = job.status == "succeeded" and is_measurable(turns)
        shares = reconcile(turns) if turns else {
            "observed": 0, "opening": 0, "output": 0, "tool_result": 0, "discarded": 0,
        }
        model = turns[0].model if turns else (result.model.get("value") or "")
        result_event = _final_result_event(job.stdout_path)
        evaluation_ran = (result.evaluation or {}).get("ran")
        evaluation_passed = (result.evaluation or {}).get("passed")
        quality_score = "" if not evaluation_ran else (100 if evaluation_passed else 0)
        critical_pass = "" if not evaluation_ran else ("pass" if evaluation_passed else "fail")

        new_summary_rows.append([
            run_date, job.run_id, condition, _prompt_id(job.snapshot_path),
            result.cost_usd.get("value"),
            quality_score,
            critical_pass,
            len(turns),
            int(measurable),
            "" if measurable else _invalid_reason(job.status, turns),
            shares["observed"], shares["opening"], shares["output"],
            shares["tool_result"], shares["discarded"],
            model,
            round(job.duration_seconds, 1) if job.duration_seconds else "",
            job.status,
            0,  # changed_files: not tracked by token_bench
            sum(len(t.tools) for t in turns),
            turns[0].cache_read_tokens if turns else "",
            gaps.get(job.run_id, ""),
            _aux_model_tokens(result_event, model),
            sum(t.context_tokens + t.output_tokens for t in turns),
            sum(t.context_tax_tokens for t in turns),
        ])

    if new_summary_rows:
        _append(activity_path, ACTIVITY_COLUMNS, new_activity_rows)
        _append(summary_path, SUMMARY_COLUMNS, new_summary_rows)
        _rebuild_comparison(summary_path, comparison_path)

    return {"runs": len(new_summary_rows), "turns": len(new_activity_rows)}


def _append(path: Path, columns: tuple, rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        if write_header:
            writer.writerow(columns)
        writer.writerows(rows)
