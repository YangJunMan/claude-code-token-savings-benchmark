"""The raw transcripts are not kept, so anything worth having must be published
before they are discarded.  These tests pin what has to survive."""

import json
import tempfile
import unittest
from pathlib import Path

from benchmark.reports.activity_log import ACTIVITY_COLUMNS, activity_rows, extract_turns
from benchmark.reports.collect import SUMMARY_COLUMNS, aux_model_tokens, washout_gaps


def transcript(tmp, turns):
    lines = []
    for i, (usage, stop) in enumerate(turns):
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"id": f"m{i}", "role": "assistant", "usage": usage,
                        "stop_reason": stop, "content": []},
        }))
    path = Path(tmp) / "transcript.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


class TurnFieldTests(unittest.TestCase):
    USAGE = {
        "input_tokens": 2, "cache_creation_input_tokens": 11001,
        "cache_read_input_tokens": 16652, "output_tokens": 398,
        "output_tokens_details": {"thinking_tokens": 20},
        "cache_creation": {"ephemeral_1h_input_tokens": 11001,
                           "ephemeral_5m_input_tokens": 0},
    }

    def test_thinking_tokens_are_kept(self):
        """Part of output_tokens, but only the transcript says how much."""
        with tempfile.TemporaryDirectory() as tmp:
            turns = extract_turns(transcript(tmp, [(self.USAGE, "tool_use"),
                                                   (self.USAGE, "end_turn")]))
            self.assertEqual(turns[0].thinking_tokens, 20)

    def test_the_cache_write_ttl_split_is_kept(self):
        """A 1-hour cache write is priced above a 5-minute one."""
        with tempfile.TemporaryDirectory() as tmp:
            turns = extract_turns(transcript(tmp, [(self.USAGE, "tool_use")]))
            self.assertEqual(turns[0].cache_1h_tokens, 11001)

    def test_the_stop_reason_of_each_turn_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            turns = extract_turns(transcript(tmp, [(self.USAGE, "tool_use"),
                                                   (self.USAGE, "end_turn")]))
            self.assertEqual([t.stop_reason for t in turns], ["tool_use", "end_turn"])

    def test_the_new_fields_reach_the_published_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            turns = extract_turns(transcript(tmp, [(self.USAGE, "tool_use")]))
            row = dict(zip(ACTIVITY_COLUMNS, activity_rows("d", "r", "c", turns)[0]))
            self.assertEqual(row["thinking_tokens"], 20)
            self.assertEqual(row["cache_1h_tokens"], 11001)
            self.assertEqual(row["stop_reason"], "tool_use")


