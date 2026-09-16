"""설치된 Claude Code CLI의 환경 조회 기능.

이 모듈은 실제 사용하는 조회 기능만 담당한다. 명령 구성과 프로세스 실행
(모델 호출)은 이후 마일스톤의 책임이며, 이 모듈은 모델을 호출하지 않는다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

CLAUDE_BIN = "claude"
_SUBPROCESS_TIMEOUT_SECONDS = 15


class ClaudeCodeError(RuntimeError):
    """claude CLI 조회가 실패했을 때 발생한다."""


@dataclass(frozen=True)
class AuthStatus:
    logged_in: bool
    auth_method: str | None
    api_provider: str | None
    subscription_type: str | None


def is_installed() -> bool:
    return shutil.which(CLAUDE_BIN) is not None


def _run(args: list[str]) -> str:
    if not is_installed():
        raise ClaudeCodeError(f"'{CLAUDE_BIN}' 실행 파일을 PATH에서 찾을 수 없다.")
    try:
        result = subprocess.run(
            [CLAUDE_BIN, *args],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCodeError(
            f"'{CLAUDE_BIN} {' '.join(args)}' 호출이 timeout됐다."
        ) from exc
    except OSError as exc:
        raise ClaudeCodeError(
            f"'{CLAUDE_BIN} {' '.join(args)}' 호출에 실패했다: {exc}"
        ) from exc

    if result.returncode != 0:
        raise ClaudeCodeError(
            f"'{CLAUDE_BIN} {' '.join(args)}'가 종료 코드 {result.returncode}로 "
            f"실패했다: {result.stderr.strip()}"
        )
    return result.stdout


def get_version() -> str:
    """모델을 호출하지 않는 버전 조회."""

    return _run(["--version"]).strip()


def get_help_text() -> str:
    """모델을 호출하지 않는 도움말 조회. 지원 플래그 확인에 쓰인다."""

    return _run(["--help"])


def get_auth_status() -> AuthStatus:
    """모델을 호출하지 않는 로그인 상태 조회. 이메일 등 계정 식별 정보는 담지 않는다."""

    raw = _run(["auth", "status"])
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClaudeCodeError(
            f"'{CLAUDE_BIN} auth status' 출력이 JSON이 아니다: {exc}"
        ) from exc

    return AuthStatus(
        logged_in=bool(document.get("loggedIn", False)),
        auth_method=document.get("authMethod"),
        api_provider=document.get("apiProvider"),
        subscription_type=document.get("subscriptionType"),
    )
