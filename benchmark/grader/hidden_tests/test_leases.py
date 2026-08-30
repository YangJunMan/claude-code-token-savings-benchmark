import tempfile
import unittest
from pathlib import Path

from gpu_platform import AdmissionService, JobStore


class LeaseHiddenTests(unittest.TestCase):
    def test_critical_foreign_worker_cannot_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AdmissionService(JobStore(Path(directory) / "jobs.db"))
            job = service.submit("a", "x")
            service.claim("gpu-1", now=10, lease_seconds=5)
            with self.assertRaises(Exception):
                service.heartbeat(job.id, "gpu-2", now=11)
            self.assertEqual(service.store.get(job.id).worker_id, "gpu-1")

    def test_critical_expiry_requeues_then_dead_letters(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AdmissionService(JobStore(Path(directory) / "jobs.db"))
            job = service.submit("a", "x")
            for attempt in range(3):
                service.claim(f"gpu-{attempt}", now=attempt * 10, lease_seconds=1)
                service.reap_expired(now=attempt * 10 + 2, max_attempts=3)
            self.assertEqual(service.store.get(job.id).state.value, "dead")

    def test_heartbeat_extends_the_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AdmissionService(JobStore(Path(directory) / "jobs.db"))
            job = service.submit("a", "x")
            service.claim("gpu-1", now=10, lease_seconds=5)
            before = service.store.get(job.id).lease_until
            service.heartbeat(job.id, "gpu-1", now=12, lease_seconds=30)
            self.assertGreater(service.store.get(job.id).lease_until, before)

    def test_completion_is_terminal_and_owner_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AdmissionService(JobStore(Path(directory) / "jobs.db"))
            job = service.submit("a", "x")
            service.claim("gpu-1", now=10, lease_seconds=5)
            service.complete(job.id, "gpu-1", succeeded=True)
            self.assertEqual(service.store.get(job.id).state.value, "succeeded")
            with self.assertRaises(Exception):
                service.complete(job.id, "gpu-1", succeeded=True)

    def test_cancel_queued_and_reject_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AdmissionService(JobStore(Path(directory) / "jobs.db"))
            job = service.submit("a", "x")
            service.cancel(job.id)
            self.assertNotEqual(service.store.get(job.id).state.value, "queued")
            with self.assertRaises(Exception):
                service.cancel(job.id)
