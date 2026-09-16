"""로컬 전용 HTTP API. CLI와 같은 token_bench 함수를 호출하는 얇은 어댑터다.

이 모듈은 HTTP 요청·응답 변환만 담당한다. 조건 해석·준비·승인·큐 등록
로직은 소유하지 않고 기존 모듈(conditions/workspace/authorization/job_store)을
그대로 호출한다 — 같은 개념을 처리하는 코드가 두 곳에 생기지 않게 한다.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from token_bench.add_condition import append_condition
from token_bench.authorization import (
    AuthorizationError,
    approve as approve_plan,
    build_estimate,
    load_approval,
    load_plan,
    save_json,
)
from token_bench.conditions import ConditionError, expand_runs, needs_customizations, inspect as inspect_conditions, load_conditions
from token_bench.job_store import (
    DEFAULT_DB_PATH,
    JobStoreError,
    enqueue as enqueue_jobs,
    get_job,
    list_jobs,
)
from token_bench.log_tail import tail as tail_log
from token_bench.preflight import check as preflight_check, unavailable_reasons
from token_bench.workspace import (
    DEFAULT_RUNS_ROOT,
    WorkspaceError,
    prepare_batch,
    resolve_prompt_path,
)

DEFAULT_CONDITIONS_PATH = Path("benchmark/conditions.json")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


class ApiError(Exception):
    """요청 처리 실패. HTTP 상태 코드와 함께 그대로 응답에 반영된다."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _conditions_summary(conditions_path: Path) -> list[dict]:
    try:
        conditions = load_conditions(conditions_path)
    except ConditionError as exc:
        raise ApiError(400, str(exc)) from exc

    # 조건마다 "지금 이 컴퓨터에서 돌릴 수 있는가"와 그렇지 않은 이유를 함께
    # 준다. 웹은 그걸로 체크박스를 끄고 설치 안내를 보여 준다.
    runs_by_id = {r.condition_id: r for r in expand_runs(conditions)}

    return [
        {
            "id": c.id,
            "repeat": c.repeat,
            "requires_tools": list(c.requires_tools),
            "repository_url": c.repository_url,
            "tool_probes": {name: list(args) for name, args in c.tool_probes},
            "unavailable_reasons": unavailable_reasons(runs_by_id[c.id]),
            "injections": [
                {
                    k: (list(v) if isinstance(v, tuple) else v)
                    for k, v in vars(i).items()
                    if v is not None
                }
                for i in c.injections
            ],
        }
        for c in conditions
    ]


def _handle_estimate(body: dict, *, conditions_path: Path) -> dict:
    include = body.get("include")
    exclude = body.get("exclude")
    timeout_seconds = body.get("timeout_seconds")
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
        raise ApiError(400, "timeout_seconds는 정수여야 한다.")

    preset = body.get("preset")
    raw_prompt_path = Path(body["prompt_path"]) if body.get("prompt_path") else None
    try:
        prompt_path = resolve_prompt_path(preset=preset, prompt_path=raw_prompt_path)
    except WorkspaceError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        runs = inspect_conditions(conditions_path, include=include, exclude=exclude)
    except ConditionError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        workspaces = prepare_batch(
            runs,
            timeout_seconds=timeout_seconds,
            task_prompt_path=prompt_path,
        )
    except WorkspaceError as exc:
        raise ApiError(400, str(exc)) from exc

    reports = [preflight_check(run) for run in runs]
    if not all(r.ok for r in reports):
        problems = [p for r in reports for p in r.problems]
        raise ApiError(400, "preflight 실패: " + "; ".join(problems))

    auth = next((r.auth for r in reports if r.auth), {})
    batch_id = workspaces[0].run_id.split("-", 1)[0]
    # CLI의 estimate와 같은 규칙으로 배치 격리 모드를 정한다.
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

    return {"plan": plan.to_dict(), "plan_path": str(plan_path)}


def _handle_approve(body: dict) -> dict:
    plan_path = body.get("plan_path")
    confirm_digest = body.get("confirm_digest")
    if not plan_path or not confirm_digest:
        raise ApiError(400, "plan_path와 confirm_digest가 필요하다.")

    try:
        plan = load_plan(Path(plan_path))
        record = approve_plan(plan, confirmed_digest=confirm_digest)
    except AuthorizationError as exc:
        raise ApiError(400, str(exc)) from exc

    approval_path = Path(plan_path).parent / "approval.json"
    save_json(record.to_dict(), approval_path)
    return {"approval": record.to_dict(), "approval_path": str(approval_path)}


def _handle_enqueue(body: dict, *, db_path: Path) -> dict:
    plan_path = body.get("plan_path")
    approval_path = body.get("approval_path")
    if not plan_path or not approval_path:
        raise ApiError(400, "plan_path와 approval_path가 필요하다.")

    try:
        plan = load_plan(Path(plan_path))
        approval = load_approval(Path(approval_path))
        jobs = enqueue_jobs(plan, approval, db_path=db_path)
    except (AuthorizationError, JobStoreError) as exc:
        raise ApiError(400, str(exc)) from exc

    return {"jobs": [j.to_dict() for j in jobs]}


