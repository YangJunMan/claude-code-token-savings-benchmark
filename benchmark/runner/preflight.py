import json
from pathlib import Path
import shutil
import subprocess

from .claude import resolve_plugin_dir, resolve_proxy_binary
from .contracts import load_config


def command_version(command):
    path = shutil.which(command)
    if not path:
        return {"path": None, "version": None}
    result = subprocess.run([path, "--version"], text=True, capture_output=True)
    return {"path": path, "version": (result.stdout or result.stderr).strip()}


def optimizer_tools(root: Path, conditions):
    """Report the tool each declared condition needs, without naming any of them.

    ``requires`` is what the user would have to install, which is not always the
    optimizer's label: a hook declares an arbitrary command line.  Diagnostics
    quote it so "missing" points at something installable.
    """
    tools = {}
    for condition in conditions:
        settings = condition.settings
        requires = condition.optimizer
        try:
            if condition.mechanism == "proxy":
                requires = settings["binary"]
                binary = resolve_proxy_binary(root, settings)
                info = {
                    "path": str(binary),
                    "version": subprocess.run([str(binary), "--version"], text=True,
                                              capture_output=True).stdout.strip(),
                }
            elif condition.mechanism == "plugin":
                info = {"path": str(resolve_plugin_dir(settings)), "version": None}
            elif condition.mechanism == "hook":
                requires = settings["command"].split()[0]
                info = command_version(requires)
            else:
                continue
        except RuntimeError:
            info = {"path": None, "version": None}
        tools[condition.optimizer] = dict(info, requires=requires)
    return tools


def run_preflight(root=Path(".")):
    config = load_config(root / "benchmark/config.json")
    tools = {"claude": command_version("claude")}
    tools.update(optimizer_tools(root, config.conditions))
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
