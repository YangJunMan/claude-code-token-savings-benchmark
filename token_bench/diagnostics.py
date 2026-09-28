"""한 실행이 왜 이렇게 됐는지(무엇을 잘못 읽고 같은 일을 반복했는지, 왜
timeout까지 끌렸는지)를 transcript에서 읽어 사람이 읽을 수 있는 이유로 남긴다.

정규식으로 test 실패·파일 재읽기만 잡던 방식을 LLM 요약으로 바꿨다 — 사용자
결정. 정규식은 "무슨 일이 있었나"(테스트가 실패했다)는 찍어도 "무엇을 잘못
인식했나"는 못 쓰고, `Read` 도구만 보기 때문에 파일을 `cat`으로 읽는 조건에서는
같은 사건을 아예 놓쳤다.

비용은 두 가지로 누른다. 모델은 가장 싼 축(`claude-haiku-4-5`)을 쓰고, raw
transcript(1MB ≈ 250K 토큰, Haiku의 200K context를 넘는다) 대신 turn별 도구
호출 요약만 넣는다.

자격증명이 없거나 호출이 실패하면 manifest를 건드리지 않고 넘어간다 — 진단은
부가 정보이고, 이것 때문에 collect 전체가 실패하면 측정 데이터를 잃는다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 기본은 현행 최저가 모델. 세대가 바뀌면 이 id가 막히므로, 그때는 Models API가
# 실제로 주는 목록에서 아래 선호 순서(싼 계열 먼저)로 다시 고른다. 가격 필드는
# API에 없어서 계열 이름으로 고른다.
DEFAULT_MODEL = os.environ.get("TOKEN_BENCH_DIAGNOSIS_MODEL", "claude-haiku-4-5")
MODEL_PREFERENCE = ("haiku", "sonnet")
# Haiku의 200K context와 회당 비용을 함께 누르는 상한. 넘는 만큼은 뒤를 자른다
# — 반복·timeout은 실행 후반에 나타나므로 앞이 아니라 중간을 버린다.
MAX_DIGEST_CHARS = 60_000
MAX_RESULT_CHARS = 300

_SYSTEM = """너는 Claude Code 실행 기록을 읽고 원인을 설명하는 분석자다.

입력은 한 실행의 turn별 도구 호출 요약이다. 다음을 한국어로 쓴다.

- 같은 일을 반복했다면, 무엇을 잘못 인식해서 반복이 시작됐는지 쓴다. 반복
  사실만 나열하지 말고 오해의 내용을 지목한다.
- 실행이 timeout으로 끊겼다면, 어디서 진행이 멈췄고 무엇이 그 상태를 벗어나지
  못하게 했는지 쓴다.
- 토큰·turn 수가 이상하게 늘어난 구간이 보이면 그 이유를 쓴다.
- 특이사항이 없으면 events를 빈 배열로 둔다. 없는 원인을 만들지 않는다.

출력은 JSON 하나만 낸다. 설명이나 코드블록을 붙이지 않는다.

{"summary": "한 줄 요약",
 "events": [{"turn": 12, "kind": "repeated_misread|timeout_stall|token_spike|other",
             "summary": "turn 12: 무엇을 어떻게 잘못 봤고 그래서 무엇이 반복됐는지"}]}
