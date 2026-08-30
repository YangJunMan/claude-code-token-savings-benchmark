import unittest
from pathlib import Path

from benchmark.runner.contracts import Condition, load_config


class ContractTests(unittest.TestCase):
    def test_config_has_fixed_order_and_4200_second_washout(self):
        config = load_config(Path("benchmark/config.json"))
        self.assertEqual([c.value for c in config.conditions], [
            "BASE", "H-ON", "C-FULL", "C-BRIEF", "R-ON"
        ])
        self.assertGreaterEqual(config.baseline_attempts, 2)
        self.assertEqual(config.washout_seconds, 4200)
        self.assertEqual(config.model, "claude-sonnet-5")
        self.assertEqual(config.effort, "medium")

    def test_every_condition_is_unique(self):
        self.assertEqual(len(Condition), len({item.value for item in Condition}))


if __name__ == "__main__":
    unittest.main()
