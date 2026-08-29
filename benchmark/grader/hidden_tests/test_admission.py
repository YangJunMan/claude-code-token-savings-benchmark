import tempfile
import unittest
from pathlib import Path

from gpu_platform import AdmissionService, JobStore


class AdmissionHiddenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = AdmissionService(JobStore(Path(self.temp.name) / "jobs.db"), gpu_limit=1)

    def tearDown(self):
        self.temp.cleanup()

    def test_claim_prefers_priority_then_fifo(self):
        low = self.service.submit("a", "low", 1)
        high = self.service.submit("b", "high", 9)
        claimed = self.service.claim("gpu-1", now=100, lease_seconds=30)
        self.assertEqual(claimed.id, high.id)
        self.assertNotEqual(claimed.id, low.id)

    def test_gpu_limit_blocks_second_claim(self):
        self.service.submit("a", "one", 1)
        self.service.submit("b", "two", 1)
        self.assertIsNotNone(self.service.claim("gpu-1", now=100))
        self.assertIsNone(self.service.claim("gpu-2", now=101))
