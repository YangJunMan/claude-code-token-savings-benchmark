import json
import os
from pathlib import Path
import pty
import select
import signal
import shutil
import subprocess
import sys
import time
import uuid

from .conditions import build_condition
from .artifacts import archive_transcript, clear_succeeded, write_manifest


def resolve_caveman_plugin_dir():
    override = os.environ.get("CAVEMAN_PLUGIN_DIR")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
        raise RuntimeError(f"CAVEMAN_PLUGIN_DIR is not a directory: {candidate}")
    roots = sorted((Path.home() / ".claude/plugins/cache/caveman/caveman").glob("*/plugins/caveman"))
    if not roots:
        raise RuntimeError("Pinned Caveman plugin directory not found")
    return roots[-1]


def resolve_headroom_binary(root: Path):
    override = os.environ.get("HEADROOM_BIN")
    candidates = [Path(override)] if override else []
    discovered = shutil.which("headroom")
    if discovered:
        candidates.append(Path(discovered))
    candidates.append(root / ".venv/bin/headroom")
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("Headroom executable not found; set HEADROOM_BIN or install headroom")


def build_headroom_command(binary: Path, optimized: bool, log_path: Path, port=8787):
    command = [str(binary), "proxy", "--port", str(port), "--mode", "cache",
               "--no-cache", "--no-subscription-tracking", "--log-file", str(log_path)]
    if not optimized:
        command.append("--no-optimize")
    return command


def _start_headroom(root: Path, optimized: bool, log_path: Path, port=8787):
    command = build_headroom_command(resolve_headroom_binary(root), optimized, log_path, port)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(60):
        probe = subprocess.run(["curl", "-fsS", f"http://127.0.0.1:{port}/readyz"], capture_output=True)
        if probe.returncode == 0:
            return process
        if process.poll() is not None:
            break
        time.sleep(1)
    process.terminate()
    try:
        output, _ = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate(timeout=5)
    raise RuntimeError(f"Headroom proxy did not become ready: {output[-1000:]}")


# Harness scaffolding and build droppings are not the agent's work, so they stay
# out of the diff, the changed-line counts and the grader's file set.
HARNESS_ONLY_PATHS = (".claude/", "isolation-mcp.json", "__pycache__/", "*.pyc", "*.db")


def prepare_worktree(fixture: Path, destination: Path):
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(fixture, destination)
    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
    exclude = destination / ".git/info/exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("\n".join(HARNESS_ONLY_PATHS) + "\n")
    subprocess.run(["git", "add", "."], cwd=destination, check=True)
    subprocess.run(["git", "-c", "user.name=Benchmark", "-c", "user.email=benchmark@invalid", "commit", "-qm", "fixture"], cwd=destination, check=True)


def stage_intent_to_add(worktree: Path):
    """Make files the agent created visible to git diff without committing them.

    ``git diff`` alone reports nothing for untracked files, so a run that solved
    the task by adding new modules used to be recorded as having changed nothing.
    """
    subprocess.run(["git", "add", "-A", "-N", "."], cwd=worktree, check=True)


def configure_api_environment(environment, *, disable_prompt_caching=True):
    """Prepare an API environment without ever falling back to OAuth."""
    configured = dict(environment)
    if not configured.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("API mode requires ANTHROPIC_API_KEY; refusing OAuth fallback")
    if disable_prompt_caching:
        configured["DISABLE_PROMPT_CACHING"] = "1"
    else:
        configured.pop("DISABLE_PROMPT_CACHING", None)
    return configured


def build_isolation_mcp_config(server_script, nonce):
    """Build a per-condition MCP tool definition to salt the tools prefix."""
    tool_name = "benchmark_sentinel_" + str(nonce).replace("-", "")
    return {
        "mcpServers": {
            "benchmark-isolation": {
                "command": sys.executable,
                "args": [str(server_script), tool_name],
            }
        }
    }


def isolation_mcp_config_path(attempt_dir):
    """Return an absolute config path because Claude runs from the worktree."""
    return Path(attempt_dir).resolve() / "isolation-mcp.json"


def clear_session(session_id: str, cwd: Path, output_path: Path, timeout=20):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execvp("claude", ["claude", "--resume", session_id])
    transcript = bytearray()
    deadline = time.time() + timeout
    write_failed = False
    sent_clear = False
    sent_exit = False
    try:
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
    finally:
        try:
            reaped, _ = os.waitpid(pid, os.WNOHANG)
            if reaped == 0:
                os.kill(pid, signal.SIGTERM)
                for _ in range(10):
                    reaped, _ = os.waitpid(pid, os.WNOHANG)
                    if reaped:
                        break
                    time.sleep(0.1)
                if not reaped:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
        except (ChildProcessError, ProcessLookupError):
            pass
        try:
            os.close(fd)
        except OSError:
            pass
    captured = bytes(transcript)
    output_path.write_bytes(captured)
    return {
        "command_sent": sent_clear,
        "write_failed": write_failed,
        "resume_marker_observed": clear_succeeded(captured),
    }


