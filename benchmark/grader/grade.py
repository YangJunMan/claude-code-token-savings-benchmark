import json
import os
from pathlib import Path
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


def score_evidence(final_text, public_returncode, changed_files):
    lowered = final_text.lower()
    if public_returncode != 0 and ("tests pass" in lowered or "tests passed" in lowered):
        return 0
    required = ("changed file", "test", "decision", "limitation")
    return 10 if changed_files and all(term in lowered for term in required) else 0


def grade_attempt(worktree: Path, result: dict, output_path: Path):
    public_code = int(result.get("public_returncode", 1))
    evidence = score_evidence(result.get("final_text", ""), public_code, result.get("changed_files", []))
    hidden_root = Path(__file__).parent / "hidden_tests"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(worktree)
    hidden = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(hidden_root), "-v"],
        text=True, capture_output=True, env=environment,
    )
    passed = hidden.stdout.count(" ... ok") + hidden.stderr.count(" ... ok")
    total = 6
    hidden_score = round(60 * min(passed, total) / total)
    changed = set(result.get("changed_files", []))
    tests_tampered = any(path.startswith("tests/test_existing_behavior.py") for path in changed)
    code_score = 10 if "gpu_platform/admission.py" in changed and not tests_tampered else 0
    docs_score = 10 if {"docs/decision.md", "docs/operations.md"}.issubset(changed) else 0
    score = hidden_score + evidence + (10 if public_code == 0 else 0) + code_score + docs_score
    hidden_output = hidden.stdout + hidden.stderr
    record = {"score": score, "hidden_score": hidden_score, "evidence": evidence,
              "public_score": 10 if public_code == 0 else 0,
              "code_score": code_score, "documentation_score": docs_score,
              "critical_pass": public_code == 0 and hidden.returncode == 0,
              "hidden_output": hidden_output}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    (output_path.parent / "hidden-tests.txt").write_text(hidden_output)
    output_path.write_text(json.dumps(record, indent=2) + "\n")
    return record
