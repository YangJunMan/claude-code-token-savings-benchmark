"""생성된 작업물의 공개 테스트 실행과 검사 범위 기록.

생성된 작업물의 공개 테스트 검사만 담당한다. 모델 프로세스 성공과 과제
테스트 성공을 구분하며, 원래 제공한 테스트가 삭제되거나 변조된 경우에는
검사를 실행하더라도 유효한 품질 통과로 처리하지 않는다.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FIXTURE_TESTS_DIR = Path("benchmark/fixture/tests")
DEFAULT_TIMEOUT_SECONDS = 300


class EvaluationError(ValueError):
    """공개 테스트를 실행할 수 없을 때 발생한다."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _original_test_hashes(fixture_tests_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(fixture_tests_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(fixture_tests_dir).as_posix()
        hashes[rel] = _sha256_file(path)
    return hashes


@dataclass(frozen=True)
class EvaluationReport:
    ran: bool
    passed: bool
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    tampered_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    checked_test_files: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "ran": self.ran,
            "passed": self.passed,
            "command": list(self.command),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "tampered_files": list(self.tampered_files),
            "missing_files": list(self.missing_files),
            "checked_test_files": list(self.checked_test_files),
        }


def check(
    workdir: Path,
    *,
    fixture_tests_dir: Path = DEFAULT_FIXTURE_TESTS_DIR,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    python_bin: str = sys.executable,
) -> EvaluationReport:
    """작업 디렉터리에서 원래 제공한 공개 테스트를 실행한다.

    원본 테스트 파일이 없거나 내용이 바뀌었으면 테스트를 진단용으로 실행할
    수는 있지만 `passed`는 항상 False로 기록한다 — 변조된 테스트의 통과는
    유효한 품질 통과가 아니다.
    """

    original_hashes = _original_test_hashes(fixture_tests_dir)
    workdir_tests_dir = workdir / "tests"

    missing: list[str] = []
    tampered: list[str] = []
    for rel, expected_hash in original_hashes.items():
        candidate = workdir_tests_dir / rel
        if not candidate.is_file():
            missing.append(rel)
            continue
        if _sha256_file(candidate) != expected_hash:
            tampered.append(rel)

    command = (python_bin, "-m", "unittest", "discover", "-s", "tests")

    try:
        result = subprocess.run(
            command,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return EvaluationReport(
            ran=True,
            passed=False,
            command=command,
            returncode=None,
            stdout=(exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            stderr=(exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
            timed_out=True,
            tampered_files=tuple(tampered),
            missing_files=tuple(missing),
            checked_test_files=tuple(sorted(original_hashes)),
        )
    except OSError as exc:
        raise EvaluationError(f"공개 테스트를 실행할 수 없다: {exc}") from exc

    passed = result.returncode == 0 and not missing and not tampered

    return EvaluationReport(
        ran=True,
        passed=passed,
        command=command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        timed_out=False,
        tampered_files=tuple(tampered),
        missing_files=tuple(missing),
        checked_test_files=tuple(sorted(original_hashes)),
    )
