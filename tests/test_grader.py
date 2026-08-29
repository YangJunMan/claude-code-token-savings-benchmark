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
        text = "Changed files: x. Tests: 7 passed. Decision: transaction. Limitation: SQLite."
        self.assertEqual(score_evidence(text, 0, ["x"]), 10)

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
            self.assertIn("Ran 6 tests", evidence.read_text())
