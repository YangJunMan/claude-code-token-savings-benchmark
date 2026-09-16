"""구독 실행 환경의 사전 점검.

실행 가능한 환경인지 판단하는 일만 담당한다. 도구 설치, 로그인, 모델 호출은
자동으로 수행하지 않는다.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from token_bench import claude_code
from token_bench.worker import WorkerError, resolve_plugin_dir
from token_bench.conditions import RunSpec, needs_customizations
from token_bench.tooling import ToolingError, fingerprint_tools

# 개인 스킬·플러그인·훅이 측정에 섞이지 않게 하는 플래그. 처치 자체가 hook·
# plugin인 조건은 `--safe-mode`에서 처치가 꺼지므로 `--setting-sources project`를
# 쓴다(worker.ISOLATION_MODES). 둘 중 어느 쪽을 쓰든 인증은 유지된다.
REQUIRED_ISOLATION_FLAG = "--safe-mode"
CUSTOMIZATION_ISOLATION_FLAG = "--setting-sources"


@dataclass(frozen=True)
class PreflightReport:
    ok: bool
    claude_version: str | None
    auth: dict | None
    problems: tuple[str, ...]
    tool_fingerprints: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "claude_version": self.claude_version,
            "auth": self.auth,
            "problems": list(self.problems),
            "tool_fingerprints": list(self.tool_fingerprints),
        }


def _flags_required_by_injections(run: RunSpec) -> list[str]:
    flags: list[str] = []
    for injection in run.injections:
        if injection.type == "config_ref":
            flags.append("--settings")
        elif injection.type == "plugin_dir":
            flags.append("--plugin-dir")
    return flags


def check(run: RunSpec, *, repo_root: Path = Path(".")) -> PreflightReport:
    """준비된 실행 하나가 구독 환경에서 실행 가능한지 점검한다."""

    problems: list[str] = []

    if not claude_code.is_installed():
        problems.append("claude CLI가 PATH에 없다.")
        return PreflightReport(
            ok=False, claude_version=None, auth=None, problems=tuple(problems)
        )

    version: str | None
    try:
        version = claude_code.get_version()
    except claude_code.ClaudeCodeError as exc:
        problems.append(str(exc))
        version = None

    auth_dict: dict | None = None
    try:
        auth = claude_code.get_auth_status()
    except claude_code.ClaudeCodeError as exc:
        problems.append(str(exc))
    else:
        auth_dict = {
            "logged_in": auth.logged_in,
            "auth_method": auth.auth_method,
            "api_provider": auth.api_provider,
            "subscription_type": auth.subscription_type,
        }
        if not auth.logged_in:
            problems.append("구독 로그인 상태가 아니다 (loggedIn=false).")
        if auth.auth_method == "apiKey" or auth.api_provider not in (
            None,
            "firstParty",
        ):
            problems.append(
                "API key 인증 경로가 감지되어 구독 실행과 혼입될 수 있다."
            )

    help_text = ""
    try:
        help_text = claude_code.get_help_text()
    except claude_code.ClaudeCodeError as exc:
        problems.append(str(exc))

    required_flag = (
        CUSTOMIZATION_ISOLATION_FLAG
        if needs_customizations(run.injections)
        else REQUIRED_ISOLATION_FLAG
    )
    if required_flag not in help_text:
        problems.append(
            f"{required_flag} 플래그를 확인할 수 없어 이 실행에 개인 설정"
            "(스킬·플러그인·훅)이 섞이지 않는다고 보장할 수 없다."
        )

    for flag in _flags_required_by_injections(run):
        if help_text and flag not in help_text:
            problems.append(
                f"조건 '{run.condition_id}'가 필요로 하는 '{flag}' 플래그를 "
                "확인할 수 없다."
            )

    for injection in run.injections:
        if injection.type in ("prompt_overlay", "config_ref"):
            referenced = repo_root / injection.path
            if not referenced.is_file():
                problems.append(
                    f"조건 '{run.condition_id}'가 참조하는 파일이 없다: "
                    f"{injection.path}"
                )
        elif injection.type == "proxy":
            if shutil.which(injection.binary) is None:
                problems.append(
                    f"조건 '{run.condition_id}'가 필요로 하는 proxy 실행 파일이 "
                    f"없다: {injection.binary}"
                )

    tool_fingerprints: tuple[dict, ...] = ()
    try:
        tool_fingerprints = fingerprint_tools(run, repo_root=repo_root)
    except ToolingError as exc:
        problems.append(f"조건 '{run.condition_id}': {exc}")

    return PreflightReport(
        ok=not problems,
        claude_version=version,
        auth=auth_dict,
        problems=tuple(problems),
        tool_fingerprints=tool_fingerprints,
    )


def unavailable_reasons(run: RunSpec, *, repo_root: Path = Path(".")) -> list[str]:
    """이 조건을 지금 실행할 수 없는 이유. 모델도 `claude`도 호출하지 않는다.

    설치 여부만 본다(로그인·플래그 확인은 check()가 한다). clone 직후 무엇을
    바로 돌릴 수 있는지 판단하는 데 쓴다.
    """

    reasons: list[str] = []
    for tool in run.requires_tools:
        if shutil.which(tool) is None:
            reasons.append(f"'{tool}' 실행 파일이 PATH에 없다")
    for injection in run.injections:
        if injection.type == "plugin_dir":
            try:
                resolve_plugin_dir(injection.path, repo_root=repo_root)
            except WorkerError:
                reasons.append(f"플러그인 디렉터리가 없다: {injection.path}")
        elif injection.type == "proxy" and shutil.which(injection.binary) is None:
            reasons.append(f"proxy 실행 파일이 없다: {injection.binary}")
    return reasons


def split_by_availability(
    runs: list[RunSpec], *, repo_root: Path = Path(".")
) -> tuple[list[RunSpec], list[tuple[RunSpec, list[str]]]]:
    """(지금 돌릴 수 있는 실행, (못 돌리는 실행, 이유들))로 나눈다."""

    ready: list[RunSpec] = []
    blocked: list[tuple[RunSpec, list[str]]] = []
    for run in runs:
        reasons = unavailable_reasons(run, repo_root=repo_root)
        if reasons:
            blocked.append((run, reasons))
        else:
            ready.append(run)
    return ready, blocked