class RunFieldTests(unittest.TestCase):
    def test_auxiliary_model_usage_is_recorded_not_merely_described(self):
        """Claude Code bills a helper model that never appears as a turn.  Without
        this column the difference from the published totals is unexplainable."""
        result = {"modelUsage": {
            "claude-sonnet-5": {"inputTokens": 10, "outputTokens": 20,
                                "cacheReadInputTokens": 5, "cacheCreationInputTokens": 1},
            "claude-haiku-4-5": {"inputTokens": 100, "outputTokens": 200,
                                 "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0},
        }}
        self.assertEqual(aux_model_tokens(result, "claude-sonnet-5"), 300)

    def test_a_single_model_run_reports_no_auxiliary_usage(self):
        result = {"modelUsage": {"claude-sonnet-5": {"inputTokens": 10, "outputTokens": 20}}}
        self.assertEqual(aux_model_tokens(result, "claude-sonnet-5"), 0)

    def test_the_washout_gap_between_consecutive_runs_is_recorded(self):
        """The cache-isolation claim has to be checkable from published data."""
        runs = [
            {"run_id": "BASE-01", "started_epoch": 1000, "last_request_epoch": 1500},
            {"run_id": "BASE-02", "started_epoch": 5700, "last_request_epoch": 6000},
        ]
        self.assertEqual(washout_gaps(runs), {"BASE-01": "", "BASE-02": 4200})

    def test_the_summary_publishes_the_run_level_evidence(self):
        for column in ("model", "duration_seconds", "terminal_reason", "changed_files",
                       "tool_calls", "first_turn_cache_read_tokens",
                       "washout_gap_seconds", "aux_model_tokens"):
            self.assertIn(column, SUMMARY_COLUMNS)


class MainModelTests(unittest.TestCase):
    def test_the_main_model_is_the_one_that_produced_the_turns(self):
        """result.json has no model field, and modelUsage is a dict whose first
        key is whichever model happened to be billed first - often the helper."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.jsonl"
            path.write_text("\n".join(json.dumps({
                "type": "assistant",
                "message": {"id": f"m{i}", "role": "assistant", "model": "claude-sonnet-5",
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                            "content": []},
            }) for i in range(2)) + "\n")
            turns = extract_turns(path)
            self.assertEqual(turns[0].model, "claude-sonnet-5")

    def test_the_auxiliary_total_excludes_the_model_that_ran_the_task(self):
        result = {"modelUsage": {
            "claude-haiku-4-5": {"inputTokens": 100, "outputTokens": 200},
            "claude-sonnet-5": {"inputTokens": 999999, "outputTokens": 999999},
        }}
        self.assertEqual(aux_model_tokens(result, "claude-sonnet-5"), 300)


class NoSilentWipeTests(unittest.TestCase):
    """Once the raw runs are discarded, a re-collect that finds nothing must not
    take the published rows down with it."""

    def _seed(self, path):
        path.write_text(
            "run_date,run_id,value\n2026-09-06,BASE-01,1\npilot,BASE-01,2\n")

    def test_collecting_a_batch_with_no_attempts_leaves_published_rows_alone(self):
        from benchmark.reports.collect import collect_batch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            activity, summary = root / "a.csv", root / "s.csv"
            self._seed(activity)
            self._seed(summary)
            empty = root / "runs" / "2026-09-06"
            empty.mkdir(parents=True)
            collect_batch(empty, activity, summary)
            self.assertIn("2026-09-06,BASE-01,1", activity.read_text())
            self.assertIn("2026-09-06,BASE-01,1", summary.read_text())

    def test_a_batch_that_does_produce_rows_still_replaces_its_own(self):
        from benchmark.reports.collect import _rewrite
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"
            self._seed(path)
            _rewrite(path, ("run_date", "run_id", "value"), "2026-09-06",
                     [["2026-09-06", "BASE-02", 9]])
            text = path.read_text()
            self.assertIn("2026-09-06,BASE-02,9", text)
            self.assertNotIn("BASE-01,1", text)
            self.assertIn("pilot,BASE-01,2", text)


class RunTotalsTests(unittest.TestCase):
    """The overview needs two per-run totals and nothing else from the turn log.
    Publishing them keeps that screen independent of the largest file."""

    def test_the_summary_carries_the_run_totals(self):
        for column in ("processed_tokens", "context_tax_tokens"):
            self.assertIn(column, SUMMARY_COLUMNS)

    def test_the_totals_match_the_turn_rows_they_summarise(self):
        import csv
        activity = Path("data/activity-log.csv")
        summary = Path("data/run-summary.csv")
        if not activity.exists():
            self.skipTest("published data is not present")
        totals = {}
        for row in csv.DictReader(activity.open()):
            key = (row["run_date"], row["run_id"])
            got = totals.setdefault(key, [0, 0])
            got[0] += int(row["context_tokens"]) + int(row["output_tokens"])
            got[1] += int(row["context_tax_tokens"])
        for row in csv.DictReader(summary.open()):
            key = (row["run_date"], row["run_id"])
            self.assertEqual(int(row["processed_tokens"]), totals[key][0], key)
            self.assertEqual(int(row["context_tax_tokens"]), totals[key][1], key)


class InvalidRunsHaveAReasonTests(unittest.TestCase):
    """A row excluded from comparison.csv must say why - CI catches a future
    collect_batch regression that publishes an invalid run silently."""

    def test_every_non_measurable_published_run_has_a_recorded_reason(self):
        import csv
        summary = Path("data/run-summary.csv")
        if not summary.exists():
            self.skipTest("published data is not present")
        with summary.open() as stream:
            for row in csv.DictReader(stream):
                if row["measurable"] == "0":
                    self.assertTrue(row.get("invalid_reason"),
                                    f"{row['run_date']}/{row['run_id']} has no invalid_reason")
