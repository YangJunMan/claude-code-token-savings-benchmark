import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.runner.cli import (
    RunLockedError, batch_run_root, default_run_root, finalize_existing_results,
    is_acceptable_result, latest_batch_run_root, next_condition, run_all, run_lock,
    washout_eligible_at)
from benchmark.runner.conditions import condition
from benchmark.runner.contracts import BenchmarkConfig, Condition, RunState, load_config
from benchmark.runner.state import StateStore


def dead_pid():
    """A pid guaranteed not to be running: spawned, then waited on."""
    process = subprocess.Popen(["true"])
    process.wait()
    return process.pid


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


def repeated_base_config():
    """A synthetic config with a repeat > 1, independent of the live repeat=1
    protocol in benchmark/config.json, so this mechanism stays covered even
    when the current round declares no repeats."""
    base = Condition(value="BASE", label="Baseline", optimizer="none", mechanism="none", repeat=2)
    headroom = Condition(value="H-ON", label="Headroom", optimizer="headroom", mechanism="none", repeat=1)
    return BenchmarkConfig(model="m", effort="e", max_turns=1, washout_seconds=0,
                           conditions=[base, headroom])


class RepeatTests(unittest.TestCase):
    """The spread between two identical runs is the floor every saving has to
    clear.  A runner that stops after one sample cannot produce that floor."""

    def test_a_condition_repeats_until_its_declared_count_is_met(self):
        config = repeated_base_config()
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            record_attempt(run_root, "BASE", 1)

            self.assertEqual(next_condition(config, run_root), config.conditions[0])

    def test_the_next_condition_follows_once_the_repeats_are_complete(self):
        config = repeated_base_config()
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            record_attempt(run_root, "BASE", 1)
            record_attempt(run_root, "BASE", 2)

            self.assertEqual(next_condition(config, run_root), config.conditions[1])


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


