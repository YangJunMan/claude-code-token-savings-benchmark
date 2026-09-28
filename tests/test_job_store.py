import threading
from pathlib import Path

import pytest

from token_bench.authorization import approve, build_estimate
from token_bench.job_store import (
    JobStoreError,
    claim_next_queued,
    delete_job,
    enqueue,
    finish_job,
    get_job,
    list_jobs,
    requeue_job,
    requeue_orphaned_running,
    retry_job,
)
from token_bench.workspace import RunWorkspace

SUBSCRIPTION_AUTH = {
    "logged_in": True,
    "auth_method": "claude.ai",
    "api_provider": "firstParty",
    "subscription_type": "pro",
}


def _workspace(condition_id="base", repeat_index=1, content_id="abc", batch_id="batch1"):
    return RunWorkspace(
        run_id=f"{batch_id}-{condition_id}__r{repeat_index}",
        content_id=content_id,
        condition_id=condition_id,
        repeat_index=repeat_index,
        workdir=Path(f"/tmp/{batch_id}/{condition_id}__r{repeat_index}/workdir"),
        snapshot_path=Path(f"/tmp/{batch_id}/{condition_id}__r{repeat_index}/snapshot.json"),
    )


def _approved_plan(workspaces, *, timeout_seconds=60):
    plan = build_estimate(
        workspaces,
        batch_id="batch1",
        timeout_seconds=timeout_seconds,
        auth=SUBSCRIPTION_AUTH, isolation="safe-mode",
    )
    approval = approve(plan, confirmed_digest=plan.digest)
    return plan, approval


