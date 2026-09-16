"""token_bench CLI 진입점. 인자 파싱과 모듈 호출만 담당한다."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from token_bench.authorization import (
    AuthorizationError,
    approve as approve_plan,
    build_estimate,
    load_approval,
    load_plan,
    save_json,
)
from token_bench.add_condition import append_condition, run_wizard
from token_bench.conditions import ConditionError, needs_customizations, inspect as inspect_conditions
from token_bench.evaluation import check as check_evaluation
from token_bench.job_store import (
    DEFAULT_DB_PATH,
    JobStoreError,
    claim_next_queued,
    enqueue as enqueue_jobs,
    finish_job,
    get_job,
    list_jobs,
)
from token_bench.preflight import check as preflight_check, split_by_availability
from token_bench.collect import (
    DEFAULT_ACTIVITY_PATH,
    DEFAULT_COMPARISON_PATH,
    DEFAULT_SUMMARY_PATH,
    collect as collect_activity,
)
from token_bench.publish import DEFAULT_OUTPUT_PATH as DEFAULT_PUBLISH_OUTPUT_PATH, publish as publish_results
from token_bench.results import interrupted_reason, ResultsError, collect as collect_result, load as load_result, save as save_result
from token_bench.webapi import DEFAULT_HOST, DEFAULT_PORT, serve as serve_webapi
from token_bench.worker import WorkerError, WorkerLockError, build_env, run_once, worker_lock
from token_bench.workspace import (
    DEFAULT_RUNS_ROOT,
    DEFAULT_TASK_PROMPT_PATH,
    PROMPT_PRESETS,
    WorkspaceError,
    load_run_snapshot,
    prepare_batch,
    resolve_prompt_path,
)

DEFAULT_CONDITIONS_PATH = Path("benchmark/conditions.json")


def _add_selection_args(parser: argparse.ArgumentParser) -> None:
    """`--only`/`--exclude`를 추가한다. 실제 필터링은 conditions.select_subset이 한다."""

    parser.add_argument(
        "--only",
        help="이 조건 id들만 실행한다(콤마로 구분, 예: base,be-brief). --exclude와 동시 사용 불가.",
    )
    parser.add_argument(
        "--exclude",
        help="이 조건 id들을 뺀 나머지를 실행한다(콤마로 구분). --only와 동시 사용 불가.",
    )
    parser.add_argument(
        "--skip-unavailable",
        action="store_true",
        help="필요한 도구·플러그인이 없는 조건은 막지 말고 건너뛴다. clone 직후 "
        "설치 없이 돌릴 수 있는 조건만으로 실험할 때 쓴다.",
    )


def _produced_any_output(stdout_path: str | None) -> bool:
    if not stdout_path:
        return False
    path = Path(stdout_path)
    return path.is_file() and path.stat().st_size > 0


def _tail(stderr_path: str | None, limit: int = 300) -> str:
    if not stderr_path or not Path(stderr_path).is_file():
        return ""
    return Path(stderr_path).read_text(encoding="utf-8", errors="replace").strip()[-limit:]


def _drop_unavailable(runs, *, enabled: bool):
    """`--skip-unavailable`이 켜져 있으면 못 돌리는 조건을 빼고 이유를 알린다."""

    if not enabled:
        return runs
    ready, blocked = split_by_availability(runs)
    for run, reasons in blocked:
        hint = f" 설치 안내: {run.repository_url}" if run.repository_url else ""
        print(
            f"건너뜀: {run.condition_id} — {', '.join(reasons)}.{hint}",
            file=sys.stderr,
        )
    return ready


def _split_csv_ids(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m token_bench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="조건 선언을 읽어 정규화된 실행 목록을 출력한다."
    )
    inspect_parser.add_argument(
        "--conditions",
        type=Path,
        default=DEFAULT_CONDITIONS_PATH,
        help=f"조건 선언 JSON 경로 (기본값: {DEFAULT_CONDITIONS_PATH})",
    )
    _add_selection_args(inspect_parser)

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="조건 선언을 실행 목록으로 펼치고 조건별 작업 디렉터리·입력 snapshot을 만든다.",
    )
    prepare_parser.add_argument(
        "--conditions",
        type=Path,
        default=DEFAULT_CONDITIONS_PATH,
        help=f"조건 선언 JSON 경로 (기본값: {DEFAULT_CONDITIONS_PATH})",
    )
    prepare_parser.add_argument(
        "--timeout-seconds", type=int, required=True, help="실행 하나의 timeout(초)"
    )
    prepare_parser.add_argument(
        "--prompt",
        type=Path,
        default=None,
        help=f"과제 프롬프트 파일 경로 (기본값: {DEFAULT_TASK_PROMPT_PATH}). --preset과 동시 사용 불가.",
    )
    prepare_parser.add_argument(
        "--preset",
        choices=sorted(PROMPT_PRESETS),
        default=None,
        help="미리 등록된 프롬프트 프리셋. --prompt와 동시 사용 불가.",
    )
    _add_selection_args(prepare_parser)

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="조건 선언의 각 실행이 구독 환경에서 실행 가능한지 점검한다.",
    )
    preflight_parser.add_argument(
        "--conditions",
        type=Path,
        default=DEFAULT_CONDITIONS_PATH,
        help=f"조건 선언 JSON 경로 (기본값: {DEFAULT_CONDITIONS_PATH})",
    )
    _add_selection_args(preflight_parser)

    estimate_parser = subparsers.add_parser(
        "estimate",
        help="실행 목록을 준비·점검하고 승인 가능한 계획(digest 포함)을 만든다.",
    )
    estimate_parser.add_argument(
        "--conditions",
        type=Path,
        default=DEFAULT_CONDITIONS_PATH,
        help=f"조건 선언 JSON 경로 (기본값: {DEFAULT_CONDITIONS_PATH})",
    )
    estimate_parser.add_argument(
        "--timeout-seconds", type=int, required=True, help="실행 하나의 timeout(초)"
    )
    estimate_parser.add_argument(
        "--prompt",
        type=Path,
        default=None,
        help=f"과제 프롬프트 파일 경로 (기본값: {DEFAULT_TASK_PROMPT_PATH}). --preset과 동시 사용 불가.",
    )
    estimate_parser.add_argument(
        "--preset",
        choices=sorted(PROMPT_PRESETS),
        default=None,
        help="미리 등록된 프롬프트 프리셋. --prompt와 동시 사용 불가.",
    )
    _add_selection_args(estimate_parser)

    approve_parser = subparsers.add_parser(
        "approve", help="estimate가 만든 계획의 digest를 확인하고 승인 기록을 만든다."
    )
    approve_parser.add_argument(
        "--plan", type=Path, required=True, help="estimate가 만든 plan.json 경로"
    )
    approve_parser.add_argument(
        "--confirm", required=True, help="plan.json에 표시된 digest와 정확히 일치해야 한다"
    )

    enqueue_parser = subparsers.add_parser(
        "enqueue", help="승인된 계획을 SQLite 작업 큐에 등록한다."
    )
    enqueue_parser.add_argument(
        "--plan", type=Path, required=True, help="estimate가 만든 plan.json 경로"
    )
    enqueue_parser.add_argument(
        "--approval", type=Path, required=True, help="approve가 만든 approval.json 경로"
    )
    enqueue_parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help=f"작업 상태 DB 경로 (기본값: {DEFAULT_DB_PATH})"
    )

    status_parser = subparsers.add_parser("status", help="등록된 작업 목록을 조회한다.")
    status_parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help=f"작업 상태 DB 경로 (기본값: {DEFAULT_DB_PATH})"
    )

    work_parser = subparsers.add_parser(
        "work", help="큐에서 작업 하나를 선점해 Claude Code 프로세스를 실행한다."
    )
    work_parser.add_argument(
        "--once",
        action="store_true",
        help="작업 하나만 처리하고 종료한다. 지정하지 않으면 상주 worker로 큐를 끝까지 순차 처리한다.",
    )
    work_parser.add_argument(
        "--conditions",
        type=Path,
        default=DEFAULT_CONDITIONS_PATH,
        help=f"조건 선언 JSON 경로 (기본값: {DEFAULT_CONDITIONS_PATH})",
    )
    work_parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help=f"작업 상태 DB 경로 (기본값: {DEFAULT_DB_PATH})"
    )
    work_parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=5.0,
        help="큐가 비었을 때 다시 확인할 때까지 대기하는 시간(초). 상주 모드에서만 쓰인다.",
    )
    work_parser.add_argument(
        "--exit-when-empty",
        action="store_true",
        help="큐가 비면 대기하지 않고 종료한다(상주 모드를 유한 실행으로 검증할 때 사용).",
    )

    result_parser = subparsers.add_parser(
        "result", help="특정 실행의 정규화된 RunResult를 조회한다."
    )
    result_parser.add_argument("--run-id", required=True, help="조회할 run_id")
    result_parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help=f"작업 상태 DB 경로 (기본값: {DEFAULT_DB_PATH})"
    )

    publish_parser = subparsers.add_parser(
        "publish",
        help="완료된(succeeded/failed) 실행 결과를 공개 CSV에 append한다.",
    )
    publish_parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help=f"작업 상태 DB 경로 (기본값: {DEFAULT_DB_PATH})"
    )
    publish_parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_PUBLISH_OUTPUT_PATH,
        help=f"공개 CSV 경로 (기본값: {DEFAULT_PUBLISH_OUTPUT_PATH})",
    )

    collect_parser = subparsers.add_parser(
        "collect",
        help="완료된 실행을 턴 단위로 data/activity-log.csv, data/run-summary.csv에 append한다.",
    )
    collect_parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help=f"작업 상태 DB 경로 (기본값: {DEFAULT_DB_PATH})"
    )
    collect_parser.add_argument(
        "--activity-out",
        type=Path,
        default=DEFAULT_ACTIVITY_PATH,
        help=f"턴 단위 CSV 경로 (기본값: {DEFAULT_ACTIVITY_PATH})",
    )
    collect_parser.add_argument(
        "--summary-out",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help=f"실행 단위 CSV 경로 (기본값: {DEFAULT_SUMMARY_PATH})",
    )
    collect_parser.add_argument(
        "--comparison-out",
        type=Path,
        default=DEFAULT_COMPARISON_PATH,
        help=f"조건 비교 CSV 경로 (기본값: {DEFAULT_COMPARISON_PATH})",
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="조건 선택·승인·등록을 위한 로컬 전용 HTTP API를 띄운다.",
    )
    serve_parser.add_argument(
        "--conditions",
        type=Path,
        default=DEFAULT_CONDITIONS_PATH,
        help=f"조건 선언 JSON 경로 (기본값: {DEFAULT_CONDITIONS_PATH})",
    )
    serve_parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help=f"작업 상태 DB 경로 (기본값: {DEFAULT_DB_PATH})"
    )
    serve_parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"바인딩할 host (기본값: {DEFAULT_HOST})"
    )
    serve_parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"바인딩할 port (기본값: {DEFAULT_PORT})"
    )

    add_condition_parser = subparsers.add_parser(
        "add-condition",
        help="질문에 답하면서 새 절약법을 conditions.json에 추가한다.",
    )
    add_condition_parser.add_argument(
        "--conditions",
        type=Path,
        default=DEFAULT_CONDITIONS_PATH,
        help=f"조건 선언 JSON 경로 (기본값: {DEFAULT_CONDITIONS_PATH})",
    )

    return parser


def _run_inspect(
    conditions_path: Path,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    skip_unavailable: bool = False,
) -> int:
    try:
        runs = inspect_conditions(conditions_path, include=include, exclude=exclude)
    except ConditionError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    runs = _drop_unavailable(runs, enabled=skip_unavailable)
    if not runs:
        print("오류: 실행할 수 있는 조건이 없다.", file=sys.stderr)
        return 1

    print(json.dumps([run.to_dict() for run in runs], ensure_ascii=False, indent=2))
    return 0


def _run_prepare(
    conditions_path: Path,
    *,
    timeout_seconds: int,
    task_prompt_path: Path = DEFAULT_TASK_PROMPT_PATH,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    skip_unavailable: bool = False,
) -> int:
    try:
        runs = inspect_conditions(conditions_path, include=include, exclude=exclude)
    except ConditionError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    runs = _drop_unavailable(runs, enabled=skip_unavailable)
    if not runs:
        print("오류: 실행할 수 있는 조건이 없다.", file=sys.stderr)
        return 1

    try:
        workspaces = prepare_batch(
            runs,
            timeout_seconds=timeout_seconds,
            task_prompt_path=task_prompt_path,
        )
    except WorkspaceError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            [
                {
                    "run_id": ws.run_id,
                    "content_id": ws.content_id,
                    "condition_id": ws.condition_id,
                    "repeat_index": ws.repeat_index,
                    "workdir": str(ws.workdir),
                    "snapshot_path": str(ws.snapshot_path),
                }
                for ws in workspaces
            ],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _run_preflight(
    conditions_path: Path,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    skip_unavailable: bool = False,
) -> int:
    try:
        runs = inspect_conditions(conditions_path, include=include, exclude=exclude)
    except ConditionError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    runs = _drop_unavailable(runs, enabled=skip_unavailable)
    if not runs:
        print("오류: 실행할 수 있는 조건이 없다.", file=sys.stderr)
        return 1

    results = []
    all_ok = True
    for run in runs:
        report = preflight_check(run)
        all_ok = all_ok and report.ok
        results.append(
            {
                "condition_id": run.condition_id,
                "repeat_index": run.repeat_index,
                **report.to_dict(),
            }
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


def _run_estimate(
    conditions_path: Path,
    *,
    timeout_seconds: int,
    task_prompt_path: Path = DEFAULT_TASK_PROMPT_PATH,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    skip_unavailable: bool = False,
) -> int:
    try:
        runs = inspect_conditions(conditions_path, include=include, exclude=exclude)
    except ConditionError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    runs = _drop_unavailable(runs, enabled=skip_unavailable)
    if not runs:
        print("오류: 실행할 수 있는 조건이 없다.", file=sys.stderr)
        return 1

    try:
        workspaces = prepare_batch(
            runs,
            timeout_seconds=timeout_seconds,
            task_prompt_path=task_prompt_path,
        )
    except WorkspaceError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    reports = [preflight_check(run) for run in runs]
    if not all(report.ok for report in reports):
        for run, report in zip(runs, reports):
            for problem in report.problems:
                print(
                    f"오류: [{run.condition_id}__r{run.repeat_index}] {problem}",
                    file=sys.stderr,
                )
        return 1

    auth = next((report.auth for report in reports if report.auth), {})
    batch_id = workspaces[0].run_id.split("-", 1)[0]
    # hook·plugin을 켜는 조건이 하나라도 있으면 배치 전체가 같은 격리 모드로
    # 돈다. 조건마다 격리가 다르면 처치 말고도 달라지는 것이 생긴다.
    isolation = (
        "project-settings"
        if any(needs_customizations(run.injections) for run in runs)
        else "safe-mode"
    )
    plan = build_estimate(
        workspaces,
        batch_id=batch_id,
        timeout_seconds=timeout_seconds,
        auth=auth,
        isolation=isolation,
        tool_fingerprints={
            workspace.run_id: report.tool_fingerprints
            for workspace, report in zip(workspaces, reports)
        },
    )

    plan_path = DEFAULT_RUNS_ROOT / batch_id / "plan.json"
    save_json(plan.to_dict(), plan_path)

    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    print(
        f"\n승인하려면 위 digest를 확인한 뒤 다음을 실행하라:\n"
        f"  python3 -m token_bench approve --plan {plan_path} --confirm {plan.digest}",
        file=sys.stderr,
    )
    return 0


def _run_approve(plan_path: Path, *, confirmed_digest: str) -> int:
    try:
        plan = load_plan(plan_path)
        record = approve_plan(plan, confirmed_digest=confirmed_digest)
    except AuthorizationError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    approval_path = plan_path.parent / "approval.json"
    save_json(record.to_dict(), approval_path)
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _run_enqueue(plan_path: Path, approval_path: Path, *, db_path: Path) -> int:
    try:
        plan = load_plan(plan_path)
        approval = load_approval(approval_path)
        jobs = enqueue_jobs(plan, approval, db_path=db_path)
    except (AuthorizationError, JobStoreError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(json.dumps([job.to_dict() for job in jobs], ensure_ascii=False, indent=2))
    return 0


def _run_status(db_path: Path) -> int:
    jobs = list_jobs(db_path=db_path)
    print(json.dumps([job.to_dict() for job in jobs], ensure_ascii=False, indent=2))
    return 0


def _process_claimed_job(job, conditions_path: Path, *, db_path: Path) -> str:
    """선점된 작업 하나를 preflight 재확인부터 결과 저장까지 처리한다.

    반환값은 job_store/worker/results가 인식하는 상태 문자열이다:
    'succeeded'·'failed'는 측정된 결과(계속 진행 가능), 'blocked'·
    'config-error'·'worker-error'는 인프라·승인 문제(순차 실행을 멈춰야 함)다.
    """

    snapshot_path = Path(job.snapshot_path)
    try:
        run = load_run_snapshot(snapshot_path, expected_content_id=job.content_id)
    except WorkspaceError as exc:
        print(f"오류: snapshot을 읽을 수 없다: {exc}", file=sys.stderr)
        return "config-error"

    run_root = snapshot_path.parent
    report = preflight_check(run, repo_root=run_root)
    if not report.ok:
        for problem in report.problems:
            print(f"오류: {problem}", file=sys.stderr)
        finish_job(
            job.run_id,
            status="blocked",
            returncode=None,
            finished_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=0.0,
            stdout_path="",
            stderr_path="",
            command_json="[]",
            db_path=db_path,
        )
        return "blocked"

    if report.tool_fingerprints != job.tool_fingerprints:
        print(
            "오류: 승인 이후 외부 도구 fingerprint가 변경되었다. estimate부터 다시 실행하라.",
            file=sys.stderr,
        )
        finish_job(
            job.run_id,
            status="blocked",
            returncode=None,
            finished_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=0.0,
            stdout_path="",
            stderr_path="",
            command_json="[]",
            db_path=db_path,
        )
        return "blocked"

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
        )
    except WorkerError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return "worker-error"

    # 프로세스가 이벤트 하나 남기지 못하고 끝났다면 측정값이 아니라 실행 오류다.
    # `failed`로 기록하면 "과제 테스트 실패"와 구분되지 않고 공개 CSV에까지
    # 빈 행으로 올라간다.
    status = outcome.status
    interrupted = interrupted_reason(outcome.stdout_path)
    if status == "failed" and interrupted:
        print(
            f"오류: 실행이 중간에 끊겼다 — 측정값으로 쓰지 않는다: {interrupted}",
            file=sys.stderr,
        )
        status = "blocked"
    elif status == "failed" and not _produced_any_output(outcome.stdout_path):
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
    )
    save_result(result, workdir.parent / "result.json")

    # succeeded 실행만 바로 공개 CSV(개요/실행상세/결과검증이 읽는 파일)에
    # 반영한다. failed/blocked(rate limit 등 인프라 문제)까지 자동으로 올리면
    # 지저분한 데이터가 그대로 웹에 노출된다 — 사용자 결정.
    if result.status == "succeeded":
        collect_activity(db_path=db_path)
        publish_results(db_path=db_path)

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return result.status


def _run_work_once(conditions_path: Path, *, db_path: Path) -> int:
    job = claim_next_queued(db_path=db_path)
    if job is None:
        print("대기 중인 작업이 없다.", file=sys.stderr)
        return 0

    status = _process_claimed_job(job, conditions_path, db_path=db_path)
    return 0 if status == "succeeded" else 1


def _run_work_loop(
    conditions_path: Path,
    *,
    db_path: Path,
    poll_interval_seconds: float,
    exit_when_empty: bool,
) -> int:
    """큐가 비면 대기하며 선언된 조건·repeat을 순서대로 끝까지 처리한다.

    인증·preflight 실패나 timeout처럼 결과가 불명확한 상태에서는 자동
    재시도 없이 남은 작업 처리를 멈춘다. 과제 테스트 실패('failed')는
    측정된 결과이므로 다음 작업으로 계속 진행한다.
    """

    try:
        with worker_lock(db_path):
            while True:
                job = claim_next_queued(db_path=db_path)
                if job is None:
                    if exit_when_empty:
                        print("대기 중인 작업이 없다. 종료한다.", file=sys.stderr)
                        return 0
                    time.sleep(poll_interval_seconds)
                    continue

                status = _process_claimed_job(job, conditions_path, db_path=db_path)
                if status not in ("succeeded", "failed"):
                    print(
                        f"인프라·승인 문제로 남은 작업 처리를 멈춘다 "
                        f"(run_id={job.run_id}, status={status}).",
                        file=sys.stderr,
                    )
                    return 1
    except WorkerLockError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


def _run_result(run_id: str, *, db_path: Path) -> int:
    job = get_job(run_id, db_path=db_path)
    if job is None:
        print(f"오류: 작업을 찾을 수 없다: {run_id}", file=sys.stderr)
        return 1

    result_path = Path(job.workdir).parent / "result.json"
    try:
        result = load_result(result_path)
    except ResultsError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _run_publish(*, db_path: Path, output_path: Path) -> int:
    new_rows = publish_results(db_path=db_path, output_path=output_path)
    print(
        json.dumps(
            {"published_count": len(new_rows), "output_path": str(output_path)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _run_collect(*, db_path: Path, activity_path: Path, summary_path: Path, comparison_path: Path) -> int:
    stats = collect_activity(
        db_path=db_path, activity_path=activity_path, summary_path=summary_path,
        comparison_path=comparison_path,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def _run_serve(*, host: str, port: int, conditions_path: Path, db_path: Path) -> int:
    server = serve_webapi(
        host=host, port=port, conditions_path=conditions_path, db_path=db_path
    )
    print(f"http://{host}:{port} 에서 대기 중 (Ctrl+C로 종료)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


def _run_add_condition(conditions_path: Path) -> int:
    condition = run_wizard()
    try:
        append_condition(conditions_path, condition)
    except ConditionError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        print("아무것도 쓰지 않았다. 다시 시도하라.", file=sys.stderr)
        return 1
    print(f"'{condition['id']}' 추가함 -> {conditions_path}")
    print(f"확인: python3 -m token_bench inspect --only {condition['id']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows는 파이프로 리다이렉트된 stdout/stderr에 로케일 기본 코드페이지
    # (흔히 cp1252)를 쓴다 — 한국어 메시지가 깨지거나 인코딩 에러가 난다.
    # reconfigure가 없는 스트림(테스트의 io.StringIO 등)에서는 조용히 넘어간다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "inspect":
        return _run_inspect(
            args.conditions,
            include=_split_csv_ids(args.only),
            exclude=_split_csv_ids(args.exclude),
            skip_unavailable=args.skip_unavailable,
        )
    if args.command == "prepare":
        try:
            task_prompt_path = resolve_prompt_path(preset=args.preset, prompt_path=args.prompt)
        except WorkspaceError as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        return _run_prepare(
            args.conditions,
            timeout_seconds=args.timeout_seconds,
            task_prompt_path=task_prompt_path,
            include=_split_csv_ids(args.only),
            exclude=_split_csv_ids(args.exclude),
            skip_unavailable=args.skip_unavailable,
        )
    if args.command == "preflight":
        return _run_preflight(
            args.conditions,
            include=_split_csv_ids(args.only),
            exclude=_split_csv_ids(args.exclude),
            skip_unavailable=args.skip_unavailable,
        )
    if args.command == "estimate":
        try:
            task_prompt_path = resolve_prompt_path(preset=args.preset, prompt_path=args.prompt)
        except WorkspaceError as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        return _run_estimate(
            args.conditions,
            timeout_seconds=args.timeout_seconds,
            task_prompt_path=task_prompt_path,
            include=_split_csv_ids(args.only),
            exclude=_split_csv_ids(args.exclude),
            skip_unavailable=args.skip_unavailable,
        )
    if args.command == "approve":
        return _run_approve(args.plan, confirmed_digest=args.confirm)
    if args.command == "enqueue":
        return _run_enqueue(args.plan, args.approval, db_path=args.db)
    if args.command == "status":
        return _run_status(args.db)
    if args.command == "work":
        if args.once:
            return _run_work_once(args.conditions, db_path=args.db)
        return _run_work_loop(
            args.conditions,
            db_path=args.db,
            poll_interval_seconds=args.poll_interval_seconds,
            exit_when_empty=args.exit_when_empty,
        )
    if args.command == "result":
        return _run_result(args.run_id, db_path=args.db)
    if args.command == "publish":
        return _run_publish(db_path=args.db, output_path=args.out)
    if args.command == "collect":
        return _run_collect(
            db_path=args.db, activity_path=args.activity_out, summary_path=args.summary_out,
            comparison_path=args.comparison_out,
        )
    if args.command == "serve":
        return _run_serve(
            host=args.host, port=args.port, conditions_path=args.conditions, db_path=args.db
        )
    if args.command == "add-condition":
        return _run_add_condition(args.conditions)

    parser.error(f"알 수 없는 명령: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
