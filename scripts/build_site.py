"""main의 웹 코드와 data 브랜치의 전체 기록으로 Pages artifact를 만든다."""

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

DATA_FILES = (
    "run-summary.csv", "token-bench-results.csv", "activity-log.csv",
    "comparison.csv", "run-diagnostics.json",
)


def _revision(directory: Path, tracked_file: str | None = None) -> str | None:
    if tracked_file is not None:
        tracked = subprocess.run(
            ["git", "-C", str(directory), "ls-files", "--error-unmatch", tracked_file],
            capture_output=True,
        )
        if tracked.returncode != 0:
            return None
    result = subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "HEAD"], capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _read_history(code_root: Path) -> tuple[Path, dict, dict]:
    root = code_root / "benchmark/history/legacy-2026-09-13"
    metadata = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    tables = {}
    for name, digest in metadata["files"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"과거 원본 checksum 불일치: {name}")
        with (root / name).open(encoding="utf-8", newline="") as stream:
            tables[name] = list(csv.DictReader(stream))
    return root, metadata, tables


def _write_table(path: Path, rows: list[dict]) -> None:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def build_site(*, code_root: Path, data_root: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"출력 경로가 이미 존재한다: {output}")
    tables = {}
    for name in DATA_FILES[:-1]:
        with (data_root / name).open(encoding="utf-8", newline="") as stream:
            tables[name] = list(csv.DictReader(stream))
    summary = tables["run-summary.csv"]
    results = tables["token-bench-results.csv"]
    activity = tables["activity-log.csv"]
    ids = {row["run_id"] for row in summary}
    result_ids = {row["run_id"] for row in results}
    if not ids or ids != result_ids or len(ids) != len(summary) or len(result_ids) != len(results):
        raise ValueError("요약과 결과의 실행 ID가 누락되거나 중복됐다.")
    if not {row["run_id"] for row in activity} <= ids:
        raise ValueError("턴 기록에 요약에 없는 실행 ID가 있다.")
    diagnostics = json.loads((data_root / "run-diagnostics.json").read_text(encoding="utf-8"))
    if not isinstance(diagnostics, dict) or not diagnostics.keys() <= ids:
        raise ValueError("진단에 요약에 없는 실행 ID가 있다.")
    history_root, history_metadata, history = _read_history(code_root)
    old_summary = history["run-summary.csv"]
    all_summary = [dict(row, pipeline="subscription") for row in summary] + [
        dict(row, pipeline="legacy", prompt_id=f"legacy:{row['run_date']}") for row in old_summary
    ]
    all_activity = activity + history["activity-log.csv"]
    all_keys = {(row["run_date"], row["run_id"]) for row in all_summary}
    if len(all_keys) != len(all_summary):
        raise ValueError("현행·과거 기록에 중복 실행 키가 있다.")
    if not {(row["run_date"], row["run_id"]) for row in history["activity-log.csv"]} <= all_keys:
        raise ValueError("과거 턴 기록의 실행 키가 요약에 없다.")
    models_by_date = {row["run_date"]: row["model"] for row in old_summary}
    all_comparison = tables["comparison.csv"] + [
        dict(row, model=models_by_date[row["run_date"]], prompt_id=f"legacy:{row['run_date']}")
        for row in history["comparison.csv"]
    ]
    manifest = {
        "run_count": len(all_summary), "subscription_run_count": len(summary),
        "legacy_run_count": len(old_summary), "turn_rows": len(all_activity),
        "diagnosis_count": len(diagnostics), "code_revision": _revision(code_root),
        "data_revision": _revision(data_root, "run-summary.csv"),
        "legacy_revision": history_metadata["source_revision"],
        "first_run": min(row["run_date"].removeprefix("pilot-") for row in all_summary),
        "last_run": max(row["run_date"].removeprefix("pilot-") for row in all_summary),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".site-", dir=output.parent) as temporary:
        stage = Path(temporary) / "site"
        shutil.copytree(code_root / "web", stage / "web")
        (stage / "data").mkdir()
        for name in DATA_FILES:
            shutil.copy2(data_root / name, stage / "data" / name)
        (stage / "data/subscription").mkdir()
        for name in DATA_FILES:
            shutil.copy2(data_root / name, stage / "data/subscription" / name)
        shutil.copytree(history_root, stage / "data/legacy")
        _write_table(stage / "data/run-summary.csv", all_summary)
        _write_table(stage / "data/activity-log.csv", all_activity)
        _write_table(stage / "data/comparison.csv", all_comparison)
        (stage / "index.html").write_text(
            '<!doctype html><meta charset="utf-8"><link rel="icon" href="data:,">'
            '<meta http-equiv="refresh" content="0; url=web/">\n', encoding="utf-8",
        )
        (stage / "site-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(stage, output)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_site(
        code_root=Path(__file__).resolve().parents[1], data_root=args.data_root, output=args.output,
    ), indent=2))
