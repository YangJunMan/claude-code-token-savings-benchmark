"""외부 도구의 실행 경로와 버전을 승인 가능한 형태로 식별한다."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from token_bench.conditions import RunSpec
from token_bench.worker import WorkerError, resolve_plugin_dir


class ToolingError(ValueError):
    """외부 도구를 식별할 수 없을 때 발생한다."""


def _sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    """디렉터리면 트리 전체를, 파일이면 그 파일 하나만 지문 찍는다."""

    if path.is_dir():
        return _sha256_tree(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint_tools(run: RunSpec, *, repo_root: Path = Path(".")) -> tuple[dict, ...]:
    """조건이 사용하는 binary와 plugin directory를 결정적으로 식별한다."""

    fingerprints: list[dict] = []
    for name in run.requires_tools:
        if shutil.which(name) is None:
            raise ToolingError(f"필요한 도구 '{name}'가 설치되어 있지 않다.")

    for name, probe_args in run.tool_probes:
        resolved = shutil.which(name)
        if resolved is None:
            raise ToolingError(f"필요한 도구 '{name}'가 설치되어 있지 않다.")
        try:
            completed = subprocess.run(
                [resolved, *probe_args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolingError(f"도구 '{name}'의 버전을 확인할 수 없다: {exc}") from exc
        if completed.returncode != 0:
            output = (completed.stderr or completed.stdout).strip()
            raise ToolingError(
                f"도구 '{name}'의 버전 확인이 실패했다"
                + (f": {output[:300]}" if output else ".")
            )
        fingerprints.append(
            {
                "kind": "binary",
                "name": name,
                "path": str(Path(resolved).resolve()),
                "version_output": (completed.stdout or completed.stderr).strip()[:1000],
            }
        )

    for injection in run.injections:
        if injection.type != "plugin_dir":
            continue
        try:
            plugin_dir = resolve_plugin_dir(injection.path, repo_root=repo_root)
        except WorkerError as exc:
            raise ToolingError(str(exc)) from exc

        # 기본은 플러그인 디렉터리 전체를 지문 찍는다. 그런데 플러그인 안에 이
        # 조건과 무관한 스킬·스크립트가 같이 들어 있으면, 그쪽이 바뀔 때마다
        # (마켓플레이스 캐시 재동기화 등) 애먼 fingerprint 불일치로 막힌다
        # (caveman-full에서 실측됨). `fingerprint_path`가 있으면 그 파일/
        # 하위디렉터리만 지문 대상으로 좁힌다.
        fingerprint_target = plugin_dir
        if injection.fingerprint_path:
            fingerprint_target = plugin_dir / injection.fingerprint_path
            if not fingerprint_target.exists():
                raise ToolingError(
                    f"plugin_dir의 fingerprint_path를 찾을 수 없다: {fingerprint_target}"
                )
        fingerprints.append(
            {
                "kind": "plugin_dir",
                "path": str(plugin_dir.resolve()),
                "sha256": _sha256_path(fingerprint_target),
            }
        )

    return tuple(fingerprints)
