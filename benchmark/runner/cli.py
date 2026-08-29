import argparse
import json
from pathlib import Path
import time

from benchmark.reports.generate import generate_report
from benchmark.grader.grade import grade_attempt
from .claude import run_attempt
from .contracts import RunState, load_config
from .preflight import run_preflight, write_environment
from .scheduler import classify_failure, quota_retry_at
from .state import StateStore


ROOT = Path(__file__).resolve().parents[2]


def is_acceptable_result(result):
    if not result.get("clear_succeeded"):
        return False
    transcript = result.get("transcript_summary")
    if not transcript or int(transcript.get("first_turn_cache_read_tokens", -1)) != 0:
        return False
    if result.get("returncode") == 0:
        return True
    return (
        result.get("terminal_reason") == "max_turns"
        and result.get("public_returncode") == 0
    )


def _acceptable_results(run_root, condition):
    results = []
    for path in sorted((run_root / condition.value).glob("*/result.json")):
        result = json.loads(path.read_text())
        if is_acceptable_result(result):
            results.append((path, result))
    return results


def next_condition(config, run_root):
    for condition in config.conditions:
        if not _acceptable_results(run_root, condition):
            return condition
    return None


def washout_eligible_at(config, run_root, condition):
    index = config.conditions.index(condition)
    if index == 0:
        return 0
    previous = config.conditions[index - 1]
    results = _acceptable_results(run_root, previous)
    if not results:
        return 0
    last_request = max(float(result["last_request_epoch"]) for _, result in results)
    return last_request + config.washout_seconds


def finalize_existing_results(config, run_root):
    store = StateStore(run_root)
    for condition in config.conditions:
        for result_path, result in _acceptable_results(run_root, condition):
            attempt_dir = result_path.parent
            quality_path = attempt_dir / "quality.json"
            if quality_path.exists():
                continue
            grade_attempt(attempt_dir / "worktree", result, quality_path)
            attempt = int(attempt_dir.name.split("-")[-1])
            store.transition(condition, RunState.CLEARING, attempt)
            store.transition(
                condition,
                RunState.COMPLETED,
                attempt,
                last_request_epoch=result["last_request_epoch"],
                terminal_reason=result.get("terminal_reason", "completed"),
            )


def run_next(root=ROOT):
    config = load_config(root / "benchmark/config.json")
    run_root = root / "benchmark/runs"
    store = StateStore(run_root)
    condition = next_condition(config, run_root)
    if condition is None:
        return None
    attempt = len(list((run_root / condition.value).glob("attempt-*"))) + 1
    attempt_dir = run_root / condition.value / f"attempt-{attempt:02d}"
    store.transition(condition, RunState.PREFLIGHT, attempt)
    store.transition(condition, RunState.RUNNING, attempt)
    try:
        result = run_attempt(root, condition, attempt_dir)
    except Exception as error:
        failure = classify_failure(str(error))
        state = RunState.INVALID_QUOTA_INTERRUPTED if failure.invalidate_attempt else RunState.FAILED
        store.transition(condition, state, attempt, error=str(error))
        raise
    if not is_acceptable_result(result):
        text = json.dumps(result) + (attempt_dir / "stderr.log").read_text()
        failure = classify_failure(text)
        state = RunState.INVALID_QUOTA_INTERRUPTED if failure.invalidate_attempt else RunState.FAILED
        store.transition(condition, state, attempt, error=text[-2000:])
        return result
    grade_attempt(attempt_dir / "worktree", result, attempt_dir / "quality.json")
    store.transition(condition, RunState.CLEARING, attempt)
    store.transition(condition, RunState.COMPLETED, attempt,
                     last_request_epoch=result["last_request_epoch"])
    return result


def run_all(root=ROOT):
    config = load_config(root / "benchmark/config.json")
    run_root = root / "benchmark/runs"
    finalize_existing_results(config, run_root)
    while next_condition(config, run_root) is not None:
        condition = next_condition(config, run_root)
        eligible = washout_eligible_at(config, run_root, condition)
        if time.time() < eligible:
            StateStore(run_root).transition(
                condition, RunState.WAITING_WASHOUT, 1, eligible_epoch=eligible)
            while time.time() < eligible:
                time.sleep(min(60, eligible - time.time()))
        result = run_next(root)
        if not result or not is_acceptable_result(result):
            failure_text = json.dumps(result or {})
            stderr_path = run_root / condition.value / f"attempt-{len(list((run_root / condition.value).glob('attempt-*'))):02d}" / "stderr.log"
            if stderr_path.exists():
                failure_text += stderr_path.read_text()
            if classify_failure(failure_text).invalidate_attempt:
                retry_epoch = quota_retry_at(failure_text)
                StateStore(run_root).transition(
                    condition,
                    RunState.WAITING_CLAUDE_QUOTA,
                    len(list((run_root / condition.value).glob("attempt-*"))),
                    eligible_epoch=retry_epoch,
                )
                while time.time() < retry_epoch:
                    time.sleep(min(60, retry_epoch - time.time()))
                continue
            return 2
    generate_report(root / "benchmark/runs", root / "benchmark/reports")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "run-next", "run-all", "status", "report"))
    args = parser.parse_args()
    if args.command == "preflight":
        record = run_preflight(ROOT)
        write_environment(ROOT / "benchmark/runs/environment.json", record)
        print(json.dumps(record, indent=2))
        raise SystemExit(0 if record["ok"] else 1)
    if args.command == "run-next":
        run_next()
    elif args.command == "run-all":
        raise SystemExit(run_all())
    elif args.command == "status":
        state = StateStore(ROOT / "benchmark/runs").load()
        print(json.dumps(state, indent=2))
    else:
        generate_report(ROOT / "benchmark/runs", ROOT / "benchmark/reports")


if __name__ == "__main__":
    main()
