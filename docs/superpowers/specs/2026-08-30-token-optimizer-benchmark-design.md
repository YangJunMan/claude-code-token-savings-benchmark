# Token Optimizer Benchmark Design

## 1. Objective

Measure whether Headroom, Caveman, and RTK reduce Claude Code token usage and API-equivalent cost on a realistic coding-heavy task without materially reducing implementation quality.

The benchmark uses Claude Sonnet 5 at `medium` effort. Codex builds and operates the harness, schedules every condition, preserves raw evidence, evaluates outputs, and produces the final report.

The benchmark reports observed results only. It does not generalize a single machine's measurements into universal product claims.

## 2. Experimental Questions

1. Does Headroom optimization reduce provider-reported input processing and API-equivalent cost compared with the same proxy in passthrough mode?
2. Does Caveman `full` reduce output tokens and total cost compared with Caveman `off`?
3. Does a simple `Be brief` instruction achieve similar savings to Caveman `full`?
4. Does RTK reduce provider-reported input processing and total cost by filtering shell command output?
5. Does any saving condition reduce functional quality, documentation accuracy, or evidence completeness?

## 3. Conditions

Seven valid runs are required.

| ID | Condition | Treatment | Primary Comparison |
|---|---|---|---|
| H-ON | Headroom optimized | Headroom proxy with optimization enabled and semantic cache disabled | H-OFF |
| H-OFF | Headroom passthrough | Same Headroom proxy and provider-cache policy with optimization disabled | H-ON |
| C-FULL | Caveman full | Caveman plugin loaded; `/caveman full` active | C-NON |
| C-NON | Caveman non | User plugins excluded; no Caveman instruction | C-FULL and C-BRIEF |
| C-BRIEF | Be brief | User plugins excluded; one fixed brevity instruction appended | C-NON and C-FULL |
| R-ON | RTK on | RTK project-scoped rewrite hook enabled | R-OFF |
| R-OFF | RTK off | Same environment without command rewriting | R-ON |

All unrelated optimizers must be disabled for every condition. `H-OFF`, `C-NON`, and `R-OFF` are repeated direct or no-treatment observations that expose baseline drift, but only the named paired comparison is causal.

## 4. Fixed Execution Order and Washout

The fixed order is:

1. H-ON
2. H-OFF
3. C-FULL
4. C-NON
5. C-BRIEF
6. R-ON
7. R-OFF

After each run except the last:

1. Preserve the complete result, session identifier, transcript, stderr, repository diff, test output, timestamps, and usage fields.
2. Run `/clear` in the completed Claude Code session and record evidence that it succeeded.
3. Record the timestamp of the last Claude request.
4. Wait at least 70 minutes from that timestamp.
5. Start the next condition only after the wait and preflight checks both pass.

Claude Pro main-conversation prompt-cache entries use a one-hour inactivity TTL in the current authenticated configuration. The ten-minute margin is mandatory. A first-turn cache hit after the washout is recorded as a cache-isolation failure and the affected run is excluded until repeated.

The six mandatory waits total 420 minutes. Runtime and quota waits are additional.

## 5. Workload

The fixture is an existing Python service for admitting Kubernetes GPU batch jobs. It contains an incomplete implementation, public regression tests, realistic incident evidence, API contracts, Kubernetes manifests, and short operational documentation.

Claude receives one English master prompt and must work entirely in English. The task requires:

- priority and FIFO GPU job admission;
- idempotent submission;
- SQLite transaction safety under concurrent requests;
- worker leases, heartbeat, expiry, retry, and dead-letter handling;
- GPU concurrency and per-user quota enforcement;
- Prometheus-style metrics and structured logs;
- database migration behavior;
- Kubernetes probes, configuration, resource controls, and rollout safety;
- unit, integration, and concurrency tests;
- CI updates;
- a concise architecture decision and operations runbook update;
- a final evidence-based implementation report.

The intended changed-line mix is:

| Artifact | Target Share |
|---|---:|
| Implementation code | 45-55% |
| Test code | 25-35% |
| Kubernetes and CI configuration | 5-10% |
| Documentation | 15-20% |

The target per valid run is 600,000-1,000,000 provider-reported input-related tokens, 15,000-30,000 output tokens including thinking, 15-28 Claude turns, and 400-800 changed source/test lines. These are workload-sizing targets, not success claims.

## 6. Prompt Controls

The master prompt, fixture commit, model, effort, tool permissions, maximum turns, environment variables, and acceptance criteria are fixed across conditions.

The common language instruction is:

```text
Work entirely in English. Use English for code comments, documentation,
test names, implementation notes, and the final response.
```

The C-FULL condition explicitly loads the pinned Caveman plugin. C-NON and C-BRIEF exclude user plugins because the installed Caveman skill declares `be brief` as an automatic trigger; loading it in C-BRIEF would contaminate the generic-instruction control. C-BRIEF appends exactly:

```text
Be brief. Keep the final response concise without omitting the requested
implementation evidence, test results, design decisions, and limitations.
```

