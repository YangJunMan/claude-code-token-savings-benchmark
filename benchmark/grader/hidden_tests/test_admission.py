import tempfile
import unittest
from pathlib import Path

from gpu_platform import AdmissionService, JobStore


class AdmissionHiddenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp.name) / "jobs.db")
        self.service = AdmissionService(self.store, gpu_limit=1)

    def tearDown(self):
        self.temp.cleanup()

    def test_critical_claim_prefers_priority_then_fifo(self):
        low = self.service.submit("a", "low", 1)
        high = self.service.submit("b", "high", 9)
        claimed = self.service.claim("gpu-1", now=100, lease_seconds=30)
        self.assertEqual(claimed.id, high.id)
        self.assertNotEqual(claimed.id, low.id)

    def test_critical_gpu_limit_blocks_second_claim(self):
        self.service.submit("a", "one", 1)
        self.service.submit("b", "two", 1)
        self.assertIsNotNone(self.service.claim("gpu-1", now=100))
        self.assertIsNone(self.service.claim("gpu-2", now=101))

    def test_fifo_within_equal_priority(self):
        first = self.service.submit("a", "first", 5)
        self.service.submit("b", "second", 5)
        self.assertEqual(self.service.claim("gpu-1", now=10).id, first.id)

    def test_per_user_limit_rejects_extra_submission(self):
        service = AdmissionService(self.store, gpu_limit=8, per_user_limit=2)
        service.submit("alice", "k1")
        service.submit("alice", "k2")
        with self.assertRaises(Exception):
            service.submit("alice", "k3")

    def test_typed_errors_are_not_bare_builtins(self):
        service = AdmissionService(self.store, gpu_limit=8, per_user_limit=1)
        service.submit("bob", "k1")
        try:
            service.submit("bob", "k2")
        except Exception as error:  # noqa: BLE001 - the type is the assertion
            self.assertNotIn(type(error), (ValueError, RuntimeError, Exception))
        else:
            self.fail("expected the per-user limit to be enforced")
