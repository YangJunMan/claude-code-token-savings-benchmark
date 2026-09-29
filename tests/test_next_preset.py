"""무인 스케줄러가 어떤 프리셋으로 돌릴지 정하는 규칙."""

import csv
from pathlib import Path

import pytest

from token_bench.collect import (
    RUNS_PER_PRESET,
    SUMMARY_COLUMNS,
    next_condition,
    next_preset,
    successful_runs_by_condition,
)

CONDITIONS = Path("benchmark/conditions.json")
LABELS = ("BASE", "BE_BRIEF", "HEADROOM", "CAVEMAN-FULL", "RTK")


def _summary(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in SUMMARY_COLUMNS})
    return path


def _runs(preset: str, *, per_condition: dict[str, int], status="succeeded") -> list[dict]:
    rows = []
    for condition, count in per_condition.items():
        for i in range(count):
            rows.append({
                "run_id": f"{preset}-{condition}-{i}",
                "condition": condition,
                "prompt_id": preset,
                "terminal_reason": status,
            })
    return rows


def test_starts_with_small_when_nothing_ran(tmp_path):
    path = _summary(tmp_path / "run-summary.csv", [])
    assert next_preset(path, conditions_path=CONDITIONS) == "small"


def test_missing_summary_is_treated_as_empty(tmp_path):
    assert next_preset(tmp_path / "absent.csv", conditions_path=CONDITIONS) == "small"


def test_stays_on_small_until_every_condition_reaches_the_threshold(tmp_path):
    counts = {label: RUNS_PER_PRESET for label in LABELS}
    counts["RTK"] = RUNS_PER_PRESET - 1  # 하나만 모자라도 넘어가지 않는다
    path = _summary(tmp_path / "run-summary.csv", _runs("small", per_condition=counts))
    assert next_preset(path, conditions_path=CONDITIONS) == "small"


def test_switches_to_large_when_all_conditions_are_full(tmp_path):
    path = _summary(
        tmp_path / "run-summary.csv",
        _runs("small", per_condition={label: RUNS_PER_PRESET for label in LABELS}),
    )
    assert next_preset(path, conditions_path=CONDITIONS) == "large"


def test_failed_runs_do_not_count_toward_the_threshold(tmp_path):
    rows = _runs("small", per_condition={label: RUNS_PER_PRESET for label in LABELS})
    rows += _runs("small", per_condition={"BASE": 5}, status="timeout")
    rows = [r for r in rows if not (r["condition"] == "BASE" and r["terminal_reason"] == "succeeded")][:]
    rows += _runs("small", per_condition={"BASE": RUNS_PER_PRESET - 1})
    path = _summary(tmp_path / "run-summary.csv", rows)
    assert next_preset(path, conditions_path=CONDITIONS) == "small"


def test_stays_on_large_after_the_last_preset_is_full(tmp_path):
    full = {label: RUNS_PER_PRESET for label in LABELS}
    path = _summary(
        tmp_path / "run-summary.csv",
        _runs("small", per_condition=full) + _runs("large", per_condition=full),
    )
    assert next_preset(path, conditions_path=CONDITIONS) == "large"


def test_counts_only_the_requested_preset(tmp_path):
    path = _summary(
        tmp_path / "run-summary.csv",
        _runs("large", per_condition={label: RUNS_PER_PRESET for label in LABELS}),
    )
    counts = successful_runs_by_condition(path, prompt_id="small")
    assert counts == {}
    # large만 찼어도 small이 비어 있으면 small을 먼저 채운다.
    assert next_preset(path, conditions_path=CONDITIONS) == "small"


def test_picks_the_condition_with_the_fewest_runs(tmp_path):
    """한 tick에 조건 하나만 돌리므로 매번 가장 뒤처진 조건을 집는다."""
    counts = {label: 5 for label in LABELS}
    counts["HEADROOM"] = 2
    path = _summary(tmp_path / "run-summary.csv", _runs("small", per_condition=counts))
    assert next_condition(path, preset="small", conditions_path=CONDITIONS) == "headroom"


def test_ties_follow_the_declared_order(tmp_path):
    path = _summary(
        tmp_path / "run-summary.csv",
        _runs("small", per_condition={label: 3 for label in LABELS}),
    )
    # conditions.json의 첫 조건이 base다.
    assert next_condition(path, preset="small", conditions_path=CONDITIONS) == "base"


def test_a_condition_with_no_runs_wins(tmp_path):
    counts = {label: 7 for label in LABELS if label != "RTK"}
    path = _summary(tmp_path / "run-summary.csv", _runs("small", per_condition=counts))
    assert next_condition(path, preset="small", conditions_path=CONDITIONS) == "rtk"


def test_condition_choice_is_per_preset(tmp_path):
    """small을 다 채우고 large로 넘어가면 large 기준으로 다시 고른다."""
    full = {label: RUNS_PER_PRESET for label in LABELS}
    rows = _runs("small", per_condition=full)
    rows += _runs("large", per_condition={"BASE": 2})
    path = _summary(tmp_path / "run-summary.csv", rows)
    assert next_preset(path, conditions_path=CONDITIONS) == "large"
    # large에서는 BASE만 2건 있으므로 아직 0건인 조건이 먼저다.
    assert next_condition(path, preset="large", conditions_path=CONDITIONS) == "be-brief"


def test_estimate_accepts_an_explicit_isolation_mode():
    """조건 하나씩 돌리면 격리 모드가 조건마다 갈린다 — 지정으로 고정해야 한다."""
    import subprocess
    import sys

    seen = set()
    for condition in ("base", "rtk"):
        out = subprocess.run(
            [sys.executable, "-m", "token_bench", "estimate", "--only", condition,
             "--isolation", "project-settings", "--timeout-seconds", "1800",
             "--preset", "small"],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            pytest.skip(f"이 환경에서 {condition} preflight를 통과하지 못한다")
        import json
        seen.add(json.loads(out.stdout)["isolation"])
    assert seen == {"project-settings"}


def test_priority_lists_every_condition_least_sampled_first(tmp_path):
    """조건 하나가 영구히 깨져도 나머지 수집이 멈추지 않으려면, 하나가 아니라
    순서 전체가 필요하다(2026-09-29 headroom 실측)."""
    from token_bench.collect import condition_priority

    counts = {label: 5 for label in LABELS}
    counts["HEADROOM"] = 0
    counts["RTK"] = 2
    path = _summary(tmp_path / "run-summary.csv", _runs("small", per_condition=counts))

    order = condition_priority(path, preset="small", conditions_path=CONDITIONS)

    assert order[0] == "headroom"
    assert order[1] == "rtk"
    assert set(order) == {"base", "be-brief", "headroom", "caveman-full", "rtk"}
    # 첫 조건은 next_condition과 같아야 한다.
    assert order[0] == next_condition(path, preset="small", conditions_path=CONDITIONS)
