import time
import uuid

from .models import Job, JobState
from .store import JobStore


class AdmissionService:
    """Existing submission behavior; production scheduling work is intentionally incomplete."""

    def __init__(self, store: JobStore, gpu_limit: int = 1, per_user_limit: int = 3):
        self.store = store
        self.gpu_limit = gpu_limit
        self.per_user_limit = per_user_limit

    def submit(self, user_id: str, idempotency_key: str, priority: int = 0) -> Job:
        existing = self.store.find_by_key(user_id, idempotency_key)
        if existing:
            return existing
        job = Job(
            id=str(uuid.uuid4()), user_id=user_id, idempotency_key=idempotency_key,
            priority=priority, state=JobState.QUEUED, created_at=time.time(),
        )
        self.store.insert(job)
        return job

    def claim(self, worker_id: str, now: float, lease_seconds: int = 30):
        raise NotImplementedError("priority admission and leasing are not implemented")

    def heartbeat(self, job_id: str, worker_id: str, now: float, lease_seconds: int = 30):
        raise NotImplementedError("heartbeat is not implemented")

    def complete(self, job_id: str, worker_id: str, succeeded: bool, error: str = ""):
        raise NotImplementedError("completion is not implemented")

    def reap_expired(self, now: float, max_attempts: int = 3):
        raise NotImplementedError("lease reaping is not implemented")
