from dataclasses import dataclass
from enum import Enum
from typing import Optional


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"


@dataclass(frozen=True)
class Job:
    id: str
    user_id: str
    idempotency_key: str
    priority: int
    state: JobState
    created_at: float
    attempts: int = 0
    worker_id: Optional[str] = None
    lease_until: Optional[float] = None
    last_error: Optional[str] = None
