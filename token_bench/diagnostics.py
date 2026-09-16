"""한 실행이 왜 이렇게 됐는지(테스트 실패→재수정, 같은 파일 재확인 등) 사람이
읽을 수 있는 이유를 transcript에서 뽑는다.

"BASE 대비 처리 토큰이 더 컸다" 같은 숫자만으로는 원인을 알 수 없다 - 그
숫자 뒤에 있는 사건(테스트가 실패해서 고쳤다, 같은 파일을 다시 읽었다 등)을
찾아 turn 단위로 남긴다. LLM 요약을 쓰지 않는다 - 매 collect마다 모델을
호출하면 비용이 들고, 정규식으로 충분히 잡히는 패턴(test 실패/통과, 파일
재읽기)이다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_FAIL_MARKERS = re.compile(r"FAILED \(|Traceback \(most recent call last\)|ERROR: ")
_PASS_MARKERS = re.compile(r"\bOK\b\s*$")
_TEST_NAME = re.compile(r"\b(test_\w+)\b")
_ERROR_LINE = re.compile(r"(AssertionError|AttributeError|TypeError|ValueError|KeyError|Exception)[:\s].{0,120}")
_TEST_COMMAND = re.compile(r"unittest|pytest|go test|npm test|npm run test")


@dataclass(frozen=True)
class Finding:
    turn: int
    kind: str  # "test_failure" | "test_recovered" | "repeated_read"
    summary: str


def _events(stdout_path: str | Path) -> list[dict]:
    path = Path(stdout_path)
    if not path.is_file():
        return []
    msgs: dict[str, list[tuple[str, str, dict]]] = {}
    order: list[str] = []
    results: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
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


def diagnose(stdout_path: str | Path) -> list[Finding]:
    """test 실패→재통과, 같은 파일 재읽기 패턴을 찾아 turn 순서대로 반환한다."""

    calls = _events(stdout_path)
    findings: list[Finding] = []

    last_failure: str | None = None  # 가장 최근 실패한 turn의 테스트 이름들
    read_seen: dict[str, int] = {}

    for turn, name, inp, result in calls:
        if name == "Bash" and _TEST_COMMAND.search(inp.get("command", "")):
            if _FAIL_MARKERS.search(result):
                error = _ERROR_LINE.search(result)
                test_name = _TEST_NAME.search(result)
                detail = error.group(0) if error else "테스트 실패"
                which = f" ({test_name.group(1)})" if test_name else ""
                findings.append(Finding(
                    turn, "test_failure",
                    f"turn {turn}: 테스트 실패{which} — {detail}",
                ))
                last_failure = test_name.group(1) if test_name else "이전 테스트"
            elif _PASS_MARKERS.search(result) and last_failure:
                findings.append(Finding(
                    turn, "test_recovered",
                    f"turn {turn}: 앞서 실패했던 테스트({last_failure}) 수정 후 통과",
                ))
                last_failure = None
        elif name == "Read":
            file_path = inp.get("file_path", "")
            if file_path:
                if file_path in read_seen:
                    findings.append(Finding(
                        turn, "repeated_read",
                        f"turn {turn}: {Path(file_path).name} 다시 읽음"
                        f"(처음 turn {read_seen[file_path]}) — 앞서 읽은 내용으로"
                        " 부족했거나 다시 확인이 필요했다는 뜻",
                    ))
                else:
                    read_seen[file_path] = turn

    return findings


def diagnosis_summary(findings: list[Finding]) -> str:
    if not findings:
        return "특이사항 없음 — 되짚어야 할 실패·재확인이 감지되지 않았다."
    return " / ".join(f.summary for f in findings)


def update_manifest(run_id: str, stdout_path: str | Path, manifest_path: Path) -> None:
    """모든 run_id의 진단 결과를 파일 하나(`data/run-diagnostics.json`)에 모은다.

    웹 페이지가 실행을 고를 때마다 파일을 따로 fetch하지 않고, 부팅 시 이
    manifest 하나만 읽으면 되게 하려는 것이다. 특이사항 없는 실행은 항목을
    아예 안 만든다(예전에 지운 run_id가 다시 쌓이는 것도 여기서 막힌다).
    """
    findings = diagnose(stdout_path)

    manifest: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}

    if findings:
        manifest[run_id] = {
            "summary": diagnosis_summary(findings),
            "events": [f.__dict__ for f in findings],
        }
    else:
        manifest.pop(run_id, None)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
