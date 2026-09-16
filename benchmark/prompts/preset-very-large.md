# Production implementation task (very large preset)

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

### Additional required behavior (large preset)

13. Add weighted fair-share scheduling on top of priority/FIFO: track recent GPU-second consumption per user in `JobStore` and let `AdmissionService.claim_next` prefer users under their fair share when priorities tie, with a documented tie-break when shares tie too.
14. Add a job dependency graph: `AdmissionService.submit` accepts an optional `depends_on: list[job_id]`, a dependent job cannot be claimed until all its dependencies reach a terminal success state, a failed/dead-lettered dependency must transition dependents to a new `blocked` terminal state (not silently keep them queued forever), and cyclic dependencies must be rejected at submission time with a typed error.
15. Add a second Prometheus-style metric family for fair-share and dependency-graph state (per-user consumed share, blocked-job count, longest pending dependency chain depth) and extend the transition log schema with a `caused_by` field that names the triggering event (heartbeat, lease expiry, dependency resolution, operator command).
16. Add an admin CLI subcommand `requeue` that moves a `dead_letter` job back to `queued` with a reset attempt counter, only when explicitly forced, and that records the operator action in the transition log distinctly from automatic transitions.
17. Add a `docs/scheduling.md` design document explaining the fair-share algorithm, its complexity, and the dependency-graph cycle-detection approach, with at least one worked numeric example.
18. Extend `k8s/deployment.yaml` with a `PodDisruptionBudget` and a `HorizontalPodAutoscaler` driven by the new queue-depth metric, and explain in `docs/operations.md` how they interact with graceful shutdown during a scale-down.

### Additional required behavior (very large preset)

19. Add GPU device-class awareness: jobs declare a requested `gpu_class` (e.g. `a100`, `h100`), the store tracks per-class capacity separately, `AdmissionService.submit` must reject a class it does not recognize with a typed error, and the fair-share and dependency logic from items 13-14 must be computed per class, not globally — write out why a naive global computation would be wrong and prevent that mistake in code (e.g. with a lint-style test, not just a comment).
20. Add a preemption policy: a job submitted with a `preemptible=False` flag above a configurable priority threshold may preempt a running `preemptible=True` job of the same GPU class when capacity is exhausted; the preempted job returns to `queued` with its attempt counter unchanged and a `preempted_at` timestamp recorded, and a job may not be preempted more than a configurable number of times before it is dead-lettered instead.
21. Add a budget-tracking subsystem: each user has a monthly GPU-second budget; `AdmissionService.submit` rejects submissions once bucket + max, in-flight active-job GPU-second estimate would exceed the remaining budget, using pessimistic estimation, and expose a `budget` CLI subcommand and metrics snapshot fields for remaining budget per user and total over-budget rejection count.
22. Add a replay/audit log: every state transition (including preemption, budget rejection, and dependency-blocked transitions) must be appended to an append-only `audit_log` table with a monotonic sequence number, and add a `replay` CLI subcommand that reconstructs the current `jobs` table state from only the audit log and asserts it matches the live table (a real, runnable consistency check, not a docstring claim).
23. Add a second SQL migration (on top of the one in item 8) introducing the class-capacity, preemption, budget, and audit-log schema, with its own idempotent upgrade path that composes correctly after the first migration has already been applied to an existing database — write an integration test that applies both migrations in sequence to a database seeded with pre-existing rows and checks no rows are lost or corrupted.
24. Add a `docs/capacity-planning.md` document covering device-class capacity planning, preemption trade-offs, and budget exhaustion runbook steps, and a `docs/audit.md` document covering how to use the `replay` subcommand during an incident.
25. Extend the concurrency tests from item 11 to cover preemption and budget rejection under real concurrent threads (not just sequential unit tests), proving that two threads racing to submit against a nearly-exhausted budget cannot both succeed when only one should.

## Size and shape

Aim for roughly this distribution of changed lines. These are guidance, not a limit to spend turns trimming toward:

| Area | Target |
|---|---|
| Implementation code (`gpu_platform/`, `migrations/`) | 1100-1400 lines |
| Tests (`tests/`) | 700-950 lines |
| Kubernetes and CI | 100-160 lines |
| Documentation | 250-350 lines |

Documentation must stay smaller than the code and test changes.

## Constraints

- Python 3.9+ and the standard library only. No network access, no new dependencies.
- Preserve the public API where practical, and explain any change you must make.
- Do not remove acceptance requirements and do not replace real behavior with mocks or stubs.
- Run the complete public test suite with `python3 -m unittest discover -s tests -v` and inspect the final diff before you finish.

## Final response

Report the changed files, the important design decisions and trade-offs (especially for per-class fair-share, preemption, and budget tracking), the exact test commands you ran with their results, operational limitations, and anything you did not complete. Do not claim a test passed unless you actually ran it and saw it pass.
