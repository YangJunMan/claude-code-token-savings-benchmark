import csv
import json
import tempfile
import unittest
from pathlib import Path

from benchmark.reports.activity_log import extract_turns
from benchmark.reports.collect import collect_batch, invalid_reason


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


class ComparisonPublishingTests(unittest.TestCase):
    def test_collect_publishes_the_batch_comparison(self):
        """The page must not have to recompute what Python already decided."""
        import csv
        from benchmark.reports.collect import collect_batch
        from benchmark.reports.comparison import COMPARISON_COLUMNS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_root = Path("benchmark/runs/2026-09-06")
            if not run_root.exists():
                self.skipTest("raw runs are not published")
            collect_batch(run_root, root / "activity.csv", root / "summary.csv",
                          root / "comparison.csv")
            rows = list(csv.DictReader(open(root / "comparison.csv")))
            self.assertEqual(list(rows[0]), list(COMPARISON_COLUMNS))
            self.assertTrue(all(r["run_date"] == "2026-09-06" for r in rows))
            self.assertNotIn("BASE", [r["condition"] for r in rows])
            self.assertTrue(all(r["noise_processed_pct"] for r in rows))


def _turns_from(tmp, lines):
    path = Path(tmp) / "transcript.jsonl"
    path.write_text("\n".join(lines))
    return extract_turns(path)


ACCEPTABLE_RESULT = {
    "returncode": 0, "terminal_reason": "completed", "is_error": False,
    "final_text": "Changed files: a.py", "changed_files": ["a.py"],
    "transcript_summary": {"first_turn_cache_read_tokens": 0},
}


class InvalidReasonTests(unittest.TestCase):
    """One published value has to say *why*, not just *that*, a run is
    excluded - and say every applicable reason, since more than one can
    apply to the same run."""

    def test_a_measurable_run_has_no_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            turns = _turns_from(tmp, [turn("m1", 0, 1000, 40), turn("m2", 1000, 460, 25),
                                      turn("m3", 1460, 25, 10)])
            self.assertEqual(invalid_reason(ACCEPTABLE_RESULT, turns), "")

    def test_max_turns_truncation_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            turns = _turns_from(tmp, [turn("m1", 0, 1000, 40)])
            result = dict(ACCEPTABLE_RESULT, terminal_reason="max_turns", is_error=True)
            self.assertEqual(invalid_reason(result, turns), "max_turns")

    def test_a_quota_interruption_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            turns = _turns_from(tmp, [turn("m1", 0, 1000, 40), turn("m2", 1000, 460, 25)])
            result = dict(ACCEPTABLE_RESULT, returncode=1, is_error=True,
                         result="You've hit your session limit · resets 3:40am (Asia/Seoul)")
            self.assertEqual(invalid_reason(result, turns), "quota_interrupted")

    def test_a_quota_interruption_that_also_compacted_reports_both(self):
        """The actual 2026-09-08 C-BRIEF incident: a session-limit hit whose
        final_text came back empty, on a transcript that also compacted."""
        with tempfile.TemporaryDirectory() as tmp:
            turns = _turns_from(tmp, [turn("m1", 0, 1000, 40), turn("m2", 0, 500, 10)])
            result = dict(ACCEPTABLE_RESULT, returncode=1, is_error=True, final_text="",
                         result="You've hit your session limit · resets 3:40am (Asia/Seoul)")
            self.assertEqual(invalid_reason(result, turns),
                            "quota_interrupted+empty_response+compacted")

    def test_no_changed_files_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            turns = _turns_from(tmp, [turn("m1", 0, 1000, 40)])
            result = dict(ACCEPTABLE_RESULT, changed_files=[])
            self.assertEqual(invalid_reason(result, turns), "no_changed_files")

    def test_missing_cache_evidence_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            turns = _turns_from(tmp, [turn("m1", 0, 1000, 40)])
            result = dict(ACCEPTABLE_RESULT,
                         transcript_summary={"first_turn_cache_read_tokens": None})
            self.assertEqual(invalid_reason(result, turns), "cache_evidence_missing")
