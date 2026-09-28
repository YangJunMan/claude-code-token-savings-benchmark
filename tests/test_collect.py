import csv
from pathlib import Path

from token_bench.collect import SUMMARY_COLUMNS, _rebuild_comparison


def _write_summary(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in SUMMARY_COLUMNS})


def _row(run_id, condition, *, run_date, processed=1000, cost=1.0, tax=100, quality=100):
    return {
        "run_date": run_date,
        "run_id": run_id,
        "condition": condition,
        "prompt_id": "small",
        "cost_usd": cost,
        "quality_score": quality,
        "measurable": "1",
        "processed_tokens": processed,
        "context_tax_tokens": tax,
    }


def _comparison(tmp_path, rows) -> list[dict]:
    summary_path = tmp_path / "run-summary.csv"
    comparison_path = tmp_path / "comparison.csv"
    _write_summary(summary_path, rows)
    _rebuild_comparison(summary_path, comparison_path)
    with comparison_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_base_from_an_earlier_date_is_still_the_baseline(tmp_path):
    """2026-09-21 실측 버그: base는 9/19에, 재시도한 조건은 9/20에 끝났다.
    날짜로 묶던 예전 로직은 9/20 그룹에 base가 없어 그 조건을 비교표에서 통째로
    빠뜨렸다. 기준선을 시간축에서 끌어오면 날짜가 갈려도 비교된다."""

    rows = _comparison(tmp_path, [
        _row("batch1-base__r1", "BASE", run_date="2026-09-19", processed=1000, cost=1.0),
        _row("batch2-rtk__r1", "RTK", run_date="2026-09-20", processed=900, cost=0.9),
    ])

    assert len(rows) == 1
    assert rows[0]["condition"] == "RTK"
    assert rows[0]["run_date"] == "2026-09-20"  # 처치 실행의 날짜
    assert rows[0]["processed_delta_pct"] == "-10.0"


def test_a_batch_holding_one_condition_still_gets_compared(tmp_path):
    """bench.yml은 한 번에 조건 하나만 돌린다 — batch에 base가 같이 있는 일이
    없다. batch로 묶는 방식이었다면 비교 행이 하나도 생기지 않는다."""

    rows = _comparison(tmp_path, [
        _row("b1-base__r1", "BASE", run_date="2026-09-19", processed=1000),
        _row("b2-rtk__r1", "RTK", run_date="2026-09-19", processed=900),
        _row("b3-headroom__r1", "HEADROOM", run_date="2026-09-19", processed=1100),
    ])

    assert {r["condition"] for r in rows} == {"RTK", "HEADROOM"}
    assert {r["condition"]: r["processed_delta_pct"] for r in rows} == {
        "RTK": "-10.0", "HEADROOM": "10.0",
    }


def test_baseline_is_the_mean_of_the_window(tmp_path):
    rows = _comparison(tmp_path, [
        _row("b1-base__r1", "BASE", run_date="2026-09-19", processed=1000),
        _row("b2-base__r1", "BASE", run_date="2026-09-19", processed=2000),
        _row("b3-rtk__r1", "RTK", run_date="2026-09-20", processed=1350),
    ])

    assert len(rows) == 1
    assert rows[0]["baseline_runs"] == "2"
    assert rows[0]["processed_delta_pct"] == "-10.0"  # 1350 vs 평균 1500


def test_later_base_runs_do_not_leak_into_an_earlier_comparison(tmp_path):
    """기준선은 그 처치 실행의 날짜까지 쌓인 BASE만 본다."""

    rows = _comparison(tmp_path, [
        _row("b1-base__r1", "BASE", run_date="2026-09-19", processed=1000),
        _row("b2-rtk__r1", "RTK", run_date="2026-09-19", processed=900),
        _row("b3-base__r1", "BASE", run_date="2026-09-25", processed=5000),
    ])

    assert len(rows) == 1
    assert rows[0]["baseline_runs"] == "1"
    assert rows[0]["processed_delta_pct"] == "-10.0"


def test_window_is_capped(tmp_path):
    from token_bench.collect import BASELINE_WINDOW

    rows = _comparison(tmp_path, [
        _row(f"b{i}-base__r1", "BASE", run_date="2026-09-19", processed=1000)
        for i in range(BASELINE_WINDOW + 5)
    ] + [_row("bx-rtk__r1", "RTK", run_date="2026-09-20", processed=900)])

    assert rows[0]["baseline_runs"] == str(BASELINE_WINDOW)


def test_presets_are_never_compared_against_each_other(tmp_path):
    small = _row("b1-base__r1", "BASE", run_date="2026-09-19", processed=1000)
    large = _row("b2-base__r1", "BASE", run_date="2026-09-19", processed=9000)
    large["prompt_id"] = "large"
    treatment = _row("b3-rtk__r1", "RTK", run_date="2026-09-20", processed=8100)
    treatment["prompt_id"] = "large"

    rows = _comparison(tmp_path, [small, large, treatment])

    assert len(rows) == 1
    assert rows[0]["prompt_id"] == "large"
    assert rows[0]["processed_delta_pct"] == "-10.0"  # 9000 기준, 1000은 무관
