import json

from token_bench.transcript import Transcript


def test_transcript_ignores_invalid_rows_and_sidechains(tmp_path):
    path = tmp_path / "stdout.jsonl"
    path.write_bytes(b'broken\n[]\nnull\n"text"\n' + b'\xff\n' + b'\n'.join(
        json.dumps(row).encode() for row in [
            {"type": "system", "model": "main"},
            {"type": "result", "is_error": True, "result": "session limit"},
            {"type": "result", "isSidechain": True, "total_cost_usd": 999},
        ]
    ))
    transcript = Transcript.load(path)
    assert transcript.system_event["model"] == "main"
    assert transcript.result_event["result"] == "session limit"
    assert transcript.interrupted_reason == "session limit"
    assert transcript.has_output
    assert Transcript.load(transcript) is transcript


def test_missing_and_malformed_logs_preserve_missing_reasons(tmp_path):
    assert "없거나 비어" in Transcript.load(None).parse_error
    assert Transcript.load(None).has_output is False
    path = tmp_path / "stdout.jsonl"
    path.write_text("not json\n[]\n", encoding="utf-8")
    transcript = Transcript.load(path)
    assert transcript.has_output
    assert transcript.result_event == {}
    assert "JSON Lines" in transcript.parse_error


def test_weekly_and_other_hit_limit_messages_count_as_usage_limits():
    from token_bench.transcript import is_usage_limit_error

    assert is_usage_limit_error("You've hit your weekly limit · resets 7pm (UTC)")
    assert is_usage_limit_error("You've hit your Opus limit · resets 3am")
    assert not is_usage_limit_error("tool call failed: file not found")
