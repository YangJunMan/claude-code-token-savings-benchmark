import csv

import pytest

from tests.test_publish import _make_finished_job
from token_bench.ledger import sync_published


def test_ledger_exports_both_tables_once_with_same_attempt_key(tmp_path):
    db, job = _make_finished_job(tmp_path)
    data = tmp_path / "data"
    first = sync_published(db_path=db, data_dir=data, diagnose=False)
    assert first["runs"] == 1
    assert first["published_count"] == 1
    assert sync_published(db_path=db, data_dir=data, diagnose=False)["runs"] == 0
    for name in ["run-summary.csv", "token-bench-results.csv"]:
        rows = list(csv.DictReader((data / name).open()))
        assert len(rows) == 1
        assert rows[0]["run_id"] == job.run_id


def test_ledger_staging_error_preserves_existing_outputs(tmp_path, monkeypatch):
    db, _ = _make_finished_job(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    marker = data / "run-summary.csv"
    marker.write_text("run_id,terminal_reason\nold,succeeded\n")
    before = marker.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr("token_bench.ledger.rebuild_comparison", fail)
    with pytest.raises(OSError, match="disk full"):
        sync_published(db_path=db, data_dir=data, diagnose=False)
    assert marker.read_bytes() == before
    assert not (data / "token-bench-results.csv").exists()


def test_failed_file_swap_restores_pre_transaction_bytes(tmp_path, monkeypatch):
    from token_bench import ledger
    db, _ = _make_finished_job(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    previous = data / "run-diagnostics.json"
    previous.write_text('{"historical":{"summary":"preserve","events":[]}}')
    before = previous.read_bytes()
    real_replace = ledger.os.replace
    def fail(source, target):
        if str(target).endswith("run-summary.csv"):
            raise OSError("replace failed")
        return real_replace(source, target)
    monkeypatch.setattr(ledger.os, "replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        sync_published(db_path=db, data_dir=data, diagnose=False)
    assert previous.read_bytes() == before
    assert not (data / "token-bench-results.csv").exists()
    assert not (data / ".publish-rollback.json").exists()


def test_partial_export_reuses_existing_attempt_key(tmp_path):
    db, job = _make_finished_job(tmp_path)
    data = tmp_path / "data"
    sync_published(db_path=db, data_dir=data, diagnose=False)
    (data / "run-summary.csv").unlink()
    (data / "activity-log.csv").unlink()
    result = sync_published(db_path=db, data_dir=data, diagnose=False)
    assert result["runs"] == 1
    assert result["published_count"] == 0
    row = next(csv.DictReader((data / "run-summary.csv").open()))
    assert row["run_id"] == job.run_id


def test_interrupted_publication_is_restored_on_next_sync(tmp_path):
    import base64
    import json
    from token_bench import ledger
    data = tmp_path / "data"
    data.mkdir()
    before = {name: None for name in ledger._OUTPUT_NAMES}
    before["run-diagnostics.json"] = base64.b64encode(b'{"old":{"events":[]}}').decode()
    (data / ".publish-rollback.json").write_text(json.dumps(before))
    (data / "token-bench-results.csv").write_text("incomplete publication")
    result = sync_published(db_path=tmp_path / "state.db", data_dir=data, diagnose=False)
    assert result["runs"] == 0
    assert (data / "run-diagnostics.json").read_bytes() == b'{"old":{"events":[]}}'
    assert not (data / "token-bench-results.csv").exists()
    assert not (data / ".publish-rollback.json").exists()
