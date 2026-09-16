"""실행 계획에 대한 비용 확인과 명시적 승인.

실행에 대한 동의와 허용 조건만 담당한다. 작업 큐 등록이나 모델 호출은
다루지 않는다. 이 단계는 구독 경로만 다루며, API 예산 상한은 M10에서
추가한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from token_bench.workspace import RunWorkspace

SUBSCRIPTION_COST_DISCLAIMER = (
    "이 실행은 API 요금이 아니라 기존 Claude 구독 사용량을 소비합니다. 실제 "
    "추가 청구가 발생하는지, 구독 한도에 얼마나 근접했는지는 이 도구가 자동으로 "
    "확인할 수 없습니다. Anthropic 계정의 사용량·과금 설정을 실행 전에 직접 "
    "확인하세요."
)


class AuthorizationError(ValueError):
    """승인 확인이나 계획·승인 파일 처리에 실패했을 때 발생한다."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class EstimatePlan:
    digest: str
    batch_id: str
    run_count: int
    runs: tuple[dict, ...]
    timeout_seconds: int
    isolation: str
    auth: dict
    cost_disclaimer: str

    def to_dict(self) -> dict:
        return {
            "digest": self.digest,
            "batch_id": self.batch_id,
            "run_count": self.run_count,
            "runs": list(self.runs),
            "timeout_seconds": self.timeout_seconds,
            "isolation": self.isolation,
            "auth": self.auth,
            "cost_disclaimer": self.cost_disclaimer,
        }


def build_estimate(
    workspaces: list[RunWorkspace],
    *,
    batch_id: str,
    timeout_seconds: int,
    auth: dict,
    isolation: str,
    tool_fingerprints: dict[str, tuple[dict, ...]] | None = None,
) -> EstimatePlan:
    """준비된 실행 목록에 대한 확인 가능한 계획을 만든다.

    digest는 각 실행의 content_id(조건·repeat·최종 프롬프트·fixture·제한을 모두
    반영)와 인증 방식에 대해 계산하므로, 이 중 하나라도 바뀌면 이전 승인은
    이 계획에 대해 무효가 된다.
    """

    if not workspaces:
        raise AuthorizationError("실행 목록이 비어 있어 계획을 세울 수 없다.")

    fingerprints = tool_fingerprints or {}
    runs = tuple(
        {
            "run_id": ws.run_id,
            "condition_id": ws.condition_id,
            "repeat_index": ws.repeat_index,
            "content_id": ws.content_id,
            "workdir": str(ws.workdir),
            "snapshot_path": str(ws.snapshot_path),
            "tool_fingerprints": list(fingerprints.get(ws.run_id, ())),
        }
        for ws in workspaces
    )

    digest_payload = {
        "content_ids": [r["content_id"] for r in runs],
        "auth_method": auth.get("auth_method"),
        "api_provider": auth.get("api_provider"),
        "timeout_seconds": timeout_seconds,
        "isolation": isolation,
        "tool_fingerprints": [r["tool_fingerprints"] for r in runs],
    }

    return EstimatePlan(
        digest=_digest(digest_payload),
        batch_id=batch_id,
        run_count=len(runs),
        runs=runs,
        timeout_seconds=timeout_seconds,
        isolation=isolation,
        auth=auth,
        cost_disclaimer=SUBSCRIPTION_COST_DISCLAIMER,
    )


@dataclass(frozen=True)
class ApprovalRecord:
    digest: str
    approved_at: str
    plan: dict

    def to_dict(self) -> dict:
        return {
            "digest": self.digest,
            "approved_at": self.approved_at,
            "plan": self.plan,
        }


def approve(plan: EstimatePlan, *, confirmed_digest: str) -> ApprovalRecord:
    """표시한 계획의 digest에 대한 명시적 확인을 검사하고 승인 기록을 만든다."""

    if confirmed_digest != plan.digest:
        raise AuthorizationError(
            "확인한 digest가 현재 계획의 digest와 다르다. 조건·repeat·입력·인증 "
            "방식·실행 제한 중 하나가 바뀌었을 수 있으니 estimate를 다시 실행하라."
        )
    return ApprovalRecord(
        digest=plan.digest, approved_at=_now_iso(), plan=plan.to_dict()
    )


def save_json(document: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_plan(path: Path) -> EstimatePlan:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AuthorizationError(f"계획 파일을 찾을 수 없다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AuthorizationError(f"계획 파일이 올바른 JSON이 아니다: {exc}") from exc

    try:
        return EstimatePlan(
            digest=raw["digest"],
            batch_id=raw["batch_id"],
            run_count=raw["run_count"],
            runs=tuple(raw["runs"]),
            timeout_seconds=raw["timeout_seconds"],
            isolation=raw["isolation"],
            auth=raw["auth"],
            cost_disclaimer=raw["cost_disclaimer"],
        )
    except KeyError as exc:
        raise AuthorizationError(f"계획 파일에 필드가 없다: {exc}") from exc


def load_approval(path: Path) -> ApprovalRecord:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AuthorizationError(f"승인 파일을 찾을 수 없다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AuthorizationError(f"승인 파일이 올바른 JSON이 아니다: {exc}") from exc

    try:
        return ApprovalRecord(
            digest=raw["digest"], approved_at=raw["approved_at"], plan=raw["plan"]
        )
    except KeyError as exc:
        raise AuthorizationError(f"승인 파일에 필드가 없다: {exc}") from exc
