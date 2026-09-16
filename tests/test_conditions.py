import json
from pathlib import Path

import pytest

import token_bench.conditions as conditions_module
from token_bench.conditions import (
    ConditionError,
    expand_runs,
    inspect,
    load_conditions,
    select_subset,
)


def _write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "conditions.json"
    document = {"schema_version": 1, **document}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_default_declaration_loads_and_expands():
    conditions = load_conditions(Path("benchmark/conditions.json"))
    ids = [c.id for c in conditions]
    assert {"base", "be-brief", "headroom", "caveman-full", "rtk"} <= set(ids)

    runs = expand_runs(conditions)
    assert {"base", "be-brief", "headroom", "caveman-full", "rtk"} <= {
        r.condition_id for r in runs
    }
    assert all(r.repeat_index == 1 and r.repeat_total == 1 for r in runs)


def test_schema_version_is_required(tmp_path):
    path = tmp_path / "conditions.json"
    path.write_text(json.dumps({"conditions": [{"id": "base"}]}), encoding="utf-8")
    with pytest.raises(ConditionError, match="schema_version"):
        load_conditions(path)


def test_unknown_schema_version_is_rejected(tmp_path):
    path = _write(tmp_path, {"schema_version": 2, "conditions": [{"id": "base"}]})
    with pytest.raises(ConditionError, match="schema_version"):
        load_conditions(path)


@pytest.mark.parametrize("condition_id", ["../escape", "has space", "/absolute", "UPPER"])
def test_condition_id_must_be_a_safe_slug(tmp_path, condition_id):
    path = _write(tmp_path, {"conditions": [{"id": condition_id}]})
    with pytest.raises(ConditionError, match="id"):
        load_conditions(path)


@pytest.mark.parametrize("path_value", ["../outside.txt", "/tmp/outside.txt"])
def test_repository_file_injections_cannot_escape_repository(tmp_path, path_value):
    path = _write(
        tmp_path,
        {
            "conditions": [
                {
                    "id": "unsafe",
                    "injections": [{"type": "prompt_overlay", "path": path_value}],
                }
            ]
        },
    )
    with pytest.raises(ConditionError, match="상대경로"):
        load_conditions(path)


def test_generic_arg_injection_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        {
            "conditions": [
                {
                    "id": "unsafe",
                    "injections": [{"type": "arg", "name": "--safe-mode"}],
                }
            ]
        },
    )
    with pytest.raises(ConditionError, match="알 수 없는"):
        load_conditions(path)


def test_multiple_proxy_injections_are_rejected(tmp_path):
    proxy = {"type": "proxy", "binary": "proxy", "args": [], "ready_path": "/readyz"}
    path = _write(
        tmp_path,
        {"conditions": [{"id": "two-proxies", "injections": [proxy, proxy]}]},
    )
    with pytest.raises(ConditionError, match="proxy"):
        load_conditions(path)


def test_tool_backed_condition_requires_github_repository_and_probe(tmp_path):
    path = _write(
        tmp_path,
        {
            "conditions": [
                {
                    "id": "tool-backed",
                    "requires_tools": ["tool"],
                    "tool_probes": {"tool": ["--version"]},
                }
            ]
        },
    )
    with pytest.raises(ConditionError, match="repository_url"):
        load_conditions(path)


def test_tool_probe_keys_must_match_required_tools(tmp_path):
    path = _write(
        tmp_path,
        {
            "conditions": [
                {
                    "id": "tool-backed",
                    "requires_tools": ["tool"],
                    "tool_probes": {"other": ["--version"]},
                    "repository_url": "https://github.com/example/tool",
                }
            ]
        },
    )
    with pytest.raises(ConditionError, match="tool_probes"):
        load_conditions(path)


