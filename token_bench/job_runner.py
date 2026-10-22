"""선점된 job 하나를 실행하고 반드시 결과 상태로 끝맺는다.

CLI(`token_bench work`)와 웹 자동 실행(webapi.AutoWorker)이 같은 함수를
쓴다. job을 'running'으로 남겨 두는 경로가 없어야 한다 — 남으면 다음
worker가 orphan으로 보고 큐로 되돌려 같은 실패를 끝없이 반복한다.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from token_bench.transcript import Transcript, is_usage_limit_error
from token_bench.ledger import sync_published
from token_bench.evaluation import check as check_evaluation
from token_bench.job_store import finish_job, requeue_job
from token_bench.preflight import check as preflight_check
from token_bench.results import collect as collect_result, save as save_result
from token_bench.worker import WorkerError, build_env, run_once
from token_bench.workspace import WorkspaceError, load_run_snapshot

# 구독 사용 한도에 걸린 job을 재시도하기 전에 쉬는 시간. 정확한 한도 초기화
# 시각을 CLI 출력에서 알 수 없어(is_usage_limit_error 참고), 고정 대기 후
# 다시 시도하는 단순한 전략을 쓴다.
RATE_LIMIT_BACKOFF_SECONDS = 1800


def _tail(stderr_path: str | None, limit: int = 300) -> str:
    if not stderr_path or not Path(stderr_path).is_file():
        return ""
    return Path(stderr_path).read_text(encoding="utf-8", errors="replace").strip()[-limit:]


def _end_without_run(job, status: str, *, db_path: Path) -> str:
    """실행하지 못한 job을 측정값 없이 종결 상태로 기록한다."""

    finish_job(
        job.run_id,
        status=status,
        returncode=None,
        finished_at=datetime.now(timezone.utc).isoformat(),
        duration_seconds=0.0,
        stdout_path="",
        stderr_path="",
        command_json="[]",
        db_path=db_path,
    )
    return status


def process_job(job, *, db_path: Path, cancel_event=None) -> str:
    """선점된 작업 하나를 preflight 재확인부터 결과 저장까지 처리한다.

    반환값은 job_store/worker/results가 인식하는 상태 문자열이다:
    'succeeded'·'failed'는 측정된 결과(계속 진행 가능), 'blocked'·
    'config-error'·'worker-error'는 인프라·승인 문제(순차 실행을 멈춰야 함)다.
    'rate-limited'는 구독 사용 한도로 보여 이 job을 다시 큐에 넣었다는
    뜻이다 — 호출자가 잠시 쉬었다가 계속 진행해야 한다(순차 실행을 완전히
    멈추는 대신 나중에 이 job부터 다시 시도한다).
    """

    snapshot_path = Path(job.snapshot_path)
    try:
        run = load_run_snapshot(snapshot_path, expected_content_id=job.content_id)
    except WorkspaceError as exc:
        print(f"오류: snapshot을 읽을 수 없다: {exc}", file=sys.stderr)
        return _end_without_run(job, "config-error", db_path=db_path)

    run_root = snapshot_path.parent
    report = preflight_check(run, repo_root=run_root)
    if not report.ok:
        for problem in report.problems:
            print(f"오류: {problem}", file=sys.stderr)
        return _end_without_run(job, "blocked", db_path=db_path)

    if report.tool_fingerprints != job.tool_fingerprints:
        print(
            "오류: 승인 이후 외부 도구 fingerprint가 변경되었다. estimate부터 다시 실행하라.",
            file=sys.stderr,
        )
        return _end_without_run(job, "blocked", db_path=db_path)

    workdir = Path(job.workdir)
    prompt_path = workdir.parent / "prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    env = build_env(run.injections, base_env=dict(os.environ))
    log_dir = workdir.parent / "logs"

    try:
        outcome = run_once(
            run_id=job.run_id,
            prompt=prompt,
            injections=run.injections,
            cwd=workdir,
            timeout_seconds=job.timeout_seconds,
            log_dir=log_dir,
            env=env,
            isolation=job.isolation,
            repo_root=run_root,
            cancel_event=cancel_event,
            model=job.model,
        )
    except WorkerError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        # 2026-09-29 headroom: proxy 실패 뒤 'running'으로 남아 caveman-full이
        # 한 번도 돌지 못했다.
        return _end_without_run(job, "worker-error", db_path=db_path)

    # 프로세스가 이벤트 하나 남기지 못하고 끝났다면 측정값이 아니라 실행 오류다.
    # `failed`로 기록하면 "과제 테스트 실패"와 구분되지 않고 공개 CSV에까지
    # 빈 행으로 올라간다.
    status = outcome.status
    transcript = Transcript.load(outcome.stdout_path)
    interrupted = transcript.interrupted_reason
    if status == "failed" and interrupted and is_usage_limit_error(interrupted):
        print(
            f"경고: 구독 사용 한도로 보인다 — 다시 큐에 넣고 잠시 후 재시도한다: {interrupted}",
            file=sys.stderr,
        )
        requeue_job(job.run_id, db_path=db_path)
        return "rate-limited"
    if status == "failed" and interrupted:
        print(
            f"오류: 실행이 중간에 끊겼다 — 측정값으로 쓰지 않는다: {interrupted}",
            file=sys.stderr,
        )
        status = "blocked"
    elif status == "failed" and not transcript.has_output:
        stderr_tail = _tail(outcome.stderr_path)
        print(
            f"오류: 모델 출력이 없는 실패 — 실행 환경 문제로 기록한다. {stderr_tail}",
            file=sys.stderr,
        )
        status = "blocked"

    finished = finish_job(
        job.run_id,
        status=status,
        returncode=outcome.returncode,
        finished_at=outcome.finished_at,
        duration_seconds=outcome.duration_seconds,
        stdout_path=outcome.stdout_path,
        stderr_path=outcome.stderr_path,
        command_json=json.dumps(list(outcome.command)),
        db_path=db_path,
    )

    evaluation_report = check_evaluation(workdir)

    result = collect_result(
        finished,
        outcome,
        auth=report.auth or {},
        claude_version=report.claude_version,
        evaluation=evaluation_report,
        transcript=transcript,
    )
    save_result(result, workdir.parent / "result.json")

    # succeeded 실행만 바로 공개 CSV(개요/실행상세/결과검증이 읽는 파일)에
    # 반영한다. failed/blocked(rate limit 등 인프라 문제)까지 자동으로 올리면
    # 지저분한 데이터가 그대로 웹에 노출된다 — 사용자 결정.
    if result.status == "succeeded":
        sync_published(db_path=db_path)

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return result.status
