import unittest
from benchmark.runner.scheduler import Scheduler, classify_failure, quota_retry_at


class SchedulerTests(unittest.TestCase):
    def test_next_run_waits_4200_seconds_after_last_request(self):
        self.assertEqual(Scheduler(4200).next_eligible_at(9000), 13200)

    def test_quota_interruption_invalidates_attempt(self):
        failure = classify_failure("You've hit your session limit · resets 3:45pm")
        self.assertEqual(failure.kind, "quota")
        self.assertTrue(failure.invalidate_attempt)

    def test_other_failure_is_not_quota(self):
        self.assertEqual(classify_failure("process exited 2").kind, "execution")

    def test_quota_retry_waits_five_hours_plus_safety_margin_when_reset_is_unknown(self):
        self.assertEqual(quota_retry_at("session limit", now=1000), 19300)

    def test_quota_retry_parses_relative_reset_message(self):
        self.assertEqual(quota_retry_at("resets in 2h 10m", now=1000), 1000 + 2 * 3600 + 10 * 60 + 300)