def test_tool_probe_must_have_at_least_one_argument(tmp_path):
    path = _write(
        tmp_path,
        {
            "conditions": [
                {
                    "id": "tool-backed",
                    "requires_tools": ["tool"],
                    "tool_probes": {"tool": []},
                    "repository_url": "https://github.com/example/tool",
                }
            ]
        },
    )
    with pytest.raises(ConditionError, match="tool_probes"):
        load_conditions(path)


def test_proxy_binary_must_be_a_fingerprinted_required_tool(tmp_path):
    path = _write(
        tmp_path,
        {
            "conditions": [
                {
                    "id": "proxy-backed",
                    "repository_url": "https://github.com/example/proxy",
                    "injections": [
                        {"type": "proxy", "binary": "proxy", "args": []}
                    ],
                }
            ]
        },
    )
    with pytest.raises(ConditionError, match="requires_tools"):
        load_conditions(path)


def test_run_spec_round_trip_preserves_execution_contract(tmp_path):
    path = _write(
        tmp_path,
        {
            "conditions": [
                {
                    "id": "tool-backed",
                    "requires_tools": ["tool"],
                    "tool_probes": {"tool": ["--version"]},
                    "repository_url": "https://github.com/example/tool",
                    "injections": [{"type": "env", "name": "TOOL_MODE", "value": "on"}],
                }
            ]
        },
    )
    run = inspect(path)[0]
    assert conditions_module.run_spec_from_dict(
        conditions_module.run_spec_to_dict(run)
    ) == run


def test_inspect_matches_load_then_expand():
    path = Path("benchmark/conditions.json")
    assert inspect(path) == expand_runs(load_conditions(path))


def test_repeat_is_expanded_in_declared_order(tmp_path):
    path = _write(
        tmp_path,
        {
            "conditions": [
                {"id": "a", "repeat": 2},
                {"id": "b", "repeat": 1},
            ]
        },
    )
    runs = inspect(path)
    assert [(r.condition_id, r.repeat_index) for r in runs] == [
        ("a", 1),
        ("a", 2),
        ("b", 1),
    ]


def test_duplicate_condition_id_rejected(tmp_path):
    path = _write(
        tmp_path,
        {"conditions": [{"id": "dup"}, {"id": "dup"}]},
    )
    with pytest.raises(ConditionError, match="중복"):
        load_conditions(path)


def test_invalid_repeat_rejected(tmp_path):
    path = _write(tmp_path, {"conditions": [{"id": "a", "repeat": 0}]})
    with pytest.raises(ConditionError, match="repeat"):
        load_conditions(path)


def test_non_integer_repeat_rejected(tmp_path):
    path = _write(tmp_path, {"conditions": [{"id": "a", "repeat": "1"}]})
    with pytest.raises(ConditionError, match="repeat"):
        load_conditions(path)


def test_unknown_condition_key_rejected(tmp_path):
    path = _write(tmp_path, {"conditions": [{"id": "a", "unexpected": 1}]})
    with pytest.raises(ConditionError, match="알 수 없는 설정"):
        load_conditions(path)


def test_unknown_top_level_key_rejected(tmp_path):
    path = _write(
        tmp_path,
        {"conditions": [{"id": "a"}], "extra": True},
    )
    with pytest.raises(ConditionError, match="알 수 없는 설정"):
        load_conditions(path)


def test_unknown_injection_type_rejected(tmp_path):
    path = _write(
        tmp_path,
        {"conditions": [{"id": "a", "injections": [{"type": "hook"}]}]},
    )
    with pytest.raises(ConditionError, match="알 수 없는"):
        load_conditions(path)


@pytest.mark.parametrize(
    "name",
    ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"],
)
def test_reserved_env_injection_rejected(tmp_path, name):
    path = _write(
        tmp_path,
        {
            "conditions": [
                {
                    "id": "a",
                    "injections": [{"type": "env", "name": name, "value": "x"}],
                }
            ]
        },
    )
    with pytest.raises(ConditionError, match="runner가 소유"):
        load_conditions(path)


