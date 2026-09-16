"""M6의 원본 출력과 job 메타데이터를 공통 RunResult로 변환한다.

단일 실행의 결과 정규화만 담당한다. 조건 간 집계와 공개 보고서 생성은
다루지 않는다. 누락된 사용량·비용은 0이 아니라 null과 누락 사유로
기록한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from token_bench.evaluation import EvaluationReport
from token_bench.job_store import JobRecord
from token_bench.worker import ProcessOutcome

_NO_STDOUT = "stdout 로그 파일이 없거나 비어 있다."
_NOT_JSON = "stdout 로그를 JSON Lines로 해석할 수 없다."
_NO_SYSTEM_EVENT = "stdout 로그에 'system' 초기화 이벤트가 없다."
_NO_RESULT_EVENT = "stdout 로그에 'result' 종료 이벤트가 없다."
_NO_FIELD = "원본 로그의 종료 이벤트에 이 필드가 없다."

_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


class ResultsError(ValueError):
    """결과 파일 처리가 실패했을 때 발생한다."""


def _field(value, *, missing_reason: str | None) -> dict:
    if value is None and missing_reason is not None:
        return {"value": None, "missing_reason": missing_reason}
    return {"value": value, "missing_reason": None}


def interrupted_reason(stdout_path: str | None) -> str | None:
    """모델이 과제를 끝내지 못하고 중단됐다면 그 사유를 돌려준다.

    구독 사용 한도처럼 실행 중간에 끊긴 경우, 프로세스는 종료 코드 1로 끝나고
    턴·비용은 기록되지만 그 숫자는 "이 조건이 과제를 이만큼에 해냈다"는 측정이
    아니다. 게시 전에 걸러내야 한다.
    """

    events, _ = _parse_stream_json_lines(stdout_path)
    result_event = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if result_event is None or not result_event.get("is_error"):
        return None
    return str(result_event.get("result") or "원본 로그에 사유 없음")[:300]


def _parse_stream_json_lines(stdout_path: str | None) -> tuple[list[dict], str | None]:
    if not stdout_path:
        return [], _NO_STDOUT
    path = Path(stdout_path)
    if not path.is_file() or path.stat().st_size == 0:
        return [], _NO_STDOUT

    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not events:
        return [], _NOT_JSON
    return events, None


@dataclass(frozen=True)
class RunResult:
    run_id: str
    condition_id: str
    repeat_index: int
    content_id: str
    auth_method: dict
    api_provider: dict
    timeout_seconds: int
    isolation: str
    claude_version: dict
    model: dict
    status: str
    returncode: int | None
    started_at: str | None
    finished_at: str | None
    duration_seconds: float | None
    stdout_path: str | None
    stderr_path: str | None
    num_turns: dict
    cost_usd: dict
    usage: dict
    evaluation: dict | None
    tool_fingerprints: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "condition_id": self.condition_id,
            "repeat_index": self.repeat_index,
            "content_id": self.content_id,
            "auth_method": self.auth_method,
            "api_provider": self.api_provider,
            "timeout_seconds": self.timeout_seconds,
            "isolation": self.isolation,
            "tool_fingerprints": list(self.tool_fingerprints),
            "claude_version": self.claude_version,
            "model": self.model,
            "status": self.status,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "num_turns": self.num_turns,
            "cost_usd": self.cost_usd,
            "usage": self.usage,
            "evaluation": self.evaluation,
        }


def collect(
    job: JobRecord,
    outcome: ProcessOutcome,
    *,
    auth: dict,
    claude_version: str | None,
    evaluation: EvaluationReport | None = None,
) -> RunResult:
    """M6의 원본 출력(stdout.jsonl)과 job 메타데이터를 RunResult로 정규화한다."""

    events, parse_error = _parse_stream_json_lines(outcome.stdout_path)

    system_event = next((e for e in events if e.get("type") == "system"), None)
    result_event = next(
        (e for e in reversed(events) if e.get("type") == "result"), None
    )

    model_value = system_event.get("model") if system_event else None
    model_missing = None
    if model_value is None:
        model_missing = parse_error or _NO_SYSTEM_EVENT

    usage_raw = (result_event or {}).get("usage") or {}
    usage = {
        field: _field(
            usage_raw.get(field),
            missing_reason=(
                None
                if field in usage_raw and usage_raw.get(field) is not None
                else (parse_error or _NO_RESULT_EVENT if result_event is None else _NO_FIELD)
            ),
        )
        for field in _USAGE_FIELDS
    }

    cost_raw = (result_event or {}).get("total_cost_usd")
    cost_usd = _field(
        cost_raw,
        missing_reason=(
            None
            if cost_raw is not None
            else (parse_error or _NO_RESULT_EVENT if result_event is None else _NO_FIELD)
        ),
    )

    num_turns_raw = (result_event or {}).get("num_turns")
    num_turns = _field(
        num_turns_raw,
        missing_reason=(
            None
            if num_turns_raw is not None
            else (parse_error or _NO_RESULT_EVENT if result_event is None else _NO_FIELD)
        ),
    )

    return RunResult(
        run_id=job.run_id,
        condition_id=job.condition_id,
        repeat_index=job.repeat_index,
        content_id=job.content_id,
        auth_method=_field(auth.get("auth_method"), missing_reason="preflight에서 확인되지 않음"),
        api_provider=_field(auth.get("api_provider"), missing_reason="preflight에서 확인되지 않음"),
        timeout_seconds=job.timeout_seconds,
        isolation=job.isolation,
        tool_fingerprints=job.tool_fingerprints,
        claude_version=_field(claude_version, missing_reason="preflight에서 확인되지 않음"),
        model=_field(model_value, missing_reason=model_missing),
        status=outcome.status,
        returncode=outcome.returncode,
        started_at=outcome.started_at,
        finished_at=outcome.finished_at,
        duration_seconds=outcome.duration_seconds,
        stdout_path=outcome.stdout_path,
        stderr_path=outcome.stderr_path,
        num_turns=num_turns,
        cost_usd=cost_usd,
        usage=usage,
        evaluation=evaluation.to_dict() if evaluation is not None else None,
    )


def save(result: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load(path: Path) -> RunResult:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ResultsError(f"결과 파일을 찾을 수 없다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ResultsError(f"결과 파일이 올바른 JSON이 아니다: {exc}") from exc

    try:
        return RunResult(
            run_id=raw["run_id"],
            condition_id=raw["condition_id"],
            repeat_index=raw["repeat_index"],
            content_id=raw["content_id"],
            auth_method=raw["auth_method"],
            api_provider=raw["api_provider"],
            timeout_seconds=raw["timeout_seconds"],
            isolation=raw.get("isolation", "safe-mode"),
            tool_fingerprints=tuple(raw.get("tool_fingerprints", [])),
            claude_version=raw["claude_version"],
            model=raw["model"],
            status=raw["status"],
            returncode=raw["returncode"],
            started_at=raw["started_at"],
            finished_at=raw["finished_at"],
            duration_seconds=raw["duration_seconds"],
            stdout_path=raw["stdout_path"],
            stderr_path=raw["stderr_path"],
            num_turns=raw["num_turns"],
            cost_usd=raw["cost_usd"],
            usage=raw["usage"],
            evaluation=raw.get("evaluation"),
        )
    except KeyError as exc:
        raise ResultsError(f"결과 파일에 필드가 없다: {exc}") from exc