def _handle_add_condition(body: dict, *, conditions_path: Path) -> dict:
    """조건 하나를 추가한다. CLI `add-condition` 마법사와 같은 검증기를 쓴다.

    `injections`의 `prompt_overlay` 항목에 `text`가 딸려 있고 `path`가 아직
    없는 파일이면 그 내용으로 파일을 먼저 만든다 — CLI 마법사의 "파일이
    없으면 새로 만든다" 동작과 같다. `text`는 조건 스키마에 없는 키라 검증
    전에 떼어낸다.
    """

    condition = dict(body)
    injections = []
    for raw_injection in condition.get("injections", []):
        injection = dict(raw_injection)
        text = injection.pop("text", None)
        if injection.get("type") == "prompt_overlay" and text:
            path = injection.get("path")
            if not isinstance(path, str) or not path:
                raise ApiError(400, "prompt_overlay 주입에는 path가 필요하다.")
            posix = Path(path)
            if posix.is_absolute() or ".." in posix.parts:
                raise ApiError(400, f"path는 저장소 내부 상대경로여야 한다: {path}")
            if not posix.is_file():
                posix.parent.mkdir(parents=True, exist_ok=True)
                posix.write_text(text.strip() + "\n", encoding="utf-8")
        injections.append(injection)
    condition["injections"] = injections

    try:
        append_condition(conditions_path, condition)
    except ConditionError as exc:
        raise ApiError(400, str(exc)) from exc
    return {"condition": condition}


def _handle_log(query: dict[str, list[str]], *, db_path: Path) -> dict:
    run_id = (query.get("run_id") or [None])[0]
    if not run_id:
        raise ApiError(400, "run_id가 필요하다.")

    job = get_job(run_id, db_path=db_path)
    if job is None:
        raise ApiError(404, f"작업을 찾을 수 없다: {run_id}")

    log_path = Path(job.stdout_path) if job.stdout_path else Path(job.workdir).parent / "logs" / "stdout.jsonl"
    return {"run_id": run_id, "status": job.status, "events": tail_log(log_path, limit=20)}


def make_handler(
    *, conditions_path: Path, db_path: Path
) -> type[BaseHTTPRequestHandler]:
    """요청마다 conditions_path/db_path를 참조하는 핸들러 클래스를 만든다."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "token-bench/1.0"

        def _send_cors_headers(self) -> None:
            # web/run.html은 정적 파일 서버(예: :8765)에서 열리고 이 API는
            # 다른 포트(:8787)에서 뜬다 — 브라우저 기준 서로 다른 출처라
            # CORS 헤더 없이는 fetch가 막힌다. 둘 다 로컬 전용 도구이므로
            # 출처를 반사(echo)해 허용한다.
            origin = self.headers.get("Origin", "*")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            # POST + Content-Type: application/json은 브라우저가 CORS
            # preflight(OPTIONS)를 먼저 보낸다. 본문 없이 허용만 응답한다.
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ApiError(400, f"요청 본문이 JSON이 아니다: {exc}") from exc

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler가 요구하는 이름
            try:
                parsed = urlsplit(self.path)
                if parsed.path == "/api/conditions":
                    self._send_json(
                        200, {"conditions": _conditions_summary(conditions_path)}
                    )
                elif parsed.path == "/api/status":
                    self._send_json(
                        200,
                        {"jobs": [j.to_dict() for j in list_jobs(db_path=db_path)]},
                    )
                elif parsed.path == "/api/log":
                    self._send_json(
                        200, _handle_log(parse_qs(parsed.query), db_path=db_path)
                    )
                else:
                    self._send_json(404, {"error": "not found"})
            except ApiError as exc:
                self._send_json(exc.status, {"error": exc.message})

        def do_POST(self) -> None:  # noqa: N802
            try:
                body = self._read_json_body()
                if self.path == "/api/estimate":
                    self._send_json(
                        200, _handle_estimate(body, conditions_path=conditions_path)
                    )
                elif self.path == "/api/approve":
                    self._send_json(200, _handle_approve(body))
                elif self.path == "/api/enqueue":
                    self._send_json(200, _handle_enqueue(body, db_path=db_path))
                elif self.path == "/api/add-condition":
                    self._send_json(
                        200,
                        _handle_add_condition(body, conditions_path=conditions_path),
                    )
                else:
                    self._send_json(404, {"error": "not found"})
            except ApiError as exc:
                self._send_json(exc.status, {"error": exc.message})

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass  # 조용히 둔다 — 필요하면 표준 로거로 바꾼다.

    return Handler


def serve(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    conditions_path: Path = DEFAULT_CONDITIONS_PATH,
    db_path: Path = DEFAULT_DB_PATH,
) -> ThreadingHTTPServer:
    """서버 인스턴스를 만들어 반환한다. 시작(`serve_forever`)은 호출자가 한다."""

    handler = make_handler(conditions_path=conditions_path, db_path=db_path)
    return ThreadingHTTPServer((host, port), handler)
