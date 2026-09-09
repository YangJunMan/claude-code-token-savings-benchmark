import argparse
from datetime import date
import json
from pathlib import Path
import time

from benchmark.reports.collect import collect_batch
from benchmark.reports.generate import generate_report
from benchmark.grader.grade import grade_attempt
from .claude import run_attempt
from .contracts import RunState, is_acceptable_result, load_config
from .preflight import run_preflight, write_environment
from .scheduler import classify_failure, quota_retry_at
from .state import StateStore


ROOT = Path(__file__).resolve().parents[2]


def _acceptable_results(run_root, condition):
    results = []
    for path in sorted((run_root / condition.value).glob("*/result.json")):
        result = json.loads(path.read_text())
        if is_acceptable_result(result):
            results.append((path, result))
    return results


def batch_run_root(root: Path, batch=None):
    """One directory per batch, so a finished week never blocks the next one.

    ``next_condition`` decides what is left to do by looking at the results
    already in the run root.  With a single shared root the second week sees a
    complete set and runs nothing, which is exactly what weekly repetition needs
    to avoid.
    """
    return Path(root) / "benchmark/runs" / (batch or date.today().isoformat())


def latest_batch_run_root(root: Path):
    """Pick the batch that ran most recently, by mtime rather than by name.

    Not every batch is named for a date - the pilot is ``pilot-2026-09-05`` -
    and any such name sorts after every ``YYYY-MM-DD`` directory, which would
    aim ``status`` and ``report`` at the pilot from then on.
    """
    batches = [p for p in (Path(root) / "benchmark/runs").glob("*") if p.is_dir()]
    if not batches:
        return batch_run_root(root)
    return max(batches, key=lambda path: path.stat().st_mtime)


def default_run_root(root: Path, config) -> Path:
    """Continue whichever batch is still unfinished instead of always starting
    one dated today.

    A batch left mid-round crosses local midnight easily - washout alone is
    70 minutes - and ``batch_run_root(root)`` with no ``batch`` argument
    resolves to today's date every time it's called. Resuming after midnight
    used to abandon yesterday's in-progress batch for a same-day duplicate
    that reran every condition from scratch.
    """
    latest = latest_batch_run_root(root)
    if next_condition(config, latest) is not None:
        return latest
    return batch_run_root(root)


def next_condition(config, run_root):
    """Return the first condition that still owes runs.

    A condition is done only once it has as many acceptable results as its
    declared ``repeat``; stopping at the first success would leave every
    percentage without a noise floor to be read against.
    """
    for condition in config.conditions:
        if len(_acceptable_results(run_root, condition)) < condition.repeat:
            return condition
    return None


def washout_eligible_at(config, run_root, condition):
    """Wait out the cache behind whatever ran last, not just the previous condition.

    A ``repeat`` is a separate measurement: it exists to expose the run-to-run
    noise floor every percentage is read against.  Started straight after its own
    first attempt it reads that attempt's cache, and ``reports.generate`` grades
    the gap between consecutive runs - of any condition - against
    ``washout_seconds``, so such a repeat is published as a washout failure.
    """
    last_request = 0.0
    for other in config.conditions:
        for _, result in _acceptable_results(run_root, other):
            last_request = max(last_request, float(result["last_request_epoch"]))
    if not last_request:
        return 0
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
            store.transition(
                condition,
                RunState.COMPLETED,
                attempt,
                last_request_epoch=result["last_request_epoch"],
                terminal_reason=result.get("terminal_reason", "completed"),
            )


def run_next(root=ROOT, run_root=None):
    config = load_config(root / "benchmark/config.json")
    run_root = default_run_root(root, config) if run_root is None else run_root
    store = StateStore(run_root)
    condition = next_condition(config, run_root)
    if condition is None:
        return None
    attempt = len(list((run_root / condition.value).glob("attempt-*"))) + 1
    attempt_dir = run_root / condition.value / f"attempt-{attempt:02d}"
    store.transition(condition, RunState.PREFLIGHT, attempt)
    store.transition(condition, RunState.RUNNING, attempt)
    try:
        result = run_attempt(root, condition, attempt_dir,
                             scheduling="serial", cache_isolation="washout")
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
    store.transition(condition, RunState.COMPLETED, attempt,
                     last_request_epoch=result["last_request_epoch"])
    return result


def run_all(root=ROOT, run_root=None):
    config = load_config(root / "benchmark/config.json")
    run_root = default_run_root(root, config) if run_root is None else run_root
    finalize_existing_results(config, run_root)
    while next_condition(config, run_root) is not None:
        condition = next_condition(config, run_root)
        eligible = washout_eligible_at(config, run_root, condition)
        if time.time() < eligible:
            StateStore(run_root).transition(
                condition, RunState.WAITING_WASHOUT, 1, eligible_epoch=eligible)
            while time.time() < eligible:
                time.sleep(min(60, eligible - time.time()))
        result = run_next(root, run_root)
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
    generate_report(run_root, root / "benchmark/reports" / run_root.name)
    collect_batch(run_root, root / "data/activity-log.csv",
                  root / "data/run-summary.csv", root / "data/comparison.csv")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "status", "report"),
                        help="Legacy read-only commands; execution uses public_cli")
    args = parser.parse_args()
    if args.command == "preflight":
        record = run_preflight(ROOT)
        write_environment(batch_run_root(ROOT) / "environment.json", record)
        print(json.dumps(record, indent=2))
        raise SystemExit(0 if record["ok"] else 1)
    if args.command == "status":
        state = StateStore(latest_batch_run_root(ROOT)).load()
        print(json.dumps(state, indent=2))
    else:
        run_root = latest_batch_run_root(ROOT)
        generate_report(run_root, ROOT / "benchmark/reports" / run_root.name)


if __name__ == "__main__":
    main()
