import unittest
from pathlib import Path
from benchmark.runner.conditions import brief_overlay, build_condition, condition, conditions


class ConditionTests(unittest.TestCase):
    def test_brief_overlay_is_exact(self):
        self.assertEqual(brief_overlay(), Path("benchmark/prompts/be-brief.txt").read_text())

    def test_each_adapter_names_only_its_optimizer(self):
        expected = {
            "BASE": "none", "H-ON": "headroom",
            "C-FULL": "caveman", "C-BRIEF": "brief",
            "R-ON": "rtk",
        }
        for identifier, optimizer in expected.items():
            spec = build_condition(condition(identifier), Path("/tmp/run"))
            self.assertEqual(spec.optimizer, optimizer)

    def test_baseline_applies_no_treatment_at_all(self):
        spec = build_condition(condition("BASE"), Path("/tmp/run"))
        self.assertIsNone(spec.proxy)
        self.assertIsNone(spec.plugin)
        self.assertIsNone(spec.hook)
        self.assertEqual(spec.prompt_overlay, "")
        self.assertEqual(spec.prompt_prefix, "")

    def test_each_treatment_changes_exactly_one_thing_from_the_baseline(self):
        """The comparison is only readable while every arm differs from BASE in
        one way.  The mechanism field makes that mechanical: it selects a single
        slot, so two treatments cannot be applied by accident."""
        treatments = {"H-ON": "proxy", "C-FULL": "plugin",
                      "C-BRIEF": "prompt_overlay", "R-ON": "hook"}
        for identifier, expected in treatments.items():
            spec = build_condition(condition(identifier), Path("/tmp/run"))
            active = {
                "proxy": bool(spec.proxy),
                "plugin": bool(spec.plugin),
                "prompt_overlay": bool(spec.prompt_overlay),
                "hook": bool(spec.hook),
            }
            self.assertEqual([name for name, on in active.items() if on], [expected])

    def test_headroom_uses_its_own_default_mode(self):
        """`--mode token` corrupted the prompt; the tool is judged on its default."""
        spec = build_condition(condition("H-ON"), Path("/tmp/run"))
        self.assertIn("cache", spec.proxy["args"])

    def test_every_declared_condition_builds(self):
        """A declaration that no mechanism can serve must fail loudly here, not
        halfway through a paid run."""
        for item in conditions().values():
            self.assertEqual(build_condition(item, Path("/tmp/run")).condition, item)


if __name__ == "__main__":
    unittest.main()
