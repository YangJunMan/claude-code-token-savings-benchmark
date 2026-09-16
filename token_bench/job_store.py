"""승인된 작업의 상태와 승인 소비를 SQLite로 영속화한다.

작업 상태와 승인 소비의 영속성만 담당한다. 승인 내용 자체의 유효성은
authorization.py가 검증한다. 실제 프로세스 실행은 worker.py가 담당한다.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from token_bench.authorization import ApprovalRecord, EstimatePlan

DEFAULT_DB_PATH = Path(".token-bench/state.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS consumed_approvals (
    digest TEXT PRIMARY KEY,
    consumed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    digest TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    repeat_index INTEGER NOT NULL,
    content_id TEXT NOT NULL,
    workdir TEXT NOT NULL,
    snapshot_path TEXT NOT NULL,
    timeout_seconds INTEGER NOT NULL,
    isolation TEXT NOT NULL DEFAULT 'safe-mode',
    tool_fingerprints_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    enqueued_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_seconds REAL,
    returncode INTEGER,
    stdout_path TEXT,
    stderr_path TEXT,
    command_json TEXT
);
"""


class JobStoreError(ValueError):
    """작업 등록·조회가 실패했을 때 발생한다."""


@dataclass(frozen=True)
class JobRecord:
    sequence: int
    run_id: str
    digest: str
    batch_id: str
    condition_id: str
    repeat_index: int
    content_id: str
    workdir: str
    snapshot_path: str
    timeout_seconds: int
    isolation: str
    status: str
    enqueued_at: str
    tool_fingerprints: tuple[dict, ...] = ()
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    returncode: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    command_json: str | None = None

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "run_id": self.run_id,
            "digest": self.digest,
            "batch_id": self.batch_id,
            "condition_id": self.condition_id,
            "repeat_index": self.repeat_index,
            "content_id": self.content_id,
            "workdir": self.workdir,
            "snapshot_path": self.snapshot_path,
            "timeout_seconds": self.timeout_seconds,
            "isolation": self.isolation,
            "status": self.status,
            "enqueued_at": self.enqueued_at,
            "tool_fingerprints": list(self.tool_fingerprints),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "returncode": self.returncode,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "command_json": self.command_json,
        }


def _drop_legacy_max_turns(conn: sqlite3.Connection) -> None:
    """`max_turns`를 쓰던 시절에 만들어진 상태 저장소를 그대로 이어 쓰게 한다.

    그 컬럼은 NOT NULL이라 남아 있으면 새 INSERT가 실패한다. 기록된 값은
    강제되지 않던 수치이므로 버려도 잃는 정보가 없다.
    """

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs);")}
    if "max_turns" not in columns:
        return
    try:
        conn.execute("ALTER TABLE jobs DROP COLUMN max_turns;")
    except sqlite3.OperationalError as exc:  # SQLite 3.35 미만
        raise JobStoreError(
            "이전 버전이 만든 상태 저장소에 max_turns 컬럼이 남아 있는데 이 SQLite는 "
            "컬럼 삭제를 지원하지 않는다. 진행 중인 작업이 없다면 .token-bench/state.db를 "
            "지우고 다시 등록하라."
        ) from exc
    conn.commit()


def _add_missing_isolation_column(conn: sqlite3.Connection) -> None:
    """격리 모드가 없던 시절의 상태 저장소를 그대로 이어 쓰게 한다."""

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs);")}
    if "isolation" in columns:
        return
    conn.execute(
        "ALTER TABLE jobs ADD COLUMN isolation TEXT NOT NULL DEFAULT 'safe-mode';"
    )
    conn.commit()


def _add_missing_tool_fingerprints_column(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs);")}
    if "tool_fingerprints_json" in columns:
        return
    conn.execute(
        "ALTER TABLE jobs ADD COLUMN tool_fingerprints_json "
        "TEXT NOT NULL DEFAULT '[]';"
    )
    conn.commit()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000;")

    # 같은 새 db 파일에 여러 스레드/프로세스가 동시에 처음 연결하면, WAL 전환과
    # 스키마 생성(DDL)이 서로의 잠금과 부딪혀 `database is locked`를 즉시(수십
    # ms 안에) 낸다 — busy_timeout이 있어도 이 초기화 구간에서는 재시도되지
    # 않는 SQLite 자체의 동작이다. 그래서 이 구간만 우리가 직접 재시도한다.
    for attempt in range(10):
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(_SCHEMA)
            break
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or attempt == 9:
                raise
            time.sleep(0.05 * (attempt + 1))

    _drop_legacy_max_turns(conn)
    _add_missing_isolation_column(conn)
    _add_missing_tool_fingerprints_column(conn)
    return conn


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        sequence=row["sequence"],
        run_id=row["run_id"],
        digest=row["digest"],
        batch_id=row["batch_id"],
        condition_id=row["condition_id"],
        repeat_index=row["repeat_index"],
        content_id=row["content_id"],
        workdir=row["workdir"],
        snapshot_path=row["snapshot_path"],
        timeout_seconds=row["timeout_seconds"],
        isolation=row["isolation"],
        status=row["status"],
        enqueued_at=row["enqueued_at"],
        tool_fingerprints=tuple(json.loads(row["tool_fingerprints_json"])),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_seconds=row["duration_seconds"],
        returncode=row["returncode"],
        stdout_path=row["stdout_path"],
        stderr_path=row["stderr_path"],
        command_json=row["command_json"],
    )


