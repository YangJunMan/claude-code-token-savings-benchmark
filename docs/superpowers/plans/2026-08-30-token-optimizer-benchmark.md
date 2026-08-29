# Token Optimizer Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a reproducible seven-condition Claude Code benchmark that measures Headroom, Caveman, and RTK token/cost savings against hidden functional quality gates.

**Architecture:** A Python standard-library harness creates identical fixture worktrees, activates exactly one condition adapter, runs Claude Sonnet 5 medium, preserves immutable evidence, clears the session, and enforces a 4,200-second washout. A separate hidden grader evaluates each diff, while the reporter aggregates every model's provider usage and paired comparisons.

**Tech Stack:** Python 3.9 standard library, `unittest`, Git worktrees, Claude Code 2.1.231+, Headroom proxy, Caveman Claude Code plugin, RTK CLI, JSON/JSONL/CSV, shell subprocesses.

**Spec:** `docs/superpowers/specs/2026-08-30-token-optimizer-benchmark-design.md`

## Global Constraints

- Every Claude-facing prompt and fixture artifact is English.
- Model is exactly `claude-sonnet-5`; effort is exactly `medium`.
- Run order is H-ON, H-OFF, C-FULL, C-NON, C-BRIEF, R-ON, R-OFF.
- Wait at least 4,200 seconds from the last Claude request between valid attempts.
- Use the same fixture commit and base prompt hash for all conditions.
- Preserve interrupted attempts but exclude them from paired calculations.
- Never expose hidden tests to Claude-visible worktrees.
- Treat `costUSD` as API-equivalent estimated cost, not a Pro subscription charge.

---

### Task 1: Harness contracts and durable state

**Files:**
- Create: `benchmark/__init__.py`
- Create: `benchmark/config.json`
- Create: `benchmark/runner/__init__.py`
- Create: `benchmark/runner/contracts.py`
- Create: `benchmark/runner/state.py`
- Create: `benchmark/runner/checksums.py`
- Test: `tests/test_contracts.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `Condition`, `RunState`, `BenchmarkConfig`, `AttemptState`, `load_config(path)`, `StateStore.load()`, and `StateStore.transition()`.
- Consumes: only Python standard-library types and JSON files.

- [ ] **Step 1: Write failing contract tests**

```python
def test_config_has_fixed_order_and_4200_second_washout(self):
    config = load_config(Path("benchmark/config.json"))
    self.assertEqual([c.value for c in config.conditions], [
        "H-ON", "H-OFF", "C-FULL", "C-NON", "C-BRIEF", "R-ON", "R-OFF"
    ])
    self.assertEqual(config.washout_seconds, 4200)
    self.assertEqual(config.model, "claude-sonnet-5")
    self.assertEqual(config.effort, "medium")
```

- [ ] **Step 2: Run tests and verify the missing-module failure**

Run: `python3 -m unittest tests.test_contracts tests.test_state -v`

Expected: import failure for `benchmark.runner.contracts`.

- [ ] **Step 3: Implement immutable contracts and atomic state storage**

`config.json` must contain:

```json
{
  "model": "claude-sonnet-5",
  "effort": "medium",
  "max_turns": 28,
  "washout_seconds": 4200,
  "conditions": ["H-ON", "H-OFF", "C-FULL", "C-NON", "C-BRIEF", "R-ON", "R-OFF"],
  "target_input_related_min": 600000,
  "target_input_related_max": 1000000,
  "target_output_min": 15000,
  "target_output_max": 30000
}
```

`StateStore.transition()` must write a temporary sibling, call `os.replace`, and append the same event to `events.jsonl` with UTC and Asia/Seoul ISO timestamps.

- [ ] **Step 4: Run contract tests**

Run: `python3 -m unittest tests.test_contracts tests.test_state -v`

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add benchmark tests
git commit -m "feat: add benchmark state contracts"
```

### Task 2: English coding-heavy fixture and fixed prompt

