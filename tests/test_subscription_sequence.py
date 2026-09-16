import json
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from token_bench.worker import WorkerLockError, worker_lock

REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_runnable_conditions(dst: Path) -> None:
    """sandbox에는 이 환경에서 실제로 preflight를 통과하는 조건만 넣는다.

    실제 선언에는 외부 도구가 필요한 조건(headroom 등)이 있어서, 그대로
    복사하면 도구가 없는 기계에서 테스트가 환경 때문에 실패한다.
    """

    doc = json.loads((REPO_ROOT / "benchmark" / "conditions.json").read_text(encoding="utf-8"))
    doc["conditions"] = [c for c in doc["conditions"] if c["id"] in ("base", "be-brief")]
    dst.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_fake_claude(bin_dir: Path, *, model="claude-sonnet-5", exit_code=0) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "claude"
    script.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  --version) echo '2.1.236 (Claude Code)'; exit 0 ;;\n"
        "  auth) echo '{\"loggedIn\": true, \"authMethod\": \"claude.ai\", "
        "\"apiProvider\": \"firstParty\", \"subscriptionType\": \"pro\"}'; exit 0 ;;\n"
        "  --help) echo '--safe-mode --settings <file-or-json> --permission-mode <mode>'; exit 0 ;;\n"
        f"  *) printf '%s' \"${{LIVE_ONLY:-missing}}\" > live-env.txt; "
        f"echo '{{\"type\":\"system\",\"model\":\"{model}\"}}'; "
        f"echo '{{\"type\":\"result\",\"num_turns\":1,\"total_cost_usd\":0.01,"
        '"usage":{"input_tokens":1,"output_tokens":1,'
        '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}\';'
        f" exit {exit_code} ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_probe_script(repo_root: Path, version: str) -> Path:
    script = repo_root / "probe-version.py"
    script.write_text(f"print({version!r})\n", encoding="utf-8")
    return script


def _cli_env(fake_bin_dir: Path) -> dict:
    import os

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin_dir}:{env['PATH']}"
    return env


