import tempfile
import unittest
from pathlib import Path

from gpu_platform import AdmissionService, JobStore


class ExistingBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp.name) / "jobs.db")
        self.service = AdmissionService(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_submit_and_get_job(self):
        job = self.service.submit("alice", "upload-001", priority=7)
        self.assertEqual(self.store.get(job.id), job)

    def test_sequential_duplicate_returns_existing_job(self):
        first = self.service.submit("alice", "upload-001")
        second = self.service.submit("alice", "upload-001")
        self.assertEqual(first.id, second.id)

    def test_same_key_is_scoped_to_user(self):
        first = self.service.submit("alice", "upload-001")
        second = self.service.submit("bob", "upload-001")
        self.assertNotEqual(first.id, second.id)


if __name__ == "__main__":
    unittest.main()
