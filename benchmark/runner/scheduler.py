from dataclasses import dataclass
import re
import time


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
    return now + 5 * 3600 + 300
