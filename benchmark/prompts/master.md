# Production implementation task

Work entirely in English. Use English for code comments, documentation, test names, implementation notes, and the final response.

You are taking ownership of an incomplete Kubernetes GPU batch admission service after an incident. Inspect the repository, the API contract, and the incident log before editing. Implement a production-oriented solution rather than returning a prose-only proposal.

Required behavior:

1. Enforce `(user_id, idempotency_key)` idempotency atomically under concurrent submissions.
2. Claim queued jobs by descending priority and FIFO within equal priority.
3. Enforce global GPU concurrency and per-user active-job limits transactionally.
4. Implement worker lease ownership, heartbeat, completion, expiry, bounded retry, and dead-letter transitions.
5. Implement a deterministic Prometheus-style metrics snapshot and structured transition logging.
6. Add a forward migration for all constraints and indexes without destroying existing data.
7. Harden the Kubernetes Deployment with health probes, shutdown behavior, configuration, security context, and explicit resources.
8. Expand unit, integration, and concurrency coverage. Do not modify or weaken existing tests.
9. Update CI, the architecture decision, and the operations runbook. Keep documentation useful but smaller than the code and test changes.

Constraints:

- Use Python 3.9+ and the standard library only.
- Do not access the network or install dependencies.
- Preserve the public API where practical and explain any necessary change.
- Do not remove acceptance requirements or replace real behavior with mocks.
- Run the complete public test suite and inspect the final diff.
- Finish the implementation within 28 turns.

In the final response, report changed files, important design decisions, exact test commands and results, operational limitations, and anything not completed. Do not claim a test passed unless you ran it successfully.
