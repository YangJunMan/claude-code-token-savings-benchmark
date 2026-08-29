import json
import tempfile
import unittest
from pathlib import Path

from benchmark.runner.contracts import Condition, RunState
from benchmark.runner.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_transition_is_persisted_and_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            state = store.transition(Condition.H_ON, RunState.PREFLIGHT, attempt=1)
            self.assertEqual(store.load()["state"], "preflight")
            event = json.loads((Path(directory) / "events.jsonl").read_text().splitlines()[0])
            self.assertEqual(event["condition"], "H-ON")
            self.assertIn("timestamp_utc", event)
            self.assertEqual(state["attempt"], 1)


if __name__ == "__main__":
    unittest.main()
