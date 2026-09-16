import re
from pathlib import Path

from token_bench.webapi import DEFAULT_HOST, DEFAULT_PORT

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = REPO_ROOT / "web" / "index.html"
SETTINGS_JS = REPO_ROOT / "web" / "settings.js"

KNOWN_ENDPOINTS = {
    "/api/conditions",
    "/api/estimate",
    "/api/approve",
    "/api/enqueue",
    "/api/status",
}


def test_settings_page_files_exist():
    assert INDEX_HTML.is_file()
    assert SETTINGS_JS.is_file()


def test_index_references_settings_js_and_style():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'src="settings.js"' in html
    assert 'href="style.css"' in html


def test_settings_js_api_base_matches_webapi_defaults():
    """프론트가 접속하는 주소가 token_bench.webapi의 기본 host/port와 어긋나지 않는지 검사한다."""

    js_source = SETTINGS_JS.read_text(encoding="utf-8")
    match = re.search(r'const API_BASE = "([^"]+)";', js_source)
    assert match, "settings.js에서 API_BASE를 찾지 못했다."
    assert match.group(1) == f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"


def test_settings_js_only_calls_known_endpoints():
    js_source = SETTINGS_JS.read_text(encoding="utf-8")
    called = set(re.findall(r'fetchJson\(\s*"(/api/[a-z]+)"', js_source))
    assert called, "settings.js에서 fetchJson 호출을 찾지 못했다."
    assert called <= KNOWN_ENDPOINTS
    # estimate/approve/enqueue는 승인 흐름의 핵심이므로 실제로 호출돼야 한다.
    assert {"/api/estimate", "/api/approve", "/api/enqueue"} <= called


def test_settings_page_exposes_custom_prompt_path():
    """요구사항 4번: 웹에서도 임의 프롬프트 경로를 지정할 수 있어야 한다."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = SETTINGS_JS.read_text(encoding="utf-8")
    assert 'id="prompt-path"' in html
    assert "prompt_path" in js


def test_settings_page_exposes_preset_choices_matching_workspace():
    from token_bench.workspace import PROMPT_PRESETS

    html = INDEX_HTML.read_text(encoding="utf-8")
    for name in PROMPT_PRESETS:
        assert f'value="{name}"' in html, f"index.html에 프리셋 '{name}' 옵션이 없다."


def test_settings_js_submits_the_digest_of_the_plan_it_displayed():
    """웹은 사용자가 digest를 따라 입력하지 않지만, 화면에 띄운 그 계획의
    digest를 그대로 보내야 한다. 계획이 그 사이 바뀌었다면 서버가 거부한다.

    CLI(`approve --confirm`)의 확인 단계는 그대로 남아 있다.
    """

    js_source = SETTINGS_JS.read_text(encoding="utf-8")
    submit_fn = re.search(r"async function onSubmit\(\)\s*{(.*?)\n}", js_source, re.DOTALL)
    assert submit_fn, "onSubmit 함수를 찾지 못했다."
    body = submit_fn.group(1)
    assert "const confirmDigest = currentPlan.digest;" in body
    assert "confirm_digest: confirmDigest" in body
    assert "/api/approve" in body and "/api/enqueue" in body


def test_settings_page_shows_a_readable_plan_summary():
    """승인 화면은 원본 JSON 덤프가 아니라 무엇을 몇 번 돌리는지를 보여준다."""

    html = INDEX_HTML.read_text(encoding="utf-8")
    js_source = SETTINGS_JS.read_text(encoding="utf-8")
    assert 'id="plan-json"' not in html, "계획 JSON 덤프가 남아 있다."
    assert 'id="confirm-digest"' not in html, "digest 입력칸이 남아 있다."
    assert 'id="plan-table"' in html and 'id="plan-kpis"' in html
    for label in ["실행할 스킬", "총 실행", "실행당 제한 시간", "인증"]:
        assert label in js_source, f"계획 요약에 '{label}'이 없다."


def test_unavailable_condition_links_to_its_official_repository():
    js_source = SETTINGS_JS.read_text(encoding="utf-8")
    assert "repository.href = c.repository_url" in js_source
    assert 'repository.target = "_blank"' in js_source
    assert 'repository.rel = "noopener noreferrer"' in js_source
