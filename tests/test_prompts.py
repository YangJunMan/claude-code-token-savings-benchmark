import unittest
from pathlib import Path


class PromptTests(unittest.TestCase):
    def test_prompt_is_english_and_contains_required_work(self):
        prompt = Path("benchmark/prompts/master.md").read_text()
        for phrase in (
            "Work entirely in English", "idempotency", "lease",
            "Kubernetes", "runbook", "Do not modify or weaken existing tests",
            "{max_turns}",
        ):
            self.assertIn(phrase, prompt)

    def test_prompt_declares_the_turn_budget_exactly_once(self):
        """The runner substitutes the real cap so the prompt can never drift from it."""
        prompt = Path("benchmark/prompts/master.md").read_text()
        self.assertEqual(prompt.count("{max_turns}"), 1)

    def test_prompt_does_not_impose_a_hard_line_cap(self):
        """A hard cap made runs spend their remaining turns trimming passing code."""
        prompt = Path("benchmark/prompts/master.md").read_text()
        self.assertNotIn("keep the total under", prompt)
        self.assertIn("guidance, not a limit", prompt)

    def test_brief_overlay_is_exact(self):
        expected = (
            "Be brief. Keep the final response concise without omitting the requested\n"
            "implementation evidence, test results, design decisions, and limitations.\n"
        )
        self.assertEqual(Path("benchmark/prompts/be-brief.txt").read_text(), expected)


if __name__ == "__main__":
    unittest.main()
