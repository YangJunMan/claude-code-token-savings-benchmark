"""측정 대상 모델 목록. 모델마다 BASE가 따로 있어 모델 세대를 서로 비교한다.

`active`는 정확히 하나다 — 새 모델이 나오면 이전 모델은 `frozen`으로 두고
새 모델만 수집한다(사용자 결정). `frozen` 모델의 기존 데이터는 그대로 남는다.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_MODELS_PATH = Path("benchmark/models.json")
STATUSES = frozenset({"active", "frozen"})


class ModelsError(Exception):
    pass


def active_model(path: Path = DEFAULT_MODELS_PATH) -> str:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelsError(f"모델 목록을 찾을 수 없다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ModelsError(f"모델 목록이 올바른 JSON이 아니다: {exc}") from exc

    models = raw.get("models")
    if not isinstance(models, list) or not models:
        raise ModelsError("'models'는 비어 있지 않은 배열이어야 한다.")
    ids = []
    for entry in models:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
            raise ModelsError("모델 항목에는 비어 있지 않은 'id' 문자열이 필요하다.")
        if entry.get("status") not in STATUSES:
            raise ModelsError(f"'{entry['id']}'의 status는 {sorted(STATUSES)} 중 하나여야 한다.")
        ids.append(entry["id"])
    if len(set(ids)) != len(ids):
        raise ModelsError("모델 id가 중복됐다.")
    active = [m["id"] for m in models if m["status"] == "active"]
    if len(active) != 1:
        raise ModelsError(f"active 모델은 정확히 하나여야 한다. 현재 {len(active)}개.")
    return active[0]
