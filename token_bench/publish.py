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


def publish(
    *, db_path: Path, output_path: Path = DEFAULT_OUTPUT_PATH
) -> list[dict]:
    """아직 게시되지 않은 결과를 CSV에 append한다.

    반환값은 이번에 새로 추가된 행이다(멱등 — 같은 (run_id, status)는 다시
    추가되지 않는다).
    """

    published_keys, published_pairs = _read_published(output_path, status_column="status")
    jobs = list_jobs(db_path=db_path)

    new_rows: list[dict] = []
    for job in jobs:
        # 같은 실행의 같은 결과는 다시 쓰지 않는다. 하지만 timeout 뒤 재시도해서
        # succeeded가 된 실행은 상태가 다르므로 새 행으로 남는다 — 예전에는
        # run_id만 보고 걸러서 재시도 성공 결과가 영구히 누락됐다.
        if (job.run_id, job.status) in published_pairs:
            continue
        row = _row_for(job)
        if row is not None:
            row["run_id"] = attempt_run_id(row["run_id"], published_keys)
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
