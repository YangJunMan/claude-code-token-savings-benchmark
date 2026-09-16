"""실행 입력을 snapshot으로 고정하고 조건별 작업 디렉터리를 준비한다.

이 모듈은 실행 입력의 재현성과 작업 디렉터리 준비만 담당한다. 로그인 정보나
인증은 다루지 않으며, 설치 확인은 preflight의 몫이다.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from token_bench.conditions import (
    ConditionError,
    Injection,
    RunSpec,
    run_spec_from_dict,
    run_spec_to_dict,
)

DEFAULT_TASK_PROMPT_PATH = Path("benchmark/prompts/master.md")
DEFAULT_FIXTURE_PATH = Path("benchmark/fixture")
DEFAULT_RUNS_ROOT = Path(".token-bench/runs")
SNAPSHOT_SCHEMA_VERSION = 1

# 요구사항 5번: 기본 제공 프롬프트 프리셋 3종. 셋 다 같은 DEFAULT_FIXTURE_PATH
# 위에서 실행되고, 요구하는 구현 범위(서브 요구사항 수)만 다르다 —
# fixture 자체를 늘리지 않기로 한 판단은 docs/IMPLEMENTATION-PLAN-PRESETS.md
# 참고.
PROMPT_PRESETS: dict[str, Path] = {
    "small": DEFAULT_TASK_PROMPT_PATH,
    "large": Path("benchmark/prompts/preset-large.md"),
    "very-large": Path("benchmark/prompts/preset-very-large.md"),
}


class WorkspaceError(ValueError):
    """실행 입력 준비가 실패했을 때 발생한다."""


def resolve_prompt_path(
    *, preset: str | None = None, prompt_path: Path | None = None
) -> Path:
    """`--preset`과 `--prompt`(M17) 중 실제로 쓸 프롬프트 경로 하나를 정한다.

    CLI와 웹 백엔드가 모두 이 함수 하나를 호출한다 — 프리셋 이름→경로
    매핑이 두 곳에 따로 생기지 않게 한다.
    """

    if preset and prompt_path:
        raise WorkspaceError("preset과 prompt_path를 동시에 지정할 수 없다.")

    if preset:
        if preset not in PROMPT_PRESETS:
            raise WorkspaceError(
                f"알 수 없는 프리셋 '{preset}'. 사용 가능: {sorted(PROMPT_PRESETS)}"
            )
        return PROMPT_PRESETS[preset]

    return prompt_path or DEFAULT_TASK_PROMPT_PATH


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _snapshot_repository_assets(
    run: RunSpec, *, repo_root: Path, run_dir: Path
) -> tuple[RunSpec, list[dict], list[tuple[Path, Path]]]:
    runtime_injections: list[Injection] = []
    assets: list[dict] = []
    copies: list[tuple[Path, Path]] = []
    for index, injection in enumerate(run.injections):
        if injection.type not in ("prompt_overlay", "config_ref"):
            runtime_injections.append(injection)
            continue
        source = repo_root / injection.path
        if not source.is_file():
            raise WorkspaceError(
                f"조건 '{run.condition_id}'의 {injection.type} 파일을 찾을 수 없다: "
                f"{injection.path}"
            )
        relative_target = Path("assets") / f"{index}-{source.name}"
        assets.append(
            {
                "type": injection.type,
                "source_path": injection.path,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "snapshot_path": relative_target.as_posix(),
            }
        )
        copies.append((source, run_dir / relative_target))
        runtime_injections.append(replace(injection, path=relative_target.as_posix()))
    return replace(run, injections=tuple(runtime_injections)), assets, copies


def _content_id(
    *,
    condition_id: str,
    repeat_index: int,
    final_prompt: str,
    fixture_hash: str,
    timeout_seconds: int,
    condition: dict,
    execution_condition: dict,
    assets: list[dict],
) -> str:
    return _sha256_text(
        json.dumps(
            {
                "condition_id": condition_id,
                "repeat_index": repeat_index,
                "final_prompt": final_prompt,
                "fixture_sha256": fixture_hash,
                "timeout_seconds": timeout_seconds,
                "condition": condition,
                "execution_condition": execution_condition,
                "assets": assets,
            },
            sort_keys=True,
        )
    )


def load_run_snapshot(path: Path, *, expected_content_id: str | None = None) -> RunSpec:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceError(f"실행 snapshot을 찾을 수 없다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"실행 snapshot이 올바른 JSON이 아니다: {exc}") from exc
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != SNAPSHOT_SCHEMA_VERSION
    ):
        raise WorkspaceError(
            f"실행 snapshot의 schema_version은 {SNAPSHOT_SCHEMA_VERSION}이어야 한다."
        )
    try:
        run = run_spec_from_dict(document["execution_condition"])
        run_dir = path.parent.resolve()
        prompt = (run_dir / "prompt.md").read_text(encoding="utf-8")
        fixture_hash = _sha256_tree(run_dir / "workdir")
        assets = document["assets"]
        for asset in assets:
            asset_path = (run_dir / asset["snapshot_path"]).resolve()
            if not asset_path.is_relative_to(run_dir) or not asset_path.is_file():
                raise WorkspaceError("실행 snapshot asset 경로가 올바르지 않다.")
            if hashlib.sha256(asset_path.read_bytes()).hexdigest() != asset["sha256"]:
                raise WorkspaceError("실행 snapshot asset의 content_id가 일치하지 않는다.")
        actual_content_id = _content_id(
            condition_id=document["condition_id"],
            repeat_index=document["repeat_index"],
            final_prompt=prompt,
            fixture_hash=fixture_hash,
            timeout_seconds=document["timeout_seconds"],
            condition=document["condition"],
            execution_condition=document["execution_condition"],
            assets=assets,
        )
        if actual_content_id != document["content_id"] or (
            expected_content_id is not None and actual_content_id != expected_content_id
        ):
            raise WorkspaceError("실행 snapshot의 content_id가 일치하지 않는다.")
        return run
    except (KeyError, TypeError, OSError, ConditionError, UnicodeDecodeError) as exc:
        raise WorkspaceError(f"실행 snapshot의 condition이 올바르지 않다: {exc}") from exc


def build_final_prompt(task_prompt: str, run: RunSpec, repo_root: Path) -> str:
    """과제 프롬프트에 조건의 prompt_overlay 처치를 선언 순서대로 적용한다."""

    prompt = task_prompt
    for injection in run.injections:
        if injection.type != "prompt_overlay":
            continue
        overlay_path = repo_root / injection.path
        if not overlay_path.is_file():
            raise WorkspaceError(
                f"조건 '{run.condition_id}'의 prompt_overlay 파일을 찾을 수 없다: "
                f"{injection.path}"
            )
        overlay_text = overlay_path.read_text(encoding="utf-8")
        prompt = f"{prompt.rstrip()}\n\n{overlay_text.strip()}\n"
    return prompt


@dataclass(frozen=True)
class RunWorkspace:
    run_id: str
    content_id: str
    condition_id: str
    repeat_index: int
    workdir: Path
    snapshot_path: Path


def new_batch_id() -> str:
    return uuid.uuid4().hex[:12]


def _validate_positive_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkspaceError(f"{name}는 1 이상의 정수여야 한다: {value!r}")
    return value


def prepare_run(
    run: RunSpec,
    *,
    batch_id: str,
    timeout_seconds: int,
    repo_root: Path = Path("."),
    task_prompt_path: Path = DEFAULT_TASK_PROMPT_PATH,
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    runs_root: Path = DEFAULT_RUNS_ROOT,
) -> RunWorkspace:
    """실행 하나의 입력을 snapshot으로 고정하고 작업 디렉터리를 만든다."""

    _validate_positive_int(timeout_seconds, name="timeout_seconds")

    abs_task_prompt_path = repo_root / task_prompt_path
    abs_fixture_path = repo_root / fixture_path
    if not abs_task_prompt_path.is_file():
        raise WorkspaceError(f"과제 프롬프트를 찾을 수 없다: {task_prompt_path}")
    if not abs_fixture_path.is_dir():
        raise WorkspaceError(f"fixture 디렉터리를 찾을 수 없다: {fixture_path}")

    task_prompt = abs_task_prompt_path.read_text(encoding="utf-8")
    final_prompt = build_final_prompt(task_prompt, run, repo_root)
    fixture_hash = _sha256_tree(abs_fixture_path)

    run_dir_name = f"{run.condition_id}__r{run.repeat_index}"
    run_id = f"{batch_id}-{run_dir_name}"
    runs_base = (repo_root / runs_root / batch_id).resolve()
    run_dir = repo_root / runs_root / batch_id / run_dir_name
    if run_dir.resolve().parent != runs_base:
        raise WorkspaceError(f"실행 디렉터리가 runs root를 벗어난다: {run_dir}")
    workdir = run_dir / "workdir"
    if run_dir.exists():
        raise WorkspaceError(f"실행 디렉터리가 이미 존재한다: {run_dir}")

    execution_run, assets, asset_copies = _snapshot_repository_assets(
        run, repo_root=repo_root, run_dir=run_dir
    )

    source_condition = run_spec_to_dict(run)
    execution_condition = run_spec_to_dict(execution_run)
    content_id = _content_id(
        condition_id=run.condition_id,
        repeat_index=run.repeat_index,
        final_prompt=final_prompt,
        fixture_hash=fixture_hash,
        timeout_seconds=timeout_seconds,
        condition=source_condition,
        execution_condition=execution_condition,
        assets=assets,
    )

    run_dir.mkdir(parents=True)
    shutil.copytree(abs_fixture_path, workdir)
    for source, target in asset_copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    prompt_path = run_dir / "prompt.md"
    prompt_path.write_text(final_prompt, encoding="utf-8")

    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "run_id": run_id,
        "content_id": content_id,
        "condition_id": run.condition_id,
        "repeat_index": run.repeat_index,
        "repeat_total": run.repeat_total,
        "timeout_seconds": timeout_seconds,
        "task_prompt_path": str(task_prompt_path),
        "task_prompt_sha256": _sha256_text(task_prompt),
        "final_prompt_sha256": _sha256_text(final_prompt),
        "fixture_path": str(fixture_path),
        "fixture_sha256": fixture_hash,
        "condition": source_condition,
        "execution_condition": execution_condition,
        "assets": assets,
    }
    snapshot_path = run_dir / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return RunWorkspace(
        run_id=run_id,
        content_id=content_id,
        condition_id=run.condition_id,
        repeat_index=run.repeat_index,
        workdir=workdir,
        snapshot_path=snapshot_path,
    )


def prepare_batch(
    runs: list[RunSpec],
    *,
    timeout_seconds: int,
    repo_root: Path = Path("."),
    task_prompt_path: Path = DEFAULT_TASK_PROMPT_PATH,
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    runs_root: Path = DEFAULT_RUNS_ROOT,
    batch_id: str | None = None,
) -> list[RunWorkspace]:
    """실행 목록 전체의 입력을 같은 batch_id 아래에 준비한다."""

    resolved_batch_id = batch_id or new_batch_id()
    return [
        prepare_run(
            run,
            batch_id=resolved_batch_id,
            timeout_seconds=timeout_seconds,
            repo_root=repo_root,
            task_prompt_path=task_prompt_path,
            fixture_path=fixture_path,
            runs_root=runs_root,
        )
        for run in runs
    ]
