"""실행 원장: 게시 키·CSV 변환·비교표 재계산과 복구 가능한 동기화."""

from __future__ import annotations

import base64
import csv
import json
import os
import shutil
from tempfile import TemporaryDirectory
from pathlib import Path

from token_bench.transcript import Transcript
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

from token_bench.storage import file_lock

DEFAULT_OUTPUT_PATH = Path("data/token-bench-results.csv")

# 끝난 실행만 게시한다. blocked/running/queued는 승인 문제이거나 아직 끝나지
# 않은 실행이므로 공개 데이터에 넣지 않는다. timeout은 게시한다 — 무한 반복에
# 빠진 실행이 여기 빠지면 CSV에도 진단 레포트에도 남지 않는다(사용자 결정).
# 게시 대상이라는 것과 평균에 넣어도 된다는 것은 다르다: succeeded가 아닌 행은
# 측정값으로 쓰지 않는다(web/app.js의 summarizeByCondition).
PUBLISHABLE_STATUSES = frozenset({"succeeded", "failed", "timeout"})

CSV_COLUMNS = (
    "run_id",
    "batch_id",
    "condition_id",
    "repeat_index",
    "content_id",
    "auth_method",
    "api_provider",
    "claude_version",
    "model",
    "status",
    "evaluation_ran",
    "evaluation_passed",
    "num_turns",
    "cost_usd",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "started_at",
    "finished_at",
    "duration_seconds",
)


def _cell(value) -> str:
    """결측(None)은 빈 문자열로 남긴다 — 0으로 바꾸지 않는다."""

    return "" if value is None else str(value)


def _field_value(field: dict | None):
    if field is None:
        return None
    return field.get("value")


def _row_for(job: JobRecord) -> dict | None:
    if job.status not in PUBLISHABLE_STATUSES:
        return None

    result_path = Path(job.workdir).parent / "result.json"
    try:
        result = load_result(result_path)
    except ResultsError:
        return None

    usage = result.usage
    evaluation = result.evaluation or {}

    return {
        "run_id": result.run_id,
        "batch_id": job.batch_id,
        "condition_id": result.condition_id,
        "repeat_index": result.repeat_index,
        "content_id": result.content_id,
        "auth_method": _field_value(result.auth_method),
        "api_provider": _field_value(result.api_provider),
        "claude_version": _field_value(result.claude_version),
        "model": _field_value(result.model),
        "status": result.status,
        "evaluation_ran": evaluation.get("ran"),
        "evaluation_passed": evaluation.get("passed"),
        "num_turns": _field_value(result.num_turns),
        "cost_usd": _field_value(result.cost_usd),
        "input_tokens": _field_value(usage.get("input_tokens")),
        "output_tokens": _field_value(usage.get("output_tokens")),
        "cache_creation_input_tokens": _field_value(
            usage.get("cache_creation_input_tokens")
        ),
        "cache_read_input_tokens": _field_value(usage.get("cache_read_input_tokens")),
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "duration_seconds": result.duration_seconds,
    }


def base_run_id(run_id: str) -> str:
    """시도 번호 접미사를 뗀 원래 run_id."""

    return run_id.split("#", 1)[0]


def attempt_run_id(run_id: str, published: set[str]) -> str:
    """같은 run_id가 이미 게시돼 있으면 `run_id#2`처럼 시도 번호를 붙인다.

    재시도는 같은 run_id를 다시 쓴다(`job_store.retry_job`). CSV에 같은 값이
    두 번 들어가면 활동 로그를 `run_date/run_id`로 묶는 웹이 서로 다른 시도의
    turn을 한 실행으로 합쳐 버린다 — turn 수와 토큰 합이 부풀려진다. 시도마다
    다른 키를 주어 각 시도가 따로 보이게 한다.
    """

    if run_id not in published:
        return run_id
    attempt = 2
    while f"{run_id}#{attempt}" in published:
        attempt += 1
    return f"{run_id}#{attempt}"


def _read_published(path: Path, *, status_column: str) -> tuple[set[str], set[tuple[str, str]]]:
    """이미 게시된 (행 키 전체, (원래 run_id, status) 쌍)을 읽는다."""

    if not path.is_file():
        return set(), set()
    keys: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            run_id = row.get("run_id")
            if not run_id:
                continue
            keys.add(run_id)
            pairs.add((base_run_id(run_id), row.get(status_column) or ""))
    return keys, pairs


