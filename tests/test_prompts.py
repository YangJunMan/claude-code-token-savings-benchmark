import unittest
from pathlib import Path


class PromptTests(unittest.TestCase):
    def test_prompt_is_english_and_contains_required_work(self):
        prompt = Path("benchmark/prompts/master.md").read_text()
        for phrase in (
            "Work entirely in English", "idempotency", "worker lease",
            "Kubernetes", "operations runbook", "Do not modify or weaken existing tests",
        ):
            self.assertIn(phrase, prompt)

    def test_brief_overlay_is_exact(self):
        expected = (
            "Be brief. Keep the final response concise without omitting the requested\n"
            "implementation evidence, test results, design decisions, and limitations.\n"
        )
        self.assertEqual(Path("benchmark/prompts/be-brief.txt").read_text(), expected)


if __name__ == "__main__":
    unittest.main()
