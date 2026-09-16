"""M9의 실제 구독 순차 실행 검증.

이 파일은 실제 Claude 구독 사용량을 소비하는 모델 호출을 수행한다.
`docs/IMPLEMENTATION-PLAN.md`의 규칙에 따라 실제 모델 호출 전에는 실행
수·timeout·인증 상태·비용 확인과 사용자의 명시적 동의가 필요하다.
기본 CI와 일반 `pytest` 실행에서는 항상 건너뛰며, 사용자가 동의한 뒤
`TOKEN_BENCH_ALLOW_REAL_SUBSCRIPTION_RUN=1`을 명시적으로 설정했을 때만
실행된다.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    os.environ.get("TOKEN_BENCH_ALLOW_REAL_SUBSCRIPTION_RUN") != "1",
    reason=(
        "실제 Claude 구독 사용량을 소비한다. 사용자의 명시적 동의 후 "
        "TOKEN_BENCH_ALLOW_REAL_SUBSCRIPTION_RUN=1로만 실행한다."
    ),
)


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "token_bench", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_real_subscription_sequence_runs_base_and_be_brief():
    timeout_seconds = int(os.environ.get("TOKEN_BENCH_TIMEOUT_SECONDS", "3600"))

    est = _run_cli(
        [
            "estimate",
            "--timeout-seconds",
            str(timeout_seconds),
        ]
    )
    assert est.returncode == 0, est.stderr
    plan = json.loads(est.stdout)
    assert plan["run_count"] == 2
    assert {r["condition_id"] for r in plan["runs"]} == {"base", "be-brief"}

    plan_path = REPO_ROOT / ".token-bench" / "runs" / plan["batch_id"] / "plan.json"
    appr = _run_cli(["approve", "--plan", str(plan_path), "--confirm", plan["digest"]])
    assert appr.returncode == 0, appr.stderr

    approval_path = plan_path.parent / "approval.json"
    enq = _run_cli(["enqueue", "--plan", str(plan_path), "--approval", str(approval_path)])
    assert enq.returncode == 0, enq.stderr

    work = _run_cli(["work", "--exit-when-empty", "--poll-interval-seconds", "5"])
    assert work.returncode == 0, work.stderr

    status = _run_cli(["status"])
    jobs = json.loads(status.stdout)
    assert len(jobs) == 2
    assert all(job["status"] in ("succeeded", "failed") for job in jobs)

    intervals = [
        (job["started_at"], job["finished_at"])
        for job in sorted(jobs, key=lambda j: j["sequence"])
    ]
    assert intervals[0][1] <= intervals[1][0], "실행 시간 구간이 겹치면 안 된다."

    for job in jobs:
        result = _run_cli(["result", "--run-id", job["run_id"]])
        assert result.returncode == 0, result.stderr
        run_result = json.loads(result.stdout)
        assert run_result["auth_method"]["value"] == "claude.ai"
        assert run_result["evaluation"] is not None
