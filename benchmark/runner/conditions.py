from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .contracts import Condition


@dataclass(frozen=True)
class ConditionSpec:
    condition: Condition
    optimizer: str
    environment: Dict[str, str] = field(default_factory=dict)
    prefix: List[str] = field(default_factory=list)
    mode_command: str = ""
    prompt_overlay: str = ""
    load_caveman: bool = False
    activate_caveman: bool = False
    headroom_mode: Optional[str] = None
    rtk_hook: bool = False


REPO_ROOT = Path(__file__).resolve().parents[2]


def brief_overlay():
    """Resolve from the repository root so any working directory works."""
    return (REPO_ROOT / "benchmark/prompts/be-brief.txt").read_text()


def build_condition(condition: Condition, worktree: Path):
    """Return the single treatment applied on top of the untreated baseline.

    ``BASE`` is plain Claude Code: no proxy, no plugin, no hook.  Every treatment
    differs from it in exactly one way, so no comparison mixes two changes.
    """
    if condition is Condition.BASE:
        return ConditionSpec(condition, "none", mode_command="baseline")
    if condition is Condition.H_ON:
        # The control is a no-proxy run.  `headroom proxy --no-optimize` is not a
        # passthrough: its request log shows it still applies tool-schema
        # compaction and tool-search deferral, saving within ~2% of the optimized
        # arm, so it cannot serve as the "off" condition.
        return ConditionSpec(condition, "headroom", mode_command="optimized",
                             headroom_mode="cache")
    if condition is Condition.C_FULL:
        return ConditionSpec(condition, "caveman", mode_command="full",
                             load_caveman=True, activate_caveman=True)
    if condition is Condition.C_BRIEF:
        # This arm asks whether a plain brevity instruction removes the need for
        # the plugin, so it deliberately loads no plugin.
        return ConditionSpec(condition, "brief", mode_command="brief",
                             prompt_overlay=brief_overlay())
    if condition is Condition.R_ON:
        return ConditionSpec(condition, "rtk", mode_command="on", rtk_hook=True)
    raise ValueError(f"unhandled condition: {condition}")
