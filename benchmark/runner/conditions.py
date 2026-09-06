from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from .contracts import Condition, load_conditions


@dataclass(frozen=True)
class ConditionSpec:
    """The single treatment applied on top of the untreated baseline.

    One field per activation mechanism, so a new optimizer reuses whichever one
    it needs instead of adding another tool-specific flag.
    """

    condition: Condition
    optimizer: str
    prompt_overlay: str = ""
    prompt_prefix: str = ""
    proxy: Optional[dict] = None
    plugin: Optional[dict] = None
    hook: Optional[dict] = None


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "benchmark/config.json"


def conditions():
    """Resolve from the repository root so any working directory works."""
    return load_conditions(CONFIG_PATH)


def condition(identifier):
    return conditions()[identifier]


def brief_overlay():
    return overlay_text(condition("C-BRIEF"))


def overlay_text(condition):
    return (REPO_ROOT / condition.settings["file"]).read_text()


def build_condition(condition: Condition, worktree: Path):
    """Return the treatment declared for this condition.

    ``BASE`` is plain Claude Code: no proxy, no plugin, no hook.  Every treatment
    differs from it in exactly one way, so no comparison mixes two changes.  The
    mechanism decides which single field is populated, which is what keeps that
    guarantee mechanical rather than a matter of review.
    """
    spec = ConditionSpec(condition, condition.optimizer)
    settings = condition.settings
    if condition.mechanism == "none":
        return spec
    if condition.mechanism == "proxy":
        # The control is a no-proxy run.  `headroom proxy --no-optimize` is not a
        # passthrough: its request log shows it still applies tool-schema
        # compaction and tool-search deferral, saving within ~2% of the optimized
        # arm, so it cannot serve as the "off" condition.
        return replace(spec, proxy=settings)
    if condition.mechanism == "plugin":
        return replace(spec, plugin=settings,
                             prompt_prefix=settings.get("prompt_prefix", ""))
    if condition.mechanism == "overlay":
        # This arm asks whether a plain brevity instruction removes the need for
        # the plugin, so it deliberately loads no plugin.
        return replace(spec, prompt_overlay=overlay_text(condition))
    if condition.mechanism == "hook":
        return replace(spec, hook=settings)
    raise ValueError(f"unhandled mechanism: {condition.mechanism}")
