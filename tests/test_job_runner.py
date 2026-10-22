from pathlib import Path

import pytest

from token_bench.authorization import approve, build_estimate
from token_bench.conditions import RunSpec
from token_bench.job_runner import process_job
from token_bench.job_store import claim_next_queued, enqueue, get_job, requeue_orphaned_running
from token_bench.workspace import RunWorkspace, prepare_batch

SUBSCRIPTION_AUTH = {
    "logged_in": True,
    "auth_method": "claude.ai",
    "api_provider": "firstParty",
    "subscription_type": "pro",
}


def test_unreadable_snapshot_is_terminal_not_left_running(tmp_path):
    """snapshot을 못 읽은 job이 'running'으로 남으면 다음 worker가 orphan으로
    보고 큐에 되돌려 같은 실패를 끝없이 반복한다."""

    run_dir = tmp_path / "batch1" / "base__r1"
    workspace = RunWorkspace(
        run_id="batch1-base__r1",
        content_id="abc",
        condition_id="base",
        repeat_index=1,
        workdir=run_dir / "workdir",
        snapshot_path=run_dir / "snapshot.json",  # 만들지 않는다
    )
    plan = build_estimate(
        [workspace], batch_id="batch1", timeout_seconds=60,
        auth=SUBSCRIPTION_AUTH, isolation="safe-mode",
    )
    db_path = tmp_path / "state.db"
    enqueue(plan, approve(plan, confirmed_digest=plan.digest), db_path=db_path)

    status = process_job(claim_next_queued(db_path=db_path), db_path=db_path)

    assert status == "config-error"
    assert get_job(workspace.run_id, db_path=db_path).status == "config-error"
    assert requeue_orphaned_running(db_path=db_path) == []


@pytest.mark.parametrize("prompt_bytes", [None, b"\xff"])
def test_unreadable_prompt_is_terminal_not_requeued(tmp_path, prompt_bytes):
    workspace = prepare_batch(
        [RunSpec(condition_id="base", repeat_index=1, repeat_total=1,
                 requires_tools=(), injections=())],
        timeout_seconds=60, runs_root=tmp_path, batch_id="batch1",
    )[0]
    prompt_path = workspace.workdir.parent / "prompt.md"
    if prompt_bytes is None:
        prompt_path.unlink()
    else:
        prompt_path.write_bytes(prompt_bytes)
    plan = build_estimate(
        [workspace], batch_id="batch1", timeout_seconds=60,
        auth=SUBSCRIPTION_AUTH, isolation="safe-mode",
    )
    db_path = tmp_path / "state.db"
    enqueue(plan, approve(plan, confirmed_digest=plan.digest), db_path=db_path)

    status = process_job(claim_next_queued(db_path=db_path), db_path=db_path)

    assert status == "config-error"
    assert get_job(workspace.run_id, db_path=db_path).status == "config-error"
    assert requeue_orphaned_running(db_path=db_path) == []
