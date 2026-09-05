import csv
import json
import tempfile
import unittest
from pathlib import Path

from benchmark.reports.collect import collect_batch


USAGE = {"claude-sonnet-5": {"inputTokens": 10, "cacheCreationInputTokens": 0,
                             "cacheReadInputTokens": 0, "outputTokens": 5, "costUSD": 1.25}}


def turn(message_id, cache_read, cache_creation, output, tool="Bash"):
    return json.dumps({"type": "assistant", "message": {
        "id": message_id,
        "content": [{"type": "tool_use", "id": "t", "name": tool, "input": {}}],
        "usage": {"input_tokens": 0, "cache_read_input_tokens": cache_read,
                  "cache_creation_input_tokens": cache_creation,
                  "output_tokens": output}}})


def make_attempt(run_root, label, condition, quality=90, attempt=1):
    directory = run_root / label / f"attempt-{attempt:02d}"
    directory.mkdir(parents=True)
    (directory / "transcript.jsonl").write_text("\n".join([
        turn("m1", 0, 1000, 40),
        turn("m2", 1000, 460, 25),
        turn("m3", 1460, 25, 10),
    ]))
    (directory / "result.json").write_text(json.dumps({
        "condition": condition, "modelUsage": USAGE,
        "returncode": 0, "terminal_reason": "completed", "public_returncode": 0,
        "final_text": "Changed files: a.py", "changed_files": ["a.py"],
        "last_request_epoch": 1000,
        "transcript_summary": {"first_turn_cache_read_tokens": 0, "turns": 3},
    }))
    (directory / "quality.json").write_text(json.dumps({
        "score": quality, "critical_pass": False,
        "critical_passed": 5, "critical_total": 6,
    }))


def read(path):
    with Path(path).open() as stream:
        return list(csv.DictReader(stream))


class CollectBatchTest(unittest.TestCase):
    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp())
        self.run_root = self.workspace / "benchmark/runs/2026-09-05"
        make_attempt(self.run_root, "BASE-01", "BASE")
        self.activity = self.workspace / "data/activity-log.csv"
        self.summary = self.workspace / "data/run-summary.csv"

    def test_the_batch_directory_name_becomes_the_run_date(self):
        collect_batch(self.run_root, self.activity, self.summary)

        self.assertEqual({row["run_date"] for row in read(self.activity)}, {"2026-09-05"})

    def test_one_row_per_turn_is_written(self):
        collect_batch(self.run_root, self.activity, self.summary)

        rows = read(self.activity)
        self.assertEqual([row["turn"] for row in rows], ["1", "2", "3"])
        self.assertEqual(rows[0]["tools"], "Bash")

    def test_recollecting_the_same_batch_replaces_rather_than_duplicates(self):
        """Weekly collection must be safe to rerun; a partially collected batch
        gets finished, not doubled."""
        collect_batch(self.run_root, self.activity, self.summary)
        collect_batch(self.run_root, self.activity, self.summary)

        self.assertEqual(len(read(self.activity)), 3)
        self.assertEqual(len(read(self.summary)), 1)

    def test_a_later_batch_appends_without_touching_the_earlier_one(self):
        collect_batch(self.run_root, self.activity, self.summary)
        later = self.workspace / "benchmark/runs/2026-09-12"
        make_attempt(later, "BASE-01", "BASE")

        collect_batch(later, self.activity, self.summary)

        self.assertEqual(
            sorted({row["run_date"] for row in read(self.activity)}),
            ["2026-09-05", "2026-09-12"],
        )
        self.assertEqual(len(read(self.activity)), 6)

    def test_summary_carries_only_what_the_activity_log_cannot_derive(self):
        """Token totals are omitted on purpose: they are derivable from the
        turn rows, and storing them twice invites the two files to disagree."""
        collect_batch(self.run_root, self.activity, self.summary)

        row = read(self.summary)[0]
        self.assertEqual(row["cost_usd"], "1.25")
        self.assertEqual(row["quality_score"], "90")
        self.assertEqual(row["critical_pass"], "5/6")
        self.assertEqual(row["condition"], "BASE")
        self.assertNotIn("total_processed_tokens", row)

    def test_the_reconciliation_is_stored_rather_than_recomputed_downstream(self):
        """The page must not re-derive published numbers: a second copy of the
        formula is a second place for it to drift."""
        collect_batch(self.run_root, self.activity, self.summary)

        row = read(self.summary)[0]
        parts = ("reconcile_observed", "reconcile_opening",
                 "reconcile_output", "reconcile_tool_result", "reconcile_discarded")
        for name in parts:
            self.assertIn(name, row)
        self.assertEqual(
            int(row["reconcile_observed"]),
            sum(int(row[name]) for name in parts if name != "reconcile_observed"),
        )

    def test_measurability_is_recorded_for_each_run(self):
        collect_batch(self.run_root, self.activity, self.summary)

        self.assertEqual(read(self.summary)[0]["measurable"], "1")


class RunIdentityTest(unittest.TestCase):
    """Every row must trace to one attempt.  The weekly runner puts repeats of a
    condition in the same directory, so the directory name alone cannot identify
    them and two runs would collapse into one id."""

    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp())
        self.activity = self.workspace / "data/activity-log.csv"
        self.summary = self.workspace / "data/run-summary.csv"

    def test_repeats_of_one_condition_get_distinct_run_ids(self):
        run_root = self.workspace / "benchmark/runs/2026-09-05"
        make_attempt(run_root, "BASE", "BASE", attempt=1)
        make_attempt(run_root, "BASE", "BASE", attempt=2)

        collect_batch(run_root, self.activity, self.summary)

        self.assertEqual([row["run_id"] for row in read(self.summary)],
                         ["BASE-01", "BASE-02"])

    def test_a_labelled_directory_keeps_its_label_as_the_run_id(self):
        """The API path already names directories BASE-01 / BASE-02; suffixing
        the attempt again would produce BASE-01-01."""
        run_root = self.workspace / "benchmark/runs/2026-09-05"
        make_attempt(run_root, "BASE-01", "BASE")
        make_attempt(run_root, "BASE-02", "BASE")

        collect_batch(run_root, self.activity, self.summary)

        self.assertEqual([row["run_id"] for row in read(self.summary)],
                         ["BASE-01", "BASE-02"])


if __name__ == "__main__":
    unittest.main()
