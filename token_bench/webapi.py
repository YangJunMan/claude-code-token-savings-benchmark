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
    approve_plan_file,
    load_approval,
    load_plan,
)
from token_bench.conditions import (
    DEFAULT_CONDITIONS_PATH,
    ConditionError,
    expand_runs,
    is_repo_relative,
    load_conditions,
)
from token_bench.intake import IntakeError, create_plan
from token_bench.job_store import (
    DEFAULT_DB_PATH,
    JobStoreError,
    delete_job,
    enqueue as enqueue_jobs,
    get_job,
    list_jobs,
    retry_job,
)
from token_bench.queue_runner import QueueRunner as AutoWorker
from token_bench.log_tail import tail as tail_log
from token_bench.preflight import unavailable_reasons
from token_bench.workspace import (
    DEFAULT_RUNS_ROOT,
    PRESET_DESCRIPTIONS,
    PROMPT_PRESETS,
    WorkspaceError,
    resolve_prompt_path,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
# 요청 본문 상한. 조건 하나·계획 경로 정도라 수 KB면 충분하다.
MAX_BODY_BYTES = 1_000_000


def _runs_file(raw: object, *, field: str) -> Path:
    """요청으로 받은 계획·승인 파일 경로가 실행 디렉터리(.token-bench/runs) 안인지 확인한다.

    이 경로로 파일을 읽고(승인 시) 그 옆에 approval.json을 쓰므로, 아무 경로나
    받으면 저장소 밖 파일을 읽거나 엉뚱한 곳에 파일을 만들 수 있다.
    """

    if not isinstance(raw, str) or not raw:
        raise ApiError(400, f"{field}가 필요하다.")
    path = Path(raw)
    root = DEFAULT_RUNS_ROOT.resolve()
    if not path.resolve().is_relative_to(root):
        raise ApiError(400, f"{field}는 {DEFAULT_RUNS_ROOT} 안의 파일이어야 한다: {raw}")
    return path


class ApiError(Exception):
    """요청 처리 실패. HTTP 상태 코드와 함께 그대로 응답에 반영된다."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _presets_summary() -> list[dict]:
    """웹의 과제 선택 목록. 프리셋 이름과 설명은 workspace.py 한 곳에서만 정한다."""

    return [{"id": name, "description": PRESET_DESCRIPTIONS.get(name, "")} for name in PROMPT_PRESETS]


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
            "label": c.label,
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
    raw_prompt = body.get("prompt_path")
    if raw_prompt and (not isinstance(raw_prompt, str) or not is_repo_relative(raw_prompt)):
        raise ApiError(400, f"prompt_path는 저장소 내부 상대경로여야 한다: {raw_prompt}")
    raw_prompt_path = Path(raw_prompt) if raw_prompt else None
    try:
        prompt_path = resolve_prompt_path(preset=preset, prompt_path=raw_prompt_path)
    except WorkspaceError as exc:
        raise ApiError(400, str(exc)) from exc

    model = body.get("model", "")
    if not isinstance(model, str):
        raise ApiError(400, "model은 문자열이어야 한다.")
    try:
        prepared = create_plan(
            conditions_path, timeout_seconds=timeout_seconds,
            task_prompt_path=prompt_path, include=include, exclude=exclude, model=model,
        )
    except IntakeError as exc:
        raise ApiError(400, str(exc)) from exc
    return {"plan": prepared.plan.to_dict(), "plan_path": str(prepared.plan_path)}


def _handle_approve(body: dict) -> dict:
    confirm_digest = body.get("confirm_digest")
    if not body.get("plan_path") or not confirm_digest:
        raise ApiError(400, "plan_path와 confirm_digest가 필요하다.")
    plan_path = _runs_file(body.get("plan_path"), field="plan_path")

    try:
        record, approval_path = approve_plan_file(plan_path, confirmed_digest=confirm_digest)
    except AuthorizationError as exc:
        raise ApiError(400, str(exc)) from exc

    return {"approval": record.to_dict(), "approval_path": str(approval_path)}


def _handle_enqueue(body: dict, *, db_path: Path) -> dict:
    if not body.get("plan_path") or not body.get("approval_path"):
        raise ApiError(400, "plan_path와 approval_path가 필요하다.")
    plan_path = _runs_file(body.get("plan_path"), field="plan_path")
    approval_path = _runs_file(body.get("approval_path"), field="approval_path")

    try:
        plan = load_plan(plan_path)
        approval = load_approval(approval_path)
        jobs = enqueue_jobs(plan, approval, db_path=db_path)
    except (AuthorizationError, JobStoreError) as exc:
        raise ApiError(400, str(exc)) from exc

    return {"jobs": [j.to_dict() for j in jobs]}


def _handle_retry(body: dict, *, db_path: Path) -> dict:
    run_id = body.get("run_id")
    if not run_id:
        raise ApiError(400, "run_id가 필요하다.")

    try:
        job = retry_job(run_id, db_path=db_path)
    except JobStoreError as exc:
        raise ApiError(400, str(exc)) from exc

    return {"job": job.to_dict()}


def _handle_delete(body: dict, *, db_path: Path) -> dict:
    run_id = body.get("run_id")
    if not run_id:
        raise ApiError(400, "run_id가 필요하다.")

    try:
        delete_job(run_id, db_path=db_path)
    except JobStoreError as exc:
        raise ApiError(400, str(exc)) from exc

    return {"deleted": run_id}


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
            if not is_repo_relative(path):
                raise ApiError(400, f"path는 저장소 내부 상대경로여야 한다: {path}")
            target = Path(path)
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text.strip() + "\n", encoding="utf-8")
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


LOCAL_ORIGIN_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})


def _is_local_origin(origin: str) -> bool:
    """브라우저가 보낸 Origin이 이 컴퓨터의 로컬 주소인지 본다."""

    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https"):
        return False
    return (parts.hostname or "") in LOCAL_ORIGIN_HOSTS


def _is_local_host(host: str | None) -> bool:
    """Host 헤더가 로컬 주소인가. DNS rebinding(외부 도메인이 127.0.0.1로 풀리게
    해서 이 API를 같은 출처처럼 부르는 공격)을 막는다."""

    if not host:
        return False
    return (urlsplit(f"//{host}").hostname or "") in LOCAL_ORIGIN_HOSTS


def _reject_foreign_request(headers, *, method: str) -> None:
    """다른 사이트에서 온 요청을 거부한다.

    CORS 헤더는 응답을 읽지 못하게 할 뿐, 요청 자체는 막지 않는다. 브라우저는
    `Content-Type: text/plain` POST를 preflight 없이 보내므로, 사용자가 열어 둔
    아무 웹페이지가 실험 등록·삭제·파일 쓰기를 실행할 수 있었다. Host·Origin을
    확인하고 POST는 JSON만 받는다(JSON POST는 브라우저가 반드시 preflight를 거친다).
    """

    if not _is_local_host(headers.get("Host")):
        raise ApiError(403, "로컬 주소로만 접근할 수 있다.")
    origin = headers.get("Origin")
    if origin and not _is_local_origin(origin):
        raise ApiError(403, "다른 출처의 요청은 받지 않는다.")
    if method == "POST":
        content_type = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(415, "POST 본문은 application/json이어야 한다.")


def make_handler(
    *, conditions_path: Path, db_path: Path, auto_worker: AutoWorker
) -> type[BaseHTTPRequestHandler]:
    """요청마다 conditions_path/db_path를 참조하는 핸들러 클래스를 만든다."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "token-bench/1.0"

        def _send_cors_headers(self) -> None:
            # web/run.html은 정적 파일 서버(예: :8765)에서 열리고 이 API는
            # 다른 포트(:8787)에서 뜬다 — 브라우저 기준 서로 다른 출처라
            # CORS 헤더 없이는 fetch가 막힌다. 로컬 출처만 허용한다: 이 API는
            # 인증이 없고 실행 시작·작업 삭제·파일 쓰기를 모두 받으므로, 출처를
            # 그대로 반사하면 사용자가 열어 둔 아무 웹페이지나 서버가 켜져 있는
            # 동안 이 엔드포인트를 호출할 수 있다.
            origin = self.headers.get("Origin")
            if origin and _is_local_origin(origin):
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
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError as exc:
                raise ApiError(400, "Content-Length가 올바르지 않다.") from exc
            if length < 0 or length > MAX_BODY_BYTES:
                raise ApiError(413, f"요청 본문은 {MAX_BODY_BYTES}바이트 이하여야 한다.")
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ApiError(400, f"요청 본문이 JSON이 아니다: {exc}") from exc
            if not isinstance(body, dict):
                raise ApiError(400, "요청 본문은 JSON 객체여야 한다.")
            return body

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler가 요구하는 이름
            try:
                _reject_foreign_request(self.headers, method="GET")
                parsed = urlsplit(self.path)
                if parsed.path == "/api/conditions":
                    self._send_json(
                        200,
                        {
                            "conditions": _conditions_summary(conditions_path),
                            "presets": _presets_summary(),
                        },
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
                _reject_foreign_request(self.headers, method="POST")
                body = self._read_json_body()
                path = urlsplit(self.path).path
                if path == "/api/estimate":
                    self._send_json(
                        200, _handle_estimate(body, conditions_path=conditions_path)
                    )
                elif path == "/api/approve":
                    self._send_json(200, _handle_approve(body))
                elif path == "/api/enqueue":
                    self._send_json(200, _handle_enqueue(body, db_path=db_path))
                elif path == "/api/add-condition":
                    self._send_json(
                        200,
                        _handle_add_condition(body, conditions_path=conditions_path),
                    )
                elif path == "/api/stop":
                    self._send_json(200, {"stopped": auto_worker.stop_current()})
                elif path == "/api/retry":
                    self._send_json(200, _handle_retry(body, db_path=db_path))
                elif path == "/api/delete":
                    self._send_json(200, _handle_delete(body, db_path=db_path))
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
    auto_run: bool = True,
) -> ThreadingHTTPServer:
    """서버 인스턴스를 만들어 반환한다. 시작(`serve_forever`)은 호출자가 한다.

    `auto_run`이 참이면(기본값) 큐에 쌓이는 작업을 백그라운드 thread가 자동
    실행한다 — 웹에서 `token_bench work`를 따로 돌릴 필요가 없다(사용자
    요청). API 표면만 검증하는 테스트는 실제 실행이 끼어들지 않도록
    `auto_run=False`로 끈다.
    """

    auto_worker = AutoWorker(db_path=db_path)
    handler = make_handler(
        conditions_path=conditions_path, db_path=db_path, auto_worker=auto_worker
    )
    class LocalServer(ThreadingHTTPServer):
        def server_close(self):
            auto_worker.stop()
            super().server_close()

    server = LocalServer((host, port), handler)
    if auto_run:
        auto_worker.start()
    return server
