import unittest

from benchmark.reports.comparison import (
    COMPARISON_COLUMNS, batch_comparison, comparison_rows, delta_pct, spread_pct)


def run(condition, processed, cost, tax=0, quality=90):
    return {"condition": condition, "processed": processed, "cost": cost,
            "tax": tax, "quality": quality}


class PrimitiveTests(unittest.TestCase):
    def test_spread_needs_two_observations(self):
        self.assertIsNone(spread_pct([100]))
        self.assertIsNone(spread_pct([]))

    def test_spread_is_the_gap_over_the_mean(self):
        self.assertAlmostEqual(spread_pct([90, 110]), 20.0)

    def test_delta_is_positive_when_the_treatment_costs_more(self):
        self.assertAlmostEqual(delta_pct(110, 100), 10.0)
        self.assertAlmostEqual(delta_pct(90, 100), -10.0)

    def test_delta_against_a_zero_baseline_is_undefined(self):
        self.assertIsNone(delta_pct(10, 0))


class BatchComparisonTests(unittest.TestCase):
    def test_each_treatment_is_compared_against_the_pooled_baseline(self):
        result = batch_comparison([
            run("BASE", 100, 1.0), run("BASE", 200, 3.0),
            run("R-ON", 120, 1.0),
        ])
        self.assertAlmostEqual(result["noise"]["processed"], 66.6666, places=3)
        self.assertAlmostEqual(result["noise"]["cost"], 100.0)
        row = next(r for r in result["conditions"] if r["condition"] == "R-ON")
        self.assertAlmostEqual(row["processed"], -20.0)   # 120 vs mean 150
        self.assertAlmostEqual(row["cost"], -50.0)        # 1.0 vs mean 2.0
        self.assertEqual(row["runs"], 1)

    def test_a_batch_without_a_baseline_yields_no_comparison(self):
        result = batch_comparison([run("R-ON", 120, 1.0)])
        self.assertEqual(result["conditions"], [])
        self.assertIsNone(result["noise"]["processed"])

    def test_a_single_baseline_run_still_compares_but_reports_no_noise(self):
        result = batch_comparison([run("BASE", 100, 1.0), run("R-ON", 80, 0.8)])
        self.assertIsNone(result["noise"]["processed"])
        row = result["conditions"][0]
        self.assertAlmostEqual(row["processed"], -20.0)

    def test_rows_carry_the_batch_and_the_noise_floor(self):
        rows = comparison_rows("2026-09-06", [
            run("BASE", 100, 1.0), run("BASE", 200, 3.0), run("R-ON", 120, 1.0)])
        self.assertEqual(len(rows), 1)
        row = dict(zip(COMPARISON_COLUMNS, rows[0]))
        self.assertEqual(row["run_date"], "2026-09-06")
        self.assertEqual(row["condition"], "R-ON")
        self.assertEqual(row["runs"], 1)
        self.assertAlmostEqual(float(row["noise_processed_pct"]), 66.6666, places=3)
