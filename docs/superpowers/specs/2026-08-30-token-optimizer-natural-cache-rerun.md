# Natural-Cache Token Optimizer Rerun Specification

**Goal:** Re-run the seven Headroom/Caveman/RTK conditions with provider prompt caching enabled within each Claude Code session while isolating conditions from one another.

## Experimental contract

- Model: `claude-sonnet-5`, effort `medium`.
- The same English, coding-heavy master prompt and fixture are used for every condition.
- Each condition receives a fresh session, isolated worktree, and one stable per-condition nonce in the system prompt.
- The nonce is constant within a condition; it must not change between turns, so natural cache reuse remains possible.
- `DISABLE_PROMPT_CACHING` must be absent for every model request in this cohort.
- `/clear` is sent after every condition and its terminal/resume evidence is archived.
- A condition is cache-isolated only when its first turn has `cache_read_input_tokens=0`; later turns are expected to be free to read/write cache naturally.
- To prevent reuse of previously cached prefixes, this rerun applies the same unused built-in tool exclusion (`--disallowedTools WebSearch`) and a per-condition MCP sentinel tool (unique name derived from the nonce) to every condition; both are recorded as cohort metadata.
- Conditions run in parallel to avoid artificial TTL waits. Parallelism and any provider rate-limit contention are recorded as limitations.
- Costs are the sum of every `modelUsage[].costUSD`; token metrics separately report input, cache write, cache read, output, and their total.
- No existing `benchmark/runs-api` artifact may be overwritten.

## Budget contract

- Use the user's current `$14` remaining credit as the ceiling for this cohort.
- Select one fixed `max_turns` before execution; do not change it per condition.
- Abort before starting if the dry-run estimate exceeds the ceiling; do not silently fall back to OAuth.

## Conditions

`H-ON`, `H-OFF`, `C-FULL`, `C-NON`, `C-BRIEF`, `R-ON`, and `R-OFF`.

## Quality gate

Use the existing 100-point grader: hidden acceptance 60, public regression 10, code 10, documentation 10, and evidence 10. A paired recommendation requires positive token and cost savings, both critical gates passing, and treatment quality no more than five points below baseline.
