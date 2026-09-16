"""구독 실행 1개의 Claude Code 프로세스 수명 관리.

승인된 작업 하나를 선점하고, preflight를 재확인한 뒤 Claude Code 프로세스
하나를 시작부터 종료까지 관리한다. 반복 스케줄링(M9)과 결과 해석(M7)은
다루지 않는다.

실행 한도는 `timeout_seconds` 하나다. 설치된 Claude Code에는 turn 수를
강제하는 플래그가 없어, 강제되지 않는 turn 예산을 승인 digest와 프롬프트에
싣지 않는다(과거에 있던 `max_turns`는 그래서 제거했다).
"""

from __future__ import annotations

import contextlib
import glob
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from token_bench.claude_code import CLAUDE_BIN
from token_bench.conditions import ALLOWED_INJECTION_TYPES, Injection

# 개인 설정(스킬·플러그인·훅·MCP)이 측정에 섞이지 않게 하는 두 가지 방식.
#
# "safe-mode"는 customization을 통째로 끈다 — baseline과 프롬프트만 바꾸는 조건
# (be-brief)에는 이게 가장 강한 격리다. 하지만 hook·plugin을 켜는 것이 처치인
# 조건(RTK·Caveman)은 그 플래그 아래에서 처치 자체가 꺼진다.
#
# "project-settings"는 사용자 설정 소스를 빼고 프로젝트 소스만 읽게 한다. 개인
# 설정은 여전히 배제되지만, runner가 `--settings`/`--plugin-dir`로 명시적으로
# 넘긴 처치는 살아 있다. 한 배치 안의 모든 실행이 같은 모드를 쓴다 — 조건마다
# 격리가 다르면 처치 말고도 달라지는 것이 생긴다.
ISOLATION_MODES = {
    "safe-mode": ("--safe-mode",),
    "project-settings": ("--setting-sources", "project"),
}
DEFAULT_ISOLATION = "safe-mode"
# 헤드리스 실행에서 도구 사용 승인 프롬프트가 멈추지 않도록 한다. fixture
# 작업 디렉터리 밖에는 영향을 주지 않는다(cwd로 제한).
PERMISSION_MODE = "bypassPermissions"

TERMINATE_GRACE_SECONDS = 5


class WorkerError(ValueError):
    """프로세스를 시작할 수 없을 때 발생한다."""


class WorkerLockError(RuntimeError):
    """같은 상태 저장소에 이미 다른 worker가 상주하고 있을 때 발생한다."""


# 파일 잠금 API가 POSIX(fcntl)와 Windows(msvcrt)로 갈린다. import 시점에
# 플랫폼별 모듈을 고르기만 하고, 잠그고 푸는 동작은 아래 두 함수로 감싸서
# worker_lock 본문은 플랫폼을 몰라도 되게 한다.
if sys.platform == "win32":
    import msvcrt

    def _lock_exclusive_nonblocking(fp) -> None:
        fp.seek(0)
        msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(fp) -> None:
        with contextlib.suppress(OSError):
            fp.seek(0)
            msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_exclusive_nonblocking(fp) -> None:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fp) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def worker_lock(db_path: Path):
    """구독 실행 worker가 같은 상태 저장소에 하나만 상주하도록 강제한다."""

    lock_path = db_path.parent / "worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # msvcrt.locking은 파일에 바이트가 하나 이상 있어야 잠글 수 있다.
    if not lock_path.exists() or lock_path.stat().st_size == 0:
        lock_path.write_bytes(b"0")
    fp = open(lock_path, "r+b")
    try:
        try:
            _lock_exclusive_nonblocking(fp)
        except OSError as exc:
            raise WorkerLockError(
                f"이미 다른 worker가 '{db_path}' 상태 저장소에서 실행 중이다."
            ) from exc
        yield
    finally:
        _unlock(fp)
        fp.close()


@dataclass(frozen=True)
class ProcessOutcome:
    run_id: str
    status: str  # "succeeded" | "failed" | "timeout"
    returncode: int | None
    started_at: str
    finished_at: str
    duration_seconds: float
    stdout_path: str
    stderr_path: str
    command: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "command": list(self.command),
        }


def resolve_plugin_dir(path: str, *, repo_root: Path = Path(".")) -> Path:
    """선언된 플러그인 디렉터리를 찾는다. `~`와 glob 한 단계를 허용한다.

    Caveman처럼 설치 경로에 버전 해시가 끼는 플러그인이 있어, 선언에 `*`를
    쓸 수 있게 한다. 여러 개가 맞으면 가장 마지막(사전순)을 쓴다.
    """

    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        expanded = repo_root / expanded
    if any(ch in str(expanded) for ch in "*?["):
        matches = sorted(p for p in glob.glob(str(expanded)) if Path(p).is_dir())
        if not matches:
            raise WorkerError(f"플러그인 디렉터리를 찾을 수 없다: {path}")
        return Path(matches[-1])
    if not expanded.is_dir():
        raise WorkerError(f"플러그인 디렉터리를 찾을 수 없다: {path}")
    return expanded