**Files:**
- Create: `benchmark/fixture/pyproject.toml`
- Create: `benchmark/fixture/gpu_platform/__init__.py`
- Create: `benchmark/fixture/gpu_platform/models.py`
- Create: `benchmark/fixture/gpu_platform/store.py`
- Create: `benchmark/fixture/gpu_platform/admission.py`
- Create: `benchmark/fixture/gpu_platform/metrics.py`
- Create: `benchmark/fixture/migrations/001_initial.sql`
- Create: `benchmark/fixture/k8s/deployment.yaml`
- Create: `benchmark/fixture/.github/workflows/test.yml`
- Create: `benchmark/fixture/tests/test_existing_behavior.py`
- Create: `benchmark/fixture/tests/test_acceptance_scaffold.py`
- Create: `benchmark/fixture/docs/incident-log.txt`
- Create: `benchmark/fixture/docs/api-contract.md`
- Create: `benchmark/fixture/docs/operations.md`
- Create: `benchmark/fixture/docs/decision.md`
- Create: `benchmark/prompts/master.md`
- Create: `benchmark/prompts/be-brief.txt`
- Create: `benchmark/fixture_manifest.json`
- Test: `tests/test_fixture.py`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Produces: a Git fixture whose existing tests pass but whose requested acceptance behavior is incomplete.
- Consumes: the exact master prompt through stdin; no network access or third-party Python dependency.

- [ ] **Step 1: Write failing fixture and prompt tests**

```python
def test_prompt_is_english_and_contains_required_work(self):
    prompt = Path("benchmark/prompts/master.md").read_text()
    for phrase in (
        "Work entirely in English",
        "idempotency",
        "worker lease",
        "Kubernetes",
        "operations runbook",
        "Do not modify or weaken existing tests",
    ):
        self.assertIn(phrase, prompt)

def test_fixture_public_regression_suite_passes(self):
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd="benchmark/fixture", text=True, capture_output=True
    )
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
```

- [ ] **Step 2: Run tests and verify missing fixture files**

Run: `python3 -m unittest tests.test_fixture tests.test_prompts -v`

Expected: failures naming `benchmark/prompts/master.md` and fixture files.

- [ ] **Step 3: Build the incomplete service fixture**

Implement stable existing behavior for job creation and retrieval. Leave the requested priority admission, concurrency-safe idempotency, lease reaping, retry/dead-letter transitions, metrics, migration upgrade, manifest hardening, and new tests for Claude to implement. Public scaffold tests describe acceptance requirements but must not reveal hidden concurrency cases.

The incident log must contain repetitive but relevant scheduler events, two race traces, lease-expiry evidence, and misleading INFO noise so Headroom and RTK have realistic material to filter.

- [ ] **Step 4: Write the English master prompt**

The prompt must require inspection before editing, implementation rather than a prose-only answer, public test execution, new tests, Kubernetes/CI updates, concise documentation, and a final evidence report. It must not prescribe exact function bodies or expose hidden assertions.

- [ ] **Step 5: Generate and verify the fixture manifest**

Run:

```bash
python3 -m benchmark.runner.checksums benchmark/fixture benchmark/prompts --output benchmark/fixture_manifest.json
python3 -m unittest tests.test_fixture tests.test_prompts -v
```

Expected: public regression tests and prompt controls pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add benchmark tests
git commit -m "feat: add gpu platform benchmark fixture"
```

### Task 3: Hidden grader and quality score

**Files:**
- Create: `benchmark/grader/__init__.py`
- Create: `benchmark/grader/hidden_tests/test_admission.py`
- Create: `benchmark/grader/hidden_tests/test_concurrency.py`
- Create: `benchmark/grader/hidden_tests/test_leases.py`
- Create: `benchmark/grader/hidden_tests/test_metrics_and_migration.py`
- Create: `benchmark/grader/grade.py`
- Test: `tests/test_grader.py`

**Interfaces:**
- Produces: `grade_attempt(worktree, result_json, output_path) -> dict` with a 100-point score and critical-gate flags.
- Consumes: a completed run worktree and Claude result JSON; hidden tests remain outside that worktree.

- [ ] **Step 1: Write failing grader tests**

```python
def test_score_weights_sum_to_100(self):
    self.assertEqual(sum(SCORE_WEIGHTS.values()), 100)

def test_false_completion_claim_fails_evidence_gate(self):
    score = score_evidence(
        final_text="All tests pass.",
        public_returncode=1,
        changed_files=["gpu_platform/admission.py"],
    )
    self.assertEqual(score, 0)
```

- [ ] **Step 2: Verify missing grader failure**

Run: `python3 -m unittest tests.test_grader -v`

Expected: import failure for `benchmark.grader.grade`.

- [ ] **Step 3: Implement isolated hidden-test execution and scoring**

Copy hidden tests into a temporary directory outside the run worktree, set `PYTHONPATH` to the worktree, execute each category separately, and remove the temporary copy after recording output. Use exact weights `45/15/10/10/10/10`. Treat acceptance-test edits, hidden-test discovery attempts, and false completion claims as critical failures.

- [ ] **Step 4: Run grader tests**

Run: `python3 -m unittest tests.test_grader -v`

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add benchmark/grader tests/test_grader.py
git commit -m "feat: add blinded benchmark quality grader"
```

