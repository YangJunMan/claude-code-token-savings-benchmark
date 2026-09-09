import unittest
from pathlib import Path

from benchmark.runner.contracts import load_conditions, load_config


class ContractTests(unittest.TestCase):
    def test_published_conditions_lead_in_a_fixed_order(self):
        """The five published arms keep their order so past runs stay comparable,
        and BASE stays first because washout eligibility is measured against the
        preceding condition.  Newly declared optimizers append after them."""
        config = load_config(Path("benchmark/config.json"))
        published = ["BASE", "H-ON", "C-FULL", "C-BRIEF", "R-ON"]
        self.assertEqual([c.value for c in config.conditions][:len(published)], published)
        self.assertEqual(config.washout_seconds, 4200)
        self.assertEqual(config.model, "claude-sonnet-5")
        self.assertEqual(config.effort, "medium")

    def test_each_condition_runs_once_by_default(self):
        conditions = load_conditions(Path("benchmark/config.json"))
        for identifier, item in conditions.items():
            with self.subTest(condition=identifier):
                self.assertEqual(item.repeat, 1)

    def test_every_condition_is_unique(self):
        conditions = load_conditions(Path("benchmark/config.json"))
        self.assertEqual(len(conditions), len({item.value for item in conditions.values()}))


if __name__ == "__main__":
    unittest.main()
