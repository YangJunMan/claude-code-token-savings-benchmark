import sqlite3
from pathlib import Path
from typing import Optional

from .models import Job, JobState


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  priority INTEGER NOT NULL,
  state TEXT NOT NULL,
  created_at REAL NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  worker_id TEXT,
  lease_until REAL,
  last_error TEXT
);
"""


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def insert(self, job: Job) -> None:
        self.connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job.id, job.user_id, job.idempotency_key, job.priority, job.state.value,
             job.created_at, job.attempts, job.worker_id, job.lease_until, job.last_error),
        )
        self.connection.commit()

    def get(self, job_id: str) -> Optional[Job]:
        row = self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def find_by_key(self, user_id: str, key: str) -> Optional[Job]:
        row = self.connection.execute(
            "SELECT * FROM jobs WHERE user_id = ? AND idempotency_key = ? LIMIT 1",
            (user_id, key),
        ).fetchone()
        return self._job(row) if row else None

    @staticmethod
    def _job(row) -> Job:
        return Job(
            id=row["id"], user_id=row["user_id"], idempotency_key=row["idempotency_key"],
            priority=row["priority"], state=JobState(row["state"]), created_at=row["created_at"],
            attempts=row["attempts"], worker_id=row["worker_id"], lease_until=row["lease_until"],
            last_error=row["last_error"],
        )