### Task 4: Usage parser and paired reporter

**Files:**
- Create: `benchmark/runner/usage.py`
- Create: `benchmark/reports/__init__.py`
- Create: `benchmark/reports/generate.py`
- Test: `tests/fixtures/claude-result.json`
- Test: `tests/test_usage.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Produces: `parse_usage(result)`, `sum_model_costs(result)`, `generate_report(run_root, report_dir)`.
- Consumes: Claude JSON results, manifests, and quality JSON.

- [ ] **Step 1: Write failing multi-model usage tests**

```python
def test_sums_every_model_and_cache_bucket(self):
    usage = parse_usage(json.loads(FIXTURE.read_text()))
    self.assertEqual(usage.input_related_tokens, 535000)
    self.assertEqual(usage.output_tokens, 15000)
    self.assertAlmostEqual(usage.cost_usd, 0.53, places=6)
```

- [ ] **Step 2: Verify missing parser failure**

Run: `python3 -m unittest tests.test_usage tests.test_report -v`

Expected: import failures for usage and report modules.

- [ ] **Step 3: Implement provider usage aggregation**

Support snake-case top-level usage and camel-case `.modelUsage[]` fields. Sum every model, retain per-model rows, avoid double-counting thinking tokens inside output, and flag mismatch between client `costUSD` and manual list-price validation.

- [ ] **Step 4: Implement Markdown and CSV reporting**

Write condition metrics, paired deltas, quality gates, invalid attempts, token target deviations, cache-isolation findings, changed-line ratios, and limitations. Refuse to label a treatment recommended unless its paired saving is positive and all quality gates pass.

- [ ] **Step 5: Run parser and report tests**

Run: `python3 -m unittest tests.test_usage tests.test_report -v`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add benchmark/runner/usage.py benchmark/reports tests
git commit -m "feat: aggregate benchmark usage and reports"
```

### Task 5: Condition adapters and reversible tool setup

**Files:**
- Create: `benchmark/runner/conditions.py`
- Create: `benchmark/runner/preflight.py`
- Create: `benchmark/scripts/install-tools.sh`
- Create: `benchmark/scripts/restore-user-config.sh`
- Test: `tests/test_conditions.py`
- Test: `tests/test_preflight.py`

**Interfaces:**
- Produces: `ConditionAdapter.prepare(worktree)`, `ConditionAdapter.command(prompt_path)`, `ConditionAdapter.verify(logs)`, `ConditionAdapter.cleanup()`.
- Consumes: pinned locally installed Headroom, Caveman, RTK, Claude Code, and a saved user-config snapshot.

- [ ] **Step 1: Write failing isolation tests**

```python
def test_only_named_optimizer_is_active(self):
    for condition in Condition:
        env = build_condition(condition, Path("/tmp/run")).environment
        self.assertEqual(active_optimizer_count(env, condition), 1)

def test_brief_overlay_is_exact(self):
    self.assertEqual(
        brief_overlay(),
        "Be brief. Keep the final response concise without omitting the requested\n"
        "implementation evidence, test results, design decisions, and limitations.\n",
    )
```

- [ ] **Step 2: Verify missing adapter failure**

Run: `python3 -m unittest tests.test_conditions tests.test_preflight -v`

Expected: import failures for condition and preflight modules.

- [ ] **Step 3: Implement reversible setup**

Before changing Claude configuration, archive `~/.claude/settings.json`, plugin listings, hooks, and relevant environment variables under `benchmark/local-backup/`. Install Headroom into `.venv`, install Caveman through the Claude plugin marketplace, and install RTK through Homebrew or its signed release path. Record exact versions and checksums. The restore script must restore the snapshot and remove only benchmark-added entries.

- [ ] **Step 4: Implement adapter capability probes**

Use each installed CLI's current `--help` output to select its supported optimized, passthrough, activation, deactivation, and dry-run commands. Abort before a paid run if H-ON compression, H-OFF passthrough, Caveman mode, or RTK rewrite cannot be proven from local logs.

- [ ] **Step 5: Run adapter tests and read-only preflight**

Run:

```bash
python3 -m unittest tests.test_conditions tests.test_preflight -v
python3 -m benchmark.runner.preflight --config benchmark/config.json --dry-run
```

Expected: tests pass and preflight reports no paid Claude request was made.

- [ ] **Step 6: Commit Task 5**

```bash
git add benchmark/runner benchmark/scripts tests
git commit -m "feat: add isolated optimizer condition adapters"
```

