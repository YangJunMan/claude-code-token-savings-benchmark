import json
import os
import shutil
import stat
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from token_bench.webapi import _conditions_summary, serve

REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_runnable_conditions(dst: Path) -> None:
    """sandbox에는 이 환경에서 실제로 preflight를 통과하는 조건만 넣는다.

    실제 선언에는 외부 도구가 필요한 조건(headroom 등)이 있어서, 그대로
    복사하면 도구가 없는 기계에서 테스트가 환경 때문에 실패한다.
    """

    doc = json.loads((REPO_ROOT / "benchmark" / "conditions.json").read_text(encoding="utf-8"))
    doc["conditions"] = [c for c in doc["conditions"] if c["id"] in ("base", "be-brief")]
    dst.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_fake_claude(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "claude"
    script.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  --version) echo '2.1.236 (Claude Code)'; exit 0 ;;\n"
        "  auth) echo '{\"loggedIn\": true, \"authMethod\": \"claude.ai\", "
        "\"apiProvider\": \"firstParty\", \"subscriptionType\": \"pro\"}'; exit 0 ;;\n"
        "  --help) echo '--safe-mode --settings <file-or-json> --permission-mode <mode>'; exit 0 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """조건·fixture·prompts를 갖춘 임시 저장소로 cwd를 옮기고 fake claude를 PATH에 둔다."""

    shutil.copytree(REPO_ROOT / "benchmark" / "fixture", tmp_path / "benchmark" / "fixture")
    shutil.copytree(REPO_ROOT / "benchmark" / "prompts", tmp_path / "benchmark" / "prompts")
    _copy_runnable_conditions(tmp_path / "benchmark" / "conditions.json")

    fake_bin = tmp_path / "fakebin"
    _write_fake_claude(fake_bin)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def server():
    srv = serve(host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def _url(server, path: str) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}{path}"


def _get_json(server, path: str):
    try:
        with urllib.request.urlopen(_url(server, path), timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post_json(server, path: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _url(server, path), data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_responses_include_cors_headers_for_cross_origin_web_page(sandbox, server):
    """run.html은 다른 포트(정적 파일 서버)에서 열리므로 CORS 헤더가 실제로 필요하다."""
    req = urllib.request.Request(
        _url(server, "/api/conditions"), headers={"Origin": "http://127.0.0.1:8765"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:8765"


def test_options_preflight_is_allowed(sandbox, server):
    req = urllib.request.Request(_url(server, "/api/estimate"), method="OPTIONS")
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 204
        assert resp.headers.get("Access-Control-Allow-Methods")


def test_get_conditions_matches_declaration(sandbox, server):
    status, body = _get_json(server, "/api/conditions")
    assert status == 200
    ids = [c["id"] for c in body["conditions"]]
    assert ids == ["base", "be-brief"]


def test_conditions_api_exposes_official_repository_links():
    conditions = _conditions_summary(REPO_ROOT / "benchmark" / "conditions.json")
    by_id = {condition["id"]: condition for condition in conditions}
    assert by_id["headroom"]["repository_url"] == "https://github.com/chopratejas/headroom"
    assert by_id["caveman-full"]["repository_url"] == "https://github.com/JuliusBrussee/caveman"
    assert by_id["rtk"]["repository_url"] == "https://github.com/rtk-ai/rtk"


def test_unknown_path_returns_404(sandbox, server):
    status, body = _get_json(server, "/api/nope")
    assert status == 404


def test_estimate_with_only_filter_returns_single_run(sandbox, server):
    status, body = _post_json(
        server, "/api/estimate", {"include": ["base"], "timeout_seconds": 60}
    )
    assert status == 200, body
    plan = body["plan"]
    assert plan["run_count"] == 1
    assert plan["runs"][0]["condition_id"] == "base"


def test_approve_succeeds_for_that_plan(sandbox, server):
    status, body = _post_json(
        server, "/api/estimate", {"include": ["base"], "timeout_seconds": 60}
    )
    plan = body["plan"]

    status, body = _post_json(
        server,
        "/api/approve",
        {"plan_path": body["plan_path"], "confirm_digest": plan["digest"]},
    )
    assert status == 200, body
    assert body["approval"]["digest"] == plan["digest"]


def test_enqueue_requires_both_paths(sandbox, server):
    status, body = _post_json(server, "/api/enqueue", {"plan_path": "x"})
    assert status == 400


def test_full_roundtrip_reaches_status(sandbox, server):
    status, body = _post_json(
        server, "/api/estimate", {"timeout_seconds": 60}
    )
    assert status == 200, body
    plan_path = body["plan_path"]
    digest = body["plan"]["digest"]

    status, body = _post_json(
        server, "/api/approve", {"plan_path": plan_path, "confirm_digest": digest}
    )
    assert status == 200, body
    approval_path = body["approval_path"]

    status, body = _post_json(
        server, "/api/enqueue", {"plan_path": plan_path, "approval_path": approval_path}
    )
    assert status == 200, body
    assert len(body["jobs"]) == 2

    status, body = _get_json(server, "/api/status")
    assert status == 200
    assert len(body["jobs"]) == 2
    assert {j["condition_id"] for j in body["jobs"]} == {"base", "be-brief"}


def test_approve_rejects_wrong_digest(sandbox, server):
    status, body = _post_json(
        server, "/api/estimate", {"include": ["base"], "timeout_seconds": 60}
    )
    assert status == 200, body
    status, body = _post_json(
        server,
        "/api/approve",
        {"plan_path": body["plan_path"], "confirm_digest": "wrong-digest"},
    )
    assert status == 400


def test_estimate_accepts_custom_prompt_path(sandbox, server):
    custom_prompt = sandbox / "custom-task.md"
    custom_prompt.write_text("Do the custom task.\n", encoding="utf-8")

    status, body = _post_json(
        server,
        "/api/estimate",
        {
            "include": ["base"],
            "timeout_seconds": 60,
            "prompt_path": "custom-task.md",
        },
    )
    assert status == 200, body

    default_status, default_body = _post_json(
        server, "/api/estimate", {"include": ["base"], "timeout_seconds": 60}
    )
    assert default_status == 200, default_body
    assert body["plan"]["digest"] != default_body["plan"]["digest"]


def test_estimate_accepts_preset(sandbox, server):
    status, body = _post_json(
        server, "/api/estimate", {"include": ["base"], "max_turns": 5, "timeout_seconds": 60, "preset": "large"}
    )
    assert status == 200, body

    default_status, default_body = _post_json(
        server, "/api/estimate", {"include": ["base"], "timeout_seconds": 60}
    )
    assert default_status == 200, default_body
    assert body["plan"]["digest"] != default_body["plan"]["digest"]


def test_estimate_rejects_unknown_preset(sandbox, server):
    status, body = _post_json(
        server, "/api/estimate", {"include": ["base"], "max_turns": 5, "timeout_seconds": 60, "preset": "nope"}
    )
    assert status == 400


def test_estimate_rejects_preset_and_prompt_path_together(sandbox, server):
    status, body = _post_json(
        server,
        "/api/estimate",
        {
            "include": ["base"],
            "timeout_seconds": 60,
            "preset": "large",
            "prompt_path": "benchmark/prompts/master.md",
        },
    )
    assert status == 400


def test_estimate_rejects_non_integer_timeout(sandbox, server):
    status, body = _post_json(
        server, "/api/estimate", {"timeout_seconds": "sixty"}
    )
    assert status == 400


def test_add_condition_appends_and_is_visible_via_conditions_api(sandbox, server):
    status, body = _post_json(
        server,
        "/api/add-condition",
        {
            "id": "web-added",
            "repeat": 1,
            "requires_tools": [],
            "tool_probes": {},
            "injections": [{"type": "env", "name": "DEMO_MODE", "value": "on"}],
        },
    )
    assert status == 200, body

    status, body = _get_json(server, "/api/conditions")
    assert status == 200
    assert "web-added" in [c["id"] for c in body["conditions"]]


def test_add_condition_creates_prompt_overlay_file_from_text(sandbox, server):
    status, body = _post_json(
        server,
        "/api/add-condition",
        {
            "id": "web-overlay",
            "repeat": 1,
            "requires_tools": [],
            "tool_probes": {},
            "injections": [
                {
                    "type": "prompt_overlay",
                    "path": "benchmark/prompts/web-overlay.txt",
                    "text": "3문장 이내로 답해라",
                }
            ],
        },
    )
    assert status == 200, body
    assert (sandbox / "benchmark" / "prompts" / "web-overlay.txt").read_text(
        encoding="utf-8"
    ).strip() == "3문장 이내로 답해라"


def test_add_condition_rejects_duplicate_id_without_writing(sandbox, server):
    before = (sandbox / "benchmark" / "conditions.json").read_text(encoding="utf-8")
    status, body = _post_json(
        server,
        "/api/add-condition",
        {"id": "base", "repeat": 1, "requires_tools": [], "tool_probes": {}, "injections": []},
    )
    assert status == 400
    assert (sandbox / "benchmark" / "conditions.json").read_text(encoding="utf-8") == before


def test_log_endpoint_returns_recent_events(sandbox, server):
    status, body = _post_json(server, "/api/estimate", {"include": ["base"], "timeout_seconds": 60})
    plan_path, digest = body["plan_path"], body["plan"]["digest"]
    status, body = _post_json(server, "/api/approve", {"plan_path": plan_path, "confirm_digest": digest})
    approval_path = body["approval_path"]
    status, body = _post_json(server, "/api/enqueue", {"plan_path": plan_path, "approval_path": approval_path})
    run_id = body["jobs"][0]["run_id"]
    workdir = Path(body["jobs"][0]["workdir"])

    log_dir = workdir.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "stdout.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hello"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    status, body = _get_json(server, f"/api/log?run_id={run_id}")
    assert status == 200, body
    assert body["status"] == "queued"
    assert body["events"] == [{"kind": "text", "text": "hello"}]


def test_log_endpoint_requires_run_id(sandbox, server):
    status, body = _get_json(server, "/api/log")
    assert status == 400


def test_log_endpoint_unknown_run_id_is_404(sandbox, server):
    status, body = _get_json(server, "/api/log?run_id=nope")
    assert status == 404
