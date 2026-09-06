import json
import tempfile
import unittest
from pathlib import Path

from benchmark.reports.activity_log import (
    ACTIVITY_COLUMNS, activity_rows, extract_turns, tool_target)

WORKTREE = "/Users/someone/projects/bench/benchmark/runs/2026-09-06/BASE/attempt-01/worktree"


def transcript(tmp, calls_per_turn):
    """One assistant message per turn, each carrying the given tool_use blocks."""
    lines = []
    for index, calls in enumerate(calls_per_turn):
        lines.append(json.dumps({
            "type": "assistant",
            "message": {
                "id": f"msg_{index}",
                "role": "assistant",
                "usage": {"input_tokens": 1, "cache_read_input_tokens": 1000 * (index + 1),
                          "output_tokens": 10},
                "content": [{"type": "tool_use", "name": name, "input": payload}
                            for name, payload in calls],
            },
        }))
    path = Path(tmp) / "transcript.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


class ToolTargetTests(unittest.TestCase):
    def test_a_file_path_is_reported_relative_to_the_worktree(self):
        """Absolute paths name the machine that ran the benchmark, not the work."""
        self.assertEqual(
            tool_target("Read", {"file_path": f"{WORKTREE}/gpu_platform/store.py"}),
            "gpu_platform/store.py")

    def test_a_bash_command_is_reduced_to_the_program_it_ran(self):
        self.assertEqual(
            tool_target("Bash", {"command": f'cd "{WORKTREE}" && python3 -m unittest discover'}),
            "python3")

    def test_an_unknown_tool_contributes_no_target(self):
        self.assertEqual(tool_target("Glob", {"pattern": "**/*.py"}), "")

    def test_no_absolute_path_survives_any_tool_input(self):
        """The CI secret scan fails the build on a leaked home directory."""
        for name, payload in (
            ("Read", {"file_path": "/Users/someone/outside/secret.txt"}),
            ("Write", {"file_path": "/home/someone/outside/secret.txt"}),
            ("Bash", {"command": "cat /Users/someone/.ssh/id_rsa"}),
        ):
            target = tool_target(name, payload)
            self.assertNotIn("/Users/", target, name)
            self.assertNotIn("/home/", target, name)


class ActivityTargetTests(unittest.TestCase):
    def test_each_turn_records_what_its_tools_acted_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = transcript(tmp, [
                [("Read", {"file_path": f"{WORKTREE}/docs/api.md"}),
                 ("Read", {"file_path": f"{WORKTREE}/gpu_platform/store.py"})],
                [("Bash", {"command": f'cd "{WORKTREE}" && pytest -q'})],
            ])
            turns = extract_turns(path)
            self.assertEqual(turns[0].targets, ("docs/api.md", "gpu_platform/store.py"))
            self.assertEqual(turns[1].targets, ("pytest",))

    def test_targets_are_published_as_a_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = transcript(tmp, [
                [("Read", {"file_path": f"{WORKTREE}/docs/api.md"})],
                [("Bash", {"command": "ls"})],
            ])
            turns = extract_turns(path)
            rows = activity_rows("2026-09-06", "BASE-01", "BASE", turns)
            column = ACTIVITY_COLUMNS.index("targets")
            self.assertEqual(rows[0][column], "docs/api.md")
