import json
import shutil

from tests.test_webapi import sandbox
from token_bench.intake import create_plan
from token_bench.webapi import _handle_estimate
from token_bench.__main__ import _run_estimate


def test_cli_web_and_intake_share_digest_and_model(sandbox, monkeypatch, capsys):
    monkeypatch.setattr("token_bench.workspace.new_batch_id", lambda: "fixedbatch")
    path = sandbox / "benchmark/conditions.json"
    direct = create_plan(path, timeout_seconds=60, model="model-a")
    assert direct.plan_path.is_file()
    shutil.rmtree(direct.plan_path.parent)
    web = _handle_estimate({"timeout_seconds": 60, "model": "model-a"}, conditions_path=path)
    shutil.rmtree(direct.plan_path.parent)
    assert _run_estimate(path, timeout_seconds=60, model="model-a") == 0
    cli = json.loads(capsys.readouterr().out)
    assert cli == web["plan"] == direct.plan.to_dict()
    assert cli["model"] == "model-a"
    assert direct.plan_path.is_file()
    shutil.rmtree(direct.plan_path.parent)
    other = create_plan(path, timeout_seconds=60, model="model-b")
    assert other.plan.digest != direct.plan.digest
