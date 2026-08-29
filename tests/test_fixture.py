import subprocess
import sys
import unittest
from pathlib import Path


class FixtureTests(unittest.TestCase):
    def test_fixture_public_regression_suite_passes(self):
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd="benchmark/fixture", text=True, capture_output=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fixture_contains_code_tests_kubernetes_and_docs(self):
        required = [
            "gpu_platform/admission.py", "gpu_platform/store.py",
            "tests/test_existing_behavior.py", "k8s/deployment.yaml",
            "docs/incident-log.txt", "docs/api-contract.md",
        ]
        for relative in required:
            self.assertTrue((Path("benchmark/fixture") / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
