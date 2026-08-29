import unittest
from pathlib import Path
from benchmark.runner.conditions import brief_overlay, build_condition
from benchmark.runner.contracts import Condition


class ConditionTests(unittest.TestCase):
    def test_brief_overlay_is_exact(self):
        self.assertEqual(brief_overlay(), Path("benchmark/prompts/be-brief.txt").read_text())

    def test_each_adapter_names_only_its_optimizer(self):
        expected = {
            Condition.H_ON: "headroom", Condition.H_OFF: "headroom",
            Condition.C_FULL: "caveman", Condition.C_NON: "caveman",
            Condition.C_BRIEF: "caveman", Condition.R_ON: "rtk", Condition.R_OFF: "rtk",
        }
        for condition, optimizer in expected.items():
            self.assertEqual(build_condition(condition, Path("/tmp/run")).optimizer, optimizer)
