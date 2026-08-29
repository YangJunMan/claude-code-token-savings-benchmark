import json
from pathlib import Path
import shutil
import subprocess

from .contracts import load_config


def command_version(command):
    path = shutil.which(command)
    if not path:
        return {"path": None, "version": None}
    result = subprocess.run([path, "--version"], text=True, capture_output=True)
    return {"path": path, "version": (result.stdout or result.stderr).strip()}


def run_preflight(root=Path(".")):
    config = load_config(root / "benchmark/config.json")
    headroom = root / ".venv/bin/headroom"
    tools = {
        "claude": command_version("claude"),
        "rtk": command_version("rtk"),
        "headroom": {"path": str(headroom) if headroom.exists() else None,
                     "version": subprocess.run([str(headroom), "--version"], text=True, capture_output=True).stdout.strip() if headroom.exists() else None},
    }
    errors = [name for name, info in tools.items() if not info["path"]]
    if config.washout_seconds != 4200:
        errors.append("washout_seconds")
    prompt = root / "benchmark/prompts/master.md"
    if not prompt.exists() or "Work entirely in English" not in prompt.read_text():
        errors.append("english_prompt")
    return {"ok": not errors, "errors": errors, "tools": tools,
            "model": config.model, "effort": config.effort,
            "washout_seconds": config.washout_seconds}


def write_environment(path: Path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
