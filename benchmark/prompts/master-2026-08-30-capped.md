# Production implementation task

Work entirely in English. Use English for code comments, documentation, test names, implementation notes, and the final response.

You are taking ownership of an incomplete Kubernetes GPU batch admission service after a production incident. Read the repository, the API contract (`docs/api-contract.md`), and the incident log (`docs/incident-log.txt`) before editing. Deliver a working implementation, not a prose proposal.

## Required behavior

1. Enforce `(user_id, idempotency_key)` idempotency atomically, so concurrent duplicate submissions return the same job instead of creating two.
2. Claim queued jobs by descending priority and FIFO within equal priority.
3. Enforce global GPU concurrency and per-user active-job limits transactionally, and reject over-limit submissions with a typed error rather than a bare exception.
4. Implement the full worker lifecycle: lease ownership, heartbeat, completion, lease expiry, bounded retry with attempt counting, and a dead-letter terminal state.
5. Implement cancellation as `AdmissionService.cancel(job_id)`: a queued job leaves the `queued` state immediately, a running job is marked for cancellation and released on the next heartbeat, and cancelling an already-terminal job raises. Completing an already-terminal job must raise as well.
6. Add a typed error hierarchy in a dedicated module and use it consistently across the service instead of raising `ValueError` or `RuntimeError`.
7. Implement a deterministic Prometheus-style text metrics snapshot exposed as `Metrics().snapshot(store)` (queue depth by priority, jobs by state, lease expiries, retries, dead-letter count) and structured single-line JSON transition logging.
8. Add a `JobStore` maintenance path: a forward SQL migration under `migrations/` that adds every constraint and index the behavior above needs, plus an idempotent in-code migration runner that upgrades an existing database without destroying rows.
9. Add an operator command-line entry point invoked as `python3 -m gpu_platform.cli --database PATH <subcommand>`, exposing at least `submit`, `claim`, `heartbeat`, `complete`, `cancel`, `reap`, and `metrics`. `metrics` must print the snapshot to stdout and exit 0; other exit codes must distinguish user error from conflict.
10. Harden `k8s/deployment.yaml` with liveness/readiness/startup probes, graceful shutdown, configuration through env vars, a non-root security context, and explicit resource requests and limits.
11. Expand test coverage in `tests/`: unit tests for the state machine and errors, integration tests for the store and migration, and concurrency tests that use real threads to prove the idempotency and GPU-limit invariants hold under contention. Do not modify or weaken existing tests.
12. Update `.github/workflows/test.yml`, `docs/decision.md` (the architecture decision), and `docs/operations.md` (the runbook, including the new CLI commands and failure recovery).

## Size and shape

Aim for roughly this distribution of changed lines, and keep the total under 1,000 lines:

| Area | Target |
|---|---|
| Implementation code (`gpu_platform/`, `migrations/`) | 400-500 lines |
| Tests (`tests/`) | 250-350 lines |
| Kubernetes and CI | 40-80 lines |
| Documentation | 80-120 lines |

Documentation must stay smaller than the code and test changes.

## Constraints

- Python 3.9+ and the standard library only. No network access, no new dependencies.
- Preserve the public API where practical, and explain any change you must make.
- Do not remove acceptance requirements and do not replace real behavior with mocks or stubs.
- Run the complete public test suite with `python3 -m unittest discover -s tests -v` and inspect the final diff before you finish.
- You have at most {max_turns} assistant turns. Budget them so the implementation, the test run, and the final report all fit.

## Final response

Report the changed files, the important design decisions and trade-offs, the exact test commands you ran with their results, operational limitations, and anything you did not complete. Do not claim a test passed unless you actually ran it and saw it pass.
