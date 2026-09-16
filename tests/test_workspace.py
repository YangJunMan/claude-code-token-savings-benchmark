import hashlib
import json
from pathlib import Path

import pytest

import token_bench.workspace as workspace_module
from token_bench.conditions import Injection, RunSpec
from token_bench.workspace import (
    PROMPT_PRESETS,
    WorkspaceError,
    build_final_prompt,
    prepare_batch,
    prepare_run,
    resolve_prompt_path,
)


def _run(condition_id="base", repeat_index=1, injections=()):
    return RunSpec(
        condition_id=condition_id,
        repeat_index=repeat_index,
        repeat_total=1,
        requires_tools=(),
        injections=tuple(injections),
    )


def _make_fake_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    (repo_root / "benchmark" / "fixture" / "pkg").mkdir(parents=True)
    (repo_root / "benchmark" / "prompts").mkdir(parents=True)
    (repo_root / "benchmark" / "fixture" / "pkg" / "app.py").write_text(
        "print('hello')\n", encoding="utf-8"
    )
    (repo_root / "benchmark" / "prompts" / "master.md").write_text(
        "Implement the task.\n", encoding="utf-8"
    )
    (repo_root / "benchmark" / "prompts" / "be-brief.txt").write_text(
        "Be brief.\n", encoding="utf-8"
    )
    return repo_root