No other prompt text may differ. The base prompt SHA-256 and effective prompt SHA-256 are recorded for every run.

## 7. Repository Isolation

Each run starts from the same immutable fixture commit in a separate clean worktree. The harness verifies:

- expected fixture commit;
- no uncommitted changes;
- fixed dependency lock files;
- public baseline tests pass;
- hidden acceptance tests are absent from the Claude-visible worktree;
- optimizer state matches the condition;
- model is `claude-sonnet-5` and effort is `medium`;
- no unrelated Claude plugin, hook, or project instruction is active.

Hidden tests run outside the Claude-visible worktree after completion. Their contents are never fed back to Claude.

## 8. Usage and Cost Metrics

Provider-reported metrics are primary. Tool self-reported savings are secondary diagnostics.

For every model in `.modelUsage[]`, collect:

- ordinary input tokens;
- five-minute cache-write tokens;
- one-hour cache-write tokens;
- cache-read tokens;
- output tokens;
- exposed thinking-token detail;
- model cost estimate;
- service tier and model identifier.

Derived metrics are:

```text
input_related_tokens =
    input_tokens
  + cache_creation_input_tokens
  + cache_read_input_tokens

total_processed_tokens = input_related_tokens + output_tokens

paired_token_saving =
  (baseline_total_processed - treatment_total_processed)
  / baseline_total_processed

paired_cost_saving =
  (baseline_cost - treatment_cost)
  / baseline_cost
```

The primary cost value is the sum of `costUSD` across every model. A manual Sonnet 5 list-price calculation validates that value. The report labels it `API-equivalent estimated cost`; it is not presented as an additional Claude Pro subscription charge.

## 9. Quality Evaluation

Condition names are hidden from the grader. The 100-point score is:

| Area | Points | Gate |
|---|---:|---|
| Hidden functional tests | 45 | Admission, leases, retries, metrics, migration |
| Idempotency and race safety | 15 | Concurrent submissions and transaction behavior |
| Public regression tests | 10 | All baseline tests pass |
| Code quality | 10 | Focused design, error handling, no test tampering |
| Documentation accuracy | 10 | Commands, behavior, and limitations match implementation |
| Final response evidence | 10 | Files, tests, decisions, and limitations reported |

A treatment has no material quality loss only if:

- all critical hidden-test categories pass;
- no public regression test fails;
- its total score is no more than five points below its paired baseline;
- it makes no false test or completion claim.

Also record wall-clock time, Claude turns, tool calls, command repetitions, changed lines by artifact class, test count, and final-response length.

## 10. Quota and Failure Handling

Before each run, record `/usage` or equivalent rate-limit evidence. If the account is blocked, wait until the displayed reset time plus a five-minute safety margin.

If a session or weekly limit interrupts a run:

1. Stop the run.
2. Preserve it under `invalid-quota-interrupted`.
3. Do not include it in paired calculations.
4. Wait until the displayed reset time plus five minutes.
5. Recreate a clean fixture worktree.
6. Repeat the entire condition from the beginning.

Resuming a partially completed worktree across a quota reset is forbidden because it changes cache and service conditions mid-run.

If Codex becomes unavailable, the local runner continues scheduled waits and Claude execution using its durable state file. Codex resumes grading and reporting from preserved artifacts when available again.

Other invalidation reasons include wrong model, wrong effort, optimizer activation failure, first-turn cross-run cache hit, fixture hash mismatch, missing raw result, or grader contamination.

## 11. Runner State Model

The durable states are:

```text
pending
preflight
running
clearing
waiting_washout
waiting_claude_quota
invalid_quota_interrupted
invalid_configuration
completed
failed
```

Each transition is appended to a JSON Lines event log with UTC and Asia/Seoul timestamps. Atomic state snapshots allow safe restart after process or machine interruption.

## 12. Evidence Layout

```text
benchmark/
  fixture/
  prompts/
  grader/
  runner/
  runs/<condition>/<attempt>/
    manifest.json
    result.json
    stream.jsonl
    stderr.log
    transcript.jsonl
    git.diff
    public-tests.txt
    hidden-tests.txt
    quality.json
    optimizer.log
    clear.log
  reports/
    final-report.md
    measurements.csv
    checksums.sha256
```

Raw artifacts are immutable after an attempt completes. The checksum manifest covers prompts, fixture metadata, raw results, diffs, tests, scores, and the final report.

## 13. Reporting

The final report includes:

- environment and pinned versions;
- exact prompt and fixture hashes;
- valid and invalid attempt inventory;
- raw token categories by model and condition;
- API-equivalent cost and paired savings;
- quality scores and critical-gate outcomes;
- changed-line and code/document ratios;
- latency and turn counts;
- provider cache observations;
- Headroom, Caveman, and RTK secondary statistics;
- limitations from fixed order, single valid observation per condition, dynamic subscription quotas, and model nondeterminism;
- a recommendation only where measured savings and quality gates both support it.

No target saving, tool marketing claim, or interrupted run is reported as a measured outcome.