def test_enqueue_creates_one_job_per_run(tmp_path):
    workspaces = [_workspace("base"), _workspace("be-brief")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"

    jobs = enqueue(plan, approval, db_path=db_path)

    assert [job.run_id for job in jobs] == [ws.run_id for ws in workspaces]
    assert all(job.status == "queued" for job in jobs)


def test_enqueue_preserves_order_across_process_restart(tmp_path):
    workspaces = [_workspace("base"), _workspace("be-brief")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"

    enqueue(plan, approval, db_path=db_path)

    # 새 연결(별도 프로세스를 가장)로 다시 조회해도 순서와 상태가 유지된다.
    reloaded = list_jobs(db_path=db_path)
    assert [job.run_id for job in reloaded] == [ws.run_id for ws in workspaces]
    assert all(job.status == "queued" for job in reloaded)


def test_resubmitting_same_approval_does_not_duplicate_jobs(tmp_path):
    workspaces = [_workspace("base")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"

    first = enqueue(plan, approval, db_path=db_path)
    second = enqueue(plan, approval, db_path=db_path)

    assert first == second
    assert len(list_jobs(db_path=db_path)) == 1


def test_concurrent_enqueue_of_same_approval_creates_jobs_once(tmp_path):
    """같은 승인의 동시 제출이 별도 연결/스레드에서도 실행을 중복 생성하지 않는다."""
    workspaces = [_workspace("base"), _workspace("be-brief")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"

    barrier = threading.Barrier(5)
    errors: list[Exception] = []

    def worker():
        try:
            barrier.wait(timeout=5)
            enqueue(plan, approval, db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    jobs = list_jobs(db_path=db_path)
    assert len(jobs) == len(workspaces)
    assert len({job.run_id for job in jobs}) == len(workspaces)


def test_enqueue_rejects_approval_for_different_plan(tmp_path):
    workspaces = [_workspace("base")]
    plan, approval = _approved_plan(workspaces)

    other_plan = build_estimate(
        [_workspace("be-brief")],
        batch_id="batch1",
        timeout_seconds=60,
        auth=SUBSCRIPTION_AUTH, isolation="safe-mode",
    )
    db_path = tmp_path / "state.db"

    with pytest.raises(JobStoreError):
        enqueue(other_plan, approval, db_path=db_path)


def test_get_job_returns_none_for_unknown_run_id(tmp_path):
    db_path = tmp_path / "state.db"
    assert get_job("does-not-exist", db_path=db_path) is None


def test_get_job_returns_matching_record(tmp_path):
    workspaces = [_workspace("base")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)

    job = get_job(workspaces[0].run_id, db_path=db_path)
    assert job is not None
    assert job.condition_id == "base"
    assert job.content_id == "abc"


def test_requeue_orphaned_running_resets_to_queued_so_it_retries(tmp_path):
    """worker가 죽었을 때 'running'에 멈춘 작업은 실패로 남기지 않고 처음부터
    다시 시도한다 — 인프라 문제(프로세스가 죽음)를 측정 실패와 섞지 않기
    위해서다."""

    workspaces = [_workspace("base"), _workspace("be-brief")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)
    claimed = claim_next_queued(db_path=db_path)
    assert claimed.run_id == workspaces[0].run_id

    reaped = requeue_orphaned_running(db_path=db_path)

    assert [job.run_id for job in reaped] == [workspaces[0].run_id]
    job = get_job(workspaces[0].run_id, db_path=db_path)
    assert job.status == "queued"
    assert job.started_at is None
    # 순서(sequence)는 유지된다 — 다음 claim이 원래 자리에서 다시 집는다.
    assert claim_next_queued(db_path=db_path).run_id == workspaces[0].run_id


def test_requeue_job_resets_a_specific_running_job_to_queued(tmp_path):
    """구독 사용 한도로 끊긴 job은 실패로 남기지 않고 그 job부터 다시 시도한다."""

    workspaces = [_workspace("base"), _workspace("be-brief")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)
    claimed = claim_next_queued(db_path=db_path)

    requeue_job(claimed.run_id, db_path=db_path)

    job = get_job(claimed.run_id, db_path=db_path)
    assert job.status == "queued"
    assert job.started_at is None


def test_requeue_job_rejects_a_job_that_is_not_running(tmp_path):
    workspaces = [_workspace("base")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)

    with pytest.raises(JobStoreError):
        requeue_job(workspaces[0].run_id, db_path=db_path)


def test_retry_job_resets_a_blocked_job_to_queued(tmp_path):
    workspaces = [_workspace("base")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)
    claimed = claim_next_queued(db_path=db_path)
    finish_job(
        claimed.run_id,
        status="blocked",
        returncode=None,
        finished_at="2026-01-01T00:00:00+00:00",
        duration_seconds=0.0,
        stdout_path="",
        stderr_path="",
        command_json="[]",
        db_path=db_path,
    )

    retried = retry_job(claimed.run_id, db_path=db_path)

    assert retried.status == "queued"
    assert retried.started_at is None
    assert retried.finished_at is None


def test_retry_job_rejects_succeeded_and_active_jobs(tmp_path):
    workspaces = [_workspace("base"), _workspace("be-brief")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)
    succeeded = claim_next_queued(db_path=db_path)
    finish_job(
        succeeded.run_id,
        status="succeeded",
        returncode=0,
        finished_at="2026-01-01T00:00:00+00:00",
        duration_seconds=1.0,
        stdout_path="",
        stderr_path="",
        command_json="[]",
        db_path=db_path,
    )
    running = claim_next_queued(db_path=db_path)

    with pytest.raises(JobStoreError):
        retry_job(succeeded.run_id, db_path=db_path)
    with pytest.raises(JobStoreError):
        retry_job(running.run_id, db_path=db_path)


def test_delete_job_removes_a_queued_job(tmp_path):
    workspaces = [_workspace("base"), _workspace("be-brief")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)

    delete_job(workspaces[1].run_id, db_path=db_path)

    assert get_job(workspaces[1].run_id, db_path=db_path) is None
    assert get_job(workspaces[0].run_id, db_path=db_path) is not None


def test_delete_job_rejects_a_running_job(tmp_path):
    workspaces = [_workspace("base")]
    plan, approval = _approved_plan(workspaces)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)
    claimed = claim_next_queued(db_path=db_path)

    with pytest.raises(JobStoreError):
        delete_job(claimed.run_id, db_path=db_path)


def test_delete_job_rejects_unknown_run_id(tmp_path):
    db_path = tmp_path / "state.db"
    with pytest.raises(JobStoreError):
        delete_job("does-not-exist", db_path=db_path)
