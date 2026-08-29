import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark.runner.checksums import build_manifest


class ChecksumTests(unittest.TestCase):
    def test_manifest_excludes_its_output_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload.txt"
            output = root / "checksums.sha256"
            payload.write_text("payload\n")
            output.write_text("stale\n")
            manifest = build_manifest((root,), exclude=(output,))
            self.assertIn(str(payload), manifest)
            self.assertNotIn(str(output), manifest)


if __name__ == "__main__":
    unittest.main()
