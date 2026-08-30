import subprocess
import sys
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

    def test_snapshot_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.db")
            AdmissionService(store).submit("a", "x", 4)
            metrics = Metrics()
            self.assertEqual(str(metrics.snapshot(store)), str(metrics.snapshot(store)))


class MigrationHiddenTests(unittest.TestCase):
    def test_forward_migration_preserves_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            job = AdmissionService(JobStore(path)).submit("a", "x", 2)
            reopened = JobStore(path)
            self.assertIsNotNone(reopened.get(job.id))
            self.assertEqual(reopened.get(job.id).user_id, "a")


class CliHiddenTests(unittest.TestCase):
    def test_cli_metrics_exits_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "jobs.db"
            JobStore(database)
            # The prompt specifies `cli --database PATH <subcommand>`, so the flag
            # is global and comes before the subcommand.
            result = subprocess.run(
                [sys.executable, "-m", "gpu_platform.cli", "--database", str(database), "metrics"],
                text=True, capture_output=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip())
