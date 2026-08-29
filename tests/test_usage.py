import unittest
from benchmark.runner.usage import parse_usage


class UsageTests(unittest.TestCase):
    def test_sums_every_model_and_cache_bucket(self):
        result = {"modelUsage": {
            "claude-sonnet-5": {"inputTokens": 5000, "cacheCreationInputTokens": 70000,
                "cacheReadInputTokens": 450000, "outputTokens": 15000, "costUSD": 0.53},
            "helper": {"inputTokens": 1000, "cacheCreationInputTokens": 2000,
                "cacheReadInputTokens": 7000, "outputTokens": 500, "costUSD": 0.01}
        }}
        usage = parse_usage(result)
        self.assertEqual(usage.input_related_tokens, 535000)
        self.assertEqual(usage.output_tokens, 15500)
        self.assertAlmostEqual(usage.cost_usd, 0.54)
