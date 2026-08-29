from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import List


class Condition(Enum):
    H_ON = "H-ON"
    H_OFF = "H-OFF"
    C_FULL = "C-FULL"
    C_NON = "C-NON"
    C_BRIEF = "C-BRIEF"
    R_ON = "R-ON"
    R_OFF = "R-OFF"


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


def load_config(path: Path) -> BenchmarkConfig:
    raw = json.loads(path.read_text())
    raw["conditions"] = [Condition(value) for value in raw["conditions"]]
    return BenchmarkConfig(**raw)
