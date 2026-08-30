# Reproduction guide

## Scope

Supported: macOS and Linux, Python 3.9+, Git, Claude Code 2.1.x. Windows/WSL is not verified.
The offline path is free. The paid path is deliberately not a one-command default.

## Free path

```bash
git clone https://github.com/YangJunMan/claude-code-token-savings-benchmark.git
cd claude-code-token-savings-benchmark
make setup
make smoke
make report
git diff --exit-code docs/GENERATED_RESULTS.md
```

`make report` recomputes the published tables from the committed, sanitized aggregate CSV. It does not
claim to reconstruct private Claude transcripts. Those may contain local paths, session identifiers, or
prompt content and are intentionally excluded.

## Experimental design

- Model: Claude Sonnet 5, effort `medium`, English prompt.
- Workload: implement a small SQLite-backed GPU job admission service; mostly code with moderate docs.
- Jobs: baseline twice, then Headroom, Caveman full, `be brief`, and RTK once each.
- Cache: normal prompt caching is allowed within a job. Each job receives a unique system nonce and unique
  sentinel MCP tool name so cross-job cache reuse is minimized.
- Isolation: every job starts from a fresh fixture copy. Held-out grader tests are outside the agent worktree.
- Quality gate: functional tests plus implementation/documentation rubric.

This is a one-off exploratory benchmark. Identical baseline runs differed by 9.78% in cost and 22.06% in
processed tokens, so small deltas should not be treated as causal effects.

## Paid path and safety boundary

Install the optional tools only after reviewing their upstream instructions:

```bash
make setup-paid
brew install rtk-ai/tap/rtk       # macOS; Linux alternatives are in the RTK repository
claude plugin marketplace add JuliusBrussee/caveman
claude plugin install caveman@caveman
make preflight
```

- Headroom: <https://github.com/headroomlabs-ai/headroom/blob/main/wiki/getting-started.md>
- Caveman: <https://github.com/ryailabs/caveman/blob/main/INSTALL.md>
- RTK: <https://github.com/rtk-ai/rtk>

`make preflight` checks POSIX, Claude Code, RTK, Git, curl, Headroom, Caveman, and required fixture files. Set
`HEADROOM_BIN` or `CAVEMAN_PLUGIN_DIR` in your shell when using non-default installations. It intentionally does
not test model access because that would make a paid request.

First inspect the estimate without an API key:

```bash
make estimate
```

The original six-job cohort cost about $10.05 for included runs and $16.77 including invalid attempts. A
post-hoc second Headroom run raised the published included total to about $11.62 and the all-attempt total to
$18.33. The public reproduction plan now runs seven jobs: BASE twice and H-ON twice, because a repeated
condition is what makes its percentage interpretable, plus one run each of C-FULL, C-BRIEF and R-ON.
The additional Headroom repeat is evidence
from the historical investigation, not an automatic seventh job. Prices, model behavior, retries, and tool
versions can change. The estimator therefore shows a conservative planning ceiling, not a guaranteed charge.

Actual execution requires all of the following and otherwise fails closed:

```bash
python3 -m benchmark.runner.public_cli benchmark \
  --confirm-paid-run \
  --max-budget-usd 18 \
  --run-root benchmark/runs/reproduction-001 \
  --report-dir benchmark/reports/reproduction-001
```

- `--confirm-paid-run` must be present.
- The budget must meet the conservative ceiling printed by `make estimate`.
- `ANTHROPIC_API_KEY` must be set; OAuth fallback is rejected.
- The run directory must be empty, preventing overwrite of evidence.
- Jobs run serially. The guard stops before a projected job would exceed the total budget, and every Claude
  process also receives a `$2.50` `--max-budget-usd` cap.

Claude Code runs with `--permission-mode bypassPermissions` so the automated coding task can edit and test its
fresh fixture without interactive prompts. This is not an OS sandbox: tool subprocesses can inherit API
credentials and may access the network or paths outside the fixture. Optimizer activation can also differ by
version. Audit `benchmark/runner/claude.py`, pin tool versions, and run activation probes before spending money.
Never run untrusted prompts or repositories with an API key in the environment.

No CI workflow in this repository invokes a paid model.
