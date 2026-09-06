import tempfile
import unittest
from pathlib import Path

from benchmark.reports.generate import generate_report


class GenerateReportTests(unittest.TestCase):
    def test_report_generation_runs_end_to_end(self):
        """The batch's last step must not fail after the runs are already paid for.

        ``run_all`` calls this once every condition is done, so a name error here
        surfaces only after a full batch has been executed - eight hours in.
        An empty run root exercises the whole function body for free.
        """
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory) / "runs"
            run_root.mkdir()
            report_dir = Path(directory) / "report"
            generate_report(run_root, report_dir)
            self.assertTrue((report_dir / "final-report.md").exists())
            self.assertTrue((report_dir / "measurements.csv").exists())