def build_command(
    prompt: str,
    injections: tuple[Injection, ...],
    *,
    isolation: str = DEFAULT_ISOLATION,
    claude_bin: str = CLAUDE_BIN,
    repo_root: Path = Path("."),
) -> list[str]:
    """조건의 config_ref/plugin_dir 주입을 반영해 claude 호출 인자를 구성한다."""

    if isolation not in ISOLATION_MODES:
        raise WorkerError(f"알 수 없는 격리 모드: {isolation}")
    for injection in injections:
        if injection.type not in ALLOWED_INJECTION_TYPES:
            raise WorkerError(f"지원하지 않는 injection type: {injection.type}")

    command = [
        claude_bin,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        *ISOLATION_MODES[isolation],
        "--permission-mode",
        PERMISSION_MODE,
    ]
    for injection in injections:
        if injection.type == "config_ref":
            # claude는 작업 디렉터리(fixture 복사본)에서 돌기 때문에, 저장소
            # 기준 상대경로를 그대로 넘기면 파일을 찾지 못한다.
            command.extend(["--settings", str((repo_root / injection.path).resolve())])
        elif injection.type == "plugin_dir":
            command.extend(
                ["--plugin-dir", str(resolve_plugin_dir(injection.path, repo_root=repo_root))]
            )
    command.append(prompt)
    return command


def build_env(
    injections: tuple[Injection, ...], *, base_env: dict[str, str]
) -> dict[str, str]:
    """조건의 env 주입을 base_env 위에 덧붙인다. runner 소유 변수는 이미 거부됐다."""

    env = dict(base_env)
    for injection in injections:
        if injection.type == "env":
            env[injection.name] = injection.value or ""
    return env


PROXY_READY_TIMEOUT_SECONDS = 60
PROXY_HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind((PROXY_HOST, 0))
        return probe.getsockname()[1]


def _wait_until_ready(url: str, process: subprocess.Popen) -> None:
    """proxy가 요청을 받을 준비가 될 때까지 기다린다.

    여기서 실패하면 조건의 처치가 적용되지 않은 채 실행이 시작되므로, 조용히
    넘어가지 않고 실행 자체를 중단한다.
    """

    deadline = time.monotonic() + PROXY_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise WorkerError(f"proxy가 준비되기 전에 종료했다 (코드 {process.returncode}).")
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception:
            time.sleep(0.5)
    raise WorkerError(f"proxy가 {PROXY_READY_TIMEOUT_SECONDS}초 안에 준비되지 않았다: {url}")


@contextlib.contextmanager
def proxy_process(injection: Injection, *, log_dir: Path, env: dict[str, str]):
    """선언된 proxy를 실행 동안만 띄우고, base URL을 runner가 소유한다.

    조건 선언은 `ANTHROPIC_BASE_URL`을 직접 건드릴 수 없다(예약 변수). 대신
    proxy를 여기서 띄우고 그 주소를 자식 환경에 넣는다 — 포트와 수명을 runner가
    쥐고 있어야 실행이 끝난 뒤 프로세스가 남지 않는다.
    """

    binary = shutil.which(injection.binary)
    if binary is None:
        raise WorkerError(f"proxy 실행 파일을 찾을 수 없다: {injection.binary}")

    port = _free_port()
    log_path = log_dir / "proxy.log"
    log_dir.mkdir(parents=True, exist_ok=True)
    substitutions = {"port": str(port), "log_path": str(log_path)}
    args = [a.format(**substitutions) for a in (injection.args or ())]

    with open(log_path, "w", encoding="utf-8") as log_f:
        process = subprocess.Popen(
            [binary, *args], stdout=log_f, stderr=subprocess.STDOUT, env=env
        )
        try:
            _wait_until_ready(
                f"http://{PROXY_HOST}:{port}{injection.ready_path or '/readyz'}", process
            )
            yield f"http://{PROXY_HOST}:{port}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def run_once(
    *,
    run_id: str,
    prompt: str,
    injections: tuple[Injection, ...],
    cwd: Path,
    timeout_seconds: int,
    log_dir: Path,
    env: dict[str, str],
    isolation: str = DEFAULT_ISOLATION,
    claude_bin: str = CLAUDE_BIN,
    repo_root: Path = Path("."),
) -> ProcessOutcome:
    """Claude Code 프로세스 하나를 시작해 timeout까지 관리하고 결과를 기록한다."""

    proxy = next((i for i in injections if i.type == "proxy"), None)
    if proxy is not None:
        with proxy_process(proxy, log_dir=log_dir, env=env) as base_url:
            return run_once(
                run_id=run_id,
                prompt=prompt,
                injections=tuple(i for i in injections if i.type != "proxy"),
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                log_dir=log_dir,
                env={**env, "ANTHROPIC_BASE_URL": base_url},
                isolation=isolation,
                claude_bin=claude_bin,
                repo_root=repo_root,
            )

    command = build_command(
        prompt, injections, isolation=isolation, claude_bin=claude_bin, repo_root=repo_root
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "stdout.jsonl"
    stderr_path = log_dir / "stderr.log"

    started_at = datetime.now(timezone.utc)
    start_monotonic = time.monotonic()

    try:
        with (
            open(stdout_path, "w", encoding="utf-8") as stdout_f,
            open(stderr_path, "w", encoding="utf-8") as stderr_f,
        ):
            try:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    stdout=stdout_f,
                    stderr=stderr_f,
                    env=env,
                )
            except OSError as exc:
                raise WorkerError(f"claude 프로세스를 실행할 수 없다: {exc}") from exc

            try:
                returncode = process.wait(timeout=timeout_seconds)
                status = "succeeded" if returncode == 0 else "failed"
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=TERMINATE_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                status = "timeout"
                returncode = process.returncode
    finally:
        finished_at = datetime.now(timezone.utc)
        duration_seconds = time.monotonic() - start_monotonic

    return ProcessOutcome(
        run_id=run_id,
        status=status,
        returncode=returncode,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        duration_seconds=duration_seconds,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        command=tuple(command),
    )
