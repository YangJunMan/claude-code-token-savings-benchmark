import json
import os
import textwrap
import threading
from pathlib import Path

import pytest

from token_bench.authorization import approve, build_estimate
from token_bench.conditions import Injection, RunSpec
from token_bench.job_store import claim_next_queued, enqueue, finish_job, get_job
from token_bench.worker import WorkerError, build_command, build_env, run_once
from token_bench.workspace import RunWorkspace
from tests.fake_cli import write_fake_cli

SUBSCRIPTION_AUTH = {
    "logged_in": True,
    "auth_method": "claude.ai",
    "api_provider": "firstParty",
    "subscription_type": "pro",
}


def _write_fake_claude(tmp_path: Path, python_body: str) -> Path:
    return write_fake_cli(tmp_path, "fake-claude", python_body)


def test_build_command_includes_isolation_and_permission_flags():
    command = build_command("do the task", (), claude_bin="claude")
    assert command[0] == "claude"
    assert "--safe-mode" in command
    assert "--permission-mode" in command
    assert command[-1] == "do the task"


def test_build_command_rejects_unsupported_arg_injections():
    injections = (Injection(type="arg", name="--effort", value="high"),)
    with pytest.raises(WorkerError, match="지원하지 않는 injection type"):
        build_command("prompt", injections, claude_bin="claude")


def test_build_command_appends_config_ref_as_settings_flag(tmp_path):
    injections = (Injection(type="config_ref", path="benchmark/skills/headroom.json"),)
    command = build_command("prompt", injections, claude_bin="claude", repo_root=tmp_path)
    assert "--settings" in command
    # claude가 작업 디렉터리에서 실행되므로 절대경로로 넘어가야 한다.
    assert command[command.index("--settings") + 1] == str(
        (tmp_path / "benchmark/skills/headroom.json").resolve()
    )


def test_build_env_applies_env_injections_without_mutating_base():
    base_env = {"PATH": "/usr/bin"}
    injections = (Injection(type="env", name="SOME_SKILL_FLAG", value="1"),)
    env = build_env(injections, base_env=base_env)
    assert env["SOME_SKILL_FLAG"] == "1"
    assert "SOME_SKILL_FLAG" not in base_env


def test_run_once_records_success(tmp_path):
    fake_claude = _write_fake_claude(tmp_path, 'print(\'{"type":"result"}\')')
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    outcome = run_once(
        run_id="r1",
        prompt="hello",
        injections=(),
        cwd=workdir,
        timeout_seconds=5,
        log_dir=tmp_path / "logs",
        env=dict(os.environ),
        claude_bin=str(fake_claude),
    )

    assert outcome.status == "succeeded"
    assert outcome.returncode == 0
    assert Path(outcome.stdout_path).read_text(encoding="utf-8").strip() == '{"type":"result"}'


def test_run_once_records_failure_exit_code(tmp_path):
    fake_claude = _write_fake_claude(tmp_path, "import sys; sys.exit(7)")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    outcome = run_once(
        run_id="r1",
        prompt="hello",
        injections=(),
        cwd=workdir,
        timeout_seconds=5,
        log_dir=tmp_path / "logs",
        env=dict(os.environ),
        claude_bin=str(fake_claude),
    )

    assert outcome.status == "failed"
    assert outcome.returncode == 7


def test_run_once_kills_process_on_timeout(tmp_path):
    fake_claude = _write_fake_claude(tmp_path, "import time; time.sleep(30)")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    outcome = run_once(
        run_id="r1",
        prompt="hello",
        injections=(),
        cwd=workdir,
        timeout_seconds=1,
        log_dir=tmp_path / "logs",
        env=dict(os.environ),
        claude_bin=str(fake_claude),
    )

    assert outcome.status == "timeout"
    assert outcome.duration_seconds < 10


