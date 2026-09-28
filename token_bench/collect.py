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
from token_bench.publish import _read_published, attempt_run_id
from token_bench.results import ResultsError, load as load_result
from token_bench.conditions import load_conditions
from token_bench.workspace import PROMPT_PRESETS

DEFAULT_DIAGNOSTICS_PATH = Path("data/run-diagnostics.json")

DEFAULT_ACTIVITY_PATH = Path("data/activity-log.csv")
DEFAULT_SUMMARY_PATH = Path("data/run-summary.csv")
DEFAULT_COMPARISON_PATH = Path("data/comparison.csv")

# timeout은 가장 원인을 알아야 하는 실패다 — 무한 반복에 빠진 실행이 여기
# 빠지면 CSV에도 진단 레포트에도 남지 않는다(사용자 결정). measurable=0으로
# 기록되므로 comparison.csv의 평균에는 들어가지 않는다.
PUBLISHABLE_STATUSES = frozenset({"succeeded", "failed", "timeout"})
BASELINE_CONDITION = "BASE"
# 처치 실행을 비교할 때 기준선으로 삼는 BASE 실행 수. 90분마다 조건 하나만 돌면
# BASE는 5 tick마다 한 번 나오므로, 같은 날짜 안에서 BASE를 찾는 방식은 비교를
# 만들지 못한다. 시간축에서 최근 BASE들을 끌어와 기준선으로 쓴다.
BASELINE_WINDOW = 10

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




def _final_result_event(stdout_path: str | None) -> dict:
    if not stdout_path or not Path(stdout_path).is_file():
        return {}
    events = []
    for line in Path(stdout_path).read_text(encoding="utf-8", errors="replace").splitlines():
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


def _comparison_rows_for_date(runs: list[dict], base_runs: list[dict] | None = None) -> list[list]:
    """처치 실행들을 주어진 baseline 집합과 비교한다.

    `base_runs`를 주지 않으면 `runs` 안의 BASE를 쓴다(예전 동작).
    """
    if base_runs is None:
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


def _baseline_window(base_runs: list[dict], run_date: str) -> list[dict]:
    """그 날짜까지의 BASE 실행 중 마지막 `BASELINE_WINDOW`건을 기준선으로 쓴다.

    아직 BASE가 없던 시기의 실행은 가장 이른 BASE들과 비교한다 — 비교를 아예
    빼면 그 실행이 표에서 사라진다.
    """

    earlier = [r for r in base_runs if r["run_date"] <= run_date]
    window = earlier[-BASELINE_WINDOW:] if earlier else base_runs[:BASELINE_WINDOW]
    return window


def _rebuild_comparison(summary_path: Path, comparison_path: Path) -> None:
    """prompt_id별로, BASE의 최근 `BASELINE_WINDOW`건을 기준선으로 비교한다.

    prompt_id로 나누지 않으면 large preset BASE가 small preset HEADROOM과
    비교되는 식의 잘못된 delta가 나온다 — 프롬프트 크기가 다르면 토큰 수 자체가
    다르므로 같은 preset끼리만 비교해야 한다.

    한 번에 조건 하나만 돌리므로(`bench.yml`) 한 batch에는 조건이 하나뿐이고,
    같은 날짜에 BASE가 없는 날도 생긴다. 그래서 batch나 날짜로 묶어 그 안에서
    BASE를 찾는 방식은 비교를 하나도 만들지 못한다. 대신 기준선을 시간축에서
    끌어온다 — 처치 실행의 날짜까지 쌓인 BASE 중 최근 것들을 쓴다. 날짜가
    갈려 비교표에서 빠지던 재시도 문제도 이 방식에서는 생기지 않는다
    (2026-09-21 rtk 재시도 사례).
    """
    if not summary_path.is_file():
        return
    with summary_path.open("r", encoding="utf-8", newline="") as stream:
        summary_rows = list(csv.DictReader(stream))

    # 파일 순서가 곧 실행 순서다(append-only). 기준선 창을 그 순서로 자른다.
    by_prompt: dict[str, list[dict]] = {}
    for row in summary_rows:
        if row.get("measurable") != "1":
            continue
        quality = row.get("quality_score")
        if quality in (None, ""):
            continue  # 평가 안 돌린 실행은 quality delta에 넣을 수 없다.
        by_prompt.setdefault(row.get("prompt_id", ""), []).append({
            "condition": row["condition"],
            "processed": float(row["processed_tokens"]),
            "cost": float(row["cost_usd"]),
            "tax": float(row["context_tax_tokens"]),
            "run_date": row["run_date"],
            "quality": float(quality),
        })

    out_rows = []
    for prompt_id in sorted(by_prompt):
        runs = by_prompt[prompt_id]
        base_runs = [r for r in runs if r["condition"] == BASELINE_CONDITION]
        if not base_runs:
            continue
        by_date: dict[str, list[dict]] = {}
        for run in runs:
            if run["condition"] != BASELINE_CONDITION:
                by_date.setdefault(run["run_date"], []).append(run)
        for run_date in sorted(by_date):
            window = _baseline_window(base_runs, run_date)
            for row in _comparison_rows_for_date(by_date[run_date], window):
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

    # run-summary.csv는 status를 terminal_reason 열에 쓴다.
    published_keys, published_pairs = _read_published(
        summary_path, status_column="terminal_reason"
    )
    jobs = list_jobs(db_path=db_path)
    gaps = _washout_gaps(jobs)

    new_activity_rows: list[list] = []
    new_summary_rows: list[list] = []

    for job in jobs:
        if (job.run_id, job.status) in published_pairs or job.status not in PUBLISHABLE_STATUSES:
            continue

        result_path = Path(job.workdir).parent / "result.json"
        try:
            result = load_result(result_path)
        except ResultsError:
            continue

        turns = with_context_tax(extract_turns(job.stdout_path)) if job.stdout_path else []
        run_date = (job.started_at or job.enqueued_at)[:10]
        condition = _legacy_condition(job.condition_id)

        # 재시도는 같은 run_id를 다시 쓴다. 활동 로그와 요약에 같은 키로
        # 두 번 들어가면 웹이 두 시도의 turn을 한 실행으로 합친다.
        row_run_id = attempt_run_id(job.run_id, published_keys)
        published_keys.add(row_run_id)

        new_activity_rows.extend(activity_rows(run_date, row_run_id, condition, turns))
        if job.stdout_path:
            update_manifest(
                row_run_id, job.stdout_path, diagnostics_path,
                status=job.status, condition_id=job.condition_id,
            )

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
            run_date, row_run_id, condition, _prompt_id(job.snapshot_path),
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


