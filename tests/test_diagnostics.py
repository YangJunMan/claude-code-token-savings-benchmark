"""진단 모듈의 LLM 호출을 제외한 부분 — digest 압축, 자격증명 없을 때의 동작,
manifest 갱신."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from token_bench import diagnostics


class _NotFound(Exception):
    """SDK의 NotFoundError 자리에 끼우는 대역."""


def _transcript(path: Path, turns: int) -> None:
    lines = []
    for i in range(turns):
        lines.append(json.dumps({
            "type": "assistant",
            "message": {
                "id": f"msg_{i}",
                "usage": {"input_tokens": 1},
                "content": [{"type": "tool_use", "id": f"t{i}", "name": "Bash",
                             "input": {"command": f"pytest tests/test_{i}.py"}}],
            },
        }))
        lines.append(json.dumps({
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}",
                                     "content": "FAILED (errors=1)"}]},
        }))
    path.write_text("\n".join(lines), encoding="utf-8")


class DigestTest(unittest.TestCase):
    def test_turns_become_one_line_each(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 3)
            lines = diagnostics._digest(log).splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn("pytest tests/test_0.py", lines[0])
            self.assertIn("FAILED (errors=1)", lines[0])

    def test_oversized_digest_keeps_both_ends(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2000)
            digest = diagnostics._digest(log)
            self.assertLessEqual(len(digest), diagnostics.MAX_DIGEST_CHARS + 32)
            self.assertIn("turn 1 Bash", digest)
            self.assertIn("turn 2000 Bash", digest)

    def test_missing_transcript_is_empty(self):
        self.assertEqual(diagnostics._digest("/nonexistent/stdout.jsonl"), "")


class DiagnoseTest(unittest.TestCase):
    def test_no_credentials_skips_without_raising(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2)
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertIsNone(diagnostics.diagnose(log))

    def test_api_failure_does_not_propagate(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2)
            fake = mock.MagicMock()
            fake.NotFoundError = _NotFound
            fake.Anthropic.return_value.messages.create.side_effect = RuntimeError("429")
            with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}), \
                    mock.patch.dict("sys.modules", {"anthropic": fake}):
                self.assertIsNone(diagnostics.diagnose(log))


class ManifestTest(unittest.TestCase):
    def test_report_is_written_and_cleared(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2)
            manifest = Path(tmp) / "run-diagnostics.json"

            report = {"summary": "s", "events": [{"turn": 1, "kind": "other", "summary": "e"}]}
            with mock.patch.object(diagnostics, "diagnose", return_value=report):
                diagnostics.update_manifest("r1", log, manifest)
            self.assertEqual(json.loads(manifest.read_text())["r1"], report)

            # 특이사항이 없어진 실행은 항목이 남지 않는다.
            with mock.patch.object(diagnostics, "diagnose", return_value=None):
                diagnostics.update_manifest("r1", log, manifest)
            self.assertEqual(json.loads(manifest.read_text()), {})


if __name__ == "__main__":
    unittest.main()


class ModelFallbackTest(unittest.TestCase):
    """기본 모델이 은퇴했을 때 남아 있는 싼 계열로 갈아탄다."""

    def _sdk(self, *, available, first_error):
        fake = mock.MagicMock()
        fake.NotFoundError = _NotFound
        client = fake.Anthropic.return_value
        client.models.list.return_value = [mock.Mock(id=mid) for mid in available]
        ok = mock.Mock(content=[mock.Mock(type="text", text=json.dumps(
            {"summary": "s", "events": [{"turn": 1, "kind": "other", "summary": "e"}]}))])
        client.messages.create.side_effect = [first_error, ok]
        return fake, client

    def test_retired_model_falls_back_to_listed_model(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2)
            fake, client = self._sdk(
                available=["claude-opus-9", "claude-haiku-6-0", "claude-sonnet-9"],
                first_error=_NotFound("model not found"),
            )
            with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}), \
                    mock.patch.dict("sys.modules", {"anthropic": fake}):
                report = diagnostics.diagnose(log)
            self.assertEqual(report["events"][0]["turn"], 1)
            # haiku가 sonnet보다 먼저 선택된다.
            self.assertEqual(
                client.messages.create.call_args_list[1].kwargs["model"], "claude-haiku-6-0")

    def test_no_cheap_family_left_returns_none(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2)
            fake, _ = self._sdk(available=["claude-opus-9"], first_error=_NotFound("gone"))
            with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}), \
                    mock.patch.dict("sys.modules", {"anthropic": fake}):
                self.assertIsNone(diagnostics.diagnose(log))



class ResponseShapeTest(unittest.TestCase):
    def _run(self, text):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2)
            fake = mock.MagicMock()
            fake.NotFoundError = _NotFound
            fake.Anthropic.return_value.messages.create.return_value = mock.Mock(
                content=[mock.Mock(type="text", text=text)])
            with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}), \
                    mock.patch.dict("sys.modules", {"anthropic": fake}):
                return diagnostics.diagnose(log)

    def test_fenced_json_is_parsed(self):
        report = self._run('```json\n{"summary": "s", "events": '
                           '[{"turn": 3, "kind": "other", "summary": "e"}]}\n```')
        self.assertEqual(report["events"][0]["turn"], 3)

    def test_no_events_means_no_manifest_entry(self):
        self.assertIsNone(self._run('{"summary": "특이사항 없음", "events": []}'))


class NewestModelTest(unittest.TestCase):
    def test_created_at_decides_not_id_sort(self):
        client = mock.MagicMock()
        client.models.list.return_value = [
            mock.Mock(id="claude-haiku-4-5", created_at="2025-10-01"),
            mock.Mock(id="claude-haiku-10-0", created_at="2027-01-01"),
        ]
        self.assertEqual(diagnostics._cheapest_available(client), "claude-haiku-10-0")
