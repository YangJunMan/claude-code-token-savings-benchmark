import json
import tempfile
import unittest
from pathlib import Path

from benchmark.runner.cli import is_acceptable_result, next_condition, washout_eligible_at
from benchmark.runner.contracts import Condition, load_config


class CliResultTests(unittest.TestCase):
    def test_self_terminated_run_with_a_final_response_is_acceptable(self):
        self.assertTrue(is_acceptable_result({
            "returncode": 0, "terminal_reason": "completed", "public_returncode": 0,
            "final_text": "Changed files: gpu_platform/admission.py",
            "changed_files": ["gpu_platform/admission.py"],
            "transcript_summary": {"first_turn_cache_read_tokens": 0},
        }))

    def test_max_turn_truncation_is_not_acceptable(self):
        """A truncated run measures the turn cap, not the condition."""
        self.assertFalse(is_acceptable_result({
            "returncode": 1, "terminal_reason": "max_turns", "public_returncode": 0,
            "final_text": "", "changed_files": ["gpu_platform/admission.py"],
            "transcript_summary": {"first_turn_cache_read_tokens": 0},
        }))

    def test_run_that_changed_nothing_is_not_acceptable(self):
        """A clean exit after only asking a clarifying question is not a measurement."""
        self.assertFalse(is_acceptable_result({
            "returncode": 0, "terminal_reason": "completed", "public_returncode": 0,
            "final_text": "Could you clarify what you would like implemented?",
            "changed_files": [],
            "transcript_summary": {"first_turn_cache_read_tokens": 0},
        }))

    def test_shared_prefix_cache_read_does_not_invalidate_a_run(self):
        """Every run reuses the same fixed system prefix; that is symmetric."""
        self.assertTrue(is_acceptable_result({
            "returncode": 0, "terminal_reason": "completed", "public_returncode": 0,
            "final_text": "Changed files: gpu_platform/admission.py",
            "changed_files": ["gpu_platform/admission.py"],
            "transcript_summary": {"first_turn_cache_read_tokens": 24556},
        }))

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
            first = run_root / Condition.BASE.value / "attempt-01"
            first.mkdir(parents=True)
            (first / "result.json").write_text(json.dumps({
                "returncode": 0,
                "terminal_reason": "completed",
                "public_returncode": 0,
                "final_text": "Changed files: gpu_platform/admission.py",
                "changed_files": ["gpu_platform/admission.py"],
                "transcript_summary": {"first_turn_cache_read_tokens": 0},
            }))
            self.assertEqual(next_condition(config, run_root), Condition.H_ON)

    def test_restart_preserves_washout_from_previous_acceptable_result(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            first = run_root / Condition.BASE.value / "attempt-01"
            first.mkdir(parents=True)
            (first / "result.json").write_text(json.dumps({
                "returncode": 0,
                "terminal_reason": "completed",
                "public_returncode": 0,
                "last_request_epoch": 1000,
                "final_text": "Changed files: gpu_platform/admission.py",
                "changed_files": ["gpu_platform/admission.py"],
                "transcript_summary": {"first_turn_cache_read_tokens": 0},
            }))
            self.assertEqual(
                washout_eligible_at(config, run_root, Condition.H_ON),
                5200,
            )

            second = run_root / Condition.H_ON.value / "attempt-01"
            second.mkdir(parents=True)
            (second / "result.json").write_text(json.dumps({
                "returncode": 1,
                "errors": ["You've hit your session limit"],
                "public_returncode": 0,
                "clear_succeeded": True,
                "transcript_summary": {"first_turn_cache_read_tokens": 0},
            }))
            self.assertEqual(next_condition(config, run_root), Condition.H_ON)


if __name__ == "__main__":
    unittest.main()
