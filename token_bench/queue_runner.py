"""CLI와 Web의 큐 선점·lock·대기·취소 수명주기."""

import sys
import threading
from pathlib import Path

from token_bench.job_runner import RATE_LIMIT_BACKOFF_SECONDS, process_job
from token_bench.job_store import claim_next_queued
from token_bench.worker import WorkerLockError, worker_lock


class QueueRunner:
    def __init__(self, *, db_path: Path):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._shutdown = threading.Event()
        self._current_run_id: str | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.run, kwargs={"stop_on_error": False}, daemon=True,
        )
        self._thread.start()

    def stop_current(self) -> bool:
        with self._lock:
            if self._current_run_id is None:
                return False
            self._cancel_event.set()
            return True

    def stop(self) -> None:
        self._shutdown.set()
        self._cancel_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def run(
        self, *, once: bool = False, exit_when_empty: bool = False,
        poll_interval_seconds: float = 2.0, stop_on_error: bool = True,
    ) -> int:
        try:
            # worker_lock이 같은 DB의 중복 worker를 막고 orphan도 복구한다.
            with worker_lock(self._db_path):
                while not self._shutdown.is_set():
                    job = claim_next_queued(db_path=self._db_path)
                    if job is None:
                        if once or exit_when_empty:
                            print("대기 중인 작업이 없다. 종료한다.", file=sys.stderr)
                            return 0
                        self._shutdown.wait(poll_interval_seconds)
                        continue
                    with self._lock:
                        self._current_run_id = job.run_id
                        self._cancel_event.clear()
                        if self._shutdown.is_set():
                            self._cancel_event.set()
                    try:
                        status = process_job(job, db_path=self._db_path, cancel_event=self._cancel_event)
                    finally:
                        with self._lock:
                            self._current_run_id = None
                    if once:
                        return 0 if status == "succeeded" else 1
                    if status == "rate-limited" and exit_when_empty:
                        # 무인 실행(CI의 `work --exit-when-empty`)에서 30분을 기다리면
                        # job 시간 한도만 태우고 한도는 그대로다. 작업은 이미 큐에
                        # 되돌렸으니 여기서 끝내고 다음 예약 실행에 맡긴다.
                        print("구독 사용 한도로 보여 이번 실행을 끝낸다.", file=sys.stderr)
                        return 1
                    if status == "rate-limited":
                        print(f"{RATE_LIMIT_BACKOFF_SECONDS}초 쉬었다가 다시 시도한다.", file=sys.stderr)
                        self._shutdown.wait(RATE_LIMIT_BACKOFF_SECONDS)
                    elif stop_on_error and status not in ("succeeded", "failed"):
                        print(
                            f"인프라·승인 문제로 남은 작업 처리를 멈춘다 "
                            f"(run_id={job.run_id}, status={status}).", file=sys.stderr,
                        )
                        return 1
        except WorkerLockError as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        return 0
