from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Failure:
    kind: str
    invalidate_attempt: bool


def classify_failure(text):
    lowered = text.lower()
    quota_markers = ("session limit", "weekly limit", "5-hour limit", "resets")
    if any(marker in lowered for marker in quota_markers):
        return Failure("quota", True)
    return Failure("execution", False)


class Scheduler:
    def __init__(self, washout_seconds):
        self.washout_seconds = washout_seconds

    def next_eligible_at(self, last_request_epoch):
        return last_request_epoch + self.washout_seconds


def _parse_clock_reset(message, now):
    """Claude Code reports the reset as a wall-clock time, not a countdown:

    "You've hit your session limit · resets 3:40am (Asia/Seoul)"

    Read literally as "5 hours from now" this overshoots by however long until
    that clock time next occurs, which can itself be hours - a retry that was
    already eligible gets pushed needlessly late.
    """
    match = re.search(r"resets?\s+(\d{1,2}):(\d{2})\s*(am|pm)?(?:\s*\(([^)]+)\))?",
                      message, re.IGNORECASE)
    if not match:
        return None
    hour, minute, meridiem, tz_name = match.groups()
    hour = int(hour)
    if meridiem:
        meridiem = meridiem.lower()
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    try:
        tzinfo = ZoneInfo(tz_name) if tz_name else timezone.utc
    except ZoneInfoNotFoundError:
        # An unrecognised zone name is a sign the match was spurious - the flat
        # fallback in quota_retry_at is safer than guessing UTC.
        return None
    current = datetime.fromtimestamp(now, tz=tzinfo)
    candidate = current.replace(hour=hour, minute=int(minute), second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate.timestamp()


def quota_retry_at(message, now=None):
    """Return a conservative retry epoch, including the five-minute margin."""
    now = time.time() if now is None else now
    match = re.search(
        r"resets?\s+in\s+(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?",
        message.lower(),
    )
    if match and (match.group(1) or match.group(2)):
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        return now + hours * 3600 + minutes * 60 + 300
    clock_reset = _parse_clock_reset(message, now)
    if clock_reset is not None:
        return clock_reset + 300
    return now + 5 * 3600 + 300
