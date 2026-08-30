import json
import tempfile
import unittest
from pathlib import Path

from benchmark.runner.artifacts import clear_succeeded, summarize_transcript


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

    def test_clear_requires_command_echo_and_clean_exit_marker(self):
        self.assertTrue(clear_succeeded(b"prompt /clear Resume this session with:"))
        self.assertFalse(clear_succeeded(b"prompt /clear"))

    def test_clear_without_terminal_evidence_is_not_success(self):
        """Writing /clear to the pty is an attempt, not proof that it happened."""
        self.assertFalse(clear_succeeded(b"terminal omitted typed input"))

    def test_housekeeping_failure_does_not_lose_a_paid_run(self):
        """A completed run is already paid for; /clear failing must not raise."""
        import inspect
        from benchmark.runner import claude as module
        source = inspect.getsource(module.run_attempt)
        self.assertIn("except OSError as error:", source)
        self.assertIn("except RuntimeError as error:", source)
        clear_source = inspect.getsource(module.clear_session)
        self.assertIn("write_failed", clear_source)

    def test_harness_paths_are_excluded_from_the_measured_diff(self):
        from benchmark.runner.claude import HARNESS_ONLY_PATHS
        for pattern in ("__pycache__/", "*.pyc", ".claude/"):
            self.assertIn(pattern, HARNESS_ONLY_PATHS)


if __name__ == "__main__":
    unittest.main()
