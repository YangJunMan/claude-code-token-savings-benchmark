"""Claude stream-json의 primary events, usage, turn/tool 기록을 한 번 읽는다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PATH_TOOLS = ("Read", "Write", "Edit", "NotebookEdit")
_ABSOLUTE = re.compile(r"(?:/[^\s\"\']*)+")


def _relative_to_worktree(path):
    """Name the file by its place in the task, not on the machine that ran it.

    Every run happens in a throwaway worktree whose absolute path contains the
    operator's home directory, and the CI secret scan fails the build on one.
    """
    marker = "/worktree/"
    if marker in path:
        return path.split(marker, 1)[1]
    return ""


def tool_target(name, payload):
    """What a single tool call acted on, or "" when it cannot be named safely."""
    payload = payload or {}
    if name in PATH_TOOLS:
        return _relative_to_worktree(str(payload.get("file_path", "")))
    if name == "Bash":
        command = str(payload.get("command", ""))
        # A shell line can carry anything, including paths outside the worktree,
        # so only the program name is kept.
        command = re.sub(r'^\s*cd\s+"[^"]*"\s*&&\s*', "", command)
        program = command.strip().split()[0] if command.strip() else ""
        return "" if _ABSOLUTE.fullmatch(program) or "/" in program else program
    return ""


_USAGE_LIMIT_KEYWORDS = (
    "usage limit",
    "session limit",
    "weekly limit",
    "rate limit",
    "limit reached",
    "quota exceeded",
)
# "You've hit your <무엇> limit · resets ..." 꼴. 한도 종류(session·weekly·opus 등)가
# 늘어도 문구 틀은 같아서 키워드 목록을 따라 늘리지 않아도 잡힌다.
_HIT_LIMIT = re.compile(r"hit your [\w-]+(?: [\w-]+)? limit", re.IGNORECASE)


def is_usage_limit_error(reason: str | None) -> bool:
    """중단 사유가 구독 사용 한도로 보이면 참을 돌려준다.

    2026-09-15 실제 rtk 실행이 "You've hit your session limit · resets
    2:50am"으로 끊긴 사례(test_treatments.py)가 있어 "session limit"은
    확인된 문구다. 2026-10-21 bench 실행은 "You've hit your weekly limit"으로
    끊겼는데 예전 목록에 없어 한도가 아닌 중단(blocked)으로 기록됐다. 나머지는
    비슷한 다른 한도 메시지를 짐작으로 넓힌 것이라 다른 이유로 중단된 실행을
    오탐할 수 있고, 반대로 놓칠 수도 있다.
    """

    if not reason:
        return False
    lowered = reason.lower()
    return bool(_HIT_LIMIT.search(reason)) or any(
        keyword in lowered for keyword in _USAGE_LIMIT_KEYWORDS
    )


@dataclass(frozen=True)
class Transcript:
    events: tuple[dict, ...]
    parse_error: str | None
    has_output: bool

    @classmethod
    def load(cls, source: str | Path | Transcript | None) -> Transcript:
        if isinstance(source, cls):
            return source
        path = Path(source) if source else None
        if path is None or not path.is_file():
            return cls((), "stdout 로그 파일이 없거나 비어 있다.", False)
        raw = path.read_bytes()
        if not raw:
            return cls((), "stdout 로그 파일이 없거나 비어 있다.", False)
        events = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and not event.get("isSidechain"):
                events.append(event)
        return cls(tuple(events), None if events else "stdout 로그를 JSON Lines로 해석할 수 없다.", True)

    @property
    def system_event(self) -> dict:
        return next((e for e in self.events if e.get("type") == "system"), {})

    @property
    def result_event(self) -> dict:
        return next((e for e in reversed(self.events) if e.get("type") == "result"), {})

    @property
    def interrupted_reason(self) -> str | None:
        event = self.result_event
        if not event.get("is_error"):
            return None
        return str(event.get("result") or "원본 로그에 사유 없음")[:300]

    def assistant_messages(self):
        """Collapse the transcript into one usage record per assistant message.

        Claude Code writes one JSONL line per content block and repeats the whole
        ``usage`` object on each of them.  Sub-agent turns are skipped: they run on
        their own context, so mixing them into this one's growth would attribute a
        sub-agent's prompt to whichever tool the main thread called next.
        """
        usages = {}
        tools = {}
        targets = {}
        stops = {}
        models = {}
        order = []
        for row in self.events:
            if row.get("type") != "assistant":
                continue
            message = row.get("message", {})
            message_id = message.get("id")
            usage = message.get("usage")
            if not message_id or not usage:
                continue
            if message_id not in usages:
                usages[message_id] = usage
                stops[message_id] = message.get("stop_reason") or ""
                models[message_id] = message.get("model") or ""
                tools[message_id] = []
                targets[message_id] = []
                order.append(message_id)
            for block in message.get("content", []):
                if block.get("type") == "tool_use":
                    tools[message_id].append(block.get("name"))
                    target = tool_target(block.get("name"), block.get("input"))
                    if target:
                        targets[message_id].append(target)
        return [(usages[key], tuple(tools[key]), tuple(targets[key]), stops[key],
                 models[key]) for key in order]


    def tool_events(self) -> list[tuple[int, str, dict, str]]:
        """turn 순서대로 (turn, 도구 이름, 입력, 결과 텍스트)를 뽑는다."""

        msgs: dict[str, list[tuple[str, str, dict]]] = {}
        order: list[str] = []
        results: dict[str, str] = {}
        for row in self.events:
            if row.get("isSidechain"):
                continue
            if row.get("type") == "assistant":
                message = row.get("message", {})
                mid = message.get("id")
                if not mid or not message.get("usage"):
                    continue
                if mid not in msgs:
                    msgs[mid] = []
                    order.append(mid)
                for block in message.get("content", []):
                    if block.get("type") == "tool_use":
                        msgs[mid].append((block.get("id"), block.get("name"), block.get("input") or {}))
            elif row.get("type") == "user":
                for block in row.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        content = block.get("content")
                        if isinstance(content, list):
                            content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
                        results[block.get("tool_use_id")] = str(content or "")

        out: list[tuple[int, str, dict, str]] = []
        for turn, mid in enumerate(order, 1):
            for tool_id, name, inp in msgs[mid]:
                out.append((turn, name, inp, results.get(tool_id, "")))
        return out
