import csv
import json
from pathlib import Path

from token_bench.authorization import approve, build_estimate
from token_bench.job_store import enqueue, finish_job, claim_next_queued, retry_job
from token_bench.publish import CSV_COLUMNS, publish
from token_bench.results import RunResult, save as save_result
from token_bench.workspace import RunWorkspace

SUBSCRIPTION_AUTH = {
    "logged_in": True,
    "auth_method": "claude.ai",
    "api_provider": "firstParty",
    "subscription_type": "pro",
}


def _field(value, missing_reason=None):
    return {"value": value, "missing_reason": missing_reason}


def _make_finished_job(tmp_path, *, condition_id="base", content_id="abc", status="succeeded"):
    workdir = tmp_path / "batch1" / f"{condition_id}__r1" / "workdir"
    workdir.mkdir(parents=True)
    ws = RunWorkspace(
        run_id=f"batch1-{condition_id}__r1",
        content_id=content_id,
        condition_id=condition_id,
        repeat_index=1,
        workdir=workdir,
        snapshot_path=workdir.parent / "snapshot.json",
    )
    plan = build_estimate(
        [ws], batch_id="batch1", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    approval = approve(plan, confirmed_digest=plan.digest)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)
    job = claim_next_queued(db_path=db_path)

    result = RunResult(
        run_id=ws.run_id,
        condition_id=condition_id,
        repeat_index=1,
        content_id=content_id,
        auth_method=_field("claude.ai"),
        api_provider=_field("firstParty"),
        timeout_seconds=60,
        isolation="safe-mode",
        claude_version=_field("2.1.236"),
        model=_field("claude-sonnet-5"),
        status=status,
        returncode=0 if status == "succeeded" else 1,
        started_at="2026-09-15T00:00:00+00:00",
        finished_at="2026-09-15T00:05:00+00:00",
        duration_seconds=300.0,
        stdout_path=str(workdir.parent / "logs" / "stdout.jsonl"),
        stderr_path=str(workdir.parent / "logs" / "stderr.log"),
        num_turns=_field(3),
        cost_usd=_field(0.42),
        usage={
            "input_tokens": _field(100),
            "output_tokens": _field(50),
            "cache_creation_input_tokens": _field(10),
            "cache_read_input_tokens": _field(5),
        },
        evaluation={"ran": True, "passed": True},
    )
    save_result(result, workdir.parent / "result.json")

    finished = finish_job(
        job.run_id,
        status=status,
        returncode=result.returncode,
        finished_at=result.finished_at,
        duration_seconds=result.duration_seconds,
        stdout_path=result.stdout_path,
        stderr_path=result.stderr_path,
        command_json="[]",
        db_path=db_path,
    )
    return db_path, finished


def test_publish_appends_row_for_succeeded_job(tmp_path):
    db_path, job = _make_finished_job(tmp_path)
    out_path = tmp_path / "results.csv"

    new_rows = publish(db_path=db_path, output_path=out_path)

    assert len(new_rows) == 1
    with out_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["run_id"] == job.run_id
    assert rows[0]["cost_usd"] == "0.42"
    assert rows[0]["evaluation_passed"] == "True"


def test_publish_is_idempotent_for_same_run_id(tmp_path):
    db_path, job = _make_finished_job(tmp_path)
    out_path = tmp_path / "results.csv"

    publish(db_path=db_path, output_path=out_path)
    second = publish(db_path=db_path, output_path=out_path)

    assert second == []
    with out_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1


def test_publish_skips_blocked_and_queued_jobs(tmp_path):
    db_path, job = _make_finished_job(tmp_path, status="blocked")
    out_path = tmp_path / "results.csv"

    new_rows = publish(db_path=db_path, output_path=out_path)

    assert new_rows == []
    assert not out_path.exists()