def _run_cli(args: list[str], *, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "token_bench", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture()
def sandbox_repo(tmp_path):
    """token_bench 모듈을 import할 수 있는 임시 작업 디렉터리를 만든다."""

    import shutil

    (tmp_path / "token_bench").symlink_to(REPO_ROOT / "token_bench")
    (tmp_path / "benchmark").mkdir()
    shutil.copytree(REPO_ROOT / "benchmark" / "fixture", tmp_path / "benchmark" / "fixture")
    shutil.copytree(REPO_ROOT / "benchmark" / "prompts", tmp_path / "benchmark" / "prompts")
    _copy_runnable_conditions(tmp_path / "benchmark" / "conditions.json")
    return tmp_path


def test_worker_lock_rejects_second_holder(tmp_path):
    db_path = tmp_path / "state.db"
    with worker_lock(db_path):
        with pytest.raises(WorkerLockError):
            with worker_lock(db_path):
                pass


def test_worker_lock_is_released_after_context_exits(tmp_path):
    db_path = tmp_path / "state.db"
    with worker_lock(db_path):
        pass
    with worker_lock(db_path):
        pass  # 두 번째 진입이 막히지 않아야 한다.


def _prepare_approve_enqueue(sandbox_repo: Path, env: dict) -> None:
    est = _run_cli(
        ["estimate", "--timeout-seconds", "60"], cwd=sandbox_repo, env=env
    )
    assert est.returncode == 0, est.stderr
    plan = json.loads(est.stdout)
    plan_path = sandbox_repo / ".token-bench" / "runs" / plan["batch_id"] / "plan.json"

    appr = _run_cli(
        ["approve", "--plan", str(plan_path), "--confirm", plan["digest"]],
        cwd=sandbox_repo,
        env=env,
    )
    assert appr.returncode == 0, appr.stderr
    approval_path = plan_path.parent / "approval.json"

    enq = _run_cli(
        ["enqueue", "--plan", str(plan_path), "--approval", str(approval_path)],
        cwd=sandbox_repo,
        env=env,
    )
    assert enq.returncode == 0, enq.stderr


def test_work_loop_processes_queue_sequentially_without_overlap(sandbox_repo, tmp_path):
    fake_bin = _write_fake_claude(tmp_path / "fakebin")
    env = _cli_env(tmp_path / "fakebin")

    _prepare_approve_enqueue(sandbox_repo, env)

    result = _run_cli(
        ["work", "--exit-when-empty", "--poll-interval-seconds", "0.1"],
        cwd=sandbox_repo,
        env=env,
    )
    assert result.returncode == 0, result.stderr

    status = _run_cli(["status"], cwd=sandbox_repo, env=env)
    jobs = json.loads(status.stdout)
    assert len(jobs) == 2
    assert all(job["status"] == "succeeded" for job in jobs)

    intervals = [
        (job["started_at"], job["finished_at"]) for job in sorted(jobs, key=lambda j: j["sequence"])
    ]
    # 순차 실행이므로 두 번째 작업의 시작이 첫 번째 작업의 종료보다 이르면 안 된다.
    assert intervals[0][1] <= intervals[1][0]


def test_worker_uses_approved_snapshot_not_changed_live_registry(sandbox_repo, tmp_path):
    _write_fake_claude(tmp_path / "fakebin")
    env = _cli_env(tmp_path / "fakebin")
    _prepare_approve_enqueue(sandbox_repo, env)

    conditions_path = sandbox_repo / "benchmark" / "conditions.json"
    document = json.loads(conditions_path.read_text(encoding="utf-8"))
    document["conditions"][0]["injections"] = [
        {"type": "env", "name": "LIVE_ONLY", "value": "changed-after-approval"}
    ]
    conditions_path.write_text(json.dumps(document), encoding="utf-8")

    result = _run_cli(["work", "--once"], cwd=sandbox_repo, env=env)
    assert result.returncode == 0, result.stderr
    jobs = json.loads(_run_cli(["status"], cwd=sandbox_repo, env=env).stdout)
    marker = sandbox_repo / jobs[0]["workdir"] / "live-env.txt"
    assert marker.read_text(encoding="utf-8") == "missing"


def test_worker_fails_closed_when_approved_snapshot_is_missing(sandbox_repo, tmp_path):
    _write_fake_claude(tmp_path / "fakebin")
    env = _cli_env(tmp_path / "fakebin")
    _prepare_approve_enqueue(sandbox_repo, env)
    jobs = json.loads(_run_cli(["status"], cwd=sandbox_repo, env=env).stdout)
    (sandbox_repo / jobs[0]["snapshot_path"]).unlink()

    result = _run_cli(["work", "--once"], cwd=sandbox_repo, env=env)
    assert result.returncode == 1
    assert "snapshot" in result.stderr


def test_worker_blocks_when_approved_tool_fingerprint_changes(sandbox_repo, tmp_path):
    fake_bin = tmp_path / "fakebin"
    _write_fake_claude(fake_bin)
    probe = _write_probe_script(sandbox_repo, "probe-tool 1.0")
    env = _cli_env(fake_bin)
    python_binary = Path(sys.executable).name

    conditions_path = sandbox_repo / "benchmark" / "conditions.json"
    document = json.loads(conditions_path.read_text(encoding="utf-8"))
    document["conditions"] = [document["conditions"][0]]
    document["conditions"][0].update(
        {
            "requires_tools": [python_binary],
            "tool_probes": {python_binary: ["probe-version.py"]},
            "repository_url": "https://github.com/example/probe-tool",
        }
    )
    conditions_path.write_text(json.dumps(document), encoding="utf-8")

    _prepare_approve_enqueue(sandbox_repo, env)
    probe.write_text("print('probe-tool 2.0')\n", encoding="utf-8")

    result = _run_cli(["work", "--once"], cwd=sandbox_repo, env=env)
    assert result.returncode == 1
    assert "fingerprint" in result.stderr
    jobs = json.loads(_run_cli(["status"], cwd=sandbox_repo, env=env).stdout)
    assert jobs[0]["status"] == "blocked"


def test_work_loop_stops_on_blocked_job_without_processing_rest(sandbox_repo, tmp_path):
    import os

    # estimate/approve/enqueue까지는 가짜 claude로 정상 통과시킨다.
    fake_bin = _write_fake_claude(tmp_path / "fakebin")
    prep_env = _cli_env(tmp_path / "fakebin")
    _prepare_approve_enqueue(sandbox_repo, prep_env)

    # work 시점에는 claude를 PATH에서 완전히 지워 preflight 설치 확인이
    # 실패하게 만든다(설치가 그 사이 사라진 상황을 흉내낸다).
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    work_env = dict(os.environ)
    work_env["PATH"] = f"{empty_bin}"

    result = _run_cli(
        ["work", "--exit-when-empty", "--poll-interval-seconds", "0.1"],
        cwd=sandbox_repo,
        env=work_env,
    )
    assert result.returncode == 1

    status = _run_cli(["status"], cwd=sandbox_repo, env=work_env)
    jobs = json.loads(status.stdout)
    assert jobs[0]["status"] == "blocked"
    # 첫 작업이 막혔으므로 두 번째 작업은 큐에 그대로 남아 있어야 한다.
    assert jobs[1]["status"] == "queued"