### Task 6: Claude runner, clear operation, quota waits, and scheduler

**Files:**
- Create: `benchmark/runner/claude.py`
- Create: `benchmark/runner/scheduler.py`
- Create: `benchmark/runner/cli.py`
- Test: `tests/test_claude_runner.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Produces: `run_attempt()`, `clear_session()`, `classify_failure()`, `next_eligible_at()`, and CLI commands `preflight`, `run-next`, `run-all`, `status`, `report`.
- Consumes: contracts, state store, condition adapters, grader, and reporter.

- [ ] **Step 1: Write failing scheduler tests with a fake clock and fake Claude**

```python
def test_next_run_waits_4200_seconds_after_last_request(self):
    clock = FakeClock(10_000)
    scheduler = Scheduler(config(), clock=clock)
    self.assertEqual(scheduler.next_eligible_at(last_request_epoch=9_000), 13_200)

def test_quota_interruption_restarts_clean_attempt(self):
    failure = classify_failure("You've hit your session limit · resets 3:45pm")
    self.assertEqual(failure.kind, "quota")
    self.assertTrue(failure.invalidate_attempt)
```

- [ ] **Step 2: Verify missing runner failure**

Run: `python3 -m unittest tests.test_claude_runner tests.test_scheduler -v`

Expected: import failures for Claude runner and scheduler.

- [ ] **Step 3: Implement streamed Claude execution**

Pass the English prompt on stdin, request stream JSON and a final JSON result, pin model/effort/max turns, persist stdout and stderr incrementally, record the session ID and last request timestamp, and terminate safely on configuration or quota errors.

- [ ] **Step 4: Implement `/clear` evidence**

Open the completed session in a PTY, send `/clear`, capture the terminal transcript, require a successful clear marker, then exit. A failed clear prevents transition to `waiting_washout`.

- [ ] **Step 5: Implement scheduler recovery**

Use durable state and a fake-clock-tested loop. Sleep in bounded intervals, update heartbeat timestamps, wait to quota reset plus 300 seconds, recreate invalid worktrees, and never resume a partially completed quota-interrupted attempt.

- [ ] **Step 6: Run runner tests**

Run: `python3 -m unittest tests.test_claude_runner tests.test_scheduler -v`

Expected: all tests pass without a paid Claude request.

- [ ] **Step 7: Commit Task 6**

```bash
git add benchmark/runner tests
git commit -m "feat: schedule isolated Claude benchmark runs"
```

### Task 7: Full verification, tool installation, and experiment launch

**Files:**
- Modify: `README.md`
- Generate: `benchmark/runs/state.json`
- Generate: `benchmark/runs/events.jsonl`
- Generate: `benchmark/runs/environment.json`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a live durable seven-condition experiment and operator documentation.

- [ ] **Step 1: Run the complete offline test suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: all harness, fixture, grader, parser, adapter, and scheduler tests pass with zero paid requests.

- [ ] **Step 2: Inspect diffs and verify secrets are absent**

Run:

```bash
git diff --check
rg -n --hidden 'sk-ant-|api[_-]?key|password|token=' benchmark tests README.md || true
```

Expected: no whitespace errors and no credential material.

- [ ] **Step 3: Install and pin optimizer tools**

Run: `bash benchmark/scripts/install-tools.sh`

Expected: Claude, Headroom, Caveman, and RTK versions are written to `benchmark/runs/environment.json`; user configuration snapshot exists.

- [ ] **Step 4: Run non-paid preflight**

Run: `python3 -m benchmark.runner.cli preflight`

Expected: fixture hashes, public tests, model support, condition activation probes, hidden-test isolation, output directories, and 4,200-second policy all pass.

- [ ] **Step 5: Commit implementation before paid execution**

```bash
git add README.md benchmark tests docs
git commit -m "docs: document token optimizer experiment operation"
```

- [ ] **Step 6: Start the durable experiment**

Run: `python3 -m benchmark.runner.cli run-all`

Expected: H-ON enters `running`; after completion it is graded, cleared, and enters `waiting_washout` with an eligibility timestamp at least 4,200 seconds after its last Claude request.

- [ ] **Step 7: Generate final report after all seven valid conditions**

Run:

```bash
python3 -m benchmark.runner.cli report
python3 -m benchmark.runner.checksums benchmark/runs benchmark/reports --output benchmark/reports/checksums.sha256
```

Expected: `final-report.md`, `measurements.csv`, and checksum evidence exist; every recommendation passes its paired quality gate.
