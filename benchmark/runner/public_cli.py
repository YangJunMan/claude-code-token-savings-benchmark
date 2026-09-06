import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from .api_parallel import (
    build_reproduction_jobs,
    require_api_key,
    require_paid_run_confirmation,
    run_reproduction,
)
from .conditions import conditions as declared_conditions
from .preflight import optimizer_tools


ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_MAX_USD_PER_RUN = 2.50


def estimate(max_turns=50):
    jobs = build_reproduction_jobs(max_turns=max_turns)
    return {
        "model": "claude-sonnet-5",
        "effort": "medium",
        "jobs": [job["label"] for job in jobs],
        "job_count": len(jobs),
        "max_turns_per_job": max_turns,
        "prompt_cache": "natural within each job; isolated between jobs",
        "default_workers": 1,
        "planning_ceiling_usd": len(jobs) * HISTORICAL_MAX_USD_PER_RUN,
        "basis": "job count multiplied by a conservative $2.50 historical per-run ceiling",
    }


def paid_preflight(root=ROOT, conditions=None):
    """Check every tool the declared conditions actually need.

    The tool list is derived from the declarations rather than hardcoded, so a
    newly declared optimizer is caught here instead of failing midway through a
    paid run.
    """
    errors = []
    tools = {}
    if os.name != "posix":
        errors.append("unsupported_os: macOS/Linux POSIX required")
    for name in ("claude", "git", "curl"):
        tools[name] = shutil.which(name)
        if not tools[name]:
            errors.append(f"missing_tool: {name}")
    conditions = declared_conditions() if conditions is None else conditions
    # Shared with the weekly runner's preflight so a newly declared optimizer
    # cannot be checked by one entry point and skipped by the other.
    for name, info in optimizer_tools(root, conditions.values()).items():
        tools[name] = info["path"]
        if not info["path"]:
            errors.append(f"missing_tool: {info['requires']}")
    required = [
        root / "benchmark/prompts/master.md",
        root / "benchmark/runner/isolation_mcp_server.py",
        root / "benchmark/fixture/pyproject.toml",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing_file: {path}")
    return {"ok": not errors, "python": sys.version.split()[0], "tools": tools, "errors": errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safe public benchmark entry point")
    subparsers = parser.add_subparsers(dest="command", required=True)
    estimate_parser = subparsers.add_parser("estimate")
    estimate_parser.add_argument("--max-turns", type=int, default=50)
    subparsers.add_parser("preflight")
    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_parser.add_argument("--max-turns", type=int, default=50)
    benchmark_parser.add_argument("--max-budget-usd", type=float, required=True)
    benchmark_parser.add_argument("--confirm-paid-run", action="store_true")
    benchmark_parser.add_argument("--run-root", type=Path, required=True)
    benchmark_parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    projection = estimate(getattr(args, "max_turns", 50))
    if args.command == "estimate":
        print(json.dumps(projection, indent=2))
        return 0

    if args.command == "preflight":
        result = paid_preflight()
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    require_paid_run_confirmation(args.confirm_paid_run, args.max_budget_usd)
    require_api_key(os.environ)
    preflight = paid_preflight()
    if not preflight["ok"]:
        raise RuntimeError("Paid preflight failed before any model call: " + "; ".join(preflight["errors"]))
    if args.max_budget_usd < projection["planning_ceiling_usd"]:
        raise RuntimeError(
            f"Budget ${args.max_budget_usd:.2f} is below the conservative planning ceiling "
            f"${projection['planning_ceiling_usd']:.2f}; lower max-turns only after a pilot"
        )
    records = run_reproduction(
        ROOT, args.run_root, args.report_dir, args.max_turns, args.max_budget_usd
    )
    print(json.dumps(records, indent=2, sort_keys=True))
    return 0 if len(records) == projection["job_count"] and all(
        record.get("state") == "completed" for record in records
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
