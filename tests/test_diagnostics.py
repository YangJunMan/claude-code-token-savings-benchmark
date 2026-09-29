"""진단 모듈의 LLM 호출을 제외한 부분 — digest 압축, 자격증명 없을 때의 동작,
manifest 갱신."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from token_bench import diagnostics


def _logged_in(monkey_ok=True):
    """claude CLI가 설치돼 있고 로그인된 상태를 흉내낸다."""

    return (
        mock.patch.object(diagnostics.claude_code, "is_installed", return_value=True),
        mock.patch.object(
            diagnostics.claude_code,
            "get_auth_status",
            return_value=diagnostics.claude_code.AuthStatus(
                logged_in=monkey_ok, auth_method="oauth_token",
                api_provider="firstParty", subscription_type=None,
            ),
        ),
    )


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
    def test_no_login_skips_without_raising(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2)
            with mock.patch.object(diagnostics.claude_code, "is_installed", return_value=False):
                self.assertIsNone(diagnostics.diagnose(log))

    def test_cli_failure_does_not_propagate(self):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2)
            installed, auth = _logged_in()
            with installed, auth, mock.patch.object(
                diagnostics, "_ask", side_effect=RuntimeError("boom")
            ):
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


class ModelFallbackTest(unittest.TestCase):
    """첫 alias가 막히면 선호 순서의 다음 alias로 한 번 더 시도한다."""

    def _run(self, side_effect):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2)
            installed, auth = _logged_in()
            asked = []

            def fake_ask(model, prompt):
                asked.append(model)
                result = side_effect(model)
                if isinstance(result, Exception):
                    raise result
                return result

            with installed, auth, mock.patch.object(diagnostics, "_ask", fake_ask):
                return diagnostics.diagnose(log), asked

    def test_falls_back_to_the_next_family(self):
        ok = json.dumps({"summary": "s", "events": [{"turn": 1, "kind": "other", "summary": "e"}]})
        report, asked = self._run(
            lambda model: RuntimeError("model not found") if model == "haiku" else ok
        )
        self.assertEqual(report["events"][0]["turn"], 1)
        self.assertEqual(asked, ["haiku", "sonnet"])

    def test_every_family_failing_returns_none(self):
        report, asked = self._run(lambda model: RuntimeError("gone"))
        self.assertIsNone(report)
        self.assertEqual(asked, list(diagnostics.MODEL_PREFERENCE))


class ResponseShapeTest(unittest.TestCase):
    def _run(self, text):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "stdout.jsonl"
            _transcript(log, 2)
            installed, auth = _logged_in()
            with installed, auth, mock.patch.object(diagnostics, "_ask", return_value=text):
                return diagnostics.diagnose(log)

    def test_fenced_json_is_parsed(self):
        report = self._run('```json\n{"summary": "s", "events": '
                           '[{"turn": 3, "kind": "other", "summary": "e"}]}\n```')
        self.assertEqual(report["events"][0]["turn"], 3)

    def test_no_events_means_no_manifest_entry(self):
        self.assertIsNone(self._run('{"summary": "특이사항 없음", "events": []}'))

    def test_non_json_output_is_kept_as_one_event(self):
        report = self._run("JSON을 안 내고 이렇게 답했다")
        self.assertEqual(report["events"][0]["kind"], "other")
        self.assertIn("이렇게 답했다", report["events"][0]["summary"])


class CommandTest(unittest.TestCase):
    def test_prompt_goes_through_stdin_with_safe_mode(self):
        """`--allowed-tools` 같은 variadic 옵션 뒤에 인자로 붙이면 삼켜진다."""
        completed = mock.Mock(stdout='{"summary":"s","events":[]}')
        with mock.patch.object(diagnostics.subprocess, "run", return_value=completed) as run:
            diagnostics._ask("haiku", "프롬프트 본문")
        args, kwargs = run.call_args
        self.assertEqual(args[0][:2], [diagnostics.CLAUDE_BIN, "-p"])
        self.assertIn("--safe-mode", args[0])
        self.assertIn("--model", args[0])
        self.assertIn("프롬프트 본문", kwargs["input"])
        self.assertTrue(kwargs["check"])
        self.assertEqual(kwargs["errors"], "replace")


if __name__ == "__main__":
    unittest.main()
