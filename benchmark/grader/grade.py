import json
import os
from pathlib import Path
import re
import subprocess
import sys


SCORE_WEIGHTS = {
    "hidden_functional": 45,
    "race_safety": 15,
    "public_regression": 10,
    "code_quality": 10,
    "documentation": 10,
    "evidence": 10,
}

EVIDENCE_PATTERNS = {
    "changed_files": r"changed file|files? (changed|modified|added)|modified file",
    "test_command": r"python3? -m (unittest|pytest)|pytest|unittest discover",
    "test_result": r"\b(ok|pass(ed)?|fail(ed|ures)?)\b",
    "decisions": r"decision|trade-?off|rationale|chose|approach",
    "limitations": r"limitation|not (implemented|completed)|out of scope|caveat|remaining",
}

DOC_FILES = ("docs/decision.md", "docs/operations.md")
PROTECTED_TESTS = ("tests/test_existing_behavior.py",)
HIDDEN_TRIALS = 5


def score_evidence(final_text, public_returncode, changed_files):
    """Two points per evidence category, zeroed by a false passing-test claim."""
    lowered = (final_text or "").lower()
    if not lowered.strip() or not changed_files:
        return 0
    if public_returncode != 0 and re.search(r"all tests? (pass|passed)", lowered):
        return 0
    hits = sum(1 for pattern in EVIDENCE_PATTERNS.values() if re.search(pattern, lowered))
    return 2 * hits


def _run_hidden_tests(worktree, hidden_root, report_path):
    """Run the suite in a subprocess that reports outcomes as JSON."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(worktree)
    runner = Path(__file__).parent / "run_hidden.py"
    process = subprocess.run(
        [sys.executable, str(runner), str(hidden_root), str(report_path)],
        text=True, capture_output=True, env=environment, timeout=900,
    )
    if not report_path.exists():
        return {"outcomes": {}, "total": 0,
                "log": process.stdout + process.stderr, "stdout": ""}
    return json.loads(report_path.read_text())


def _run_hidden_trials(worktree, hidden_root, report_path, trials=HIDDEN_TRIALS):
    """Run the suite repeatedly and keep the majority outcome per test.

    One concurrency test depends on SQLite lock timing, so a single run scores
    luck as quality: the same worktree graded 15/16 and 16/16 on consecutive
    runs.  Majority over repeated trials is reproducible, and the per-test pass
    rate makes a borderline implementation visible instead of hidden.
    """
    passes, seen, last = {}, set(), None
    for trial in range(trials):
        report = _run_hidden_tests(worktree, hidden_root,
                                   report_path.with_name(f"hidden-trial-{trial}.json"))
        last = report
        for test_id, status in report["outcomes"].items():
            seen.add(test_id)
            passes[test_id] = passes.get(test_id, 0) + (1 if status == "ok" else 0)
    outcomes = {test_id: ("ok" if passes[test_id] * 2 > trials else "fail")
                for test_id in seen}
    flaky = sorted(test_id for test_id in seen if 0 < passes[test_id] < trials)
    merged = dict(last or {})
    merged.update({"outcomes": outcomes, "total": len(seen),
                   "trials": trials, "pass_counts": passes, "flaky": flaky})
    report_path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")
    return merged


def _hidden_counts(report):
    outcomes = report["outcomes"]
    passed = sum(1 for status in outcomes.values() if status == "ok")
    return passed, int(report.get("total") or len(outcomes))


def _critical_counts(report):
    """Count only the invariants that define a usable service.

    Gating on every hidden test made the gate uninformative: one cosmetic failure
    marked every condition FAIL, so no comparison could ever be judged.
    """
    critical = {test_id: status for test_id, status in report["outcomes"].items()
                if test_id.rsplit(".", 1)[-1].startswith("test_critical_")}
    return sum(1 for status in critical.values() if status == "ok"), len(critical)


def _protected_tests_modified(worktree):
    diff = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", *PROTECTED_TESTS],
        cwd=worktree, text=True, capture_output=True,
    )
    return bool(diff.stdout.strip())


def score_code_quality(worktree, changed_files):
    """Reward real implementation work, and zero the score for test tampering."""
    if _protected_tests_modified(worktree):
        return 0
    implementation = [path for path in changed_files
                      if path.startswith("gpu_platform/") and path.endswith(".py")]
    tests_added = [path for path in changed_files if path.startswith("tests/")
                   and path not in PROTECTED_TESTS]
    score = 0
    if "gpu_platform/admission.py" in changed_files:
        score += 4
    if len(implementation) >= 2:
        score += 3
    if tests_added:
        score += 3
    return score


def _lines_changed(worktree, path):
    numstat = subprocess.run(
        ["git", "diff", "--numstat", "HEAD", "--", path],
        cwd=worktree, text=True, capture_output=True,
    ).stdout.split()
    if len(numstat) < 2 or not numstat[0].isdigit():
        return 0
    return int(numstat[0]) + int(numstat[1])


def score_documentation(worktree, changed_files):
    """Five points per required document that was actually revised."""
    score = 0
    for path in DOC_FILES:
        if path in changed_files and _lines_changed(worktree, path) >= 3:
            score += 5
    return score


def grade_attempt(worktree: Path, result: dict, output_path: Path):
    public_code = int(result.get("public_returncode", 1))
    changed_files = list(result.get("changed_files", []))
    evidence = score_evidence(result.get("final_text", ""), public_code, changed_files)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    hidden = _run_hidden_trials(worktree, Path(__file__).parent / "hidden_tests",
                                output_path.parent / "hidden-tests.json")
    hidden_output = hidden.get("log", "")
    passed, total = _hidden_counts(hidden)
    critical_passed, critical_total = _critical_counts(hidden)
    weight = SCORE_WEIGHTS["hidden_functional"] + SCORE_WEIGHTS["race_safety"]
    hidden_score = round(weight * passed / total) if total else 0
    code_score = score_code_quality(worktree, changed_files)
    docs_score = score_documentation(worktree, changed_files)
    public_score = SCORE_WEIGHTS["public_regression"] if public_code == 0 else 0
    record = {
        "score": hidden_score + evidence + public_score + code_score + docs_score,
        "hidden_score": hidden_score,
        "hidden_passed": passed,
        "hidden_total": total,
        "hidden_trials": hidden.get("trials", 1),
        "flaky_tests": hidden.get("flaky", []),
        "evidence": evidence,
        "public_score": public_score,
        "code_score": code_score,
        "documentation_score": docs_score,
        "tests_tampered": _protected_tests_modified(worktree),
        "critical_passed": critical_passed,
        "critical_total": critical_total,
        "critical_pass": (public_code == 0 and critical_total > 0
                          and critical_passed == critical_total),
        "hidden_output": hidden_output,
    }
    (output_path.parent / "hidden-tests.txt").write_text(hidden_output)
    output_path.write_text(json.dumps(record, indent=2) + "\n")
    return record
