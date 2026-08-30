import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def clear_succeeded(transcript: bytes) -> bool:
    """Return whether the resumed session actually confirmed the /clear.

    Only terminal evidence counts.  Reporting "the runner wrote /clear to the pty"
    as success made this column unfalsifiable.
    """
    return b"/clear" in transcript and b"Resume this session with:" in transcript


def find_transcript(session_id: str, claude_root=None):
    root = Path(claude_root) if claude_root else Path.home() / ".claude" / "projects"
    matches = list(root.glob(f"*/{session_id}.jsonl"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one Claude transcript for {session_id}, found {len(matches)}")
    return matches[0]


def archive_transcript(session_id: str, output_path: Path, claude_root=None):
    source = find_transcript(session_id, claude_root)
    shutil.copy2(source, output_path)
    return summarize_transcript(output_path)


def summarize_transcript(path: Path):
    messages = {}
    tool_ids = set()
    final_text = ""
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") != "assistant":
            continue
        message = row.get("message", {})
        message_id = message.get("id")
        if message_id and message_id not in messages:
            messages[message_id] = message.get("usage", {})
        for block in message.get("content", []):
            if block.get("type") == "tool_use":
                tool_ids.add(block.get("id") or json.dumps(block, sort_keys=True))
            elif block.get("type") == "text":
                final_text = block.get("text", "")
    first_usage = next(iter(messages.values()), {})
    return {
        "turns": len(messages),
        "tool_calls": len(tool_ids),
        "first_turn_cache_read_tokens": int(first_usage.get("cache_read_input_tokens", 0) or 0),
        "first_turn_cache_creation_tokens": int(first_usage.get("cache_creation_input_tokens", 0) or 0),
        "final_response_chars": len(final_text),
    }


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def changed_lines(worktree: Path):
    result = subprocess.run(
        ["git", "diff", "--numstat", "HEAD"], cwd=worktree, text=True,
        capture_output=True, check=True,
    )
    added = deleted = 0
    by_class = {"code": 0, "tests": 0, "kubernetes_ci": 0, "documentation": 0, "other": 0}
    for line in result.stdout.splitlines():
        add, remove, relative = line.split("\t", 2)
        if not add.isdigit() or not remove.isdigit():
            continue
        count = int(add) + int(remove)
        added += int(add)
        deleted += int(remove)
        if relative.startswith("tests/"):
            category = "tests"
        elif relative.startswith("gpu_platform/") and relative.endswith(".py"):
            category = "code"
        elif relative.startswith("k8s/") or relative.startswith(".github/"):
            category = "kubernetes_ci"
        elif relative.startswith("docs/") or relative.lower().endswith((".md", ".txt")):
            category = "documentation"
        else:
            category = "other"
        by_class[category] += count
    return {"added": added, "deleted": deleted, "changed": added + deleted, "by_class": by_class}


def write_manifest(root: Path, condition, attempt_dir: Path, result: dict, transcript_summary: dict):
    prompt_path = attempt_dir / "effective-prompt.md"
    fixture_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=attempt_dir / "worktree",
        text=True, capture_output=True, check=True,
    ).stdout.strip()
    record = {
        "condition": condition.value,
        "model": "claude-sonnet-5",
        "effort": "medium",
        "max_turns": int(result.get("max_turns", 28)),
        "execution_mode": "api" if result.get("api_mode") else "claude.ai",
        "disable_prompt_caching": bool(result.get("disable_prompt_caching", False)),
        "session_id": result["session_id"],
        "nonce": result.get("nonce"),
        "fixture_commit": fixture_commit,
        "base_prompt_sha256": sha256(root / "benchmark/prompts/master.md"),
        "effective_prompt_sha256": sha256(prompt_path),
        "transcript": transcript_summary,
        "changed_lines": changed_lines(attempt_dir / "worktree"),
    }
    (attempt_dir / "manifest.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record
