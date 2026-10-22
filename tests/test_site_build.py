import csv
import json
from pathlib import Path

import pytest

from scripts.build_site import build_site

REPO = Path(__file__).resolve().parents[1]


def _data(root):
    root.mkdir()
    tables = {
        "run-summary.csv": ["run_id,run_date,terminal_reason", "one,2026-10-01,succeeded", "two,2026-10-02,timeout"],
        "token-bench-results.csv": ["run_id,status", "one,succeeded", "two,timeout"],
        "activity-log.csv": ["run_id,turn", "one,1"],
        "comparison.csv": ["run_date,condition", "2026-10-01,RTK"],
    }
    for name, rows in tables.items():
        (root / name).write_text("\n".join(rows) + "\n")
    (root / "run-diagnostics.json").write_text(json.dumps({"two": {"summary": "timeout", "events": []}}))
    return root


def test_site_preserves_all_runs_including_no_turn_timeout(tmp_path):
    data = _data(tmp_path / "data")
    output = tmp_path / "site"
    manifest = build_site(code_root=REPO, data_root=data, output=output)
    assert manifest["run_count"] == 22
    assert manifest["subscription_run_count"] == 2
    assert manifest["legacy_run_count"] == 20
    assert manifest["turn_rows"] == 674
    assert manifest["diagnosis_count"] == 1
    assert (output / "web/app.js").read_bytes() == (REPO / "web/app.js").read_bytes()
    assert (output / "data/subscription/run-summary.csv").read_bytes() == (data / "run-summary.csv").read_bytes()
    combined = list(csv.DictReader((output / "data/run-summary.csv").open()))
    assert len(combined) == 22
    assert len({(r["run_date"], r["run_id"]) for r in combined}) == 22
    assert {r["prompt_id"] for r in combined if r["pipeline"] == "legacy"} == {
        "legacy:pilot-2026-09-05", "legacy:2026-09-06", "legacy:2026-09-08", "legacy:2026-09-13",
    }
    assert json.loads((output / "site-manifest.json").read_text()) == manifest


def test_site_rejects_missing_result_rows_before_creating_artifact(tmp_path):
    data = _data(tmp_path / "data")
    (data / "token-bench-results.csv").write_text("run_id,status\none,succeeded\n")
    with pytest.raises(ValueError, match="실행 ID"):
        build_site(code_root=REPO, data_root=data, output=tmp_path / "site")
    assert not (tmp_path / "site").exists()
