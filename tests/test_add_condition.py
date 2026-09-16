import json
from pathlib import Path

import pytest

from token_bench.add_condition import append_condition, run_wizard
from token_bench.conditions import ConditionError, load_conditions


def _base_doc(tmp_path: Path) -> Path:
    path = tmp_path / "conditions.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "conditions": [
                    {
                        "id": "base",
                        "repeat": 1,
                        "requires_tools": [],
                        "tool_probes": {},
                        "injections": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _scripted_input(answers: list[str]):
    it = iter(answers)

    def input_fn(_prompt: str) -> str:
        return next(it)

    return input_fn


def test_wizard_prompt_overlay_creates_file_and_condition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    answers = [
        "my-skill",  # id
        "",  # repository_url
        "n",  # needs tool
        "1",  # repeat
        "1",  # injection menu: prompt_overlay
        "benchmark/prompts/my-skill.txt",  # path (new file)
        "3문장 이내로 답해라",  # overlay text
        "6",  # done adding injections
    ]
    condition = run_wizard(input_fn=_scripted_input(answers), print_fn=lambda *_: None)

    assert condition["id"] == "my-skill"
    assert condition["repeat"] == 1
    assert condition["injections"] == [
        {"type": "prompt_overlay", "path": "benchmark/prompts/my-skill.txt"}
    ]
    assert Path("benchmark/prompts/my-skill.txt").read_text(encoding="utf-8") == "3문장 이내로 답해라\n"


def test_wizard_proxy_requires_tool_first(tmp_path):
    answers = [
        "my-proxy-skill",
        "https://github.com/example/newthing",
        "y",  # needs tool
        "newthing",  # tool name
        "--version",  # probe args
        "1",  # repeat
        "5",  # injection menu: proxy
        "newthing",  # binary (default offered)
        "proxy,--port,{port}",  # args
        "/readyz",  # ready_path
        "6",  # done
    ]
    condition = run_wizard(input_fn=_scripted_input(answers), print_fn=lambda *_: None)

    assert condition["requires_tools"] == ["newthing"]
    assert condition["tool_probes"] == {"newthing": ["--version"]}
    assert condition["repository_url"] == "https://github.com/example/newthing"
    assert condition["injections"] == [
        {
            "type": "proxy",
            "binary": "newthing",
            "args": ["proxy", "--port", "{port}"],
            "ready_path": "/readyz",
        }
    ]


def test_append_condition_writes_and_validates(tmp_path):
    path = _base_doc(tmp_path)
    append_condition(
        path,
        {
            "id": "my-skill",
            "repeat": 1,
            "requires_tools": [],
            "tool_probes": {},
            "injections": [],
        },
    )

    conditions = load_conditions(path)
    assert {c.id for c in conditions} == {"base", "my-skill"}


def test_append_condition_rejects_duplicate_id_and_leaves_file_untouched(tmp_path):
    path = _base_doc(tmp_path)
    original = path.read_text(encoding="utf-8")

    with pytest.raises(ConditionError):
        append_condition(
            path,
            {
                "id": "base",
                "repeat": 1,
                "requires_tools": [],
                "tool_probes": {},
                "injections": [],
            },
        )

    assert path.read_text(encoding="utf-8") == original
    assert not path.with_suffix(".json.tmp").exists()
