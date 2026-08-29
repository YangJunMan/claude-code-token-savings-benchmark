import json
import tempfile
import unittest
from pathlib import Path

from benchmark.runner.cli import is_acceptable_result, next_condition, washout_eligible_at
from benchmark.runner.contracts import Condition, load_config


class CliResultTests(unittest.TestCase):
    def test_max_turn_budget_with_passing_tests_is_acceptable(self):
        result = {
            "returncode": 1,
            "terminal_reason": "max_turns",
            "public_returncode": 0,
            "clear_succeeded": True,
            "transcript_summary": {"first_turn_cache_read_tokens": 0},
        }
        self.assertTrue(is_acceptable_result(result))

    def test_quota_or_execution_failure_is_not_acceptable(self):
        self.assertFalse(is_acceptable_result({
            "returncode": 1,
            "terminal_reason": "max_turns",
            "public_returncode": 1,
            "clear_succeeded": True,
        }))
        self.assertFalse(is_acceptable_result({
            "returncode": 1,
            "errors": ["You've hit your session limit"],
            "public_returncode": 0,
            "clear_succeeded": True,
        }))
        self.assertFalse(is_acceptable_result({
            "returncode": 0,
            "public_returncode": 0,
            "clear_succeeded": False,
        }))
        self.assertFalse(is_acceptable_result({
            "returncode": 0,
            "public_returncode": 0,
            "clear_succeeded": True,
            "transcript_summary": {"first_turn_cache_read_tokens": 100},
        }))

    def test_next_condition_skips_acceptable_result_but_retries_invalid_result(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            first = run_root / Condition.H_ON.value / "attempt-01"
            first.mkdir(parents=True)
            (first / "result.json").write_text(json.dumps({
                "returncode": 1,
                "terminal_reason": "max_turns",
                "public_returncode": 0,
                "clear_succeeded": True,
                "transcript_summary": {"first_turn_cache_read_tokens": 0},
            }))
            self.assertEqual(next_condition(config, run_root), Condition.H_OFF)

    def test_restart_preserves_washout_from_previous_acceptable_result(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            first = run_root / Condition.H_ON.value / "attempt-01"
            first.mkdir(parents=True)
            (first / "result.json").write_text(json.dumps({
                "returncode": 1,
                "terminal_reason": "max_turns",
                "public_returncode": 0,
                "last_request_epoch": 1000,
                "clear_succeeded": True,
                "transcript_summary": {"first_turn_cache_read_tokens": 0},
            }))
            self.assertEqual(
                washout_eligible_at(config, run_root, Condition.H_OFF),
                5200,
            )

            second = run_root / Condition.H_OFF.value / "attempt-01"
            second.mkdir(parents=True)
            (second / "result.json").write_text(json.dumps({
                "returncode": 1,
                "errors": ["You've hit your session limit"],
                "public_returncode": 0,
                "clear_succeeded": True,
                "transcript_summary": {"first_turn_cache_read_tokens": 0},
            }))
            self.assertEqual(next_condition(config, run_root), Condition.H_OFF)


if __name__ == "__main__":
    unittest.main()