@pytest.mark.parametrize("name", ["--max-budget-usd", "--output-dir", "--cwd"])
def test_reserved_arg_injection_rejected(tmp_path, name):
    path = _write(
        tmp_path,
        {
            "conditions": [
                {
                    "id": "a",
                    "injections": [{"type": "arg", "name": name, "value": "1"}],
                }
            ]
        },
    )
    with pytest.raises(ConditionError, match="알 수 없는"):
        load_conditions(path)


def test_missing_declaration_file_rejected(tmp_path):
    with pytest.raises(ConditionError, match="찾을 수 없다"):
        load_conditions(tmp_path / "missing.json")


def test_invalid_json_rejected(tmp_path):
    path = tmp_path / "conditions.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConditionError, match="JSON"):
        load_conditions(path)


def test_adding_condition_via_json_edit_alone_changes_run_list(tmp_path):
    """조건 추가가 JSON 편집만으로 실행 목록에 반영되는지 검사한다."""
    path = _write(tmp_path, {"conditions": [{"id": "base"}]})
    before = [r.condition_id for r in inspect(path)]

    document = json.loads(path.read_text(encoding="utf-8"))
    document["conditions"].append({"id": "new-skill"})
    path.write_text(json.dumps(document), encoding="utf-8")

    after = [r.condition_id for r in inspect(path)]
    assert before == ["base"]
    assert after == ["base", "new-skill"]


def _three_condition_doc():
    """헬퍼: 세 조건짜리 선언을 파싱해 Condition 목록으로 반환한다."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "c.json"
        p.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "conditions": [
                        {"id": "base"},
                        {"id": "be-brief"},
                        {"id": "headroom"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return load_conditions(p)


def test_select_subset_with_no_filter_returns_all_in_order(tmp_path):
    conditions = _three_condition_doc()
    result = select_subset(conditions)
    assert [c.id for c in result] == ["base", "be-brief", "headroom"]


def test_select_subset_include_keeps_declared_order():
    conditions = _three_condition_doc()
    result = select_subset(conditions, include=["headroom", "base"])
    assert [c.id for c in result] == ["base", "headroom"]


def test_select_subset_exclude_keeps_remaining_in_order():
    conditions = _three_condition_doc()
    result = select_subset(conditions, exclude=["be-brief"])
    assert [c.id for c in result] == ["base", "headroom"]


def test_select_subset_rejects_both_include_and_exclude():
    conditions = _three_condition_doc()
    with pytest.raises(ConditionError, match="동시에"):
        select_subset(conditions, include=["base"], exclude=["headroom"])


def test_select_subset_rejects_unknown_include_id():
    conditions = _three_condition_doc()
    with pytest.raises(ConditionError, match="없는 조건"):
        select_subset(conditions, include=["not-a-real-condition"])


def test_select_subset_rejects_unknown_exclude_id():
    conditions = _three_condition_doc()
    with pytest.raises(ConditionError, match="없는 조건"):
        select_subset(conditions, exclude=["not-a-real-condition"])


def test_inspect_applies_include_filter(tmp_path):
    path = _write(
        tmp_path,
        {"conditions": [{"id": "base"}, {"id": "be-brief"}, {"id": "headroom"}]},
    )
    runs = inspect(path, include=["base"])
    assert [r.condition_id for r in runs] == ["base"]


def test_inspect_applies_exclude_filter(tmp_path):
    path = _write(
        tmp_path,
        {"conditions": [{"id": "base"}, {"id": "be-brief"}, {"id": "headroom"}]},
    )
    runs = inspect(path, exclude=["be-brief"])
    assert [r.condition_id for r in runs] == ["base", "headroom"]


def test_inspect_without_filter_is_unchanged(tmp_path):
    path = _write(
        tmp_path,
        {"conditions": [{"id": "base"}, {"id": "be-brief"}]},
    )
    assert [r.condition_id for r in inspect(path)] == [r.condition_id for r in inspect(path, include=None, exclude=None)]