def test_prepare_run_creates_isolated_workdir_and_snapshot(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    ws = prepare_run(
        _run(),
        batch_id="batch1",
        timeout_seconds=60,
        repo_root=repo_root,
    )
    assert ws.workdir.is_dir()
    assert (ws.workdir / "pkg" / "app.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert ws.snapshot_path.is_file()


def test_different_conditions_get_different_workdirs(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    ws_a = prepare_run(
        _run(condition_id="base"),
        batch_id="batch1",
        timeout_seconds=60,
        repo_root=repo_root,
    )
    ws_b = prepare_run(
        _run(condition_id="be-brief"),
        batch_id="batch1",
        timeout_seconds=60,
        repo_root=repo_root,
    )
    assert ws_a.workdir != ws_b.workdir
    assert ws_a.content_id != ws_b.content_id


def test_original_fixture_is_not_modified(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    fixture_file = repo_root / "benchmark" / "fixture" / "pkg" / "app.py"
    before = hashlib.sha256(fixture_file.read_bytes()).hexdigest()

    prepare_run(
        _run(), batch_id="batch1", timeout_seconds=60, repo_root=repo_root
    )

    after = hashlib.sha256(fixture_file.read_bytes()).hexdigest()
    assert before == after


def test_same_input_has_same_content_id(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    ws1 = prepare_run(
        _run(), batch_id="batch1", timeout_seconds=60, repo_root=repo_root
    )
    ws2 = prepare_run(
        _run(), batch_id="batch2", timeout_seconds=60, repo_root=repo_root
    )
    assert ws1.content_id == ws2.content_id
    assert ws1.run_id != ws2.run_id


def test_changing_prompt_input_changes_content_id(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    ws1 = prepare_run(
        _run(), batch_id="batch1", timeout_seconds=60, repo_root=repo_root
    )

    prompt_path = repo_root / "benchmark" / "prompts" / "master.md"
    prompt_path.write_text("Implement the task differently.\n", encoding="utf-8")

    ws2 = prepare_run(
        _run(), batch_id="batch2", timeout_seconds=60, repo_root=repo_root
    )
    assert ws1.content_id != ws2.content_id


def test_changing_env_injection_changes_content_id(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    ws1 = prepare_run(
        _run(injections=[Injection(type="env", name="TOOL_MODE", value="one")]),
        batch_id="batch1",
        timeout_seconds=60,
        repo_root=repo_root,
    )
    ws2 = prepare_run(
        _run(injections=[Injection(type="env", name="TOOL_MODE", value="two")]),
        batch_id="batch2",
        timeout_seconds=60,
        repo_root=repo_root,
    )
    assert ws1.content_id != ws2.content_id


def test_config_ref_is_copied_and_its_content_changes_content_id(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    settings = repo_root / "benchmark" / "settings" / "tool.json"
    settings.parent.mkdir()
    settings.write_text('{"mode":"one"}\n', encoding="utf-8")
    run = _run(injections=[Injection(type="config_ref", path="benchmark/settings/tool.json")])

    ws1 = prepare_run(run, batch_id="batch1", timeout_seconds=60, repo_root=repo_root)
    settings.write_text('{"mode":"two"}\n', encoding="utf-8")
    ws2 = prepare_run(run, batch_id="batch2", timeout_seconds=60, repo_root=repo_root)

    assert ws1.content_id != ws2.content_id
    approved = workspace_module.load_run_snapshot(ws1.snapshot_path)
    copied_path = ws1.snapshot_path.parent / approved.injections[0].path
    assert copied_path.read_text(encoding="utf-8") == '{"mode":"one"}\n'


def test_snapshot_round_trip_contains_the_approved_condition(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    run = _run(injections=[Injection(type="env", name="TOOL_MODE", value="approved")])
    ws = prepare_run(run, batch_id="batch1", timeout_seconds=60, repo_root=repo_root)
    assert workspace_module.load_run_snapshot(ws.snapshot_path) == run


def test_modified_execution_condition_snapshot_is_rejected(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    ws = prepare_run(_run(), batch_id="batch1", timeout_seconds=60, repo_root=repo_root)
    snapshot = json.loads(ws.snapshot_path.read_text(encoding="utf-8"))
    snapshot["execution_condition"]["injections"] = [
        {"type": "env", "name": "TOOL_MODE", "value": "tampered"}
    ]
    ws.snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(WorkspaceError, match="content_id"):
        workspace_module.load_run_snapshot(ws.snapshot_path)


def test_snapshot_must_match_the_queued_content_id(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    ws = prepare_run(_run(), batch_id="batch1", timeout_seconds=60, repo_root=repo_root)
    with pytest.raises(WorkspaceError, match="content_id"):
        workspace_module.load_run_snapshot(
            ws.snapshot_path, expected_content_id="different-approved-content"
        )


def test_prompt_overlay_injection_is_applied_to_final_prompt(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    run = _run(
        condition_id="be-brief",
        injections=[Injection(type="prompt_overlay", path="benchmark/prompts/be-brief.txt")],
    )
    task_prompt = (repo_root / "benchmark" / "prompts" / "master.md").read_text(
        encoding="utf-8"
    )
    final_prompt = build_final_prompt(task_prompt, run, repo_root)
    assert "Implement the task." in final_prompt
    assert "Be brief." in final_prompt


def test_missing_prompt_overlay_file_is_rejected(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    run = _run(
        injections=[Injection(type="prompt_overlay", path="benchmark/prompts/missing.txt")]
    )
    with pytest.raises(WorkspaceError, match="찾을 수 없다"):
        prepare_run(run, batch_id="batch1", timeout_seconds=60, repo_root=repo_root)


def test_invalid_timeout_is_rejected(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    with pytest.raises(WorkspaceError, match="timeout_seconds"):
        prepare_run(_run(), batch_id="b", timeout_seconds=0, repo_root=repo_root)


def test_duplicate_run_dir_is_rejected(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    prepare_run(_run(), batch_id="batch1", timeout_seconds=60, repo_root=repo_root)
    with pytest.raises(WorkspaceError, match="이미 존재"):
        prepare_run(
            _run(), batch_id="batch1", timeout_seconds=60, repo_root=repo_root
        )


def test_prepare_batch_shares_one_batch_id(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    runs = [_run(condition_id="base"), _run(condition_id="be-brief")]
    workspaces = prepare_batch(runs, timeout_seconds=60, repo_root=repo_root)
    batch_ids = {ws.run_id.split("-", 1)[0] for ws in workspaces}
    assert len(batch_ids) == 1


def test_prepare_against_real_repository_fixture(tmp_path):
    """실제 저장소의 benchmark/fixture, benchmark/conditions.json으로 통합 검증한다."""
    from token_bench.conditions import inspect

    repo_root = Path(__file__).resolve().parents[1]
    runs = inspect(repo_root / "benchmark" / "conditions.json")
    workspaces = prepare_batch(
        runs,
        timeout_seconds=60,
        repo_root=repo_root,
        runs_root=tmp_path / "runs",
    )
    assert [ws.condition_id for ws in workspaces] == [
        "base",
        "be-brief",
        "headroom",
        "caveman-full",
        "rtk",
    ]
    for ws in workspaces:
        assert ws.workdir.is_dir()
        assert (ws.workdir / "gpu_platform").exists()
        prompt_text = (ws.workdir.parent / "prompt.md").read_text(encoding="utf-8")
        assert "Production implementation task" in prompt_text
        assert "{max_turns}" not in prompt_text


def test_custom_prompt_path_changes_content_id_and_final_prompt(tmp_path):
    """요구사항 4번: 임의의 프롬프트 파일을 지정하면 그 내용이 실제로 반영된다."""
    repo_root = _make_fake_repo(tmp_path)
    custom_prompt = tmp_path / "my-custom-task.md"
    custom_prompt.write_text("Do something completely different.\n", encoding="utf-8")

    default_ws = prepare_run(
        _run(), batch_id="batch1", timeout_seconds=60, repo_root=repo_root
    )
    custom_ws = prepare_run(
        _run(),
        batch_id="batch2",
        timeout_seconds=60,
        repo_root=repo_root,
        task_prompt_path=custom_prompt,
    )

    assert default_ws.content_id != custom_ws.content_id
    final_prompt = (custom_ws.workdir.parent / "prompt.md").read_text(encoding="utf-8")
    assert "Do something completely different." in final_prompt


def test_custom_prompt_path_missing_file_is_rejected(tmp_path):
    repo_root = _make_fake_repo(tmp_path)
    with pytest.raises(WorkspaceError, match="찾을 수 없다"):
        prepare_run(
            _run(),
            batch_id="batch1",
            timeout_seconds=60,
            repo_root=repo_root,
            task_prompt_path=tmp_path / "does-not-exist.md",
        )


def test_cli_prepare_accepts_custom_prompt_path():
    """CLI --prompt가 실제로 workspace.prepare_batch에 전달되는지 subprocess로 확인한다."""
    import json
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    custom_prompt = repo_root / "benchmark" / "prompts" / "be-brief.txt"  # 존재하는 임의 파일로 대체 사용

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "token_bench",
            "prepare",
            "--only",
            "base",
            "--timeout-seconds",
            "60",
            "--prompt",
            str(custom_prompt.relative_to(repo_root)),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    workspaces = json.loads(result.stdout)
    assert len(workspaces) == 1
    prompt_path = Path(workspaces[0]["workdir"]).parent / "prompt.md"
    final_prompt = (repo_root / prompt_path).read_text(encoding="utf-8")
    assert "Be brief." in final_prompt
    # 정리
    import shutil

    shutil.rmtree(repo_root / Path(workspaces[0]["workdir"]).parent, ignore_errors=True)


def test_resolve_prompt_path_defaults_to_master_prompt():
    from token_bench.workspace import DEFAULT_TASK_PROMPT_PATH

    assert resolve_prompt_path() == DEFAULT_TASK_PROMPT_PATH


def test_resolve_prompt_path_small_preset_matches_default():
    from token_bench.workspace import DEFAULT_TASK_PROMPT_PATH

    assert resolve_prompt_path(preset="small") == DEFAULT_TASK_PROMPT_PATH


def test_resolve_prompt_path_returns_preset_paths():
    assert resolve_prompt_path(preset="large") == PROMPT_PRESETS["large"]
    assert resolve_prompt_path(preset="very-large") == PROMPT_PRESETS["very-large"]


def test_resolve_prompt_path_rejects_unknown_preset():
    with pytest.raises(WorkspaceError, match="알 수 없는 프리셋"):
        resolve_prompt_path(preset="does-not-exist")


def test_resolve_prompt_path_rejects_preset_and_prompt_together():
    with pytest.raises(WorkspaceError, match="동시에"):
        resolve_prompt_path(preset="large", prompt_path=Path("custom.md"))


def test_resolve_prompt_path_returns_explicit_prompt_path_unchanged():
    custom = Path("my-custom.md")
    assert resolve_prompt_path(prompt_path=custom) == custom


def test_preset_files_exist_and_are_readable():
    repo_root = Path(__file__).resolve().parents[1]
    for name, rel_path in PROMPT_PRESETS.items():
        path = repo_root / rel_path
        assert path.is_file(), f"프리셋 '{name}'의 파일이 없다: {rel_path}"
        assert path.read_text(encoding="utf-8").strip(), f"프리셋 '{name}' 파일이 비어 있다."


def test_three_presets_produce_three_different_content_ids():
    """요구사항 5번: 프리셋마다 실제로 다른 실행 입력이 된다."""
    repo_root = Path(__file__).resolve().parents[1]
    content_ids = {}
    for name in PROMPT_PRESETS:
        prompt_path = resolve_prompt_path(preset=name)
        ws = prepare_run(
            _run(condition_id="base"),
            batch_id=f"batch-{name}",
            timeout_seconds=60,
            repo_root=repo_root,
            task_prompt_path=prompt_path,
            runs_root=Path(f".token-bench-test-presets/{name}"),
        )
        content_ids[name] = ws.content_id

    assert len(set(content_ids.values())) == 3

    # 정리
    import shutil

    shutil.rmtree(repo_root / ".token-bench-test-presets", ignore_errors=True)


def test_very_large_preset_requires_more_than_large_preset():
    """very-large가 large보다 요구사항이 더 많은지(서브 요구사항 번호 개수로) 확인한다."""
    import re

    repo_root = Path(__file__).resolve().parents[1]
    large_text = (repo_root / PROMPT_PRESETS["large"]).read_text(encoding="utf-8")
    very_large_text = (repo_root / PROMPT_PRESETS["very-large"]).read_text(encoding="utf-8")

    large_count = len(re.findall(r"^\d+\.", large_text, flags=re.MULTILINE))
    very_large_count = len(re.findall(r"^\d+\.", very_large_text, flags=re.MULTILINE))

    assert very_large_count > large_count > 12  # master.md 기준 12개 요구사항보다 많아야 한다.
