from tests.test_publish import _make_finished_job
from token_bench.job_store import claim_next_queued, get_job, retry_job
from token_bench.queue_runner import QueueRunner


def test_runner_reclaims_orphan_and_stops_on_infrastructure_error(tmp_path):
    db, job = _make_finished_job(tmp_path, status="timeout")
    retry_job(job.run_id, db_path=db)
    claim_next_queued(db_path=db)  # 종료된 worker가 남긴 running 상태
    # 실제 snapshot이 없으므로 모델 호출 전 config-error로 끝난다.
    runner = QueueRunner(db_path=db)
    assert runner.run(exit_when_empty=True) == 1
    assert get_job(job.run_id, db_path=db).status == "config-error"
    assert runner.stop_current() is False


def test_empty_queue_and_stopped_runner_exit_without_waiting(tmp_path):
    runner = QueueRunner(db_path=tmp_path / "state.db")
    assert runner.run(exit_when_empty=True) == 0
    runner.stop()
    assert runner.run() == 0
