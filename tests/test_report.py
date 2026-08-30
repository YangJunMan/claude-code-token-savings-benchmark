import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark.reports.generate import (
    _acceptable, baseline_noise, cache_phase_counts, paired_comparisons,
    uniform_first_turn_cache_read,
)
from benchmark.runner.usage import parse_usage


class ReportTests(unittest.TestCase):
    def test_paired_comparisons_compare_every_treatment_to_the_pooled_baseline(self):
        rows = [
            {"condition": "BASE", "total_processed_tokens": 1000, "cost_usd": 1.0,
             "quality_score": 90, "critical_pass": True, "critical_passed": 6},
            {"condition": "BASE", "total_processed_tokens": 1000, "cost_usd": 1.0,
             "quality_score": 90, "critical_pass": True, "critical_passed": 6},
            {"condition": "H-ON", "total_processed_tokens": 800, "cost_usd": 0.8,
             "quality_score": 88, "critical_pass": True, "critical_passed": 6},
            {"condition": "C-FULL", "total_processed_tokens": 700, "cost_usd": 0.7,
             "quality_score": 80, "critical_pass": True, "critical_passed": 6},
            {"condition": "C-BRIEF", "total_processed_tokens": 750, "cost_usd": 0.75,
             "quality_score": 86, "critical_pass": True, "critical_passed": 6},
            {"condition": "R-ON", "total_processed_tokens": 950, "cost_usd": 0.95,
             "quality_score": 90, "critical_pass": True, "critical_passed": 6},
        ]
        comparisons = {item["comparison"]: item for item in paired_comparisons(rows)}
        self.assertAlmostEqual(comparisons["Headroom optimized vs baseline"]["token_saving_pct"], 20.0)
        self.assertAlmostEqual(comparisons["Caveman full vs baseline"]["cost_saving_pct"], 30.0)
        self.assertAlmostEqual(comparisons["Be brief vs baseline"]["quality_delta"], -4)
        self.assertTrue(comparisons["Headroom optimized vs baseline"]["quality_gate_pass"])
        self.assertEqual(comparisons["Headroom optimized vs baseline"]["baseline_attempts"], 2)

    def test_effect_smaller_than_the_baseline_spread_is_not_recommended(self):
        """Two identical BASE runs 10% apart make a 3% treatment effect unreadable."""
        rows = [
            {"condition": "BASE", "total_processed_tokens": 950, "cost_usd": 0.95,
             "quality_score": 90, "critical_pass": True, "critical_passed": 6},
            {"condition": "BASE", "total_processed_tokens": 1050, "cost_usd": 1.05,
             "quality_score": 90, "critical_pass": True, "critical_passed": 6},
            {"condition": "H-ON", "total_processed_tokens": 970, "cost_usd": 0.97,
             "quality_score": 90, "critical_pass": True, "critical_passed": 6},
        ]
        comparison = paired_comparisons(rows)[0]
        self.assertGreater(comparison["cost_saving_pct"], 0)
        self.assertFalse(comparison["cost_above_noise"])
        self.assertFalse(comparison["recommended"])

    def test_baseline_noise_needs_two_runs(self):
        self.assertIsNone(baseline_noise([
            {"condition": "BASE", "total_processed_tokens": 1000, "cost_usd": 1.0,
             "quality_score": 90, "critical_pass": True},
        ]))

    def test_quality_gate_rejects_a_lost_critical_invariant(self):
        """Losing an invariant the untreated run held fails the gate outright."""
        rows = [
            {"condition": "BASE", "total_processed_tokens": 1000, "cost_usd": 1.0,
             "quality_score": 90, "critical_pass": False, "critical_passed": 5},
            {"condition": "H-ON", "total_processed_tokens": 800, "cost_usd": 0.8,
             "quality_score": 90, "critical_pass": False, "critical_passed": 4},
        ]
        self.assertFalse(paired_comparisons(rows)[0]["quality_gate_pass"])

    def test_quality_gate_passes_when_the_baseline_itself_is_imperfect(self):
        rows = [
            {"condition": "BASE", "total_processed_tokens": 1000, "cost_usd": 1.0,
             "quality_score": 90, "critical_pass": False, "critical_passed": 5},
            {"condition": "H-ON", "total_processed_tokens": 800, "cost_usd": 0.8,
             "quality_score": 92, "critical_pass": False, "critical_passed": 5},
        ]
        self.assertTrue(paired_comparisons(rows)[0]["quality_gate_pass"])

    def test_max_turn_truncation_is_not_acceptable(self):
        result = {"api_mode": True, "returncode": 1, "terminal_reason": "max_turns",
                  "public_returncode": 0, "final_text": "", "changed_files": ["a.py"],
                  "transcript_summary": {"first_turn_cache_read_tokens": 0}}
        with TemporaryDirectory() as directory:
            self.assertFalse(_acceptable(result, Path(directory)))

    def test_completed_run_with_evidence_is_acceptable(self):
        result = {"api_mode": True, "returncode": 0, "terminal_reason": "completed",
                  "public_returncode": 0, "final_text": "Changed files: a.py",
                  "changed_files": ["a.py"],
                  "transcript_summary": {"first_turn_cache_read_tokens": 24556}}
        with TemporaryDirectory() as directory:
            self.assertTrue(_acceptable(result, Path(directory)))

    def test_condition_grouping_uses_the_result_not_the_directory_name(self):
        """Reproduction runs live in per-run label directories like BASE-01."""
        from benchmark.reports.generate import _row_for
        with TemporaryDirectory() as directory:
            attempt = Path(directory) / "BASE-01" / "attempt-01"
            attempt.mkdir(parents=True)
            (attempt / "result.json").write_text(json.dumps({
                "condition": "BASE", "returncode": 0, "terminal_reason": "completed",
                "final_text": "Changed files: a.py", "changed_files": ["a.py"],
                "public_returncode": 0, "max_turns": 50,
                "transcript_summary": {"first_turn_cache_read_tokens": 0, "turns": 3,
                                       "tool_calls": 2},
                "modelUsage": {"m": {"inputTokens": 1, "cacheCreationInputTokens": 1,
                                     "cacheReadInputTokens": 1, "outputTokens": 1,
                                     "costUSD": 1.0}},
            }))
            row = _row_for(attempt / "result.json")
        self.assertEqual(row["condition"], "BASE")
        self.assertEqual(row["run_label"], "BASE-01")

    def test_shared_prefix_cache_read_is_symmetric(self):
        self.assertTrue(uniform_first_turn_cache_read([
            {"first_turn_cache_read_tokens": 24556},
            {"first_turn_cache_read_tokens": 24556},
        ]))

    def test_asymmetric_first_turn_cache_read_is_contamination(self):
        self.assertFalse(uniform_first_turn_cache_read([
            {"first_turn_cache_read_tokens": 24556},
            {"first_turn_cache_read_tokens": 0},
        ]))

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
