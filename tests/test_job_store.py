import threading
from pathlib import Path

import pytest

from token_bench.authorization import approve, build_estimate
from token_bench.job_store import JobStoreError, enqueue, get_job, list_jobs
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
        t.join(timeout=10)

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
