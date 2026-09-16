"""새 절약법을 대화형으로 `conditions.json`에 추가한다.

`docs/ADDING-A-SKILL.md`를 읽고 5가지 injection type(`prompt_overlay`·
`config_ref`·`plugin_dir`·`env`·`proxy`) 중 뭘 써야 할지 직접 고르는 건
어렵다. 이 모듈은 "이 도구가 CLI 인자로 켜지나요, 설정 파일로 켜지나요?" 같은
질문으로 그 선택을 대신하고, 결과 JSON을 `conditions.py`의 검증기로 확인한
뒤에만 파일에 쓴다 — 스키마는 여기서 새로 정의하지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from token_bench.conditions import ConditionError, load_conditions

InputFn = Callable[[str], str]
PrintFn = Callable[[str], None]

_INJECTION_MENU = """이 절약법은 어떻게 켜집니까?
  1) 프롬프트에 지시문을 덧붙인다 (prompt_overlay)
  2) Claude Code 설정 파일을 참조시킨다 — hook 등 (config_ref)
  3) 플러그인 디렉터리를 켠다 (plugin_dir)
  4) 환경변수를 설정한다 (env)
  5) CLI를 프록시 서버로 띄운다 (proxy)
  6) (더 추가할 게 없다)
"""


def _ask(prompt: str, input_fn: InputFn, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input_fn(f"{prompt}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default


def _ask_yes_no(prompt: str, input_fn: InputFn, *, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input_fn(f"{prompt} ({hint}): ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


def _ask_relative_path(prompt: str, input_fn: InputFn) -> str:
    while True:
        path = _ask(prompt, input_fn)
        posix = Path(path)
        if posix.is_absolute() or ".." in posix.parts:
            print("저장소 내부 상대경로만 된다 (예: benchmark/prompts/my-skill.txt).")
            continue
        return path


def _wizard_injection(
    *, input_fn: InputFn, print_fn: PrintFn, requires_tools: list[str]
) -> dict | None:
    print_fn(_INJECTION_MENU)
    choice = _ask("번호 선택", input_fn, default="6")

    if choice == "1":
        path = _ask_relative_path(
            "프롬프트 overlay 파일 경로 (없으면 새로 만든다)", input_fn
        )
        if not Path(path).is_file():
            text = _ask("파일에 넣을 지시문 (예: '답변을 3문장 이내로 써라')", input_fn)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(text + "\n", encoding="utf-8")
            print_fn(f"{path} 생성함.")
        return {"type": "prompt_overlay", "path": path}

    if choice == "2":
        path = _ask_relative_path(
            "설정 JSON 파일 경로 (benchmark/settings/ 아래 권장)", input_fn
        )
        return {"type": "config_ref", "path": path}

    if choice == "3":
        path = _ask("플러그인 디렉터리 경로 (glob 가능)", input_fn)
        return {"type": "plugin_dir", "path": path}

    if choice == "4":
        name = _ask("환경변수 이름", input_fn)
        value = _ask("환경변수 값", input_fn)
        return {"type": "env", "name": name, "value": value}

    if choice == "5":
        if not requires_tools:
            print_fn("proxy를 쓰려면 먼저 requires_tools에 실행 파일 이름이 있어야 한다.")
            return None
        binary = _ask(
            f"어떤 도구를 프록시로 띄우나 (requires_tools: {requires_tools})",
            input_fn,
            default=requires_tools[0],
        )
        args_raw = _ask(
            "실행 인자, 쉼표로 구분 (포트는 {port}, 로그는 {log_path}로 쓴다)",
            input_fn,
            default="proxy,--port,{port}",
        )
        ready_path = _ask("준비 확인용 HTTP 경로", input_fn, default="/readyz")
        return {
            "type": "proxy",
            "binary": binary,
            "args": [a.strip() for a in args_raw.split(",") if a.strip()],
            "ready_path": ready_path,
        }

    return None


def run_wizard(*, input_fn: InputFn = input, print_fn: PrintFn = print) -> dict:
    """질문에 답하면 검증 전 조건 JSON dict를 만든다."""

    print_fn("새 절약법을 추가한다. 모르는 항목은 그냥 Enter — 기본값을 쓴다.\n")

    cond_id = _ask("조건 id (소문자, 하이픈 가능, 예: my-skill)", input_fn)
    repository_url = _ask(
        "공식 GitHub repository URL (없으면 Enter)", input_fn, default=""
    )

    needs_tool = _ask_yes_no(
        "이 절약법을 쓰려면 별도 CLI 도구를 설치해야 하나?", input_fn, default=False
    )
    requires_tools: list[str] = []
    tool_probes: dict[str, list[str]] = {}
    if needs_tool:
        tool = _ask("도구 실행 파일 이름 (예: headroom)", input_fn)
        probe = _ask("설치 확인 인자, 쉼표로 구분", input_fn, default="--version")
        requires_tools = [tool]
        tool_probes = {tool: [a.strip() for a in probe.split(",") if a.strip()]}

    repeat_raw = _ask("반복 횟수", input_fn, default="1")
    try:
        repeat = int(repeat_raw)
    except ValueError:
        repeat = 1

    injections: list[dict] = []
    while True:
        injection = _wizard_injection(
            input_fn=input_fn, print_fn=print_fn, requires_tools=requires_tools
        )
        if injection is None:
            break
        injections.append(injection)
        print_fn(f"추가됨: {injection}\n")

    condition: dict = {
        "id": cond_id,
        "repeat": max(repeat, 1),
        "requires_tools": requires_tools,
        "tool_probes": tool_probes,
        "injections": injections,
    }
    if repository_url:
        condition["repository_url"] = repository_url
    return condition


def append_condition(conditions_path: Path, condition: dict) -> None:
    """조건 하나를 선언 파일에 추가한다. 기존 검증기를 통과할 때만 쓴다.

    검증은 파일에 쓰기 *전에* 임시로 합친 문서 전체를 `load_conditions`로
    돌려서 한다 — 이 조건 하나만 봐서는 안 잡히는 중복 id 같은 오류가 있다.
    """

    document = json.loads(conditions_path.read_text(encoding="utf-8"))
    document["conditions"].append(condition)

    tmp_path = conditions_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        load_conditions(tmp_path)  # ConditionError를 여기서 그대로 올린다
    except ConditionError:
        tmp_path.unlink(missing_ok=True)
        raise
    tmp_path.replace(conditions_path)
