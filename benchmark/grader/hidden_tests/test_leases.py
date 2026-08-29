import tempfile
import unittest
from pathlib import Path

from gpu_platform import AdmissionService, JobStore


class LeaseHiddenTests(unittest.TestCase):
    def test_foreign_worker_cannot_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AdmissionService(JobStore(Path(directory) / "jobs.db"))
            job = service.submit("a", "x")
            service.claim("gpu-1", now=10, lease_seconds=5)
            with self.assertRaises((PermissionError, ValueError)):
                service.heartbeat(job.id, "gpu-2", now=11)

    def test_expiry_requeues_then_dead_letters(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AdmissionService(JobStore(Path(directory) / "jobs.db"))
            job = service.submit("a", "x")
            for attempt in range(3):
                service.claim(f"gpu-{attempt}", now=attempt * 10, lease_seconds=1)
                service.reap_expired(now=attempt * 10 + 2, max_attempts=3)
            self.assertEqual(service.store.get(job.id).state.value, "dead")
