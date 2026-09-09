import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from benchmark.reports.collect import collect_batch
from benchmark.reports.generate import generate_report
from benchmark.runner.api_parallel import run_reproduction
from benchmark.runner.claude import run_attempt
from benchmark.runner.conditions import condition
from benchmark.runner.public_cli import estimate, main
from tests.test_collect import make_attempt, read, turn


ROOT = Path(__file__).resolve().parents[1]


class CollectionValidityTests(unittest.TestCase):
    def test_missing_cache_evidence_is_rejected_by_both_entrypoints(self):
        from benchmark.reports.generate import _acceptable
        from benchmark.runner.cli import is_acceptable_result

        result = {"returncode": 0, "terminal_reason": "completed",
                  "changed_files": ["a.py"], "final_text": "Done",
                  "transcript_summary": {"first_turn_cache_read_tokens": None}}
        self.assertFalse(is_acceptable_result(result))
        self.assertFalse(_acceptable(result))

    def test_invalid_and_compacted_runs_are_diagnostic_only(self):
        for failure in ('max_turns', 'compaction'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                runs = root / 'batch'
                make_attempt(runs, 'BASE-01', 'BASE')
                make_attempt(runs, 'H-ON-01', 'H-ON')
                attempt = runs / 'H-ON-01/attempt-01'
                if failure == 'max_turns':
                    path = attempt / 'result.json'
                    result = json.loads(path.read_text())
                    result.update(terminal_reason='max_turns', is_error=True)
                    path.write_text(json.dumps(result))
                else:
                    (attempt / 'transcript.jsonl').write_text('\n'.join([
                        turn('m1', 0, 1000, 40), turn('m2', 0, 500, 10),
                    ]))
                collect_batch(runs, root / 'activity.csv', root / 'summary.csv',
                              root / 'comparison.csv')
                self.assertEqual(read(root / 'comparison.csv'), [])
                diagnostics = read(root / 'summary.csv')
                self.assertEqual(len(diagnostics), 2)
                self.assertEqual(diagnostics[1]['measurable'], '0')


class PaidCostTests(unittest.TestCase):
    def test_grader_failure_preserves_cost_and_stops_at_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('benchmark.runner.api_parallel.run_attempt',
                       return_value={'total_cost_usd': 2.4}), patch(
                       'benchmark.runner.api_parallel.grade_attempt',
                       side_effect=TimeoutError('grader timeout')):
                records = run_reproduction(ROOT, root / 'runs', root / 'report', 50, 5)
            self.assertEqual(len(records), 2)
            self.assertEqual([r['cost_usd'] for r in records], [2.4, 2.4])
            saved = json.loads((root / 'report/reproduction-summary.json').read_text())
            self.assertEqual(saved, records)

    def test_unknown_cost_stops_further_paid_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('benchmark.runner.api_parallel.run_attempt',
                       side_effect=RuntimeError('output unavailable')):
                records = run_reproduction(ROOT, root / 'runs', root / 'report', 50, 18)
            self.assertEqual(len(records), 1)
            self.assertIsNone(records[0].get('cost_usd'))

    def test_housekeeping_failure_recovers_cost_from_saved_result(self):
        def fail_after_payment(root, condition, attempt_dir, **kwargs):
            (attempt_dir / 'result.json').write_text(json.dumps({'total_cost_usd': 2.4}))
            raise RuntimeError('git failed')

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('benchmark.runner.api_parallel.run_attempt', side_effect=fail_after_payment):
                records = run_reproduction(ROOT, root / 'runs', root / 'report', 50, 5)
            self.assertEqual([r.get('cost_usd') for r in records], [2.4, 2.4])


class ExecutionConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copytree(ROOT / 'benchmark/fixture', self.root / 'benchmark/fixture')
        shutil.copytree(ROOT / 'benchmark/prompts', self.root / 'benchmark/prompts')
        config = json.loads((ROOT / 'benchmark/config.json').read_text())
        config.update(model='test-model', effort='high', max_turns=17)
        (self.root / 'benchmark/config.json').write_text(json.dumps(config))

    def test_estimate_and_cli_use_config_unless_turns_are_overridden(self):
        with patch('benchmark.runner.public_cli.ROOT', self.root):
            projection = estimate()
            self.assertEqual((projection['model'], projection['effort'],
                              projection['max_turns_per_job']), ('test-model', 'high', 17))
            for argv, expected in ((['estimate'], 17), (['estimate', '--max-turns', '9'], 9)):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(argv), 0)
                self.assertEqual(json.loads(output.getvalue())['max_turns_per_job'], expected)

    def test_command_and_manifest_use_config_and_explicit_turn_override(self):
        real_run = subprocess.run
        commands = []

        def execute(command, **kwargs):
            if command[0] == 'claude':
                commands.append(command)
                return subprocess.CompletedProcess(command, 0, json.dumps({
                    'subtype': 'success', 'result': 'Done', 'total_cost_usd': 1.2,
                }), '')
            return real_run(command, **kwargs)

        for override, expected in (({}, 17), ({'max_turns': 9}, 9)):
            attempt = self.root / f'attempt-{expected}'
            with patch('benchmark.runner.claude.subprocess.run', side_effect=execute), patch(
                    'benchmark.runner.claude.archive_transcript', return_value={
                        'first_turn_cache_read_tokens': 0}):
                result = run_attempt(self.root, condition('BASE'), attempt, **override)
            command = commands[-1]
            self.assertEqual(command[command.index('--model') + 1], 'test-model')
            self.assertEqual(command[command.index('--effort') + 1], 'high')
            self.assertEqual(command[command.index('--max-turns') + 1], str(expected))
            manifest = json.loads((attempt / 'manifest.json').read_text())
            self.assertEqual((manifest['model'], manifest['effort'], manifest['max_turns']),
                             ('test-model', 'high', expected))
            self.assertEqual(result['model'], 'test-model')

    def test_paid_result_is_saved_before_housekeeping(self):
        real_run = subprocess.run

        def execute(command, **kwargs):
            if command[0] == 'claude':
                return subprocess.CompletedProcess(command, 0, json.dumps({
                    'subtype': 'success', 'result': 'Done', 'total_cost_usd': 1.2,
                }), '')
            return real_run(command, **kwargs)

        attempt = self.root / 'attempt'
        with patch('benchmark.runner.claude.subprocess.run', side_effect=execute), patch(
                'benchmark.runner.claude.stage_intent_to_add', side_effect=RuntimeError('git failed')):
            with self.assertRaises(RuntimeError):
                run_attempt(self.root, condition('BASE'), attempt)
        self.assertTrue((attempt / 'result.json').exists())
        self.assertEqual(json.loads((attempt / 'result.json').read_text())['total_cost_usd'], 1.2)


class SchedulingReportTests(unittest.TestCase):
    def test_report_uses_timestamps_and_each_runs_isolation_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / 'batch'
            # Directory order deliberately differs from chronological order.
            for label, start, end, api, policy in (
                ('BASE-02', 100, 110, True, 'nonce'),
                ('BASE-01', 120, 130, False, 'washout'),
            ):
                make_attempt(runs, label, 'BASE')
                path = runs / label / 'attempt-01/result.json'
                result = json.loads(path.read_text())
                result.update(started_epoch=start, last_request_epoch=end, api_mode=api,
                              scheduling='serial', cache_isolation=policy, washout_seconds=5)
                path.write_text(json.dumps(result))
            generate_report(runs, root / 'report')
            report = (root / 'report/final-report.md').read_text()
            section = report.split('## Cache isolation and scheduling')[1].split('##')[0]
            self.assertIn('10.0s', section)
            self.assertIn('PASS', section)
            self.assertIn('nonce', section)
            self.assertIn('serial', section)
            self.assertNotIn('parallel', section)
