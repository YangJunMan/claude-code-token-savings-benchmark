import json
import tempfile
import unittest
from pathlib import Path

from benchmark.runner.artifacts import summarize_transcript


class ArtifactTests(unittest.TestCase):
    def test_transcript_summary_deduplicates_turn_usage_and_counts_tools(self):
        rows = [
            {"type": "assistant", "message": {"id": "m1", "usage": {
                "input_tokens": 2, "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 0, "output_tokens": 10,
            }, "content": [{"type": "thinking", "text": "x"}]}},
            {"type": "assistant", "message": {"id": "m1", "usage": {
                "input_tokens": 2, "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 0, "output_tokens": 10,
            }, "content": [{"type": "tool_use", "id": "t1"}]}},
            {"type": "assistant", "message": {"id": "m2", "usage": {
                "input_tokens": 2, "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 100, "output_tokens": 20,
            }, "content": [
                {"type": "tool_use", "id": "t2"},
                {"type": "text", "text": "done"},
            ]}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            summary = summarize_transcript(path)
        self.assertEqual(summary["turns"], 2)
        self.assertEqual(summary["tool_calls"], 2)
        self.assertEqual(summary["first_turn_cache_read_tokens"], 0)
        self.assertEqual(summary["final_response_chars"], 4)

    def test_housekeeping_failure_does_not_lose_a_paid_run(self):
        """A completed run is already paid for, so a transcript that cannot be
        archived is recorded as unmeasurable rather than raised away."""
        import inspect
        from benchmark.runner import claude as module
        source = inspect.getsource(module.run_attempt)
        self.assertIn("except RuntimeError as error:", source)

    def test_harness_paths_are_excluded_from_the_measured_diff(self):
        from benchmark.runner.claude import HARNESS_ONLY_PATHS
        for pattern in ("__pycache__/", "*.pyc", ".claude/"):
            self.assertIn(pattern, HARNESS_ONLY_PATHS)


if __name__ == "__main__":
    unittest.main()