def _publish_jobs(
    jobs, *, output_path: Path = DEFAULT_OUTPUT_PATH, run_ids=None
) -> list[dict]:
    """아직 게시되지 않은 결과를 CSV에 append한다.

    반환값은 이번에 새로 추가된 행이다(멱등 — 같은 (run_id, status)는 다시
    추가되지 않는다).
    """

    published_keys, published_pairs = _read_published(output_path, status_column="status")

    new_rows: list[dict] = []
    for job in jobs:
        # 같은 실행의 같은 결과는 다시 쓰지 않는다. 하지만 timeout 뒤 재시도해서
        # succeeded가 된 실행은 상태가 다르므로 새 행으로 남는다 — 예전에는
        # run_id만 보고 걸러서 재시도 성공 결과가 영구히 누락됐다.
        if (job.run_id, job.status) in published_pairs:
            continue
        row = _row_for(job)
        if row is not None:
            row["run_id"] = (run_ids or {}).get((job.run_id, job.status)) or attempt_run_id(row["run_id"], published_keys)
            published_keys.add(row["run_id"])
            new_rows.append(row)

    if new_rows:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not output_path.is_file() or output_path.stat().st_size == 0
        with output_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if write_header:
                writer.writeheader()
            for row in new_rows:
                writer.writerow({col: _cell(row.get(col)) for col in CSV_COLUMNS})

    return new_rows


DEFAULT_DIAGNOSTICS_PATH = Path("data/run-diagnostics.json")

DEFAULT_ACTIVITY_PATH = Path("data/activity-log.csv")
DEFAULT_SUMMARY_PATH = Path("data/run-summary.csv")
DEFAULT_COMPARISON_PATH = Path("data/comparison.csv")

# timeout은 가장 원인을 알아야 하는 실패다 — 무한 반복에 빠진 실행이 여기
# 빠지면 CSV에도 진단 레포트에도 남지 않는다(사용자 결정). measurable=0으로
# 기록되므로 comparison.csv의 평균에는 들어가지 않는다.
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


def condition_label(condition_id: str) -> str:
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
    "noise_processed_pct", "noise_cost_pct", "model",
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
        by_prompt.setdefault((row.get("model", ""), row.get("prompt_id", "")), []).append({
            "condition": row["condition"],
            "processed": float(row["processed_tokens"]),
            "cost": float(row["cost_usd"]),
            "tax": float(row["context_tax_tokens"]),
            "run_date": row["run_date"],
            "quality": float(quality),
        })

    out_rows = []
    for model, prompt_id in sorted(by_prompt):
        runs = by_prompt[(model, prompt_id)]
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
                out_rows.append([run_date, prompt_id, *row, model])

    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    with comparison_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(COMPARISON_COLUMNS)
        writer.writerows(out_rows)


def _collect_jobs(
    jobs, *, run_ids=None, diagnose=True, activity_path: Path = DEFAULT_ACTIVITY_PATH,
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    comparison_path: Path = DEFAULT_COMPARISON_PATH,
    diagnostics_path: Path = DEFAULT_DIAGNOSTICS_PATH,
) -> dict:
    """아직 게시되지 않은 succeeded/failed 작업을 턴 단위로 CSV에 append한다."""

    # run-summary.csv는 status를 terminal_reason 열에 쓴다.
    published_keys, published_pairs = _read_published(
        summary_path, status_column="terminal_reason"
    )
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

        transcript = Transcript.load(job.stdout_path)
        turns = with_context_tax(extract_turns(transcript))
        run_date = (job.started_at or job.enqueued_at)[:10]
        condition = condition_label(job.condition_id)

        # 재시도는 같은 run_id를 다시 쓴다. 활동 로그와 요약에 같은 키로
        # 두 번 들어가면 웹이 두 시도의 turn을 한 실행으로 합친다.
        row_run_id = (run_ids or {}).get((job.run_id, job.status)) or attempt_run_id(job.run_id, published_keys)
        published_keys.add(row_run_id)

        new_activity_rows.extend(activity_rows(run_date, row_run_id, condition, turns))
        if diagnose and job.stdout_path:
            update_manifest(
                row_run_id, transcript, diagnostics_path,
                status=job.status, condition_id=job.condition_id,
            )

        measurable = job.status == "succeeded" and is_measurable(turns)
        shares = reconcile(turns) if turns else {
            "observed": 0, "opening": 0, "output": 0, "tool_result": 0, "discarded": 0,
        }
        model = turns[0].model if turns else (result.model.get("value") or "")
        result_event = transcript.result_event
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




_OUTPUT_NAMES = (
    "token-bench-results.csv", "activity-log.csv", "run-summary.csv",
    "comparison.csv", "run-diagnostics.json",
)


def _restore(data_dir: Path, journal: Path) -> None:
    before = json.loads(journal.read_text(encoding="utf-8"))
    for name in _OUTPUT_NAMES:
        target = data_dir / name
        if before[name] is None:
            target.unlink(missing_ok=True)
        else:
            temporary = data_dir / (name + ".restore")
            temporary.write_bytes(base64.b64decode(before[name]))
            os.replace(temporary, target)
    journal.unlink()


