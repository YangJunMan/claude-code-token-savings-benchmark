from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import List


class Condition(Enum):
    """One untreated baseline plus one arm per optimizer.

    ``H-OFF``, ``C-NON`` and ``R-OFF`` used to be separate controls, but they were
    byte-identical configurations: no proxy, no plugin, no hook, same prompt.
    Running that one cell three times spent budget on three samples of a single
    condition while reporting them as three independent controls.  They are
    collapsed into ``BASE``, and the freed budget pays for repeating ``BASE``,
    which is what makes the run-to-run noise floor measurable.
    """

    BASE = "BASE"
    H_ON = "H-ON"
    C_FULL = "C-FULL"
    C_BRIEF = "C-BRIEF"
    R_ON = "R-ON"


class RunState(Enum):
    PENDING = "pending"
    PREFLIGHT = "preflight"
    RUNNING = "running"
    CLEARING = "clearing"
    WAITING_WASHOUT = "waiting_washout"
    WAITING_CLAUDE_QUOTA = "waiting_claude_quota"
    INVALID_QUOTA_INTERRUPTED = "invalid_quota_interrupted"
    INVALID_CONFIGURATION = "invalid_configuration"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class BenchmarkConfig:
    model: str
    effort: str
    max_turns: int
    washout_seconds: int
    conditions: List[Condition]
    target_input_related_min: int
    target_input_related_max: int
    target_output_min: int
    target_output_max: int
    baseline_attempts: int = 1
    budget_usd: float = 0.0


def load_config(path: Path) -> BenchmarkConfig:
    raw = json.loads(path.read_text())
    raw["conditions"] = [Condition(value) for value in raw["conditions"]]
    return BenchmarkConfig(**raw)
