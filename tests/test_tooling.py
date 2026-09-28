from pathlib import Path

from token_bench.conditions import Injection, RunSpec
from token_bench.tooling import fingerprint_tools


def _run_spec(plugin_path: str, *, fingerprint_path: str | None = None) -> RunSpec:
    return RunSpec(
        condition_id="plugin-condition",
        repeat_index=1,
        repeat_total=1,
        requires_tools=(),
        injections=(
            Injection(type="plugin_dir", path=plugin_path, fingerprint_path=fingerprint_path),
        ),
    )


def test_plugin_dir_fingerprint_covers_the_whole_tree_by_default(tmp_path):
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "SKILL.md").write_text("treatment content", encoding="utf-8")
    (plugin_dir / "unrelated.py").write_text("noise v1", encoding="utf-8")

    before = fingerprint_tools(_run_spec(str(plugin_dir)))[0]["sha256"]
    (plugin_dir / "unrelated.py").write_text("noise v2", encoding="utf-8")
    after = fingerprint_tools(_run_spec(str(plugin_dir)))[0]["sha256"]

    assert before != after


def test_fingerprint_path_ignores_unrelated_file_changes(tmp_path):
    """2026-09-21 실측 버그: caveman-full의 plugin_dir 지문이 처치와 무관한
    파일(다른 스킬의 스크립트 등)이 바뀔 때마다 흔들려서, 승인 이후 아무
    내용도 안 바뀐 것처럼 보이는데도 계속 blocked됐다. fingerprint_path를
    주면 그 파일만 지문 대상이 된다."""

    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "SKILL.md").write_text("treatment content", encoding="utf-8")
    (plugin_dir / "unrelated.py").write_text("noise v1", encoding="utf-8")

    spec = _run_spec(str(plugin_dir), fingerprint_path="SKILL.md")
    before = fingerprint_tools(spec)[0]["sha256"]
    (plugin_dir / "unrelated.py").write_text("noise v2", encoding="utf-8")
    after = fingerprint_tools(spec)[0]["sha256"]

    assert before == after

    (plugin_dir / "SKILL.md").write_text("changed treatment content", encoding="utf-8")
    changed = fingerprint_tools(spec)[0]["sha256"]
    assert changed != before
