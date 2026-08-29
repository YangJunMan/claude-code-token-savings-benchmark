import unittest

from benchmark.runner.api_parallel import API_CONDITIONS, build_jobs, require_api_key


class ApiParallelTests(unittest.TestCase):
    def test_build_jobs_has_one_unique_nonce_per_condition(self):
        jobs = build_jobs(max_turns=12)
        self.assertEqual([job["condition"] for job in jobs], API_CONDITIONS)
        self.assertEqual(len({job["nonce"] for job in jobs}), 7)
        self.assertTrue(all(job["max_turns"] == 12 for job in jobs))

    def test_api_runner_refuses_to_fall_back_to_oauth(self):
        with self.assertRaises(RuntimeError):
            require_api_key({"ANTHROPIC_API_KEY": ""})
        self.assertEqual(require_api_key({"ANTHROPIC_API_KEY": "not-printed"}), "not-printed")


if __name__ == "__main__":
    unittest.main()
