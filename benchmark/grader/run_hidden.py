"""Run the hidden suite and report outcomes as JSON, immune to stdout pollution.

Parsing unittest's verbose text is not safe here: an implementation that writes
structured logs to stdout interleaves them with the ``... ok`` markers, which
silently scored a passing run as zero.  The outcome is written to a file instead,
and the tests' own stdout is redirected away from it.
"""
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes[test.id()] = "ok"

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes[test.id()] = "fail"

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes[test.id()] = "error"

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes[test.id()] = "skip"


def main():
    hidden_root, output_path = sys.argv[1], sys.argv[2]
    suite = unittest.defaultTestLoader.discover(start_dir=hidden_root)
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordingResult)
    with contextlib.redirect_stdout(io.StringIO()) as captured:
        result = runner.run(suite)
    Path(output_path).write_text(json.dumps({
        "outcomes": result.outcomes,
        "total": result.testsRun,
        "log": stream.getvalue(),
        "stdout": captured.getvalue()[:20000],
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