class DefaultRunRootTests(unittest.TestCase):
    """Washout alone is 70 minutes, so a round in progress crosses local
    midnight easily. Resuming with no explicit --run-root used to abandon
    that batch for a same-day duplicate that reran every condition."""

    def test_continues_an_unfinished_batch_instead_of_starting_todays(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unfinished = batch_run_root(root, "2026-09-08")
            record_attempt(unfinished, "BASE", 1)

            self.assertEqual(default_run_root(root, config), unfinished)

    def test_starts_a_fresh_batch_once_the_latest_one_is_finished(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            finished = batch_run_root(root, "2026-09-05")
            for item in config.conditions:
                for attempt in range(1, item.repeat + 1):
                    record_attempt(finished, item.value, attempt)

            self.assertEqual(default_run_root(root, config), batch_run_root(root))

    def test_starts_a_fresh_batch_when_none_exists_yet(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(default_run_root(root, config), batch_run_root(root))


class FinalizeExistingResultsTests(unittest.TestCase):
    """A grader crash here used to take down run_all() before its main loop
    even started, with nothing recorded for any condition."""

    def test_a_grading_failure_is_recorded_instead_of_crashing_startup(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            record_attempt(run_root, "BASE", 1)
            with patch("benchmark.runner.cli.grade_attempt",
                      side_effect=RuntimeError("grader boom")):
                finalize_existing_results(config, run_root)  # must not raise
            state = StateStore(run_root).load()
            self.assertEqual(state["state"], RunState.FAILED.value)
            self.assertIn("grader boom", state["error"])

    def test_a_quota_failure_while_grading_is_marked_invalid_not_failed(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            record_attempt(run_root, "BASE", 1)
            with patch("benchmark.runner.cli.grade_attempt",
                      side_effect=RuntimeError("You've hit your session limit")):
                finalize_existing_results(config, run_root)
            state = StateStore(run_root).load()
            self.assertEqual(state["state"], RunState.INVALID_QUOTA_INTERRUPTED.value)

    def test_a_later_condition_still_finalizes_after_an_earlier_grading_failure(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            record_attempt(run_root, "BASE", 1)
            record_attempt(run_root, "H-ON", 1)
            calls = []

            def grade(worktree, result, output_path):
                calls.append(worktree)
                if len(calls) == 1:
                    raise RuntimeError("grader boom")
                output_path.write_text("{}")

            with patch("benchmark.runner.cli.grade_attempt", side_effect=grade):
                finalize_existing_results(config, run_root)
            self.assertEqual(len(calls), 2)
            self.assertTrue((run_root / "H-ON/attempt-01/quality.json").exists())


if __name__ == "__main__":
    unittest.main()


class WashoutRepeatTests(unittest.TestCase):
    ACCEPTABLE = {
        "returncode": 0,
        "terminal_reason": "completed",
        "public_returncode": 0,
        "last_request_epoch": 1000,
        "final_text": "Changed files: gpu_platform/admission.py",
        "changed_files": ["gpu_platform/admission.py"],
        "transcript_summary": {"first_turn_cache_read_tokens": 0},
    }

    def test_second_attempt_of_the_same_condition_waits_out_the_cache(self):
        """A repeat is a separate measurement and needs the same cache isolation.

        ``reports.generate`` grades the gap between consecutive runs, whatever
        their condition, against ``washout_seconds``.  A repeat started straight
        after its own first attempt reads that attempt's cache and is reported as
        a washout failure, which destroys the noise floor ``repeat`` exists for.
        """
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            first = run_root / condition("BASE").value / "attempt-01"
            first.mkdir(parents=True)
            (first / "result.json").write_text(json.dumps(self.ACCEPTABLE))
            self.assertEqual(
                washout_eligible_at(config, run_root, condition("BASE")), 5200)

    def test_first_run_of_a_batch_waits_for_nothing(self):
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                washout_eligible_at(config, Path(directory), condition("BASE")), 0)

    def test_washout_follows_the_most_recent_run_not_the_declaration_order(self):
        """H-ON's wait is set by BASE's second attempt, not its first."""
        config = load_config(Path("benchmark/config.json"))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            for attempt, epoch in (("attempt-01", 1000), ("attempt-02", 9000)):
                path = run_root / condition("BASE").value / attempt
                path.mkdir(parents=True)
                (path / "result.json").write_text(
                    json.dumps({**self.ACCEPTABLE, "last_request_epoch": epoch}))
            self.assertEqual(
                washout_eligible_at(config, run_root, condition("H-ON")), 13200)


class LatestBatchTests(unittest.TestCase):
    def test_latest_batch_is_the_most_recent_one_not_the_last_alphabetically(self):
        """Batch names are not all ISO dates, so sorting them by text misreads them.

        ``pilot-2026-09-05`` sorts after every ``YYYY-MM-DD`` directory, which
        would point ``status`` and ``report`` at the pilot forever.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / "benchmark/runs"
            older = runs / "pilot-2026-09-05"
            newer = runs / "2026-09-06"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            import os
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))
            self.assertEqual(latest_batch_run_root(root), newer)

    def test_an_empty_runs_directory_falls_back_to_today(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(latest_batch_run_root(root), batch_run_root(root))


class RunLockTests(unittest.TestCase):
    """Nothing else stops two run_all() processes from driving the same
    run_root's `claude -p` at once - this is the only thing that does."""

    def test_a_second_holder_is_refused_while_the_first_is_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            (run_root / "run_all.lock").write_text(str(os.getpid()))

            with self.assertRaises(RunLockedError):
                with run_lock(run_root):
                    pass

    def test_a_stale_lock_from_a_dead_pid_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            (run_root / "run_all.lock").write_text(str(dead_pid()))

            with run_lock(run_root):
                pass  # must not raise

    def test_the_lock_is_released_on_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            with run_lock(run_root):
                self.assertTrue((run_root / "run_all.lock").exists())
            self.assertFalse((run_root / "run_all.lock").exists())

    def test_the_lock_is_released_even_if_the_body_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            with self.assertRaises(RuntimeError):
                with run_lock(run_root):
                    raise RuntimeError("boom")
            self.assertFalse((run_root / "run_all.lock").exists())

    def test_run_all_refuses_to_start_against_a_locked_run_root(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory) / "2026-09-08"
            run_root.mkdir(parents=True)
            (run_root / "run_all.lock").write_text(str(os.getpid()))

            with self.assertRaises(RunLockedError):
                run_all(Path("."), run_root)
