import unittest

from benchmark.runner.api_parallel import API_CONDITIONS, build_jobs, require_api_key
from benchmark.runner.claude import (
    configure_api_environment,
    build_isolation_mcp_config,
    isolation_mcp_config_path,
)


class ApiParallelTests(unittest.TestCase):
    def test_build_jobs_has_one_unique_nonce_per_condition(self):
        jobs = build_jobs(max_turns=12)
        self.assertEqual([job["condition"] for job in jobs], API_CONDITIONS)
        self.assertEqual(len({job["nonce"] for job in jobs}), 7)
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
        self.assertEqual(len(set(names)), 7)
        self.assertTrue(all(name.startswith("benchmark_sentinel_") for name in names))
        self.assertTrue(all(job["isolation_mcp"] is True for job in jobs))

    def test_mcp_config_argument_is_absolute_for_worktree_subprocess(self):
        path = isolation_mcp_config_path("benchmark/runs-api-natural-v3/C-NON/attempt-01")
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


if __name__ == "__main__":
    unittest.main()
