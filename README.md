# Token Optimizer Benchmark

This repository measures Headroom, Caveman, and RTK on one fixed English Kubernetes GPU platform task. The controller pins Claude Sonnet 5 at medium effort, clears each completed session, and waits 4,200 seconds before the next condition.

```bash
python3 -m unittest discover -s tests -v
python3 -m benchmark.runner.cli preflight
python3 -m benchmark.runner.cli run-all
python3 -m benchmark.runner.cli status
python3 -m benchmark.runner.cli report
```

Raw attempts live under ignored `benchmark/runs/`. Do not treat API-equivalent `costUSD` as an additional Claude Pro charge. Restore user configuration from `benchmark/local-backup/` after the experiment if the Caveman plugin is no longer wanted.
