"""기존 collect 인터페이스와 다음 측정 조건 선택."""

import csv
from pathlib import Path

from token_bench.conditions import DEFAULT_CONDITIONS_PATH, load_conditions
from token_bench.ledger import (
    BASELINE_WINDOW, DEFAULT_ACTIVITY_PATH, DEFAULT_COMPARISON_PATH,
    DEFAULT_DIAGNOSTICS_PATH, DEFAULT_SUMMARY_PATH, SUMMARY_COLUMNS,
    collect, condition_label, rebuild_comparison,
)
from token_bench.workspace import PROMPT_PRESETS

# 어떤 프리셋으로 얼마나 모을지. `small`이 조건마다 이 횟수에 닿으면 `large`로
# 넘어간다 — 가벼운 과제에서 조건별 분산을 먼저 확정하고 무거운 과제로 옮기려는
# 것이다(사용자 결정). 횟수는 조건별 누적이며, 한 tick에 조건 하나만 돌린다.
PRESET_SEQUENCE = ("small", "large")
RUNS_PER_PRESET = 30


def successful_runs_by_condition(
    summary_path: Path, *, prompt_id: str, model: str | None = None
) -> dict[str, int]:
    """한 프리셋에서 조건별로 성공한 실행이 몇 건 쌓였는지 센다.

    `succeeded`만 센다 — 중간에 끊긴 실행은 그 조건의 표본이 아니다. `model`을
    주면 그 모델의 실행만 센다 — 모델마다 표본을 따로 채운다.

    `measurable=0`으로 표시된 실행도 세지 않는다. 성공했어도 평균에서 제외된
    실행(예: 구버전 CLI로 돌아 격리된 실행)을 표본으로 세면, 비교에 쓸 수 있는
    표본이 모자란 채로 다음 프리셋으로 넘어간다.
    """

    counts: dict[str, int] = {}
    if not summary_path.is_file():
        return counts
    with summary_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("prompt_id") != prompt_id:
                continue
            if model is not None and row.get("model") != model:
                continue
            if row.get("terminal_reason") != "succeeded" or row.get("measurable") == "0":
                continue
            condition = row.get("condition") or ""
            counts[condition] = counts.get(condition, 0) + 1
    return counts


def condition_priority(
    summary_path: Path,
    *,
    preset: str,
    conditions_path: Path = DEFAULT_CONDITIONS_PATH,
    model: str | None = None,
) -> list[str]:
    """표본이 적은 조건부터 나열한다. 한 tick은 이 중 실제로 돌 수 있는 첫 조건을 쓴다.

    한 tick에 조건 하나만 돌리므로(사용자 결정: 간격은 세트가 아니라 실험 단위다)
    매번 가장 뒤처진 조건을 집어 균등하게 쌓는다. 동수면 conditions.json의 선언
    순서를 따른다.

    하나가 아니라 순서 전체를 주는 이유: 어떤 조건의 도구가 runner에서 사라지면
    그 조건은 영구히 표본이 가장 적은 상태로 남아 매번 다시 뽑힌다. 그러면 나머지
    조건의 수집이 통째로 멈춘다(2026-09-29 headroom 실측: 4회 연속 실패, 다른
    조건은 한 번도 돌지 못했다). 호출자가 앞에서부터 돌 수 있는 것을 고르면
    고장난 조건 하나가 전체를 막지 않는다.
    """

    declared = [condition.id for condition in load_conditions(conditions_path)]
    counts = successful_runs_by_condition(summary_path, prompt_id=preset, model=model)
    return sorted(
        declared,
        key=lambda cid: (counts.get(condition_label(cid), 0), declared.index(cid)),
    )


def next_condition(
    summary_path: Path,
    *,
    preset: str,
    conditions_path: Path = DEFAULT_CONDITIONS_PATH,
) -> str:
    """표본이 가장 적은 조건 하나."""

    return condition_priority(
        summary_path, preset=preset, conditions_path=conditions_path
    )[0]


def next_preset(
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    *,
    conditions_path: Path = DEFAULT_CONDITIONS_PATH,
    runs_per_preset: int = RUNS_PER_PRESET,
    model: str | None = None,
) -> str:
    """지금 돌려야 할 프리셋을 정한다.

    선언된 모든 조건이 그 프리셋에서 `runs_per_preset`건을 채우면 다음 프리셋으로
    넘어간다. 조건 하나라도 모자라면 넘어가지 않는다 — 조건 간 비교가 목적이므로
    표본이 고르지 않은 채로 과제를 바꾸면 그 프리셋의 비교가 미완성으로 남는다.
    마지막 프리셋까지 채웠으면 그 프리셋을 계속 쓴다.
    """

    conditions = [
        condition_label(condition.id) for condition in load_conditions(conditions_path)
    ]
    for preset in PRESET_SEQUENCE:
        counts = successful_runs_by_condition(summary_path, prompt_id=preset, model=model)
        if any(counts.get(condition, 0) < runs_per_preset for condition in conditions):
            return preset
    return PRESET_SEQUENCE[-1]
