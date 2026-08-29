from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from pathlib import Path

from gpu_platform import AdmissionService, JobStore


class ConcurrencyHiddenTests(unittest.TestCase):
    def test_concurrent_idempotency_returns_one_job(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            def submit(_):
                return AdmissionService(JobStore(path)).submit("alice", "same", 3).id
            with ThreadPoolExecutor(max_workers=8) as pool:
                ids = list(pool.map(submit, range(16)))
            self.assertEqual(len(set(ids)), 1)
