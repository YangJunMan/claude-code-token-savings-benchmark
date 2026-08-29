import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark.reports.generate import _acceptable, cache_phase_counts, paired_comparisons
from benchmark.runner.usage import parse_usage


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

    def test_api_clear_recovery_is_separate_auditable_evidence(self):
        result = {
            "api_mode": True,
            "clear_succeeded": False,
            "returncode": 1,
            "terminal_reason": "max_turns",
            "public_returncode": 0,
        }
        with TemporaryDirectory() as directory:
            attempt = Path(directory)
            (attempt / "clear-recovery.json").write_text(json.dumps({
                "command_sent": True,
                "resume_marker_observed": True,
            }))
            self.assertTrue(_acceptable(result, attempt))

    def test_nonzero_first_turn_cache_read_is_not_acceptable(self):
        result = {
            "api_mode": True,
            "clear_succeeded": True,
            "returncode": 1,
            "terminal_reason": "max_turns",
            "public_returncode": 0,
            "transcript_summary": {"first_turn_cache_read_tokens": 7304},
        }
        with TemporaryDirectory() as directory:
            self.assertFalse(_acceptable(result, Path(directory)))

    def test_zero_first_turn_cache_read_is_acceptable(self):
        result = {
            "api_mode": True,
            "clear_succeeded": True,
            "returncode": 1,
            "terminal_reason": "max_turns",
            "public_returncode": 0,
            "transcript_summary": {"first_turn_cache_read_tokens": 0},
        }
        with TemporaryDirectory() as directory:
            self.assertTrue(_acceptable(result, Path(directory)))

    def test_cache_phase_counts_separate_first_turn_from_later_turns(self):
        usage = parse_usage({"modelUsage": {"model": {
            "inputTokens": 10,
            "cacheCreationInputTokens": 120,
            "cacheReadInputTokens": 450,
            "outputTokens": 20,
            "costUSD": 0.1,
        }}})
        phases = cache_phase_counts(usage, {
            "first_turn_cache_creation_tokens": 120,
            "first_turn_cache_read_tokens": 0,
        })
        self.assertEqual(phases, {
            "first_turn_cache_creation_tokens": 120,
            "first_turn_cache_read_tokens": 0,
            "later_turn_cache_creation_tokens": 0,
            "later_turn_cache_read_tokens": 450,
        })


if __name__ == "__main__":
    unittest.main()
