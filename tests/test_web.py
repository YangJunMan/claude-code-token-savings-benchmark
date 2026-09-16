import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from token_bench.publish import CSV_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "web" / "app.js"
INDEX_HTML = REPO_ROOT / "web" / "index.html"


def test_web_files_exist():
    assert APP_JS.is_file()
    assert INDEX_HTML.is_file()
    assert (REPO_ROOT / "web" / "style.css").is_file()


def test_index_references_app_and_style():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'src="app.js"' in html
    assert 'href="style.css"' in html


def test_app_js_csv_columns_match_publish_module():
    """웹 페이지가 읽는 컬럼 이름이 publish.py가 쓰는 컬럼과 어긋나지 않는지 검사한다."""

    js_source = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"const CSV_COLUMNS = \[(.*?)\];", js_source, flags=re.DOTALL)
    assert match, "app.js에서 CSV_COLUMNS 배열을 찾지 못했다."

    js_columns = tuple(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert js_columns == CSV_COLUMNS


@pytest.mark.skipif(shutil.which("node") is None, reason="node가 설치되어 있지 않다.")
def test_app_js_summarizes_sample_csv_correctly():
    sample_csv = "\n".join(
        [
            ",".join(CSV_COLUMNS),
            _row(
                run_id="b1-base__r1",
                condition_id="base",
                status="succeeded",
                evaluation_ran="True",
                evaluation_passed="True",
                num_turns="10",
                cost_usd="1.0",
                output_tokens="100",
                cache_read_input_tokens="1000",
            ),
            _row(
                run_id="b1-base__r2",
                condition_id="base",
                status="succeeded",
                evaluation_ran="True",
                evaluation_passed="False",
                num_turns="20",
                cost_usd="2.0",
                output_tokens="200",
                cache_read_input_tokens="2000",
            ),
            _row(
                run_id="b1-be-brief__r1",
                condition_id="be-brief",
                status="failed",
                evaluation_ran="True",
                evaluation_passed="True",
                num_turns="",  # 누락
                cost_usd="0.5",
                output_tokens="50",
                cache_read_input_tokens="500",
            ),
        ]
    )

    script = f"""
    const {{ parseCsv, toRecords, summarizeByCondition }} = require({json.dumps(str(APP_JS))});
    const csv = {json.dumps(sample_csv)};
    const records = toRecords(parseCsv(csv));
    const summary = summarizeByCondition(records);
    console.log(JSON.stringify(summary));
    """
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr

    summary = {row["conditionId"]: row for row in json.loads(result.stdout)}

    base = summary["base"]
    assert base["runCount"] == 2
    assert base["avgCost"] == pytest.approx(1.5)
    assert base["avgTurns"] == pytest.approx(15.0)
    assert base["passRate"] == pytest.approx(0.5)

    be_brief = summary["be-brief"]
    assert be_brief["runCount"] == 1
    # num_turns가 누락이면 평균 계산에서 제외되고 0으로 취급되지 않는다.
    assert be_brief["avgTurns"] is None
    assert be_brief["passRate"] == pytest.approx(1.0)


def _row(**overrides) -> str:
    values = {col: "" for col in CSV_COLUMNS}
    values.update(overrides)
    return ",".join(values[col] for col in CSV_COLUMNS)
