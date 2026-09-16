import sys
import textwrap
from pathlib import Path

from token_bench.evaluation import check


def _write_fixture_tests(fixture_dir: Path, *, passing: bool) -> None:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "__init__.py").write_text("", encoding="utf-8")
    body = "True" if passing else "False"
    (fixture_dir / "test_sample.py").write_text(
        textwrap.dedent(
            f"""
            import unittest

            class SampleTests(unittest.TestCase):
                def test_something(self):
                    self.assertTrue({body})
            """
        ),
        encoding="utf-8",
    )


def _copy_tests_into_workdir(fixture_dir: Path, workdir: Path) -> None:
    workdir_tests = workdir / "tests"
    workdir_tests.mkdir(parents=True, exist_ok=True)
    for path in fixture_dir.iterdir():
        (workdir_tests / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def test_passing_unmodified_tests_report_passed(tmp_path):
    fixture_dir = tmp_path / "fixture_tests"
    workdir = tmp_path / "workdir"
    _write_fixture_tests(fixture_dir, passing=True)
    _copy_tests_into_workdir(fixture_dir, workdir)

    report = check(workdir, fixture_tests_dir=fixture_dir, python_bin=sys.executable)

    assert report.ran is True
    assert report.passed is True
    assert report.returncode == 0
    assert report.missing_files == ()
    assert report.tampered_files == ()
    assert "test_sample.py" in report.checked_test_files


def test_failing_unmodified_tests_report_not_passed(tmp_path):
    fixture_dir = tmp_path / "fixture_tests"
    workdir = tmp_path / "workdir"
    _write_fixture_tests(fixture_dir, passing=False)
    _copy_tests_into_workdir(fixture_dir, workdir)

    report = check(workdir, fixture_tests_dir=fixture_dir, python_bin=sys.executable)

    assert report.ran is True
    assert report.passed is False
    assert report.returncode != 0
    assert report.missing_files == ()
    assert report.tampered_files == ()


def test_missing_test_file_is_never_a_valid_pass(tmp_path):
    fixture_dir = tmp_path / "fixture_tests"
    workdir = tmp_path / "workdir"
    _write_fixture_tests(fixture_dir, passing=True)
    workdir_tests = workdir / "tests"
    workdir_tests.mkdir(parents=True)
    (workdir_tests / "__init__.py").write_text("", encoding="utf-8")
    # test_sample.py는 일부러 복사하지 않는다(모델이 삭제한 상황을 흉내낸다).

    report = check(workdir, fixture_tests_dir=fixture_dir, python_bin=sys.executable)

    assert "test_sample.py" in report.missing_files
    assert report.passed is False


def test_tampered_test_file_is_never_a_valid_pass(tmp_path):
    fixture_dir = tmp_path / "fixture_tests"
    workdir = tmp_path / "workdir"
    _write_fixture_tests(fixture_dir, passing=True)
    _copy_tests_into_workdir(fixture_dir, workdir)

    # 모델이 원본 테스트 내용을 바꿔서 항상 통과하게 만든 상황을 흉내낸다.
    tampered = (workdir / "tests" / "test_sample.py").read_text(encoding="utf-8")
    tampered = tampered.replace("assertTrue(True)", "assertTrue(True)  # tampered")
    (workdir / "tests" / "test_sample.py").write_text(tampered, encoding="utf-8")

    report = check(workdir, fixture_tests_dir=fixture_dir, python_bin=sys.executable)

    assert "test_sample.py" in report.tampered_files
    assert report.passed is False


def test_timeout_is_reported_and_not_a_pass(tmp_path):
    fixture_dir = tmp_path / "fixture_tests"
    workdir = tmp_path / "workdir"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "__init__.py").write_text("", encoding="utf-8")
    (fixture_dir / "test_slow.py").write_text(
        textwrap.dedent(
            """
            import time
            import unittest

            class SlowTests(unittest.TestCase):
                def test_sleep(self):
                    time.sleep(30)
            """
        ),
        encoding="utf-8",
    )
    _copy_tests_into_workdir(fixture_dir, workdir)

    report = check(
        workdir, fixture_tests_dir=fixture_dir, timeout_seconds=1, python_bin=sys.executable
    )

    assert report.timed_out is True
    assert report.passed is False


def test_original_repository_fixture_tests_are_discoverable():
    """실제 저장소의 benchmark/fixture/tests가 그대로 통과하는지 통합 검증한다."""
    repo_root = Path(__file__).resolve().parents[1]
    fixture_dir = repo_root / "benchmark" / "fixture" / "tests"
    workdir = repo_root / "benchmark" / "fixture"

    report = check(workdir, fixture_tests_dir=fixture_dir, python_bin=sys.executable)

    assert report.ran is True
    assert report.missing_files == ()
    assert report.tampered_files == ()
    assert report.passed is True