# 어떤 프리셋으로 얼마나 모을지. `small`이 조건마다 이 횟수에 닿으면 `large`로
# 넘어간다 — 가벼운 과제에서 조건별 분산을 먼저 확정하고 무거운 과제로 옮기려는
# 것이다(사용자 결정). 횟수는 조건별 누적이며, 한 tick에 조건 하나만 돌린다.
PRESET_SEQUENCE = ("small", "large")
RUNS_PER_PRESET = 30


def successful_runs_by_condition(
    summary_path: Path, *, prompt_id: str
) -> dict[str, int]:
    """한 프리셋에서 조건별로 성공한 실행이 몇 건 쌓였는지 센다.

    `succeeded`만 센다 — 중간에 끊긴 실행은 그 조건의 표본이 아니다.
    """

    counts: dict[str, int] = {}
    if not summary_path.is_file():
        return counts
    with summary_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("prompt_id") != prompt_id:
                continue
            if row.get("terminal_reason") != "succeeded":
                continue
            condition = row.get("condition") or ""
            counts[condition] = counts.get(condition, 0) + 1
    return counts


def next_condition(
    summary_path: Path,
    *,
    preset: str,
    conditions_path: Path = Path("benchmark/conditions.json"),
) -> str:
    """이 프리셋에서 표본이 가장 적은 조건의 id를 고른다.

    한 tick에 조건 하나만 돌리므로(사용자 결정: 간격은 세트가 아니라 실험 단위다)
    매번 가장 뒤처진 조건을 집어 균등하게 쌓는다. 실행이 실패해 한 조건만 표본이
    모자라도 다음 차례에 그 조건이 다시 선택되므로 따로 보정할 필요가 없다.
    동수면 conditions.json의 선언 순서를 따른다.
    """

    declared = [condition.id for condition in load_conditions(conditions_path)]
    counts = successful_runs_by_condition(summary_path, prompt_id=preset)
    return min(declared, key=lambda cid: counts.get(_legacy_condition(cid), 0))


def next_preset(
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    *,
    conditions_path: Path = Path("benchmark/conditions.json"),
    runs_per_preset: int = RUNS_PER_PRESET,
) -> str:
    """지금 돌려야 할 프리셋을 정한다.

    선언된 모든 조건이 그 프리셋에서 `runs_per_preset`건을 채우면 다음 프리셋으로
    넘어간다. 조건 하나라도 모자라면 넘어가지 않는다 — 조건 간 비교가 목적이므로
    표본이 고르지 않은 채로 과제를 바꾸면 그 프리셋의 비교가 미완성으로 남는다.
    마지막 프리셋까지 채웠으면 그 프리셋을 계속 쓴다.
    """

    conditions = [
        _legacy_condition(condition.id) for condition in load_conditions(conditions_path)
    ]
    for preset in PRESET_SEQUENCE:
        counts = successful_runs_by_condition(summary_path, prompt_id=preset)
        if any(counts.get(condition, 0) < runs_per_preset for condition in conditions):
            return preset
    return PRESET_SEQUENCE[-1]