def test_publish_never_writes_zero_for_missing_values(tmp_path):
    workdir = tmp_path / "batch1" / "base__r1" / "workdir"
    workdir.mkdir(parents=True)
    ws = RunWorkspace(
        run_id="batch1-base__r1",
        content_id="abc",
        condition_id="base",
        repeat_index=1,
        workdir=workdir,
        snapshot_path=workdir.parent / "snapshot.json",
    )
    plan = build_estimate(
        [ws], batch_id="batch1", timeout_seconds=60, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    approval = approve(plan, confirmed_digest=plan.digest)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)
    job = claim_next_queued(db_path=db_path)

    result = RunResult(
        run_id=ws.run_id,
        condition_id="base",
        repeat_index=1,
        content_id="abc",
        auth_method=_field("claude.ai"),
        api_provider=_field("firstParty"),
        timeout_seconds=60,
        isolation="safe-mode",
        claude_version=_field("2.1.236"),
        model=_field(None, "stdout 로그 없음"),
        status="failed",
        returncode=1,
        started_at="2026-09-15T00:00:00+00:00",
        finished_at="2026-09-15T00:05:00+00:00",
        duration_seconds=300.0,
        stdout_path="",
        stderr_path="",
        num_turns=_field(None, "누락"),
        cost_usd=_field(None, "누락"),
        usage={
            "input_tokens": _field(None, "누락"),
            "output_tokens": _field(None, "누락"),
            "cache_creation_input_tokens": _field(None, "누락"),
            "cache_read_input_tokens": _field(None, "누락"),
        },
        evaluation=None,
    )
    save_result(result, workdir.parent / "result.json")
    finish_job(
        job.run_id,
        status="failed",
        returncode=1,
        finished_at=result.finished_at,
        duration_seconds=300.0,
        stdout_path="",
        stderr_path="",
        command_json="[]",
        db_path=db_path,
    )

    out_path = tmp_path / "results.csv"
    publish(db_path=db_path, output_path=out_path)

    with out_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    row = rows[0]
    for col in ("model", "num_turns", "cost_usd", "input_tokens"):
        assert row[col] == "", f"{col}는 결측이면 빈 문자열이어야 한다: {row[col]!r}"


def test_csv_header_matches_csv_columns_constant(tmp_path):
    db_path, job = _make_finished_job(tmp_path)
    out_path = tmp_path / "results.csv"
    publish(db_path=db_path, output_path=out_path)

    with out_path.open(encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert tuple(header) == CSV_COLUMNS


def test_retried_run_is_published_as_a_second_attempt(tmp_path):
    """timeout 뒤 재시도해서 성공한 실행이 누락되지 않는다.

    재시도는 같은 run_id를 다시 쓴다. 예전에는 run_id만 보고 걸러서 두 번째
    결과가 CSV에 영원히 들어가지 않았다.
    """
    db_path, job = _make_finished_job(tmp_path, status="timeout")
    out_path = tmp_path / "results.csv"

    assert [r["status"] for r in publish(db_path=db_path, output_path=out_path)] == ["timeout"]

    # 웹의 "재시도" 버튼과 같은 경로로 되돌린 뒤 성공으로 끝낸다.
    retry_job(job.run_id, db_path=db_path)
    claimed = claim_next_queued(db_path=db_path)
    assert claimed is not None
    result_path = Path(job.workdir).parent / "result.json"
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    raw["status"] = "succeeded"
    result_path.write_text(json.dumps(raw), encoding="utf-8")
    finish_job(
        claimed.run_id,
        status="succeeded",
        returncode=0,
        finished_at="2026-09-15T01:05:00+00:00",
        duration_seconds=300.0,
        stdout_path=claimed.stdout_path or "",
        stderr_path=claimed.stderr_path or "",
        command_json="[]",
        db_path=db_path,
    )

    new_rows = publish(db_path=db_path, output_path=out_path)
    assert [r["status"] for r in new_rows] == ["succeeded"]
    # 시도마다 다른 키로 남아야 웹이 두 시도의 turn을 한 실행으로 합치지 않는다.
    assert new_rows[0]["run_id"] == f"{job.run_id}#2"

    with out_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["run_id"], r["status"]) for r in rows] == [
        (job.run_id, "timeout"),
        (f"{job.run_id}#2", "succeeded"),
    ]

    # 같은 상태를 다시 게시하지 않는다(멱등).
    assert publish(db_path=db_path, output_path=out_path) == []
