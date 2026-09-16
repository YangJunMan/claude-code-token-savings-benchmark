"""실행 중인 작업의 stdout.jsonl에서 최근 이벤트를 뽑아 사람이 읽을 수 있게 만든다.

웹의 "실험 설정" 탭이 몇 초마다 이 결과를 폴링해서 "지금 모델이 뭘 하고
있는지" 보여준다. 파일을 그냥 읽기만 하므로 Windows·WSL·Linux·macOS 어디서든
`token_bench serve`가 도는 컴퓨터 기준으로 동일하게 동작한다 — OS별 분기가
없다.
"""

from __future__ import annotations

import json
from pathlib import Path

_PREVIEW_LIMIT = 400


def _preview(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def tail(stdout_path: str | Path, *, limit: int = 20) -> list[dict]:
    """최근 이벤트 `limit`개를 시간순으로 반환한다. 로그가 없으면 빈 목록."""

    path = Path(stdout_path)
    if not path.is_file():
        return []

    events: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("isSidechain"):
            continue

        row_type = row.get("type")
        if row_type == "assistant":
            for block in row.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    events.append({"kind": "text", "text": _preview(block["text"])})
                elif block.get("type") == "tool_use":
                    events.append(
                        {
                            "kind": "tool_use",
                            "name": block.get("name", ""),
                            "input": _preview(json.dumps(block.get("input") or {}, ensure_ascii=False)),
                        }
                    )
        elif row_type == "user":
            for block in row.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content")
                    if isinstance(content, list):
                        content = " ".join(
                            b.get("text", "") for b in content if isinstance(b, dict)
                        )
                    events.append({"kind": "tool_result", "text": _preview(str(content or ""))})
        elif row_type == "result":
            events.append(
                {
                    "kind": "result",
                    "is_error": bool(row.get("is_error")),
                    "num_turns": row.get("num_turns"),
                    "text": _preview(str(row.get("result", ""))),
                }
            )

    return events[-limit:]
