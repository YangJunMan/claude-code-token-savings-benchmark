from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Dict, List


# Every optimizer activates in one of these ways.  A new token-saving skill is
# added by declaring which one it uses, not by editing Python.
MECHANISMS = ("none", "proxy", "plugin", "overlay", "hook")


@dataclass(frozen=True)
class Condition:
    """One untreated baseline plus one arm per optimizer.

    ``H-OFF``, ``C-NON`` and ``R-OFF`` used to be separate controls, but they were
    byte-identical configurations: no proxy, no plugin, no hook, same prompt.
    Running that one cell three times spent budget on three samples of a single
    condition while reporting them as three independent controls.  They are
    collapsed into ``BASE``, and the freed budget pays for repeating ``BASE``,
    which is what makes the run-to-run noise floor measurable.

    ``value`` carries the id because run directories and every recorded
    measurement are keyed by it; renaming the field would orphan past runs.
    """

    value: str
    label: str
    optimizer: str
    mechanism: str
    # Excluded from equality and hashing so the dataclass stays usable as a dict
    # key; ``value`` already identifies a condition uniquely.
    settings: Dict = field(default_factory=dict, compare=False)
    repeat: int = 1


def build_conditions(declarations) -> Dict[str, Condition]:
    conditions = {}
    for declaration in declarations:
        identifier = declaration["id"]
        if identifier in conditions:
            raise ValueError(f"duplicate condition id: {identifier}")
        mechanism = declaration.get("mechanism", "none")
        if mechanism not in MECHANISMS:
            raise ValueError(f"unknown mechanism for {identifier}: {mechanism}")
        conditions[identifier] = Condition(
            value=identifier,
            label=declaration.get("label", identifier),
            optimizer=declaration.get("optimizer", "none"),
            mechanism=mechanism,
            settings=declaration.get(mechanism, {}),
            repeat=int(declaration.get("repeat", 1)),
        )
    return conditions


def load_conditions(path: Path) -> Dict[str, Condition]:
    return build_conditions(json.loads(Path(path).read_text())["conditions"])


class RunState(Enum):
    PENDING = "pending"
    PREFLIGHT = "preflight"
    RUNNING = "running"
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


def load_config(path: Path) -> BenchmarkConfig:
    raw = json.loads(Path(path).read_text())
    raw["conditions"] = list(build_conditions(raw["conditions"]).values())
    return BenchmarkConfig(**raw)


def is_acceptable_result(result):
    """A run is measurable only if Claude finished the task on its own.

    A ``max_turns`` truncation is an invalid attempt: the model never reaches the
    documentation, test-reporting and final-response phase, so its token total
    measures the turn cap rather than the condition.  A run that changed no file
    is invalid too, even on a clean exit - a model that answers with a clarifying
    question and stops has produced a token count for a task it never attempted.

    The first-turn cache read is recorded, not required to be zero.  Every run
    starts from the same fixed Claude Code system prompt and tool definitions, so
    the provider may serve that prefix from cache for whichever run goes second.
    That is shared boilerplate, not another condition's work, and it lands on
    every condition identically.  Cross-run contamination is caught instead by
    ``reports.generate.uniform_first_turn_cache_read``.
    """
    transcript = result.get("transcript_summary") or {}
    first_read = transcript.get("first_turn_cache_read_tokens")
    if first_read is None or int(first_read) < 0:
        return False
    if result.get("terminal_reason", "completed") != "completed":
        return False
    if result.get("returncode") != 0 or result.get("is_error"):
        return False
    if not result.get("changed_files"):
        return False
    return bool((result.get("final_text") or "").strip())
