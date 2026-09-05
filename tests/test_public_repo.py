import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.runner.claude import (
    build_proxy_command,
    resolve_plugin_dir,
    resolve_proxy_binary,
)
from benchmark.runner.conditions import build_condition
from benchmark.runner.conditions import condition


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

    def test_proxy_binary_prefers_the_declared_environment_override(self):
        settings = condition("H-ON").settings
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / settings["binary"]
            executable.write_text("#!/bin/sh\n")
            executable.chmod(0o755)
            with patch.dict(os.environ, {settings["env_override"]: str(executable)}):
                self.assertEqual(resolve_proxy_binary(ROOT, settings), executable)

    def test_plugin_directory_prefers_the_declared_environment_override(self):
        settings = condition("C-FULL").settings
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "plugin"
            plugin.mkdir()
            with patch.dict(os.environ, {settings["env_override"]: str(plugin)}):
                self.assertEqual(resolve_plugin_dir(settings), plugin)

    def test_plugin_glob_finds_a_versioned_directory(self):
        """The pinned path carries a version segment, so the wildcard has to
        match a whole segment rather than a name prefix."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cache/thing/thing"
            (root / "17f9f2ec2377/plugins/thing").mkdir(parents=True)
            settings = {"path_glob": str(root / "*/plugins/thing"),
                        "env_override": "UNSET_FOR_THIS_TEST"}

            self.assertEqual(
                resolve_plugin_dir(settings), root / "17f9f2ec2377/plugins/thing"
            )

    def test_headroom_reproduction_uses_cache_mode(self):
        """`--mode token` corrupted the prompt, so the declaration must not drift
        back to it."""
        command = build_proxy_command(
            Path("/tmp/headroom"), condition("H-ON").settings,
            log_path=Path("/tmp/log.jsonl"), port=8787,
        )
        self.assertIn("cache", command)
        self.assertNotIn("token", command)

    def test_proxy_argument_template_is_filled_in(self):
        command = build_proxy_command(
            Path("/tmp/headroom"), condition("H-ON").settings,
            log_path=Path("/tmp/log.jsonl"), port=9001,
        )
        self.assertIn("9001", command)
        self.assertIn("/tmp/log.jsonl", command)
        self.assertNotIn("{port}", command)

    def test_brief_condition_builds_outside_repository_cwd(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                spec = build_condition(condition("C-BRIEF"), Path(directory) / "worktree")
            finally:
                os.chdir(previous)
        self.assertIn("Be brief", spec.prompt_overlay)


if __name__ == "__main__":
    unittest.main()
