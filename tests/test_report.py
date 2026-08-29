import unittest

from benchmark.reports.generate import paired_comparisons


class ReportTests(unittest.TestCase):
    def test_paired_comparisons_compute_token_cost_and_quality_deltas(self):
        rows = [
            {"condition": "H-ON", "total_processed_tokens": 800,
             "cost_usd": 0.8, "quality_score": 88, "critical_pass": True},
            {"condition": "H-OFF", "total_processed_tokens": 1000,
             "cost_usd": 1.0, "quality_score": 90, "critical_pass": True},
            {"condition": "C-FULL", "total_processed_tokens": 700,
             "cost_usd": 0.7, "quality_score": 80, "critical_pass": True},
            {"condition": "C-NON", "total_processed_tokens": 1000,
             "cost_usd": 1.0, "quality_score": 90, "critical_pass": True},
            {"condition": "C-BRIEF", "total_processed_tokens": 750,
             "cost_usd": 0.75, "quality_score": 86, "critical_pass": True},
            {"condition": "R-ON", "total_processed_tokens": 950,
             "cost_usd": 0.95, "quality_score": 90, "critical_pass": True},
            {"condition": "R-OFF", "total_processed_tokens": 1000,
             "cost_usd": 1.0, "quality_score": 90, "critical_pass": True},
        ]
        comparisons = {item["comparison"]: item for item in paired_comparisons(rows)}
        self.assertAlmostEqual(comparisons["Headroom ON vs OFF"]["token_saving_pct"], 20.0)
        self.assertAlmostEqual(comparisons["Caveman full vs non"]["cost_saving_pct"], 30.0)
        self.assertEqual(comparisons["Caveman brief vs non"]["quality_delta"], -4)
        self.assertTrue(comparisons["Headroom ON vs OFF"]["quality_gate_pass"])

    def test_quality_gate_rejects_more_than_five_point_loss(self):
        rows = [
            {"condition": "R-ON", "total_processed_tokens": 900,
             "cost_usd": 0.9, "quality_score": 84, "critical_pass": True},
            {"condition": "R-OFF", "total_processed_tokens": 1000,
             "cost_usd": 1.0, "quality_score": 90, "critical_pass": True},
        ]
        comparison = paired_comparisons(rows)[0]
        self.assertFalse(comparison["quality_gate_pass"])
        self.assertFalse(comparison["recommended"])


if __name__ == "__main__":
    unittest.main()
