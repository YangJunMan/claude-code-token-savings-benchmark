import unittest
import tempfile
from pathlib import Path

from benchmark.grader.grade import SCORE_WEIGHTS, grade_attempt, score_evidence


class GraderTests(unittest.TestCase):
    def test_score_weights_sum_to_100(self):
        self.assertEqual(sum(SCORE_WEIGHTS.values()), 100)

    def test_false_completion_claim_fails_evidence_gate(self):
        self.assertEqual(score_evidence("All tests pass.", 1, ["gpu_platform/admission.py"]), 0)

    def test_evidence_requires_files_tests_decisions_and_limits(self):
        text = ("Changed files: x. Ran python3 -m unittest discover -s tests: 7 passed. "
                "Decision: transaction. Limitation: SQLite.")
        self.assertEqual(score_evidence(text, 0, ["x"]), 10)

    def test_evidence_gives_partial_credit(self):
        text = "Changed files: x. Decision: transaction."
        self.assertLess(score_evidence(text, 0, ["x"]), 10)
        self.assertGreater(score_evidence(text, 0, ["x"]), 0)

    def test_empty_final_response_scores_no_evidence(self):
        self.assertEqual(score_evidence("", 0, ["x"]), 0)

    def test_majority_over_trials_decides_a_flaky_test(self):
        """A test that passes 3 of 5 trials counts as passing, and is flagged flaky."""
        from benchmark.grader.grade import _run_hidden_trials
        import benchmark.grader.grade as module
        calls = []

        def fake_run(worktree, hidden_root, path):
            calls.append(path)
            status = "ok" if len(calls) <= 3 else "fail"
            return {"outcomes": {"m.T.test_a": status, "m.T.test_b": "ok"}, "total": 2}

        original = module._run_hidden_tests
        module._run_hidden_tests = fake_run
        try:
            with tempfile.TemporaryDirectory() as directory:
                report = _run_hidden_trials(Path(directory), Path(directory),
                                            Path(directory) / "hidden-tests.json", trials=5)
        finally:
            module._run_hidden_tests = original
        self.assertEqual(report["outcomes"]["m.T.test_a"], "ok")
        self.assertEqual(report["flaky"], ["m.T.test_a"])
        self.assertEqual(len(calls), 5)

    def test_only_critical_named_tests_gate_quality(self):
        from benchmark.grader.grade import _critical_counts
        report = {"outcomes": {"m.T.test_critical_a": "ok", "m.T.test_critical_b": "fail",
                               "m.T.test_other": "fail"}}
        self.assertEqual(_critical_counts(report), (1, 2))

    def test_grade_preserves_hidden_test_output_as_separate_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "quality.json"
            grade_attempt(Path("benchmark/fixture"), {
                "public_returncode": 0,
                "final_text": "",
                "changed_files": [],
            }, output)
            evidence = output.parent / "hidden-tests.txt"
            self.assertTrue(evidence.exists())
            self.assertRegex(evidence.read_text(), r"Ran \d+ tests")
