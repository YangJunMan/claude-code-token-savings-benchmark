import json
import tempfile
import unittest
from pathlib import Path

from benchmark.runner.cli import (
    batch_run_root, is_acceptable_result, next_condition, washout_eligible_at)
from benchmark.runner.conditions import condition
from benchmark.runner.contracts import load_config


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
            first = run_root / condition("BASE").value / "attempt-01"
            first.mkdir(parents=True)
            (first / "result.json").write_text(json.dumps({
                "returncode": 0,
                "terminal_reason": "completed",
                "public_returncode": 0,
                "final_text": "Changed files: gpu_platform/admission.py",
                "changed_files": ["gpu_platform/admission.py"],
                "transcript_summary": {"first_turn_cache_read_tokens": 0},
            }))
            repeated = run_root / condition("BASE").value / "attempt-02"
            repeated.mkdir(parents=True)
            (repeated / "result.json").write_text((first / "result.json").read_text())
            self.assertEqual(next_condition(config, run_root), condition("H-ON"))

    def test_restart_preserves_washout_from_previous_acceptable_result(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            first = run_root / condition("BASE").value / "attempt-01"
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
            repeated = run_root / condition("BASE").value / "attempt-02"
            repeated.mkdir(parents=True)
            (repeated / "result.json").write_text((first / "result.json").read_text())
            self.assertEqual(
                washout_eligible_at(config, run_root, condition("H-ON")),
                5200,
            )

            second = run_root / condition("H-ON").value / "attempt-01"
            second.mkdir(parents=True)
            (second / "result.json").write_text(json.dumps({
                "returncode": 1,
                "errors": ["You've hit your session limit"],
                "public_returncode": 0,
                "clear_succeeded": True,
                "transcript_summary": {"first_turn_cache_read_tokens": 0},
            }))
            self.assertEqual(next_condition(config, run_root), condition("H-ON"))

ACCEPTABLE = {
    "returncode": 0, "terminal_reason": "completed", "public_returncode": 0,
    "final_text": "Changed files: gpu_platform/admission.py",
    "changed_files": ["gpu_platform/admission.py"],
    "last_request_epoch": 1000,
    "transcript_summary": {"first_turn_cache_read_tokens": 0},
}


def record_attempt(run_root, condition_id, attempt):
    directory = run_root / condition_id / f"attempt-{attempt:02d}"
    directory.mkdir(parents=True)
    (directory / "result.json").write_text(json.dumps(ACCEPTABLE))


class RepeatTests(unittest.TestCase):
    """The spread between two identical runs is the floor every saving has to
    clear.  A runner that stops after one sample cannot produce that floor."""

    def test_a_condition_repeats_until_its_declared_count_is_met(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            record_attempt(run_root, "BASE", 1)

            self.assertEqual(next_condition(config, run_root), condition("BASE"))

    def test_the_next_condition_follows_once_the_repeats_are_complete(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            record_attempt(run_root, "BASE", 1)
            record_attempt(run_root, "BASE", 2)

            self.assertEqual(next_condition(config, run_root), condition("H-ON"))


class BatchTests(unittest.TestCase):
    """Weekly repetition needs a fresh run root; reusing one makes the second
    week look already finished."""

    def test_each_batch_gets_its_own_directory(self):
        root = Path("/tmp/bench")

        self.assertEqual(
            batch_run_root(root, "2026-09-05"), root / "benchmark/runs/2026-09-05"
        )

    def test_a_finished_batch_does_not_block_the_next_one(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            finished = batch_run_root(root, "2026-09-05")
            for item in config.conditions:
                for attempt in range(1, item.repeat + 1):
                    record_attempt(finished, item.value, attempt)
            self.assertIsNone(next_condition(config, finished))

            fresh = batch_run_root(root, "2026-09-12")

            self.assertEqual(next_condition(config, fresh), condition("BASE"))


if __name__ == "__main__":
    unittest.main()
