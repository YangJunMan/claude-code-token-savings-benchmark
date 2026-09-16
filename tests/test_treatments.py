"""hook·plugin·proxy 처치가 실제 실행 인자와 환경까지 도달하는지 검사한다.

`--safe-mode`는 hook·plugin을 통째로 끄기 때문에, 그 둘이 처치인 조건은 다른
격리 모드로 돌아야 한다. 여기서는 그 규칙과 주입이 명령/환경에 반영되는지를
모델 호출 없이 검사한다.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from token_bench.conditions import (
    Injection,
    RunSpec,
    inspect,
    needs_customizations,
)
from token_bench.worker import (
    ISOLATION_MODES,
    build_command,
    build_env,
    proxy_process,
    resolve_plugin_dir,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(injections=()) -> RunSpec:
    return RunSpec(
        condition_id="x",
        repeat_index=1,
        repeat_total=1,
        requires_tools=(),
        injections=tuple(injections),
    )


def test_declared_conditions_cover_every_published_optimizer():
    """공개 측정값에 있는 다섯 조건이 모두 선언되어 있어야 한다."""

    runs = inspect(REPO_ROOT / "benchmark" / "conditions.json")
    assert {
        "base",
        "be-brief",
        "headroom",
        "caveman-full",
        "rtk",
    } <= {r.condition_id for r in runs}


def test_hook_and_plugin_conditions_need_a_different_isolation():
    assert needs_customizations((Injection(type="config_ref", path="a.json"),))
    assert needs_customizations((Injection(type="plugin_dir", path="/tmp/p"),))
    # 프롬프트만 바꾸는 처치는 safe-mode에서도 그대로 적용된다.
    assert not needs_customizations((Injection(type="prompt_overlay", path="a.txt"),))
    assert not needs_customizations((Injection(type="proxy", binary="p", args=()),))


def test_safe_mode_is_the_default_isolation():
    command = build_command("프롬프트", ())
    assert "--safe-mode" in command


def test_customization_isolation_swaps_safe_mode_for_project_settings():
    command = build_command("프롬프트", (), isolation="project-settings")
    assert "--safe-mode" not in command
    assert command[command.index("--setting-sources") + 1] == "project"


def test_unknown_isolation_is_rejected():
    with pytest.raises(Exception):
        build_command("프롬프트", (), isolation="none")


def test_hook_settings_reach_the_command():
    command = build_command(
        "프롬프트",
        (Injection(type="config_ref", path="benchmark/settings/rtk.json"),),
        isolation="project-settings",
        repo_root=REPO_ROOT,
    )
    assert command[command.index("--settings") + 1].endswith("benchmark/settings/rtk.json")


def test_plugin_dir_reaches_the_command_and_resolves_globs(tmp_path):
    plugin = tmp_path / "cache" / "abc123" / "caveman"
    plugin.mkdir(parents=True)
    command = build_command(
        "프롬프트",
        (Injection(type="plugin_dir", path=str(tmp_path / "cache" / "*" / "caveman")),),
        isolation="project-settings",
    )
    assert command[command.index("--plugin-dir") + 1] == str(plugin)


def test_missing_plugin_dir_is_reported(tmp_path):
    with pytest.raises(Exception, match="플러그인 디렉터리"):
        resolve_plugin_dir(str(tmp_path / "없음"), repo_root=tmp_path)


def test_rtk_settings_file_declares_a_pretooluse_hook():
    settings = json.loads(
        (REPO_ROOT / "benchmark" / "settings" / "rtk.json").read_text(encoding="utf-8")
    )
    hooks = settings["hooks"]["PreToolUse"]
    assert hooks[0]["matcher"] == "Bash"
    assert hooks[0]["hooks"][0]["command"].startswith("rtk ")


def test_env_injection_reaches_the_child_environment():
    env = build_env(
        (Injection(type="env", name="ENABLE_TOOL_SEARCH", value="true"),),
        base_env={"PATH": "/usr/bin"},
    )
    assert env["ENABLE_TOOL_SEARCH"] == "true"
    assert env["PATH"] == "/usr/bin"


def _fake_proxy(tmp_path: Path) -> Path:
    """`--port`로 받은 포트에서 /readyz에 200을 주는 최소 HTTP 서버."""

    script = tmp_path / "fakeproxy"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
        "    def log_message(self, *a): pass\n"
        "HTTPServer(('127.0.0.1', port), H).serve_forever()\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_proxy_is_started_and_its_base_url_is_owned_by_the_runner(tmp_path, monkeypatch):
    script = _fake_proxy(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    injection = Injection(
        type="proxy",
        binary=script.name,
        args=("--port", "{port}"),
        ready_path="/readyz",
    )

    with proxy_process(injection, log_dir=tmp_path / "logs", env=dict(os.environ)) as url:
        assert url.startswith("http://127.0.0.1:")
        probe = subprocess.run(
            [sys.executable, "-c", f"import urllib.request;urllib.request.urlopen('{url}/readyz')"],
            capture_output=True,
        )
        assert probe.returncode == 0, probe.stderr

    # 컨텍스트를 벗어나면 proxy는 살아 있으면 안 된다.
    still_up = subprocess.run(
        [sys.executable, "-c", f"import urllib.request;urllib.request.urlopen('{url}/readyz')"],
        capture_output=True,
    )
    assert still_up.returncode != 0


def test_missing_proxy_binary_is_reported(tmp_path):
    injection = Injection(type="proxy", binary="존재하지않는프록시", args=())
    with pytest.raises(Exception, match="proxy 실행 파일"):
        with proxy_process(injection, log_dir=tmp_path, env=dict(os.environ)):
            pass


def test_isolation_modes_are_the_only_two():
    assert set(ISOLATION_MODES) == {"safe-mode", "project-settings"}


def test_missing_tool_is_reported_with_its_install_hint(tmp_path):
    """도구가 없는 조건은 이유와 설치 방법을 함께 돌려줘야 한다."""

    from token_bench.preflight import split_by_availability

    runs = inspect(REPO_ROOT / "benchmark" / "conditions.json")
    ready, blocked = split_by_availability(runs)

    assert {r.condition_id for r in ready} | {r.condition_id for r, _ in blocked} == {
        "base",
        "be-brief",
        "headroom",
        "caveman-full",
        "rtk",
    }
    # 어떤 조건이 막히든, 막혔다면 이유와 설치 안내가 둘 다 있어야 한다.
    for run, reasons in blocked:
        assert reasons
        assert run.repository_url, f"{run.condition_id}에 repository URL이 없다."


def test_declarations_that_need_tools_all_carry_an_install_hint():
    runs = inspect(REPO_ROOT / "benchmark" / "conditions.json")
    for run in runs:
        needs_tool = bool(run.requires_tools) or any(
            i.type in ("plugin_dir", "proxy") for i in run.injections
        )
        if needs_tool:
            assert run.repository_url, f"{run.condition_id}: 공식 repository URL이 없다."


def test_base_and_be_brief_need_nothing_installed():
    """clone 직후 아무것도 깔지 않고 돌릴 수 있는 조건이 있어야 한다."""

    from token_bench.preflight import unavailable_reasons

    runs = {r.condition_id: r for r in inspect(REPO_ROOT / "benchmark" / "conditions.json")}
    assert unavailable_reasons(runs["base"]) == []
    assert unavailable_reasons(runs["be-brief"]) == []


def test_skip_unavailable_filters_and_explains(tmp_path):
    """--skip-unavailable은 못 돌리는 조건을 빼고 이유를 stderr로 알린다."""

    result = subprocess.run(
        [sys.executable, "-m", "token_bench", "inspect", "--skip-unavailable"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    selected = {r["condition_id"] for r in json.loads(result.stdout)}
    assert {"base", "be-brief"} <= selected

    from token_bench.preflight import split_by_availability

    _, blocked = split_by_availability(inspect(REPO_ROOT / "benchmark" / "conditions.json"))
    for run, _ in blocked:
        assert run.condition_id not in selected
        assert f"건너뜀: {run.condition_id}" in result.stderr


def test_settings_path_is_absolute_because_claude_runs_in_the_workdir(tmp_path):
    """`--settings`는 절대경로여야 한다.

    claude는 fixture 복사본(workdir)에서 실행되므로 저장소 기준 상대경로를
    그대로 넘기면 "Settings file not found"로 즉시 실패한다(실측).
    """

    command = build_command(
        "프롬프트",
        (Injection(type="config_ref", path="benchmark/settings/rtk.json"),),
        isolation="project-settings",
        repo_root=REPO_ROOT,
    )
    settings_arg = Path(command[command.index("--settings") + 1])
    assert settings_arg.is_absolute()
    assert settings_arg == (REPO_ROOT / "benchmark" / "settings" / "rtk.json").resolve()
    assert settings_arg.is_file()


def test_interrupted_run_is_not_treated_as_a_measurement(tmp_path):
    """구독 한도 등으로 중간에 끊긴 실행은 측정값이 아니다(실측 사례).

    2026-09-15 rtk 실행이 19턴에서 세션 한도로 끊겼는데, 종료 코드만 보면
    `failed`(= 과제 테스트 실패)와 구분되지 않아 공개 CSV에 올라갈 뻔했다.
    """

    from token_bench.results import interrupted_reason

    stdout = tmp_path / "stdout.jsonl"
    stdout.write_text(
        json.dumps({"type": "system", "subtype": "init", "model": "claude-sonnet-5"}) + "\n"
        + json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "You've hit your session limit · resets 2:50am",
                "num_turns": 19,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert "session limit" in interrupted_reason(str(stdout))

    finished = tmp_path / "ok.jsonl"
    finished.write_text(
        json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 46})
        + "\n",
        encoding="utf-8",
    )
    assert interrupted_reason(str(finished)) is None
    assert interrupted_reason(None) is None
