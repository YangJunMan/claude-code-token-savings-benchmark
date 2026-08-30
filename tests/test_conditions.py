import unittest
from pathlib import Path
from benchmark.runner.conditions import brief_overlay, build_condition
from benchmark.runner.contracts import Condition


class ConditionTests(unittest.TestCase):
    def test_brief_overlay_is_exact(self):
        self.assertEqual(brief_overlay(), Path("benchmark/prompts/be-brief.txt").read_text())

    def test_each_adapter_names_only_its_optimizer(self):
        expected = {
            Condition.BASE: "none", Condition.H_ON: "headroom",
            Condition.C_FULL: "caveman", Condition.C_BRIEF: "brief",
            Condition.R_ON: "rtk",
        }
        for condition, optimizer in expected.items():
            self.assertEqual(build_condition(condition, Path("/tmp/run")).optimizer, optimizer)

    def test_baseline_applies_no_treatment_at_all(self):
        spec = build_condition(Condition.BASE, Path("/tmp/run"))
        self.assertIsNone(spec.headroom_mode)
        self.assertFalse(spec.load_caveman)
        self.assertFalse(spec.rtk_hook)
        self.assertEqual(spec.prompt_overlay, "")

    def test_each_treatment_changes_exactly_one_thing_from_the_baseline(self):
        treatments = {
            Condition.H_ON: "headroom_mode", Condition.C_FULL: "load_caveman",
            Condition.C_BRIEF: "prompt_overlay", Condition.R_ON: "rtk_hook",
        }
        for condition, field in treatments.items():
            spec = build_condition(condition, Path("/tmp/run"))
            active = {
                "headroom_mode": bool(spec.headroom_mode),
                "load_caveman": spec.load_caveman,
                "prompt_overlay": bool(spec.prompt_overlay),
                "rtk_hook": spec.rtk_hook,
            }
            self.assertEqual([name for name, on in active.items() if on], [field])

    def test_headroom_uses_its_own_default_mode(self):
        """`--mode token` corrupted the prompt; the tool is judged on its default."""
        self.assertEqual(build_condition(Condition.H_ON, Path("/tmp/run")).headroom_mode, "cache")


if __name__ == "__main__":
    unittest.main()