def _jobs_for_digest(conn: sqlite3.Connection, digest: str) -> list[JobRecord]:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE digest = ? ORDER BY sequence", (digest,)
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def enqueue(
    plan: EstimatePlan,
    approval: ApprovalRecord,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[JobRecord]:
    """승인 소비와 작업 등록을 하나의 트랜잭션으로 수행한다.

    같은 승인(digest)의 재제출은 새 작업을 만들지 않고 기존 작업을 그대로
    반환한다. 동시에 제출돼도 `consumed_approvals`의 PRIMARY KEY 제약이
    한쪽만 통과시킨다.
    """

    if approval.digest != plan.digest:
        raise JobStoreError("승인의 digest가 계획의 digest와 다르다.")
    if approval.plan != plan.to_dict():
        raise JobStoreError("승인이 검사한 계획과 지금 제출한 계획이 다르다.")

    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = _jobs_for_digest(conn, plan.digest)
            if existing:
                conn.commit()
                return existing

            now = datetime.now(timezone.utc).isoformat()
            try:
                conn.execute(
                    "INSERT INTO consumed_approvals (digest, consumed_at) VALUES (?, ?)",
                    (plan.digest, now),
                )
            except sqlite3.IntegrityError:
                # 다른 트랜잭션이 먼저 이 승인을 소비했다. 그 결과를 그대로 쓴다.
                existing = _jobs_for_digest(conn, plan.digest)
                conn.commit()
                if not existing:
                    raise JobStoreError(
                        "승인이 이미 소비된 것으로 기록되었지만 작업이 없다. "
                        "상태 저장소가 손상되었을 수 있다."
                    )
                return existing

            for run in plan.runs:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        run_id, digest, batch_id, condition_id, repeat_index,
                        content_id, workdir, snapshot_path,
                        timeout_seconds, isolation, tool_fingerprints_json,
                        status, enqueued_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                    """,
                    (
                        run["run_id"],
                        plan.digest,
                        plan.batch_id,
                        run["condition_id"],
                        run["repeat_index"],
                        run["content_id"],
                        run["workdir"],
                        run["snapshot_path"],
                        plan.timeout_seconds,
                        plan.isolation,
                        json.dumps(run.get("tool_fingerprints", []), sort_keys=True),
                        now,
                    ),
                )
            conn.commit()
            return _jobs_for_digest(conn, plan.digest)
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def list_jobs(*, db_path: Path = DEFAULT_DB_PATH) -> list[JobRecord]:
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY sequence").fetchall()
        return [_row_to_record(row) for row in rows]
    finally:
        conn.close()


def get_job(run_id: str, *, db_path: Path = DEFAULT_DB_PATH) -> JobRecord | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return _row_to_record(row) if row else None
    finally:
        conn.close()


def claim_next_queued(*, db_path: Path = DEFAULT_DB_PATH) -> JobRecord | None:
    """대기 중인 작업 하나를 원자적으로 선점해 'running'으로 바꾼다.

    같은 작업을 두 worker가 동시에 선점할 수 없다: `UPDATE ... WHERE
    status='queued'`가 한쪽에서만 행에 매치된다.
    """

    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT run_id FROM jobs WHERE status = 'queued' ORDER BY sequence LIMIT 1"
            ).fetchone()
            if row is None:
                conn.commit()
                return None

            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ? "
                "WHERE run_id = ? AND status = 'queued'",
                (now, row["run_id"]),
            )
            if cursor.rowcount == 0:
                # 다른 worker가 그 사이에 먼저 선점했다.
                conn.commit()
                return None

            claimed = conn.execute(
                "SELECT * FROM jobs WHERE run_id = ?", (row["run_id"],)
            ).fetchone()
            conn.commit()
            return _row_to_record(claimed)
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def finish_job(
    run_id: str,
    *,
    status: str,
    returncode: int | None,
    finished_at: str,
    duration_seconds: float,
    stdout_path: str,
    stderr_path: str,
    command_json: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> JobRecord:
    """'running' 상태인 작업 하나를 종료 정보와 함께 최종 상태로 옮긴다."""

    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.execute(
                """
                UPDATE jobs SET
                    status = ?, returncode = ?, finished_at = ?,
                    duration_seconds = ?, stdout_path = ?, stderr_path = ?,
                    command_json = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (
                    status,
                    returncode,
                    finished_at,
                    duration_seconds,
                    stdout_path,
                    stderr_path,
                    command_json,
                    run_id,
                ),
            )
            if cursor.rowcount == 0:
                raise JobStoreError(
                    f"'running' 상태가 아닌 작업은 종료 처리할 수 없다: {run_id}"
                )
            row = conn.execute(
                "SELECT * FROM jobs WHERE run_id = ?", (run_id,)
            ).fetchone()
            conn.commit()
            return _row_to_record(row)
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()