def run_attempt(root: Path, condition, attempt_dir: Path, *, max_turns=50,
                api_mode=False, nonce=None, port=8787, disable_prompt_caching=True,
                isolation_tools=(), isolation_mcp=False, max_budget_usd=None):
    spec = build_condition(condition, attempt_dir / "worktree")
    worktree = attempt_dir / "worktree"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    prepare_worktree(root / "benchmark/fixture", worktree)
    prompt = (root / "benchmark/prompts/master.md").read_text()
    if "{max_turns}" not in prompt:
        raise RuntimeError("master prompt must declare the turn budget via {max_turns}")
    prompt = prompt.replace("{max_turns}", str(max_turns))
    if spec.activate_caveman:
        prompt = "Use the caveman skill in full mode for the entire task.\n\n" + prompt
    prompt += "\n" + spec.prompt_overlay
    (attempt_dir / "effective-prompt.md").write_text(prompt)
    if spec.rtk_hook:
        settings = worktree / ".claude/settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"hooks": {"PreToolUse": [{
            "matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]
        }]}}, indent=2) + "\n")
    session_id = str(uuid.uuid4())
    command = ["claude", "-p", "--model", "claude-sonnet-5", "--effort", "medium",
               "--max-turns", str(max_turns), "--output-format", "json", "--permission-mode", "bypassPermissions",
               "--session-id", session_id, "--setting-sources", "project"]
    if max_budget_usd is not None:
        command.extend(["--max-budget-usd", str(max_budget_usd)])
    if nonce:
        command.extend(["--append-system-prompt", f"Benchmark isolation nonce: {nonce}"])
    if isolation_tools:
        command.extend(["--disallowedTools", *isolation_tools])
    if isolation_mcp:
        mcp_path = isolation_mcp_config_path(attempt_dir)
        mcp_path.write_text(json.dumps(build_isolation_mcp_config(
            root / "benchmark/runner/isolation_mcp_server.py", nonce
        ), indent=2, sort_keys=True) + "\n")
        command.extend(["--mcp-config", str(mcp_path), "--strict-mcp-config"])
    if spec.load_caveman:
        command.extend(["--plugin-dir", str(resolve_caveman_plugin_dir())])
    environment = os.environ.copy()
    environment.pop("ANTHROPIC_BASE_URL", None)
    if api_mode:
        environment = configure_api_environment(
            environment, disable_prompt_caching=disable_prompt_caching
        )
    proxy = None
    if spec.headroom_mode:
        proxy = _start_headroom(root, True, attempt_dir / "optimizer.jsonl", port=port)
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
                   "api_mode": api_mode, "disable_prompt_caching": bool(api_mode and disable_prompt_caching),
                   "max_turns": max_turns, "nonce": nonce,
                   "started_epoch": started, "last_request_epoch": time.time()})
    parsed["final_text"] = "" if parsed.get("is_error") else parsed.get("result", "")
    parsed["terminal_reason"] = {
        "success": "completed", "error_max_turns": "max_turns",
    }.get(parsed.get("subtype", ""), parsed.get("subtype") or "unknown")
    stage_intent_to_add(worktree)
    with (attempt_dir / "git.diff").open("w") as diff_stream:
        subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=worktree, text=True, stdout=diff_stream)
    tests = subprocess.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=worktree, text=True, capture_output=True)
    (attempt_dir / "public-tests.txt").write_text(tests.stdout + tests.stderr)
    parsed["public_returncode"] = tests.returncode
    parsed["changed_files"] = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"], cwd=worktree, text=True, capture_output=True
    ).stdout.splitlines()
    # Everything from here on is bookkeeping. A completed run has already been paid
    # for, so a failure in housekeeping is recorded, never raised.
    try:
        clear_evidence = clear_session(session_id, worktree, attempt_dir / "clear.log")
    except OSError as error:
        clear_evidence = {"command_sent": False, "write_failed": True,
                          "resume_marker_observed": False, "error": str(error)}
    log_path = attempt_dir / "clear.log"
    parsed["clear_succeeded"] = clear_succeeded(log_path.read_bytes()) if log_path.exists() else False
    parsed["clear_command_sent"] = clear_evidence["command_sent"]
    parsed["clear_resume_marker_observed"] = clear_evidence["resume_marker_observed"]
    try:
        transcript_summary = archive_transcript(session_id, attempt_dir / "transcript.jsonl")
    except RuntimeError as error:
        # Without a transcript the first-turn cache evidence is unknown, which the
        # validity rule treats as unmeasurable rather than silently acceptable.
        transcript_summary = {"turns": parsed.get("num_turns", 0), "tool_calls": 0,
                              "first_turn_cache_read_tokens": -1,
                              "first_turn_cache_creation_tokens": 0,
                              "final_response_chars": len(parsed.get("final_text") or ""),
                              "error": str(error)}
    parsed["transcript_summary"] = transcript_summary
    write_manifest(root, condition, attempt_dir, parsed, transcript_summary)
    (attempt_dir / "result.json").write_text(json.dumps(parsed, indent=2, sort_keys=True) + "\n")
    return parsed
