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
        fingerprints.append(
            {
                "kind": "plugin_dir",
                "path": str(plugin_dir.resolve()),
                "sha256": _sha256_tree(plugin_dir),
            }
        )

    return tuple(fingerprints)