def _publish_transaction(data_dir: Path, operation):
    """출력은 stage에서 완성한다. 교체 도중 중단되면 다음 호출이 전본을 복구한다.

    파일별 replace는 atomic이다. 여러 파일을 동시에 읽는 외부 reader의
    snapshot isolation이나 전원 장애 시 디스크 durability는 보장하지 않는다.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(data_dir / ".publish.lock"):
        journal = data_dir / ".publish-rollback.json"
        if journal.exists():
            _restore(data_dir, journal)
        with TemporaryDirectory(prefix=".publish-", dir=data_dir) as temporary:
            stage = Path(temporary)
            before = {}
            for name in _OUTPUT_NAMES:
                target = data_dir / name
                before[name] = base64.b64encode(target.read_bytes()).decode() if target.is_file() else None
                if target.is_file():
                    shutil.copy2(target, stage / name)
            result = operation(stage)
            changed = [name for name in _OUTPUT_NAMES if (stage / name).is_file() and (
                before[name] is None or (stage / name).read_bytes() != base64.b64decode(before[name])
            )]
            if not changed:
                return result
            pending = data_dir / ".publish-rollback.tmp"
            pending.write_text(json.dumps(before), encoding="utf-8")
            os.replace(pending, journal)
            try:
                for name in changed:
                    os.replace(stage / name, data_dir / name)
            except BaseException:
                _restore(data_dir, journal)
                raise
            journal.unlink()
            return result


def _attempt_keys(jobs, data_dir: Path) -> dict:
    """이전에 부분 게시된 시도도 두 표에서 같은 키로 완성한다."""
    keys, pairs = set(), {}
    for name, status in [("token-bench-results.csv", "status"), ("run-summary.csv", "terminal_reason")]:
        path = data_dir / name
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                key = row["run_id"]
                pair = (base_run_id(key), row[status])
                if pair in pairs and pairs[pair] != key:
                    raise ValueError(f"게시된 시도 키가 표마다 다르다: {pair[0]}")
                pairs[pair] = key
                keys.add(key)
    for job in jobs:
        pair = (job.run_id, job.status)
        if job.status in PUBLISHABLE_STATUSES and pair not in pairs:
            pairs[pair] = attempt_run_id(job.run_id, keys)
            keys.add(pairs[pair])
    return pairs


def sync_published(*, db_path: Path, data_dir: Path = Path("data"), diagnose: bool = True) -> dict:
    """완료 작업을 한 번 조회하고 모든 게시물을 같은 시도 키로 동기화한다."""
    def synchronize(stage):
        jobs = list_jobs(db_path=db_path)
        run_ids = _attempt_keys(jobs, stage)
        activity = _collect_jobs(
            jobs, run_ids=run_ids, diagnose=diagnose,
            activity_path=stage / "activity-log.csv", summary_path=stage / "run-summary.csv",
            comparison_path=stage / "comparison.csv", diagnostics_path=stage / "run-diagnostics.json",
        )
        rows = _publish_jobs(jobs, output_path=stage / "token-bench-results.csv", run_ids=run_ids)
        return {**activity, "published_count": len(rows), "published_rows": rows}
    return _publish_transaction(data_dir, synchronize)


def publish(*, db_path: Path, output_path: Path = DEFAULT_OUTPUT_PATH) -> list[dict]:
    """기존 단일 CSV 명령 계약을 유지한다."""
    if output_path == DEFAULT_OUTPUT_PATH:
        return sync_published(db_path=db_path, diagnose=False)["published_rows"]
    return _publish_jobs(list_jobs(db_path=db_path), output_path=output_path)


def collect(
    *, db_path: Path, activity_path: Path = DEFAULT_ACTIVITY_PATH,
    summary_path: Path = DEFAULT_SUMMARY_PATH, comparison_path: Path = DEFAULT_COMPARISON_PATH,
    diagnostics_path: Path = DEFAULT_DIAGNOSTICS_PATH,
) -> dict:
    """기존 collect 출력 경로와 반환값 계약을 유지한다."""
    if (activity_path, summary_path, comparison_path, diagnostics_path) == (
        DEFAULT_ACTIVITY_PATH, DEFAULT_SUMMARY_PATH, DEFAULT_COMPARISON_PATH, DEFAULT_DIAGNOSTICS_PATH,
    ):
        stats = sync_published(db_path=db_path)
        return {"runs": stats["runs"], "turns": stats["turns"]}
    return _collect_jobs(
        list_jobs(db_path=db_path), activity_path=activity_path, summary_path=summary_path,
        comparison_path=comparison_path, diagnostics_path=diagnostics_path,
    )
