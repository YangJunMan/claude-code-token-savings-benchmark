import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublishedReportTests(unittest.TestCase):
    def test_report_aggregates_two_headroom_runs(self):
        subprocess.run(
            ["python3", "scripts/render_published_report.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        report = (ROOT / "docs/GENERATED_RESULTS.md").read_text()
        self.assertIn("| BASE mean (n=2) | $1.892 | 2,782,435 |", report)
        self.assertIn("| H-ON mean (n=2) | $1.393 | 1,762,016 |", report)
        self.assertIn("| H-ON | +26.4% | +36.7% | +19.7% |", report)
        self.assertIn("| Context per turn | -41.4% | 10.6% | 8.4% | No | Robust |", report)


if __name__ == "__main__":
    unittest.main()
