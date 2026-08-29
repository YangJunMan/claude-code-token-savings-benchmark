from datetime import datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from .contracts import Condition, RunState


class StateStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = root / "state.json"
        self.event_path = root / "events.jsonl"

    def load(self):
        if not self.state_path.exists():
            return None
        return json.loads(self.state_path.read_text())

    def transition(self, condition: Condition, state: RunState, attempt: int, **extra):
        now = datetime.now(timezone.utc)
        record = {
            "condition": condition.value,
            "state": state.value,
            "attempt": attempt,
            "timestamp_utc": now.isoformat(),
            "timestamp_seoul": now.astimezone(ZoneInfo("Asia/Seoul")).isoformat(),
            **extra,
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, self.state_path)
        with self.event_path.open("a") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        return record
