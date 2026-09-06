from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
import uuid

from benchmark.grader.grade import grade_attempt
from benchmark.reports.generate import generate_report
from .claude import run_attempt
from .cli import is_acceptable_result
from .conditions import condition as declared_condition, conditions as declared_conditions


def build_reproduction_plan(conditions=None):
    """Expand each declaration into its repeats, in declaration order.

    The baseline is repeated because the spread between two identical runs is the
    floor every saving has to clear; without it no percentage can be interpreted.
    H-ON is repeated because a single observation of it overstated the saving by
    nine percentage points.  Both counts are declared, not coded, so a new
    optimizer chooses its own without touching this file.
    """
    conditions = declared_conditions() if conditions is None else conditions
    plan = []
    for item in conditions.values():
        if item.repeat == 1:
            plan.append((item.value, item.value))
            continue
        plan.extend(
            (f"{item.value}-{index:02d}", item.value)
            for index in range(1, item.repeat + 1)
        )
    return tuple(plan)


REPRODUCTION_PLAN = build_reproduction_plan()


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
    condition = declared_condition(job["condition"])
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
