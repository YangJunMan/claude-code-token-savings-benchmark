import json
import tempfile
import unittest
from pathlib import Path

from benchmark.runner.contracts import build_conditions, load_conditions
from benchmark.runner.api_parallel import build_reproduction_plan
from benchmark.runner.conditions import build_condition
from benchmark.runner.preflight import optimizer_tools, run_preflight
from benchmark.runner.public_cli import paid_preflight


BASE_DECLARATION = {"id": "BASE", "label": "Baseline", "optimizer": "none",
                    "mode_command": "baseline", "mechanism": "none"}


def write_config(conditions):
    path = Path(tempfile.mkdtemp()) / "config.json"
    path.write_text(json.dumps({"conditions": conditions}))
    return path


class LoadConditionsTest(unittest.TestCase):
    def test_a_new_optimizer_needs_only_a_declaration(self):
        """The whole point: adding a token-saving skill must not touch Python.

        If this test ever needs a code change to pass, the registry has
        regressed back into a hardcoded list.
        """
        newcomer = {"id": "X-ON", "label": "Some New Skill", "optimizer": "newthing",
                    "mode_command": "on", "mechanism": "hook",
                    "hook": {"matcher": "Bash", "command": "newthing hook"}}

        conditions = load_conditions(write_config([BASE_DECLARATION, newcomer]))

        self.assertEqual(conditions["X-ON"].label, "Some New Skill")
        self.assertEqual(conditions["X-ON"].mechanism, "hook")
        self.assertEqual(conditions["X-ON"].settings["command"], "newthing hook")

    def test_value_keeps_the_id_so_run_directories_stay_stable(self):
        """Run directories are named by `condition.value`; renaming that field
        would silently orphan every previously recorded run."""
        conditions = load_conditions(write_config([BASE_DECLARATION]))

        self.assertEqual(conditions["BASE"].value, "BASE")

    def test_declaration_order_is_preserved(self):
        """Washout eligibility is computed from the previous condition in order."""
        second = dict(BASE_DECLARATION, id="Z-ON")
        third = dict(BASE_DECLARATION, id="A-ON")

        conditions = load_conditions(write_config([BASE_DECLARATION, second, third]))

        self.assertEqual(list(conditions), ["BASE", "Z-ON", "A-ON"])

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            load_conditions(write_config([BASE_DECLARATION, dict(BASE_DECLARATION)]))


class PreflightFollowsDeclarationsTest(unittest.TestCase):
    """Declaring a new optimizer must also make preflight check for its tool.

    Otherwise a newly declared condition fails halfway through a paid run
    instead of before the first model call.
    """

    def test_a_declared_hook_command_is_checked(self):
        declared = build_conditions([
            BASE_DECLARATION,
            {"id": "X-ON", "label": "X", "optimizer": "x", "mode_command": "on",
             "mechanism": "hook",
             "hook": {"matcher": "Bash", "command": "definitely-not-installed hook"}},
        ])

        result = paid_preflight(conditions=declared)

        self.assertFalse(result["ok"])
        self.assertIn("missing_tool: definitely-not-installed", result["errors"])

    def test_a_baseline_only_config_needs_no_optimizer_tool(self):
        result = paid_preflight(conditions=build_conditions([BASE_DECLARATION]))

        self.assertEqual(
            [error for error in result["errors"] if error.startswith("missing_tool")], []
        )


class ReproductionPlanTest(unittest.TestCase):
    """Repeats are the budget line that makes any percentage interpretable, so
    how often a condition runs belongs in its declaration, not in Python."""

    def test_repeat_count_comes_from_the_declaration(self):
        conditions = build_conditions([
            dict(BASE_DECLARATION, repeat=2),
            {"id": "X-ON", "label": "X", "optimizer": "x", "mode_command": "on",
             "mechanism": "none"},
        ])

        plan = build_reproduction_plan(conditions)

        self.assertEqual(plan, (("BASE-01", "BASE"), ("BASE-02", "BASE"), ("X-ON", "X-ON")))

    def test_unrepeated_condition_keeps_its_bare_id_as_the_label(self):
        """Run directories are named by the label; suffixing a single run would
        break every path recorded for it."""
        plan = build_reproduction_plan(build_conditions([BASE_DECLARATION]))

        self.assertEqual(plan, (("BASE", "BASE"),))


class AddingASkillTouchesNoPythonTest(unittest.TestCase):
    """The end-to-end promise: a declaration alone carries a new optimizer
    through every stage that has to know about it."""

    DECLARATION = {"id": "X-ON", "label": "Some New Skill", "optimizer": "newthing",
                   "mode_command": "on", "repeat": 2, "mechanism": "hook",
                   "hook": {"event": "PreToolUse", "matcher": "*",
                            "command": "newthing hook claude"}}

    def setUp(self):
        self.conditions = build_conditions([BASE_DECLARATION, self.DECLARATION])

    def test_it_reaches_the_treatment_spec(self):
        spec = build_condition(self.conditions["X-ON"], Path("/tmp/run"))

        self.assertEqual(spec.hook["command"], "newthing hook claude")
        self.assertIsNone(spec.proxy)
        self.assertIsNone(spec.plugin)

    def test_it_reaches_the_reproduction_plan_with_its_declared_repeats(self):
        labels = [label for label, _ in build_reproduction_plan(self.conditions)]

        self.assertEqual(labels, ["BASE", "X-ON-01", "X-ON-02"])

    def test_it_reaches_preflight(self):
        errors = paid_preflight(conditions=self.conditions)["errors"]

        self.assertIn("missing_tool: newthing", errors)

    def test_both_preflight_entry_points_check_the_same_tools(self):
        """Two separate implementations of the same check drift: a new skill
        gets added to one and silently skipped by the other."""
        paid = paid_preflight(conditions=self.conditions)
        tools = optimizer_tools(Path("."), self.conditions.values())

        self.assertEqual(
            {info["requires"] for info in tools.values() if not info["path"]},
            {name.split(": ")[1] for name in paid["errors"]
             if name.startswith("missing_tool")},
        )


class ConditionIsUsableAsAKeyTest(unittest.TestCase):
    """The Enum this replaced was hashable, and callers group results by
    condition.  A dict field silently removed that."""

    def test_conditions_can_be_grouped_in_a_set_or_dict(self):
        conditions = build_conditions([
            BASE_DECLARATION,
            {"id": "X-ON", "label": "X", "optimizer": "x", "mode_command": "on",
             "mechanism": "hook", "hook": {"matcher": "Bash", "command": "x hook"}},
        ])

        grouped = {item: item.value for item in conditions.values()}

        self.assertEqual(len(set(conditions.values())), 2)
        self.assertEqual(grouped[conditions["X-ON"]], "X-ON")


if __name__ == "__main__":
    unittest.main()
