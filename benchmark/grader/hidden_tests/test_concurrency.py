from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from pathlib import Path

from gpu_platform import AdmissionService, JobStore


class ConcurrencyHiddenTests(unittest.TestCase):
    def test_critical_concurrent_idempotency_returns_one_job(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            def submit(_):
                return AdmissionService(JobStore(path)).submit("alice", "same", 3).id
            with ThreadPoolExecutor(max_workers=8) as pool:
                ids = list(pool.map(submit, range(16)))
            self.assertEqual(len(set(ids)), 1)

    def test_critical_concurrent_claims_respect_gpu_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            service = AdmissionService(JobStore(path), gpu_limit=2)
            for index in range(10):
                service.submit(f"user-{index}", f"key-{index}", 1)
            def claim(worker):
                return AdmissionService(JobStore(path), gpu_limit=2).claim(
                    f"gpu-{worker}", now=100 + worker, lease_seconds=60)
            with ThreadPoolExecutor(max_workers=8) as pool:
                claimed = [job for job in pool.map(claim, range(8)) if job is not None]
            self.assertLessEqual(len({job.id for job in claimed}), 2)
