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


def test_retry_on_a_later_date_still_compares_against_the_same_batchs_base(tmp_path):
    """2026-09-21 실측 버그: 같은 batch의 base는 9/19에, 재시도한 조건은
    9/20에 끝나면 날짜로 묶던 예전 로직은 9/20 그룹에 base가 없어 그 조건을
    비교표에서 통째로 빠뜨렸다. batch_id로 묶으면 날짜가 갈려도 비교된다."""

    summary_path = tmp_path / "run-summary.csv"
    comparison_path = tmp_path / "comparison.csv"
    _write_summary(
        summary_path,
        [
            _row("batch1-base__r1", "BASE", run_date="2026-09-19", processed=1000, cost=1.0),
            _row("batch1-rtk__r1", "RTK", run_date="2026-09-20", processed=900, cost=0.9),
        ],
    )

    _rebuild_comparison(summary_path, comparison_path)

    with comparison_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["condition"] == "RTK"
    assert rows[0]["run_date"] == "2026-09-19"  # 그룹 내 최소 날짜
    assert rows[0]["processed_delta_pct"] == "-10.0"


def test_different_batches_are_not_mixed_together(tmp_path):
    summary_path = tmp_path / "run-summary.csv"
    comparison_path = tmp_path / "comparison.csv"
    _write_summary(
        summary_path,
        [
            _row("batch1-base__r1", "BASE", run_date="2026-09-19", processed=1000),
            _row("batch1-rtk__r1", "RTK", run_date="2026-09-19", processed=900),
            _row("batch2-base__r1", "BASE", run_date="2026-09-19", processed=2000),
            _row("batch2-rtk__r1", "RTK", run_date="2026-09-19", processed=1800),
        ],
    )

    _rebuild_comparison(summary_path, comparison_path)

    with comparison_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert {row["processed_delta_pct"] for row in rows} == {"-10.0"}
