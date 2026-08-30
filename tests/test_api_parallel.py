import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from benchmark.runner.api_parallel import (
    REPRODUCTION_PLAN,
    API_CONDITIONS,
    build_jobs,
    build_reproduction_jobs,
    require_api_key,
    require_paid_run_confirmation,
    run_reproduction,
)
from benchmark.runner.claude import (
    configure_api_environment,
    build_isolation_mcp_config,
    isolation_mcp_config_path,
)


class ApiParallelTests(unittest.TestCase):
    def test_build_jobs_has_one_unique_nonce_per_condition(self):
        jobs = build_jobs(max_turns=12)
        self.assertEqual([job["condition"] for job in jobs], API_CONDITIONS)
        self.assertEqual(len({job["nonce"] for job in jobs}), len(jobs))
        self.assertTrue(all(job["max_turns"] == 12 for job in jobs))

    def test_natural_cache_jobs_leave_provider_prompt_caching_enabled(self):
        jobs = build_jobs(max_turns=12, disable_prompt_caching=False)
        self.assertTrue(all(job["disable_prompt_caching"] is False for job in jobs))

    def test_natural_cache_jobs_carry_the_same_tool_prefix_isolation_variant(self):
        jobs = build_jobs(
            max_turns=12, disable_prompt_caching=False,
            isolation_tools=("WebSearch",),
        )
        self.assertTrue(all(job["isolation_tools"] == ("WebSearch",) for job in jobs))

    def test_natural_cache_jobs_have_unique_mcp_tool_prefix_salts(self):
        jobs = build_jobs(max_turns=12, disable_prompt_caching=False, isolation_mcp=True)
        configs = [build_isolation_mcp_config("/tmp/sentinel.py", job["nonce"]) for job in jobs]
        names = [next(iter(config["mcpServers"].values()))["args"][1] for config in configs]
        self.assertEqual(len(set(names)), len(jobs))
        self.assertTrue(all(name.startswith("benchmark_sentinel_") for name in names))
        self.assertTrue(all(job["isolation_mcp"] is True for job in jobs))

    def test_mcp_config_argument_is_absolute_for_worktree_subprocess(self):
        path = isolation_mcp_config_path("benchmark/runs/BASE/attempt-01")
        self.assertTrue(path.is_absolute())

    def test_natural_cache_environment_does_not_set_disable_flag(self):
        environment = configure_api_environment(
            {"ANTHROPIC_API_KEY": "not-printed"}, disable_prompt_caching=False
        )
        self.assertNotIn("DISABLE_PROMPT_CACHING", environment)

    def test_api_runner_refuses_to_fall_back_to_oauth(self):
        with self.assertRaises(RuntimeError):
            require_api_key({"ANTHROPIC_API_KEY": ""})
        self.assertEqual(require_api_key({"ANTHROPIC_API_KEY": "not-printed"}), "not-printed")

    def test_public_reproduction_plan_repeats_the_baseline_and_headroom(self):
        """Repeats are the budget line that makes any percentage interpretable."""
        conditions = [condition for _, condition in REPRODUCTION_PLAN]
        counts = {name: conditions.count(name) for name in set(conditions)}
        self.assertEqual(counts["BASE"], 2)
        self.assertEqual(counts["H-ON"], 2)
        self.assertEqual(counts["C-FULL"], 1)
        self.assertEqual(counts["C-BRIEF"], 1)
        self.assertEqual(counts["R-ON"], 1)

    def test_paid_run_requires_exact_confirmation_and_positive_budget(self):
        with self.assertRaises(RuntimeError):
            require_paid_run_confirmation(False, 12.0)
        with self.assertRaises(ValueError):
            require_paid_run_confirmation(True, 0)
        self.assertEqual(require_paid_run_confirmation(True, 12.0), 12.0)

    def test_reproduction_refuses_nonempty_output_root(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            (run_root / "existing.txt").write_text("immutable")
            with self.assertRaises(FileExistsError):
                run_reproduction(Path("."), run_root, run_root / "report", 50, 15.0)

    def test_reproduction_stops_between_jobs_when_budget_is_reached(self):
        records = [
            {"label": "BASE-01", "condition": "BASE", "state": "completed", "cost_usd": 1.5},
            {"label": "BASE-02", "condition": "BASE", "state": "completed", "cost_usd": 1.5},
        ]
        with tempfile.TemporaryDirectory() as directory, patch(
            "benchmark.runner.api_parallel._run_one", side_effect=records
        ) as mocked, patch("benchmark.runner.api_parallel.generate_report"):
            result = run_reproduction(
                Path("."), Path(directory) / "runs", Path(directory) / "report", 50, 4.0
            )
        self.assertEqual(len(result), 2)
        self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
