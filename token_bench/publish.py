"""완료된 로컬 실행 결과를 공개 CSV(`data/token-bench-results.csv`)로 append한다.

완료된 실행 결과를 공개 CSV 행으로 변환·append하는 일만 담당한다. 웹 표시나
조건 간 집계(평균 계산 등)는 이 모듈이 하지 않는다 — 그건 M13(웹 페이지)의
책임이다.
"""

from __future__ import annotations

import csv
from pathlib import Path

from token_bench.job_store import JobRecord, list_jobs
from token_bench.results import ResultsError, load as load_result

DEFAULT_OUTPUT_PATH = Path("data/token-bench-results.csv")

# 측정된 결과로 볼 수 있는 상태만 게시한다. blocked/timeout/running/queued는
# 인프라·승인 문제이거나 아직 끝나지 않은 실행이므로 공개 데이터에 넣지 않는다.
PUBLISHABLE_STATUSES = frozenset({"succeeded", "failed"})

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


def _read_published_run_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {row["run_id"] for row in reader if row.get("run_id")}


def publish(
    *, db_path: Path, output_path: Path = DEFAULT_OUTPUT_PATH
) -> list[dict]:
    """아직 게시되지 않은 succeeded/failed 작업을 CSV에 append한다.

    반환값은 이번에 새로 추가된 행이다(멱등 — 같은 run_id는 다시 추가되지
    않는다).
    """

    already_published = _read_published_run_ids(output_path)
    jobs = list_jobs(db_path=db_path)

    new_rows: list[dict] = []
    for job in jobs:
        if job.run_id in already_published:
            continue
        row = _row_for(job)
        if row is not None:
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
