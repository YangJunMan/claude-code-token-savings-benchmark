# Natural-Cache Token Optimizer Rerun Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a seven-condition Claude Sonnet 5 medium benchmark with natural provider prompt caching inside each condition and cross-condition cache isolation.

**Architecture:** Keep the completed `benchmark/runs-api` cohort immutable and add an explicit cache-policy parameter to the existing runner. The executed cohort writes to `benchmark/runs-api-natural-v3` and `benchmark/reports-api-natural-v3`, using one stable nonce per condition and recording first-turn and later-turn cache usage. Earlier natural-cache probes remain preserved as invalid exploratory artifacts.

**Tech Stack:** Python 3, `unittest`, Claude Code CLI, Anthropic API key, Headroom proxy, Caveman plugin, RTK hook, JSON/CSV/Markdown artifacts, SHA-256 manifests.

**Spec:** `docs/superpowers/specs/2026-08-30-token-optimizer-natural-cache-rerun.md`

## Global Constraints

- Never overwrite `benchmark/runs-api` or `benchmark/reports-api`.
- Omit `DISABLE_PROMPT_CACHING` in the natural-cache cohort.
- Keep one stable nonce per condition and require first-turn cache read `0`.
- Apply the same `--disallowedTools WebSearch` isolation variant and a per-condition MCP sentinel tool to all seven conditions so a new `tools` prefix is used without changing pair asymmetry.
- Use one fixed `max_turns` and seven parallel workers.
- Sum every `modelUsage[].costUSD` and stop before the `$14` ceiling.
- Keep prompts in English and preserve the existing 100-point quality rubric.

### Task 1: Make cache policy explicit

**Files:**
- Modify: `benchmark/runner/claude.py`
- Modify: `benchmark/runner/api_parallel.py`
- Test: `tests/test_api_parallel.py`

- [x] **Step 1: Write a failing test** asserting `build_jobs` records `disable_prompt_caching=False` for natural-cache jobs and that `run_attempt` receives the policy explicitly.
- [x] **Step 2: Run the focused test and verify it fails for the missing field/parameter.**
- [x] **Step 3: Add a `disable_prompt_caching` parameter to `run_attempt` and pass it from the API runner; only set the environment variable when true.**
- [x] **Step 4: Run the focused test and the full unit suite.**
- [x] **Step 5: Commit the runner change.**

### Task 2: Add a budgeted natural-cache launcher

**Files:**
- Modify: `benchmark/runner/api_parallel.py`
- Test: `tests/test_api_parallel.py`

- [x] **Step 1: Write a failing test** for the natural cohort default root, report root, and fixed cache policy metadata.
- [x] **Step 2: Run the focused test and verify it fails.**
- [x] **Step 3: Add `--natural-cache`, `--run-root`, `--report-dir`, the shared tool-prefix isolation variant, and a preflight budget guard without making any model request during preflight.**
- [x] **Step 4: Run the focused test and the full unit suite.**
- [x] **Step 5: Commit the launcher change.**

### Task 3: Execute and grade the cohort

**Files:**
- Create: `benchmark/runs-api-natural-v3/`
- Create: `benchmark/reports-api-natural-v3/`

- [x] **Step 1: Run the fixed-turn dry-run budget calculation and record it.**
- [x] **Step 2: Inject the API key without printing it and launch all seven conditions in parallel.**
- [x] **Step 3: Confirm every condition has raw result, transcript, clear evidence, manifest, public tests, hidden tests, and quality JSON.**
- [x] **Step 4: Confirm first-turn cache read is zero and later-turn cache fields are recorded before accepting a condition.**

### Task 4: Report and verify

**Files:**
- Modify: `benchmark/reports/generate.py` if natural-cache labeling requires it.
- Create: `benchmark/reports-api-natural-v3/final-report.md`
- Create: `benchmark/reports-api-natural-v3/measurements.csv`
- Create: `benchmark/reports-api-natural-v3/checksums.sha256`

- [x] **Step 1: Generate per-condition measurements and paired comparisons without mixing the old cohort.**
- [x] **Step 2: Add a natural-cache section that distinguishes first-turn isolation from later-turn cache reuse.**
- [x] **Step 3: Run the complete unit suite, checksum verification, and independent token/cost recomputation.**
- [x] **Step 4: Commit source and report metadata; preserve raw run directories as ignored artifacts.**

## Execution notes

- v3 used `max_turns=10`, seven parallel workers, no `DISABLE_PROMPT_CACHING`, the same `--disallowedTools WebSearch`, and a unique unused MCP sentinel per condition.
- The first H-ON attempt was rejected because its first turn read 7,304 cached tokens; after a provider-cache TTL washout, H-ON `attempt-02` passed with first-turn read 0. The rejected path-failure probe is preserved under `benchmark/runs-api-natural-v3-failed-mcp-path/`, and the cache-contaminated H-ON attempt remains under `benchmark/runs-api-natural-v3/H-ON/attempt-01/`.
