"""조건 선언(JSON)을 읽어 실행 목록으로 정규화한다.

이 모듈은 선언을 해석하는 일만 담당한다. 설치 확인, 디렉터리 준비,
인증, 모델 호출은 다른 마일스톤의 모듈이 담당한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

SCHEMA_VERSION = 1

# 검증된 사용 방식이 없는 generic arg는 runner 불변식을 우회할 수 있어 허용하지 않는다.
ALLOWED_INJECTION_TYPES = frozenset(
    {"prompt_overlay", "config_ref", "env", "plugin_dir", "proxy"}
)

# config_ref(hook 설정)와 plugin_dir는 Claude Code가 "customization"으로 분류해
# `--safe-mode`에서 통째로 꺼 버리는 범주다. 이런 처치를 선언한 조건이 하나라도
# 있으면 배치 전체를 다른 격리 방식으로 돌려야 한다(worker.ISOLATION_MODES).
CUSTOMIZATION_INJECTION_TYPES = frozenset({"config_ref", "plugin_dir"})

# runner가 소유하는 설정. condition의 env 주입이 이 이름을 쓰면 거부한다.
RESERVED_ENV_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
    }
)
_CONDITION_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_GITHUB_REPOSITORY_URL = re.compile(
    r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$"
)
_CONDITION_KEYS = frozenset(
    {"id", "repeat", "requires_tools", "tool_probes", "repository_url", "injections"}
)
_INJECTION_KEYS_BY_TYPE = {
    "prompt_overlay": frozenset({"type", "path"}),
    "config_ref": frozenset({"type", "path"}),
    "plugin_dir": frozenset({"type", "path"}),
    "env": frozenset({"type", "name", "value"}),
    "proxy": frozenset({"type", "binary", "args", "ready_path"}),
}


class ConditionError(ValueError):
    """선언이 잘못되었을 때 발생한다."""


@dataclass(frozen=True)
class Injection:
    type: str
    path: str | None = None
    name: str | None = None
    value: str | None = None
    binary: str | None = None
    args: tuple[str, ...] | None = None
    ready_path: str | None = None


@dataclass(frozen=True)
class Condition:
    id: str
    repeat: int
    requires_tools: tuple[str, ...]
    tool_probes: tuple[tuple[str, tuple[str, ...]], ...]
    injections: tuple[Injection, ...]
    repository_url: str | None = None


@dataclass(frozen=True)
class RunSpec:
    """선언된 조건 하나의 repeat 한 회차."""

    condition_id: str
    repeat_index: int  # 1부터 시작
    repeat_total: int
    requires_tools: tuple[str, ...]
    injections: tuple[Injection, ...]
    tool_probes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    repository_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "repeat_index": self.repeat_index,
            "repeat_total": self.repeat_total,
            "requires_tools": list(self.requires_tools),
            "tool_probes": {name: list(args) for name, args in self.tool_probes},
            "repository_url": self.repository_url,
            "injections": [
                {
                    k: (list(v) if isinstance(v, tuple) else v)
                    for k, v in vars(inj).items()
                    if v is not None
                }
                for inj in self.injections
            ],
        }


def _parse_injection(raw: Any, *, condition_id: str, index: int) -> Injection:
    if not isinstance(raw, dict):
        raise ConditionError(
            f"조건 '{condition_id}'의 injections[{index}]는 객체여야 한다."
        )
    inj_type = raw.get("type")
    if inj_type not in ALLOWED_INJECTION_TYPES:
        raise ConditionError(
            f"조건 '{condition_id}'의 injections[{index}]에 알 수 없는 type "
            f"'{inj_type}'이 있다. 허용값: {sorted(ALLOWED_INJECTION_TYPES)}"
        )
    allowed_keys = _INJECTION_KEYS_BY_TYPE[inj_type]
    unknown = set(raw.keys()) - allowed_keys
    if unknown:
        raise ConditionError(
            f"조건 '{condition_id}'의 injections[{index}]에 알 수 없는 설정 "
            f"{sorted(unknown)}이 있다."
        )

    if inj_type == "proxy":
        binary = raw.get("binary")
        if not isinstance(binary, str) or not binary:
            raise ConditionError(
                f"조건 '{condition_id}'의 injections[{index}]는 'binary'가 필요하다."
            )
        args_raw = raw.get("args", [])
        if not isinstance(args_raw, list) or not all(
            isinstance(a, str) for a in args_raw
        ):
            raise ConditionError(
                f"조건 '{condition_id}'의 injections[{index}]의 'args'는 문자열 배열이어야 한다."
            )
        ready_path = raw.get("ready_path", "/readyz")
        if not isinstance(ready_path, str) or not ready_path.startswith("/"):
            raise ConditionError(
                f"조건 '{condition_id}'의 injections[{index}]의 'ready_path'는 '/'로 "
                "시작하는 문자열이어야 한다."
            )
        return Injection(
            type=inj_type,
            binary=binary,
            args=tuple(args_raw),
            ready_path=ready_path,
        )

    if inj_type in ("prompt_overlay", "config_ref", "plugin_dir"):
        path = raw.get("path")
        if not isinstance(path, str) or not path:
            raise ConditionError(
                f"조건 '{condition_id}'의 injections[{index}]는 'path'가 필요하다."
            )
        if inj_type in ("prompt_overlay", "config_ref"):
            posix = PurePosixPath(path)
            windows = PureWindowsPath(path)
            if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts:
                raise ConditionError(
                    f"조건 '{condition_id}'의 injections[{index}] path는 "
                    "저장소 내부 상대경로여야 한다."
                )
        return Injection(type=inj_type, path=path)

    # env
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ConditionError(
            f"조건 '{condition_id}'의 injections[{index}]는 'name'이 필요하다."
        )
    value = raw.get("value")
    if value is not None and not isinstance(value, str):
        raise ConditionError(
            f"조건 '{condition_id}'의 injections[{index}]의 'value'는 문자열이어야 한다."
        )

    if inj_type == "env" and (
        name in RESERVED_ENV_NAMES
        or name.startswith("ANTHROPIC_")
        or name.startswith("CLAUDE_")
    ):
        raise ConditionError(
            f"조건 '{condition_id}'는 runner가 소유한 환경변수 '{name}'을 "
            "덮어쓸 수 없다."
        )
    return Injection(type=inj_type, name=name, value=value)


def _parse_condition(raw: Any, *, index: int) -> Condition:
    if not isinstance(raw, dict):
        raise ConditionError(f"conditions[{index}]는 객체여야 한다.")

    unknown = set(raw.keys()) - _CONDITION_KEYS
    if unknown:
        raise ConditionError(
            f"conditions[{index}]에 알 수 없는 설정 {sorted(unknown)}이 있다."
        )

    cond_id = raw.get("id")
    if not isinstance(cond_id, str) or not _CONDITION_ID.fullmatch(cond_id):
        raise ConditionError(
            f"conditions[{index}]의 id는 소문자 영숫자로 시작하고 "
            "소문자 영숫자·점·밑줄·하이픈만 포함해야 한다."
        )

    repeat = raw.get("repeat", 1)
    if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 1:
        raise ConditionError(
            f"조건 '{cond_id}'의 repeat은 1 이상의 정수여야 한다: {repeat!r}"
        )

    requires_tools_raw = raw.get("requires_tools", [])
    if not isinstance(requires_tools_raw, list) or not all(
        isinstance(t, str) and t for t in requires_tools_raw
    ):
        raise ConditionError(
            f"조건 '{cond_id}'의 requires_tools는 비어 있지 않은 문자열의 배열이어야 한다."
        )

    tool_probes_raw = raw.get("tool_probes", {})
    if not isinstance(tool_probes_raw, dict) or not all(
        isinstance(tool, str)
        and isinstance(args, list)
        and bool(args)
        and all(isinstance(arg, str) and arg for arg in args)
        for tool, args in tool_probes_raw.items()
    ):
        raise ConditionError(
            f"조건 '{cond_id}'의 tool_probes는 도구 이름에서 인자 배열로 가는 객체여야 한다."
        )
    if set(tool_probes_raw) != set(requires_tools_raw):
        raise ConditionError(
            f"조건 '{cond_id}'의 tool_probes 키는 requires_tools와 정확히 같아야 한다."
        )

    repository_url = raw.get("repository_url")
    if repository_url is not None and (
        not isinstance(repository_url, str)
        or not _GITHUB_REPOSITORY_URL.fullmatch(repository_url)
    ):
        raise ConditionError(
            f"조건 '{cond_id}'의 repository_url은 GitHub HTTPS repository URL이어야 한다."
        )

    injections_raw = raw.get("injections", [])
    if not isinstance(injections_raw, list):
        raise ConditionError(f"조건 '{cond_id}'의 injections는 배열이어야 한다.")
    injections = tuple(
        _parse_injection(inj, condition_id=cond_id, index=i)
        for i, inj in enumerate(injections_raw)
    )
    if sum(injection.type == "proxy" for injection in injections) > 1:
        raise ConditionError(f"조건 '{cond_id}'에는 proxy를 하나만 선언할 수 있다.")
    for injection in injections:
        if injection.type == "proxy" and injection.binary not in requires_tools_raw:
            raise ConditionError(
                f"조건 '{cond_id}'의 proxy binary는 requires_tools에 포함해야 한다."
            )
    needs_repository = bool(requires_tools_raw) or any(
        injection.type in ("plugin_dir", "proxy") for injection in injections
    )
    if needs_repository and repository_url is None:
        raise ConditionError(
            f"조건 '{cond_id}'에는 공식 GitHub repository_url이 필요하다."
        )

    return Condition(
        id=cond_id,
        repeat=repeat,
        requires_tools=tuple(requires_tools_raw),
        tool_probes=tuple(
            (tool, tuple(tool_probes_raw[tool])) for tool in requires_tools_raw
        ),
        injections=injections,
        repository_url=repository_url,
    )


def load_conditions(path: Path) -> list[Condition]:
    """선언 파일을 읽어 검증된 Condition 목록을 반환한다."""

    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConditionError(f"조건 선언 파일을 찾을 수 없다: {path}") from exc

    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConditionError(f"조건 선언 파일이 올바른 JSON이 아니다: {exc}") from exc

    if not isinstance(document, dict) or "conditions" not in document:
        raise ConditionError("조건 선언 파일에는 최상위 'conditions' 배열이 필요하다.")

    if document.get("schema_version") != SCHEMA_VERSION:
        raise ConditionError(
            f"조건 선언 파일의 schema_version은 {SCHEMA_VERSION}이어야 한다."
        )

    unknown_top = set(document.keys()) - {"schema_version", "conditions"}
    if unknown_top:
        raise ConditionError(f"조건 선언 파일에 알 수 없는 설정 {sorted(unknown_top)}이 있다.")

    conditions_raw = document["conditions"]
    if not isinstance(conditions_raw, list) or not conditions_raw:
        raise ConditionError("'conditions'는 비어 있지 않은 배열이어야 한다.")

    conditions = [
        _parse_condition(raw, index=i) for i, raw in enumerate(conditions_raw)
    ]

    seen_ids: set[str] = set()
    for condition in conditions:
        if condition.id in seen_ids:
            raise ConditionError(f"조건 id '{condition.id}'가 중복되었다.")
        seen_ids.add(condition.id)

    return conditions


def expand_runs(conditions: list[Condition]) -> list[RunSpec]:
    """선언 순서대로 각 조건의 repeat을 펼쳐 실행 목록을 만든다."""

    runs: list[RunSpec] = []
    for condition in conditions:
        for i in range(1, condition.repeat + 1):
            runs.append(
                RunSpec(
                    condition_id=condition.id,
                    repeat_index=i,
                    repeat_total=condition.repeat,
                    requires_tools=condition.requires_tools,
                    tool_probes=condition.tool_probes,
                    injections=condition.injections,
                    repository_url=condition.repository_url,
                )
            )
    return runs


def run_spec_to_dict(run: RunSpec) -> dict[str, Any]:
    return run.to_dict()


def run_spec_from_dict(raw: Any) -> RunSpec:
    if not isinstance(raw, dict):
        raise ConditionError("condition snapshot은 객체여야 한다.")
    condition = _parse_condition(
        {
            "id": raw.get("condition_id"),
            "repeat": raw.get("repeat_total"),
            "requires_tools": raw.get("requires_tools", []),
            "tool_probes": raw.get("tool_probes", {}),
            "repository_url": raw.get("repository_url"),
            "injections": raw.get("injections", []),
        },
        index=0,
    )
    repeat_index = raw.get("repeat_index")
    if not isinstance(repeat_index, int) or isinstance(repeat_index, bool):
        raise ConditionError("condition snapshot의 repeat_index는 정수여야 한다.")
    return RunSpec(
        condition_id=condition.id,
        repeat_index=repeat_index,
        repeat_total=condition.repeat,
        requires_tools=condition.requires_tools,
        tool_probes=condition.tool_probes,
        injections=condition.injections,
        repository_url=condition.repository_url,
    )


def select_subset(
    conditions: list[Condition],
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[Condition]:
    """원하는 조건만 골라 선언 순서를 유지한 부분집합을 반환한다.

    `include`와 `exclude`를 동시에 지정하면 모호하므로 거부한다. 둘 다
    비어 있으면 전체를 그대로 반환한다(기존 동작과 동일).
    """

    if include and exclude:
        raise ConditionError("include와 exclude를 동시에 지정할 수 없다.")

    known_ids = {c.id for c in conditions}

    if include:
        unknown = set(include) - known_ids
        if unknown:
            raise ConditionError(f"선언에 없는 조건 id: {sorted(unknown)}")
        wanted = set(include)
        return [c for c in conditions if c.id in wanted]

    if exclude:
        unknown = set(exclude) - known_ids
        if unknown:
            raise ConditionError(f"선언에 없는 조건 id: {sorted(unknown)}")
        excluded = set(exclude)
        return [c for c in conditions if c.id not in excluded]

    return list(conditions)


def inspect(
    path: Path,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[RunSpec]:
    """선언을 읽어 정규화된 실행 목록을 반환한다. 설치·모델 호출은 하지 않는다.

    `include`/`exclude`로 원하는 조건만 골라 실행 목록을 만들 수 있다
    (요구사항 3번). 웹 백엔드(M15)도 이 함수를 그대로 호출한다.
    """

    conditions = load_conditions(path)
    conditions = select_subset(conditions, include=include, exclude=exclude)
    return expand_runs(conditions)


def needs_customizations(injections: tuple[Injection, ...]) -> bool:
    """이 실행이 `--safe-mode`가 꺼 버리는 처치(hook·plugin)를 요구하는가."""

    return any(i.type in CUSTOMIZATION_INJECTION_TYPES for i in injections)
