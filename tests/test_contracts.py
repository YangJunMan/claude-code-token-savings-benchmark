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

    def test_the_baseline_is_repeated_so_the_noise_floor_is_measurable(self):
        conditions = load_conditions(Path("benchmark/config.json"))
        self.assertEqual(conditions["BASE"].repeat, 2)

    def test_every_condition_is_unique(self):
        conditions = load_conditions(Path("benchmark/config.json"))
        self.assertEqual(len(conditions), len({item.value for item in conditions.values()}))


if __name__ == "__main__":
    unittest.main()