"""


def _events(stdout_path: str | Path) -> list[tuple[int, str, dict, str]]:
    """turn 순서대로 (turn, 도구 이름, 입력, 결과 텍스트)를 뽑는다."""

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


def _digest(stdout_path: str | Path) -> str:
    """transcript를 turn별 한 줄 요약으로 압축한다."""

    lines: list[str] = []
    for turn, name, inp, result in _events(stdout_path):
        target = (
            inp.get("command")
            or inp.get("file_path")
            or inp.get("pattern")
            or inp.get("description")
            or ""
        )
        head = " ".join(str(result).split())[:MAX_RESULT_CHARS]
        lines.append(f"turn {turn} {name}: {str(target)[:200]} => {head}")

    text = "\n".join(lines)
    if len(text) <= MAX_DIGEST_CHARS:
        return text
    # 반복과 정지는 실행 후반에 드러난다. 앞뒤를 남기고 가운데를 버린다.
    keep = MAX_DIGEST_CHARS // 2
    return f"{text[:keep]}\n...(중략)...\n{text[-keep:]}"


def _create(client, model: str, prompt: str):
    return client.messages.create(
        model=model,
        max_tokens=1500,
        system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )


def _cheapest_available(client) -> str | None:
    """Models API가 주는 목록에서 선호 계열 순으로 하나 고른다.

    같은 계열이 여럿이면 `created_at`이 가장 최근인 것을 쓴다 — id 사전순은
    버전 순서가 아니다(`claude-haiku-10-0` < `claude-haiku-4-5`).
    """

    try:
        available = [
            (model.id, getattr(model, "created_at", None) or "")
            for model in client.models.list()
        ]
    except Exception as exc:
        print(f"모델 목록을 읽을 수 없다: {exc}", file=sys.stderr)
        return None
    for family in MODEL_PREFERENCE:
        matches = [entry for entry in available if family in entry[0]]
        if matches:
            return max(matches, key=lambda entry: str(entry[1]))[0]
    return None


def diagnose(
    stdout_path: str | Path,
    *,
    status: str = "succeeded",
    condition_id: str = "",
    model: str = DEFAULT_MODEL,
) -> dict | None:
    """실행 하나를 LLM으로 진단한다. 자격증명·호출 실패 시 None."""

    digest = _digest(stdout_path)
    if not digest:
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("진단 건너뜀: ANTHROPIC_API_KEY가 없다.", file=sys.stderr)
        return None

    try:
        import anthropic
    except ImportError:
        print("진단 건너뜀: anthropic 패키지가 없다.", file=sys.stderr)
        return None

    prompt = (
        f"조건: {condition_id or '(미지정)'}\n"
        f"실행 종료 상태: {status}\n\n"
        f"turn 기록:\n{digest}"
    )
    client = anthropic.Anthropic()
    try:
        response = _create(client, model, prompt)
    except anthropic.NotFoundError:
        # 이 id가 은퇴했다. 남아 있는 모델 중 싼 계열로 한 번 더 시도한다.
        fallback = _cheapest_available(client)
        if fallback is None:
            print(f"진단 실패: {model}이 없고 대체 모델도 못 찾았다.", file=sys.stderr)
            return None
        print(f"{model} 사용 불가 — {fallback}으로 대체한다.", file=sys.stderr)
        try:
            response = _create(client, fallback, prompt)
        except Exception as exc:
            print(f"진단 실패({fallback}): {exc}", file=sys.stderr)
            return None
    except Exception as exc:  # 진단 실패가 측정 데이터 수집을 막지 않는다.
        print(f"진단 실패({model}): {exc}", file=sys.stderr)
        return None

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if text.startswith("```"):
        # ```json ... ``` 으로 감싸 오는 경우가 흔하다. 울타리만 벗긴다.
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        # 모델이 JSON을 안 냈으면 원문을 그대로 한 건으로 남긴다. 버리면
        # 왜 진단이 비었는지 알 수 없다.
        return {"summary": text[:500], "events": [{"turn": 0, "kind": "other", "summary": text[:1000]}]}
    if not isinstance(report, dict) or not report.get("events"):
        return None
    return {"summary": str(report.get("summary", "")), "events": report["events"]}


def update_manifest(
    run_id: str,
    stdout_path: str | Path,
    manifest_path: Path,
    *,
    status: str = "succeeded",
    condition_id: str = "",
) -> None:
    """모든 run_id의 진단 결과를 파일 하나(`data/run-diagnostics.json`)에 모은다.

    웹 페이지가 실행을 고를 때마다 파일을 따로 fetch하지 않고, 부팅 시 이
    manifest 하나만 읽으면 되게 하려는 것이다. 특이사항 없는 실행은 항목을
    아예 안 만든다(예전에 지운 run_id가 다시 쌓이는 것도 여기서 막힌다).
    """
    report = diagnose(stdout_path, status=status, condition_id=condition_id)

    manifest: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}

    if report:
        manifest[run_id] = report
    else:
        manifest.pop(run_id, None)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
