import json
from pathlib import Path

import pytest

from token_bench.job_store import JobRecord
from token_bench.results import ResultsError, collect, load, save
from token_bench.worker import ProcessOutcome

SUBSCRIPTION_AUTH = {
    "logged_in": True,
    "auth_method": "claude.ai",
    "api_provider": "firstParty",
    "subscription_type": "pro",
}


def _job(**overrides) -> JobRecord:
    defaults = dict(
        sequence=1,
        run_id="batch1-base__r1",
        digest="digest1",
        batch_id="batch1",
        condition_id="base",
        repeat_index=1,
        content_id="content1",
        workdir="/tmp/batch1/base__r1/workdir",
        snapshot_path="/tmp/batch1/base__r1/snapshot.json",
        timeout_seconds=60,
        isolation="safe-mode",
        status="running",
        enqueued_at="2026-09-15T00:00:00+00:00",
    )
    defaults.update(overrides)
    return JobRecord(**defaults)


def _outcome(stdout_path=None, **overrides) -> ProcessOutcome:
    defaults = dict(
        run_id="batch1-base__r1",
        status="succeeded",
        returncode=0,
        started_at="2026-09-15T00:00:00+00:00",
        finished_at="2026-09-15T00:05:00+00:00",
        duration_seconds=300.0,
        stdout_path=stdout_path or "",
        stderr_path="",
        command=("claude", "--print"),
    )
    defaults.update(overrides)
    return ProcessOutcome(**defaults)


def _write_stdout(tmp_path: Path, lines: list[dict]) -> str:
    path = tmp_path / "stdout.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return str(path)


def test_collect_extracts_model_and_usage_from_stream_json(tmp_path):
    stdout_path = _write_stdout(
        tmp_path,
        [
            {"type": "system", "subtype": "init", "model": "claude-sonnet-5"},
            {"type": "assistant", "message": {}},
            {
                "type": "result",
                "num_turns": 3,
                "total_cost_usd": 0.42,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 5,
                },
            },
        ],
    )
    job = _job()
    outcome = _outcome(stdout_path=stdout_path)

    result = collect(job, outcome, auth=SUBSCRIPTION_AUTH, claude_version="2.1.236 (Claude Code)")

    assert result.model["value"] == "claude-sonnet-5"
    assert result.model["missing_reason"] is None
    assert result.usage["input_tokens"]["value"] == 100
    assert result.usage["input_tokens"]["missing_reason"] is None
    assert result.cost_usd["value"] == 0.42
    assert result.num_turns["value"] == 3
    assert result.auth_method["value"] == "claude.ai"
    assert result.run_id == job.run_id
    assert result.condition_id == "base"
    assert result.content_id == "content1"


def test_collect_preserves_external_tool_fingerprints(tmp_path):
    job = _job(tool_fingerprints=({"name": "rtk", "version_output": "rtk 1.0"},))
    result = collect(
        job,
        _outcome(stdout_path=str(tmp_path / "missing.jsonl")),
        auth=SUBSCRIPTION_AUTH,
        claude_version="2.1.236",
    )
    assert result.tool_fingerprints == (
        {"name": "rtk", "version_output": "rtk 1.0"},
    )


def test_collect_never_fills_missing_usage_with_zero(tmp_path):
    """usage 필드가 없으면 null과 누락 사유를 남기고, 0으로 바꾸지 않는다."""
    stdout_path = _write_stdout(
        tmp_path,
        [{"type": "system", "model": "claude-sonnet-5"}],  # result 이벤트 없음
    )
    job = _job()
    outcome = _outcome(stdout_path=stdout_path, status="timeout", returncode=None)

    result = collect(job, outcome, auth=SUBSCRIPTION_AUTH, claude_version="2.1.236")

    for field in result.usage.values():
        assert field["value"] is None
        assert field["missing_reason"]
    assert result.cost_usd["value"] is None
    assert result.cost_usd["missing_reason"]
    assert result.status == "timeout"


def test_collect_handles_missing_stdout_file(tmp_path):
    job = _job()
    outcome = _outcome(stdout_path=str(tmp_path / "does-not-exist.jsonl"), status="failed", returncode=1)

    result = collect(job, outcome, auth=SUBSCRIPTION_AUTH, claude_version="2.1.236")

    assert result.model["value"] is None
    assert "로그" in result.model["missing_reason"]
    for field in result.usage.values():
        assert field["value"] is None


def test_collect_handles_corrupted_stdout(tmp_path):
    path = tmp_path / "stdout.jsonl"
    path.write_text("not json at all\n{{{", encoding="utf-8")
    job = _job()
    outcome = _outcome(stdout_path=str(path), status="failed", returncode=1)

    result = collect(job, outcome, auth=SUBSCRIPTION_AUTH, claude_version="2.1.236")

    assert result.model["value"] is None
    assert result.usage["input_tokens"]["value"] is None


def test_result_tracks_condition_and_repeat_and_content_id(tmp_path):
    job = _job(condition_id="be-brief", repeat_index=2, content_id="xyz")
    outcome = _outcome(stdout_path=str(tmp_path / "missing.jsonl"))
    result = collect(job, outcome, auth=SUBSCRIPTION_AUTH, claude_version="2.1.236")

    assert result.condition_id == "be-brief"
    assert result.repeat_index == 2
    assert result.content_id == "xyz"


def test_save_and_load_round_trip(tmp_path):
    job = _job()
    outcome = _outcome(stdout_path=str(tmp_path / "missing.jsonl"))
    result = collect(job, outcome, auth=SUBSCRIPTION_AUTH, claude_version="2.1.236")

    path = tmp_path / "result.json"
    save(result, path)
    loaded = load(path)

    assert loaded == result


def test_load_missing_file_raises():
    with pytest.raises(ResultsError, match="찾을 수 없다"):
        load(Path("/nonexistent/result.json"))


def test_load_invalid_json_raises(tmp_path):
    path = tmp_path / "result.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ResultsError, match="JSON"):
        load(path)


def test_failed_run_preserves_raw_output_paths(tmp_path):
    stdout_path = _write_stdout(tmp_path, [{"type": "system", "model": "claude-sonnet-5"}])
    job = _job()
    outcome = _outcome(stdout_path=stdout_path, stderr_path=str(tmp_path / "stderr.log"), status="failed", returncode=2)

    result = collect(job, outcome, auth=SUBSCRIPTION_AUTH, claude_version="2.1.236")

    assert result.status == "failed"
    assert result.returncode == 2
    assert result.stdout_path == stdout_path
    assert result.stderr_path == str(tmp_path / "stderr.log")
