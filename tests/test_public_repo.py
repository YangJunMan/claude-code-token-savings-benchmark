import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.runner.claude import (
    build_headroom_command,
    resolve_caveman_plugin_dir,
    resolve_headroom_binary,
)
from benchmark.runner.conditions import build_condition
from benchmark.runner.contracts import Condition


ROOT = Path(__file__).resolve().parents[1]


class PublicRepoTests(unittest.TestCase):
    def test_public_entrypoint_files_exist(self):
        for relative in (
            "Makefile",
            ".env.example",
            "docs/FULL_REPORT.md",
            "docs/REPRODUCTION.md",
            "data/published-measurements.csv",
        ):
            self.assertTrue((ROOT / relative).exists(), relative)

    def test_sensitive_local_files_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text()
        self.assertIn(".env", ignored.splitlines())
        self.assertIn("*.pem", ignored.splitlines())
        self.assertIn("__pycache__/", ignored.splitlines())

    def test_headroom_binary_prefers_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "headroom"
            executable.write_text("#!/bin/sh\n")
            executable.chmod(0o755)
            with patch.dict(os.environ, {"HEADROOM_BIN": str(executable)}):
                self.assertEqual(resolve_headroom_binary(ROOT), executable)

    def test_caveman_directory_prefers_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "caveman"
            plugin.mkdir()
            with patch.dict(os.environ, {"CAVEMAN_PLUGIN_DIR": str(plugin)}):
                self.assertEqual(resolve_caveman_plugin_dir(), plugin)

    def test_headroom_reproduction_uses_cache_mode(self):
        command = build_headroom_command(
            Path("/tmp/headroom"), optimized=True, log_path=Path("/tmp/log.jsonl"), port=8787
        )
        self.assertIn("cache", command)
        self.assertNotIn("token", command)

    def test_brief_condition_builds_outside_repository_cwd(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                spec = build_condition(Condition.C_BRIEF, Path(directory) / "worktree")
            finally:
                os.chdir(previous)
        self.assertIn("Be brief", spec.prompt_overlay)


if __name__ == "__main__":
    unittest.main()
