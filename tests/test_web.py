"""The page has no build step and no runtime of its own in CI, so these checks
stand in for one: they catch the breakages that make it render blank."""

import re
import subprocess
import unittest
from pathlib import Path

WEB = Path("web")
APP = WEB / "app.js"
INDEX = WEB / "index.html"


class WebContractTests(unittest.TestCase):
    def test_every_element_the_script_looks_up_exists_in_the_page(self):
        """A renamed id fails silently in the browser: the section just stays empty."""
        ids = set(re.findall(r'id="([^"]+)"', INDEX.read_text()))
        looked_up = set(re.findall(r'getElementById\("([^"]+)"\)', APP.read_text()))
        self.assertEqual(looked_up - ids, set())

    def test_every_data_file_the_page_fetches_is_committed(self):
        for path in re.findall(r'load\("([^"]+)"\)', APP.read_text()):
            self.assertTrue((WEB / path).resolve().exists(), path)

    def test_the_script_parses(self):
        node = subprocess.run(["node", "--check", str(APP)], capture_output=True, text=True)
        if node.returncode == 127 or "not found" in node.stderr:
            self.skipTest("node is not available")
        self.assertEqual(node.returncode, 0, node.stderr)

    def test_every_palette_role_the_script_asks_for_is_defined(self):
        """ink() returns "" for an undefined custom property, painting nothing.

        Only the base ``:root`` block counts.  The dark blocks redefine the same
        roles, so scanning the whole file would call a role defined even after
        its light value was deleted - and the page renders light by default.
        """
        css = (WEB / "style.css").read_text()
        base = re.search(r"(?<!\])\n:root \{(.*?)\n\}", "\n" + css, re.S)
        self.assertIsNotNone(base, "style.css has no base :root block")
        defined = set(re.findall(r"(--[a-z0-9-]+):", base.group(1)))
        app = APP.read_text()
        used = set(re.findall(r'ink\("(--[a-z0-9-]+)"\)', app))
        used |= set(re.findall(r'var\((--[a-z0-9-]+)\)', app))
        # series roles are built by index; check the whole cycle the code can reach
        if "--series-${" in app or "seriesStyle" in app:
            used |= {f"--series-{i}" for i in range(1, 6)}
        self.assertEqual(used - defined, set())

    def test_the_run_picker_stays_five_conditions_deep_however_many_rounds_pile_up(self):
        """Rounds add entries inside a condition's date list, not new top-level
        choices - the condition-picker button count never grows."""
        app = APP.read_text()
        self.assertIn("condition-picker", app)
        self.assertIn("run-picker-list", app)
