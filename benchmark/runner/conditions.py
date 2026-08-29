from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

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


def brief_overlay():
    return Path("benchmark/prompts/be-brief.txt").read_text()


def build_condition(condition: Condition, worktree: Path):
    if condition in (Condition.H_ON, Condition.H_OFF):
        return ConditionSpec(condition, "headroom", mode_command="optimized" if condition is Condition.H_ON else "passthrough")
    if condition in (Condition.C_FULL, Condition.C_NON, Condition.C_BRIEF):
        mode = "full" if condition is Condition.C_FULL else "off"
        overlay = brief_overlay() if condition is Condition.C_BRIEF else ""
        return ConditionSpec(condition, "caveman", mode_command=mode, prompt_overlay=overlay,
                             load_caveman=condition is Condition.C_FULL)
    return ConditionSpec(condition, "rtk", mode_command="on" if condition is Condition.R_ON else "off")
