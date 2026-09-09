from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

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

    def test_quota_retry_parses_an_absolute_clock_reset_message(self):
        """Claude Code reports the reset as a wall-clock time, e.g.

        "You've hit your session limit · resets 3:40am (Asia/Seoul)" - a bare
        "in Xh Ym" parse fails on this and used to fall back to +5h05m,
        overshooting a reset that was only, say, 20 minutes away."""
        seoul = ZoneInfo("Asia/Seoul")
        now = datetime(2026, 9, 9, 3, 21, 55, tzinfo=seoul).timestamp()
        expected = datetime(2026, 9, 9, 3, 40, 0, tzinfo=seoul).timestamp() + 300
        retry = quota_retry_at("You've hit your session limit · resets 3:40am (Asia/Seoul)", now=now)
        self.assertEqual(retry, expected)

    def test_quota_retry_rolls_an_absolute_clock_reset_to_the_next_day_if_already_past(self):
        seoul = ZoneInfo("Asia/Seoul")
        now = datetime(2026, 9, 9, 4, 0, 0, tzinfo=seoul).timestamp()
        expected = datetime(2026, 9, 10, 3, 40, 0, tzinfo=seoul).timestamp() + 300
        retry = quota_retry_at("resets 3:40am (Asia/Seoul)", now=now)
        self.assertEqual(retry, expected)

    def test_quota_retry_falls_back_when_the_timezone_name_is_unrecognised(self):
        retry = quota_retry_at("resets 3:40am (Nowhere/Fake)", now=1000)
        self.assertEqual(retry, 1000 + 5 * 3600 + 300)
