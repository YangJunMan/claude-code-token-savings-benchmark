import tempfile
import unittest
from pathlib import Path

from gpu_platform import AdmissionService, JobStore
from gpu_platform.metrics import Metrics


class MetricsHiddenTests(unittest.TestCase):
    def test_snapshot_reports_queue_and_running(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.db")
            service = AdmissionService(store)
            service.submit("a", "x", 4)
            snapshot = Metrics().snapshot(store)
            rendered = snapshot if isinstance(snapshot, str) else str(snapshot)
            self.assertIn("queue", rendered.lower())
