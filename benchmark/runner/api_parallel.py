import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
import uuid

from benchmark.grader.grade import grade_attempt
from benchmark.reports.generate import generate_report
from .artifacts import sha256
from .claude import run_attempt
from .cli import is_acceptable_result
from .contracts import Condition, load_config


API_CONDITIONS = [condition.value for condition in (
    Condition.BASE, Condition.H_ON, Condition.C_FULL,
    Condition.C_BRIEF, Condition.R_ON,
)]

# The baseline is repeated because the spread between two identical runs is the
# floor every saving has to clear; without it no percentage can be interpreted.
# H-ON is repeated because a single observation of it overstated the saving by
# nine percentage points.
REPRODUCTION_PLAN = (
    ("BASE-01", Condition.BASE.value),
    ("BASE-02", Condition.BASE.value),
    ("H-ON-01", Condition.H_ON.value),
    ("H-ON-02", Condition.H_ON.value),
    ("C-FULL", Condition.C_FULL.value),
    ("C-BRIEF", Condition.C_BRIEF.value),
    ("R-ON", Condition.R_ON.value),
)


def require_api_key(environment):
    key = environment.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("API mode requires ANTHROPIC_API_KEY; refusing OAuth fallback")
    return key


def require_paid_run_confirmation(confirmed, max_budget_usd):
    if not confirmed:
        raise RuntimeError("Paid API run refused: pass --confirm-paid-run after reviewing the estimate")
    if max_budget_usd <= 0:
        raise ValueError("--max-budget-usd must be positive")
    return float(max_budget_usd)


def build_jobs(max_turns=50, disable_prompt_caching=True, isolation_tools=(), isolation_mcp=False):
    return [
        {
            "condition": condition,
            "max_turns": max_turns,
            "max_budget_usd": 2.50,
            "nonce": str(uuid.uuid4()),
            "disable_prompt_caching": disable_prompt_caching,
            "isolation_tools": tuple(isolation_tools),
            "isolation_mcp": isolation_mcp,
        }
        for condition in API_CONDITIONS
    ]


def build_reproduction_jobs(max_turns=50):
    return [
        {
            "label": label,
            "condition": condition,
            "max_turns": max_turns,
            "max_budget_usd": 2.50,
            "nonce": str(uuid.uuid4()),
            "disable_prompt_caching": False,
            "isolation_tools": ("WebSearch",),
            "isolation_mcp": True,
        }
        for label, condition in REPRODUCTION_PLAN
    ]


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_one(root, run_root, job, index, events_path, events_lock):
    condition = Condition(job["condition"])
    label = job.get("label", condition.value)
    attempt_dir = run_root / label / "attempt-01"
    state_path = attempt_dir / "api-state.json"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "condition": condition.value, "state": "running", "nonce": job["nonce"],
        "started_at": _now(),
    }, indent=2) + "\n")
    try:
        result = run_attempt(
            root,
            condition,
            attempt_dir,
            max_turns=job["max_turns"],
            max_budget_usd=job.get("max_budget_usd"),
            api_mode=True,
            nonce=job["nonce"],
            port=8800 + index,
            disable_prompt_caching=job["disable_prompt_caching"],
            isolation_tools=job["isolation_tools"],
            isolation_mcp=job["isolation_mcp"],
        )
        quality = grade_attempt(attempt_dir / "worktree", result, attempt_dir / "quality.json")
        state = "completed" if is_acceptable_result(result) else "invalid"
        record = {
            "label": label,
            "condition": condition.value,
            "state": state,
            "returncode": result.get("returncode"),
            "cost_usd": result.get("total_cost_usd"),
            "quality_score": quality.get("score"),
            "finished_at": _now(),
        }
    except Exception as error:
        record = {
            "label": label,
            "condition": condition.value, "state": "error",
            "error": str(error), "finished_at": _now(),
        }
    state_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    with events_lock:
        with events_path.open("a") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def run_reproduction(root, run_root, report_dir, max_turns, max_budget_usd, projected_job_usd=2.50):
    """Run the six-job public protocol serially and stop between jobs at budget."""
    if run_root.exists() and any(run_root.iterdir()):
        raise FileExistsError(f"Refusing to overwrite immutable run root: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_root / "api-events.jsonl"
    events_lock = threading.Lock()
    records = []
    for index, job in enumerate(build_reproduction_jobs(max_turns=max_turns)):
        spent = sum(float(item.get("cost_usd") or 0) for item in records)
        if spent + projected_job_usd > max_budget_usd:
            break
        record = _run_one(root, run_root, job, index, events_path, events_lock)
        records.append(record)
        spent = sum(float(item.get("cost_usd") or 0) for item in records)
        if spent >= max_budget_usd:
            break
    generate_report(run_root, report_dir)
    summary_path = report_dir / "reproduction-summary.json"
    summary_path.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")
    return records


def run_parallel(root, run_root, report_dir, max_turns=12, workers=7,
                 disable_prompt_caching=True, isolation_tools=(), isolation_mcp=False):
    require_api_key(os.environ)
    config = load_config(root / "benchmark/config.json")
    if max_turns < 1:
        raise ValueError("max_turns must be positive")
    run_root.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    (run_root / "api-config.json").write_text(json.dumps({
        "model": config.model, "effort": config.effort,
        "max_turns": max_turns, "parallel_workers": workers,
        "disable_prompt_caching": disable_prompt_caching,
        "isolation_tools": list(isolation_tools),
        "isolation_mcp": isolation_mcp,
        "nonce": "unique system nonce per condition",
        "conditions": API_CONDITIONS,
        "fixture_sha256": sha256(root / "benchmark/fixture/pyproject.toml"),
    }, indent=2, sort_keys=True) + "\n")
    events_path = run_root / "api-events.jsonl"
    events_lock = threading.Lock()
    jobs = build_jobs(
        max_turns, disable_prompt_caching=disable_prompt_caching,
        isolation_tools=isolation_tools,
        isolation_mcp=isolation_mcp,
    )
    records = []
    with ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as executor:
        futures = [executor.submit(_run_one, root, run_root, job, index, events_path, events_lock)
                   for index, job in enumerate(jobs)]
        for future in as_completed(futures):
            records.append(future.result())
    generate_report(run_root, report_dir)
    (run_root / "api-summary.json").write_text(json.dumps(sorted(records, key=lambda x: x["condition"]),
                                                          indent=2, sort_keys=True) + "\n")
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--run-root", type=Path, default=None)
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--workers", type=int, default=7)
    parser.add_argument("--natural-cache", action="store_true",
                        help="Enable provider prompt caching within each condition")
    args = parser.parse_args()
    run_root = args.run_root or args.root / (
        "benchmark/runs-api-natural" if args.natural_cache else "benchmark/runs-api"
    )
    report_dir = args.report_dir or args.root / (
        "benchmark/reports-api-natural" if args.natural_cache else "benchmark/reports-api"
    )
    records = run_parallel(
        args.root, run_root, report_dir, args.max_turns, args.workers,
        disable_prompt_caching=not args.natural_cache,
        isolation_tools=("WebSearch",) if args.natural_cache else (),
        isolation_mcp=args.natural_cache,
    )
    print(json.dumps(sorted(records, key=lambda x: x["condition"]), indent=2, sort_keys=True))
    raise SystemExit(0 if all(item["state"] == "completed" for item in records) else 2)


if __name__ == "__main__":
    main()
