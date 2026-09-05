import glob
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from .conditions import build_condition
from .artifacts import archive_transcript, write_manifest


def resolve_plugin_dir(settings):
    """Resolve a declared plugin directory, honouring its environment override."""
    override = os.environ.get(settings.get("env_override", ""))
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
        raise RuntimeError(f"{settings['env_override']} is not a directory: {candidate}")
    pattern = str(Path(settings["path_glob"]).expanduser())
    roots = sorted(Path(match) for match in glob.glob(pattern))
    if not roots:
        raise RuntimeError(f"Pinned plugin directory not found: {settings['path_glob']}")
    return roots[-1]


def resolve_proxy_binary(root: Path, settings):
    """Find a declared proxy executable: override, then PATH, then the venv."""
    name = settings["binary"]
    override = os.environ.get(settings.get("env_override", ""))
    candidates = [Path(override)] if override else []
    discovered = shutil.which(name)
    if discovered:
        candidates.append(Path(discovered))
    candidates.append(root / ".venv/bin" / name)
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError(
        f"{name} executable not found; set {settings.get('env_override')} or install {name}"
    )


def build_proxy_command(binary: Path, settings, log_path: Path, port=8787):
    """Fill the declared argument template.  Nothing here names a specific tool."""
    substitutions = {"port": str(port), "log_path": str(log_path), "binary": str(binary)}
    return [str(binary)] + [
        argument.format(**substitutions) for argument in settings["args"]
    ]


def _start_proxy(root: Path, settings, log_path: Path, port=8787):
    binary = resolve_proxy_binary(root, settings)
    command = build_proxy_command(binary, settings, log_path, port)
    ready_url = f"http://127.0.0.1:{port}{settings.get('ready_path', '/readyz')}"
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(60):
        probe = subprocess.run(["curl", "-fsS", ready_url], capture_output=True)
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
    raise RuntimeError(f"{settings['binary']} proxy did not become ready: {output[-1000:]}")


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
    if spec.prompt_prefix:
        prompt = spec.prompt_prefix + prompt
    prompt += "\n" + spec.prompt_overlay
    (attempt_dir / "effective-prompt.md").write_text(prompt)
    if spec.hook:
        settings_path = worktree / ".claude/settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps({"hooks": {spec.hook.get("event", "PreToolUse"): [{
            "matcher": spec.hook["matcher"],
            "hooks": [{"type": "command", "command": spec.hook["command"]}]
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
    if spec.plugin:
        command.extend(["--plugin-dir", str(resolve_plugin_dir(spec.plugin))])
    environment = os.environ.copy()
    environment.pop("ANTHROPIC_BASE_URL", None)
    if api_mode:
        environment = configure_api_environment(
            environment, disable_prompt_caching=disable_prompt_caching
        )
    proxy = None
    if spec.proxy:
        proxy = _start_proxy(root, spec.proxy, attempt_dir / "optimizer.jsonl", port=port)
        environment["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
        environment.update(spec.proxy.get("env", {}))
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
