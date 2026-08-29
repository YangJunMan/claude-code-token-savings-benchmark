# GPU Admission API Contract

Submissions are scoped by `(user_id, idempotency_key)`. The same pair must always return the same job, including under concurrent requests. Higher integer priority runs first; equal priority uses FIFO ordering. At most `gpu_limit` jobs may be running. A user may have at most `per_user_limit` non-terminal jobs.

Workers claim one job with a lease, extend only their own lease, and complete only their own running job. An expired lease returns a job to the queue until `max_attempts`; the next expiry moves it to `dead`. Every state transition must be transactional.

Metrics expose queue depth by priority, running jobs, retry count, dead jobs, and idempotency conflicts. Logs are JSON objects with `event`, `job_id`, `user_id`, and transition fields.
