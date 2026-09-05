import json
import tempfile
import unittest
from pathlib import Path

from benchmark.reports.generate import collect_rows, paired_comparisons, treatments
from benchmark.runner.contracts import build_conditions


DECLARATIONS = [
    {"id": "BASE", "label": "Baseline", "optimizer": "none",
     "mode_command": "baseline", "mechanism": "none", "repeat": 2},
    {"id": "X-ON", "label": "Some New Skill", "optimizer": "newthing",
     "mode_command": "on", "mechanism": "hook",
     "hook": {"matcher": "Bash", "command": "newthing hook"}},
]


def write_result(run_root, label, condition, cost, tokens):
    directory = run_root / label / "attempt-01"
    directory.mkdir(parents=True)
    (directory / "result.json").write_text(json.dumps({
        "condition": condition,
        "returncode": 0, "terminal_reason": "completed", "public_returncode": 0,
        "final_text": "Changed files: a.py", "changed_files": ["a.py"],
        "last_request_epoch": 1000,
        "transcript_summary": {"first_turn_cache_read_tokens": 0, "turns": 10},
        "modelUsage": {"claude-sonnet-5": {
            "inputTokens": tokens, "cacheCreationInputTokens": 0,
            "cacheReadInputTokens": 0, "outputTokens": 0, "costUSD": cost,
        }},
    }))
    (directory / "quality.json").write_text(json.dumps({"score": 90, "critical_pass": "6/6"}))


class ReportFollowsTheRegistryTest(unittest.TestCase):
    """A skill that runs but never reaches the results table has not been added.

    The declaration must carry it all the way to the published comparison.
    """

    def setUp(self):
        self.conditions = build_conditions(DECLARATIONS)

    def test_a_newly_declared_condition_becomes_a_comparison(self):
        self.assertEqual(
            treatments(self.conditions), (("Some New Skill vs baseline", "X-ON"),)
        )

    def test_a_newly_declared_condition_survives_row_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            write_result(run_root, "BASE-01", "BASE", 1.0, 1000)
            write_result(run_root, "BASE-02", "BASE", 1.0, 1000)
            write_result(run_root, "X-ON", "X-ON", 0.5, 500)

            valid, invalid = collect_rows(run_root, self.conditions)

            self.assertEqual([row["condition"] for row in valid],
                             ["BASE", "BASE", "X-ON"])
            self.assertEqual(invalid, [])

    def test_the_new_condition_is_compared_against_the_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            write_result(run_root, "BASE-01", "BASE", 1.0, 1000)
            write_result(run_root, "BASE-02", "BASE", 1.0, 1000)
            write_result(run_root, "X-ON", "X-ON", 0.5, 500)
            valid, _ = collect_rows(run_root, self.conditions)

            result = {item["comparison"]: item
                      for item in paired_comparisons(valid, self.conditions)}

            self.assertAlmostEqual(
                result["Some New Skill vs baseline"]["cost_saving_pct"], 50.0
            )


if __name__ == "__main__":
    unittest.main()
