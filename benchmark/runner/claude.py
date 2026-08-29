import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import time
import uuid

from .conditions import build_condition
from .artifacts import archive_transcript, clear_succeeded, write_manifest


def _caveman_plugin_dir():
    roots = sorted((Path.home() / ".claude/plugins/cache/caveman/caveman").glob("*/plugins/caveman"))
    if not roots:
        raise RuntimeError("Pinned Caveman plugin directory not found")
    return roots[-1]


def _start_headroom(root: Path, optimized: bool, log_path: Path, port=8787):
    command = [str(root / ".venv/bin/headroom"), "proxy", "--port", str(port), "--mode", "token",
               "--no-cache", "--no-subscription-tracking", "--log-file", str(log_path)]
    if not optimized:
        command.append("--no-optimize")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(60):
        probe = subprocess.run(["curl", "-fsS", f"http://127.0.0.1:{port}/readyz"], capture_output=True)
        if probe.returncode == 0:
            return process
        if process.poll() is not None:
            break
        time.sleep(1)
    output = process.stdout.read() if process.stdout else ""
    raise RuntimeError(f"Headroom proxy did not become ready: {output[-1000:]}")


def prepare_worktree(fixture: Path, destination: Path):
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(fixture, destination)
    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
    subprocess.run(["git", "add", "."], cwd=destination, check=True)
    subprocess.run(["git", "-c", "user.name=Benchmark", "-c", "user.email=benchmark@invalid", "commit", "-qm", "fixture"], cwd=destination, check=True)


def clear_session(session_id: str, cwd: Path, output_path: Path, timeout=20):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execvp("claude", ["claude", "--resume", session_id])
    transcript = bytearray()
    deadline = time.time() + timeout
    sent_clear = False
    sent_exit = False
    while time.time() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.5)
        if readable:
            try:
                transcript.extend(os.read(fd, 65536))
            except OSError:
                break
        if not sent_clear and time.time() > deadline - timeout + 2:
            os.write(fd, b"/clear\r")
            sent_clear = True
        elif sent_clear and not sent_exit and time.time() > deadline - timeout + 6:
            os.write(fd, b"/exit\r")
            sent_exit = True
    output_path.write_bytes(bytes(transcript))
    return sent_clear and clear_succeeded(bytes(transcript))


def run_attempt(root: Path, condition, attempt_dir: Path, *, max_turns=28,
                api_mode=False, nonce=None, port=8787):
    spec = build_condition(condition, attempt_dir / "worktree")
    worktree = attempt_dir / "worktree"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    prepare_worktree(root / "benchmark/fixture", worktree)
    prompt = (root / "benchmark/prompts/master.md").read_text()
    if spec.load_caveman:
        prompt = "Use the caveman skill in full mode for the entire task.\n\n" + prompt
    prompt += "\n" + spec.prompt_overlay
    (attempt_dir / "effective-prompt.md").write_text(prompt)
    if condition.value == "R-ON":
        settings = worktree / ".claude/settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"hooks": {"PreToolUse": [{
            "matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]
        }]}}, indent=2) + "\n")
    session_id = str(uuid.uuid4())
    command = ["claude", "-p", "--model", "claude-sonnet-5", "--effort", "medium",
               "--max-turns", str(max_turns), "--output-format", "json", "--permission-mode", "bypassPermissions",
               "--session-id", session_id, "--setting-sources", "project"]
    if nonce:
        command.extend(["--append-system-prompt", f"Benchmark isolation nonce: {nonce}"])
    if spec.load_caveman:
        command.extend(["--plugin-dir", str(_caveman_plugin_dir())])
    environment = os.environ.copy()
    environment.pop("ANTHROPIC_BASE_URL", None)
    if api_mode:
        if not environment.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("API mode requires ANTHROPIC_API_KEY; refusing OAuth fallback")
        environment["DISABLE_PROMPT_CACHING"] = "1"
    proxy = None
    if condition.value in ("H-ON", "H-OFF"):
        proxy = _start_headroom(root, condition.value == "H-ON", attempt_dir / "optimizer.jsonl", port=port)
        environment["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
        environment["ENABLE_TOOL_SEARCH"] = "true"
    started = time.time()
    try:
        result = subprocess.run(command, cwd=worktree, env=environment, input=prompt,
                                text=True, capture_output=True)
    finally:
        if proxy:
            proxy.terminate()
            try:
                proxy.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proxy.kill()
    (attempt_dir / "stdout.json").write_text(result.stdout)
    (attempt_dir / "stderr.log").write_text(result.stderr)
    parsed = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {"raw": result.stdout}
    parsed.update({"condition": condition.value, "session_id": session_id, "returncode": result.returncode,
                   "api_mode": api_mode, "max_turns": max_turns, "nonce": nonce,
                   "started_epoch": started, "last_request_epoch": time.time()})
    parsed["final_text"] = parsed.get("result", "")
    with (attempt_dir / "git.diff").open("w") as diff_stream:
        subprocess.run(["git", "diff", "--binary"], cwd=worktree, text=True, stdout=diff_stream)
    tests = subprocess.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=worktree, text=True, capture_output=True)
    (attempt_dir / "public-tests.txt").write_text(tests.stdout + tests.stderr)
    parsed["public_returncode"] = tests.returncode
    parsed["changed_files"] = subprocess.run(
        ["git", "diff", "--name-only"], cwd=worktree, text=True, capture_output=True
    ).stdout.splitlines()
    parsed["clear_succeeded"] = clear_session(session_id, worktree, attempt_dir / "clear.log")
    transcript_summary = archive_transcript(session_id, attempt_dir / "transcript.jsonl")
    parsed["transcript_summary"] = transcript_summary
    write_manifest(root, condition, attempt_dir, parsed, transcript_summary)
    (attempt_dir / "result.json").write_text(json.dumps(parsed, indent=2, sort_keys=True) + "\n")
    return parsed