def test_run_once_raises_when_binary_missing(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    with pytest.raises(WorkerError):
        run_once(
            run_id="r1",
            prompt="hello",
            injections=(),
            cwd=workdir,
            timeout_seconds=5,
            log_dir=tmp_path / "logs",
            env=dict(os.environ),
            claude_bin=str(tmp_path / "does-not-exist"),
        )


def _enqueue_one_job(tmp_path):
    workdir = tmp_path / "batch1" / "base__r1" / "workdir"
    workdir.mkdir(parents=True)
    (tmp_path / "batch1" / "base__r1" / "prompt.md").write_text(
        "do the task", encoding="utf-8"
    )
    ws = RunWorkspace(
        run_id="batch1-base__r1",
        content_id="abc",
        condition_id="base",
        repeat_index=1,
        workdir=workdir,
        snapshot_path=tmp_path / "batch1" / "base__r1" / "snapshot.json",
    )
    plan = build_estimate(
        [ws], batch_id="batch1", timeout_seconds=5, auth=SUBSCRIPTION_AUTH, isolation="safe-mode"
    )
    approval = approve(plan, confirmed_digest=plan.digest)
    db_path = tmp_path / "state.db"
    enqueue(plan, approval, db_path=db_path)
    return db_path, ws


def test_claim_next_queued_marks_job_running_and_prevents_duplicate_claim(tmp_path):
    db_path, ws = _enqueue_one_job(tmp_path)

    claimed = claim_next_queued(db_path=db_path)
    assert claimed is not None
    assert claimed.run_id == ws.run_id
    assert claimed.status == "running"

    second_claim = claim_next_queued(db_path=db_path)
    assert second_claim is None


def test_concurrent_claim_gives_job_to_exactly_one_worker(tmp_path):
    db_path, ws = _enqueue_one_job(tmp_path)

    barrier = threading.Barrier(5)
    claims: list = []
    lock = threading.Lock()

    def worker():
        barrier.wait(timeout=5)
        job = claim_next_queued(db_path=db_path)
        with lock:
            claims.append(job)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    successful = [c for c in claims if c is not None]
    assert len(successful) == 1
    assert successful[0].run_id == ws.run_id


def test_finish_job_transitions_running_job_to_final_status(tmp_path):
    db_path, ws = _enqueue_one_job(tmp_path)
    claim_next_queued(db_path=db_path)

    finished = finish_job(
        ws.run_id,
        status="succeeded",
        returncode=0,
        finished_at="2026-09-15T00:00:00+00:00",
        duration_seconds=1.5,
        stdout_path="stdout.jsonl",
        stderr_path="stderr.log",
        command_json="[]",
        db_path=db_path,
    )
    assert finished.status == "succeeded"
    assert finished.returncode == 0

    reloaded = get_job(ws.run_id, db_path=db_path)
    assert reloaded.status == "succeeded"


def test_finish_job_rejects_non_running_job(tmp_path):
    db_path, ws = _enqueue_one_job(tmp_path)
    # 아직 선점(claim)하지 않았으므로 상태는 'queued'다.
    from token_bench.job_store import JobStoreError

    with pytest.raises(JobStoreError):
        finish_job(
            ws.run_id,
            status="succeeded",
            returncode=0,
            finished_at="2026-09-15T00:00:00+00:00",
            duration_seconds=1.5,
            stdout_path="stdout.jsonl",
            stderr_path="stderr.log",
            command_json="[]",
            db_path=db_path,
        )


def test_full_lifecycle_with_fake_cli_end_to_end(tmp_path):
    """claim -> run_once(가짜 CLI) -> finish_job까지 실제로 이어지는지 검증한다."""
    fake_claude = _write_fake_claude(tmp_path, 'print(\'{"type":"result"}\')')
    db_path, ws = _enqueue_one_job(tmp_path)

    job = claim_next_queued(db_path=db_path)
    assert job is not None

    outcome = run_once(
        run_id=job.run_id,
        prompt="do the task",
        injections=(),
        cwd=Path(job.workdir),
        timeout_seconds=job.timeout_seconds,
        log_dir=Path(job.workdir).parent / "logs",
        env=dict(os.environ),
        claude_bin=str(fake_claude),
    )

    finished = finish_job(
        job.run_id,
        status=outcome.status,
        returncode=outcome.returncode,
        finished_at=outcome.finished_at,
        duration_seconds=outcome.duration_seconds,
        stdout_path=outcome.stdout_path,
        stderr_path=outcome.stderr_path,
        command_json=json.dumps(list(outcome.command)),
        db_path=db_path,
    )

    assert finished.status == "succeeded"
    assert finished.returncode == 0
    assert Path(finished.stdout_path).exists()
