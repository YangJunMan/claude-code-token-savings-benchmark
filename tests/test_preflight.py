import shutil
import sys
from pathlib import Path

import pytest

from token_bench import claude_code, preflight
from token_bench.conditions import Injection, RunSpec

HELP_WITH_SAFE_MODE = "... --safe-mode ... --settings <file-or-json> ..."


def _run(condition_id="base", requires_tools=(), injections=()):
    return RunSpec(
        condition_id=condition_id,
        repeat_index=1,
        repeat_total=1,
        requires_tools=tuple(requires_tools),
        injections=tuple(injections),
    )


def _patch_healthy(monkeypatch):
    monkeypatch.setattr(preflight.claude_code, "is_installed", lambda: True)
    monkeypatch.setattr(preflight.claude_code, "get_version", lambda: "2.1.236 (Claude Code)")
    monkeypatch.setattr(
        preflight.claude_code,
        "get_auth_status",
        lambda: claude_code.AuthStatus(
            logged_in=True,
            auth_method="claude.ai",
            api_provider="firstParty",
            subscription_type="pro",
        ),
    )
    monkeypatch.setattr(preflight.claude_code, "get_help_text", lambda: HELP_WITH_SAFE_MODE)


def test_healthy_environment_passes(monkeypatch):
    _patch_healthy(monkeypatch)
    report = preflight.check(_run())
    assert report.ok is True
    assert report.problems == ()
    assert report.auth["subscription_type"] == "pro"


def test_claude_not_installed_is_reported(monkeypatch):
    monkeypatch.setattr(preflight.claude_code, "is_installed", lambda: False)
    report = preflight.check(_run())
    assert report.ok is False
    assert any("claude CLI" in p for p in report.problems)


def test_not_logged_in_is_rejected(monkeypatch):
    _patch_healthy(monkeypatch)
    monkeypatch.setattr(
        preflight.claude_code,
        "get_auth_status",
        lambda: claude_code.AuthStatus(
            logged_in=False, auth_method=None, api_provider=None, subscription_type=None
        ),
    )
    report = preflight.check(_run())
    assert report.ok is False
    assert any("loggedIn" in p for p in report.problems)


def test_api_key_auth_is_rejected_for_subscription_path(monkeypatch):
    _patch_healthy(monkeypatch)
    monkeypatch.setattr(
        preflight.claude_code,
        "get_auth_status",
        lambda: claude_code.AuthStatus(
            logged_in=True, auth_method="apiKey", api_provider="direct", subscription_type=None
        ),
    )
    report = preflight.check(_run())
    assert report.ok is False
    assert any("API key" in p for p in report.problems)


def test_missing_safe_mode_flag_is_rejected(monkeypatch):
    _patch_healthy(monkeypatch)
    monkeypatch.setattr(preflight.claude_code, "get_help_text", lambda: "... --print ...")
    report = preflight.check(_run())
    assert report.ok is False
    assert any("--safe-mode" in p for p in report.problems)


def test_missing_required_tool_is_reported_by_name(monkeypatch):
    _patch_healthy(monkeypatch)
    report = preflight.check(_run(requires_tools=["definitely-not-a-real-tool"]))
    assert report.ok is False
    assert any("definitely-not-a-real-tool" in p for p in report.problems)


def test_installed_tool_path_and_version_are_fingerprinted(monkeypatch):
    _patch_healthy(monkeypatch)
    binary = Path(sys.executable).name
    run = RunSpec(
        condition_id="python-tool",
        repeat_index=1,
        repeat_total=1,
        requires_tools=(binary,),
        injections=(),
        tool_probes=((binary, ("--version",)),),
        repository_url="https://github.com/python/cpython",
    )
    report = preflight.check(run)
    assert report.ok is True
    assert report.tool_fingerprints[0]["name"] == binary
    assert Path(report.tool_fingerprints[0]["path"]).is_absolute()
    assert "Python" in report.tool_fingerprints[0]["version_output"]


def test_missing_referenced_prompt_overlay_file_is_rejected(tmp_path, monkeypatch):
    _patch_healthy(monkeypatch)
    run = _run(
        injections=[Injection(type="prompt_overlay", path="benchmark/prompts/missing.txt")]
    )
    report = preflight.check(run, repo_root=tmp_path)
    assert report.ok is False
    assert any("missing.txt" in p for p in report.problems)


def test_installation_probe_calls_run_it_first(monkeypatch):
    """설치 확인이 실패하면 다른 조회를 시도하지 않는다."""
    calls = []
    monkeypatch.setattr(preflight.claude_code, "is_installed", lambda: False)

    def _boom():
        calls.append("called")
        raise AssertionError("설치 확인 실패 후에는 다른 조회를 호출하지 않아야 한다.")

    monkeypatch.setattr(preflight.claude_code, "get_version", _boom)
    monkeypatch.setattr(preflight.claude_code, "get_auth_status", _boom)
    monkeypatch.setattr(preflight.claude_code, "get_help_text", _boom)

    preflight.check(_run())
    assert calls == []


@pytest.mark.skipif(
    shutil.which("claude") is None, reason="claude CLI가 설치되어 있지 않다."
)
def test_real_installed_claude_code_preflight_is_non_billing():
    """실제 설치 환경에서 preflight가 모델 호출 없이 동작하는지 확인한다."""
    from token_bench.conditions import inspect

    repo_root = Path(__file__).resolve().parents[1]
    runs = inspect(repo_root / "benchmark" / "conditions.json")
    for run in runs:
        report = preflight.check(run, repo_root=repo_root)
        assert report.claude_version
        assert report.auth is not None
        assert "auth_method" in report.auth
