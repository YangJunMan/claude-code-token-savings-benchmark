# Generated benchmark table

> Source: `data/published-measurements.csv`. The tables are reproducible from sanitized aggregates; raw private transcripts are not published.

## Individual runs

| Run | Condition | Cost | Processed tokens | Output tokens | Quality | Critical | Turns | Validation |
|---|---|---:|---:|---:|---:|---:|---:|---|
| BASE-01 | BASE | $1.799 | 2,475,482 | 51,826 | 96 | 5/6 | 30 | held-out grader |
| BASE-02 | BASE | $1.984 | 3,089,387 | 47,645 | 96 | 5/6 | 41 | held-out grader |
| H-ON-01 | H-ON | $1.218 | 1,407,679 | 35,311 | 98 | 6/6 | 28 | held-out grader |
| H-ON-02 | H-ON | $1.567 | 2,116,352 | 44,596 | not scored | not scored | 48 | public tests passed; held-out grader not run |
| C-FULL | C-FULL | $1.960 | 3,191,468 | 48,657 | 100 | 6/6 | 39 | held-out grader |
| C-BRIEF | C-BRIEF | $1.510 | 2,307,237 | 39,820 | 96 | 5/6 | 33 | held-out grader |
| R-ON | R-ON | $1.580 | 1,944,432 | 45,300 | 98 | 6/6 | 26 | held-out grader |

## Condition means

| Condition | Cost | Processed tokens | Output tokens | Observations |
|---|---:|---:|---:|---:|
| BASE mean (n=2) | $1.892 | 2,782,435 | 49,736 | 2 |
| H-ON mean (n=2) | $1.393 | 1,762,016 | 39,954 | 2 |
| C-FULL (n=1) | $1.960 | 3,191,468 | 48,657 | 1 |
| C-BRIEF (n=1) | $1.510 | 2,307,237 | 39,820 | 1 |
| R-ON (n=1) | $1.580 | 1,944,432 | 45,300 | 1 |

## Relative to the two-run baseline mean

| Condition | Cost saving | Processed-token saving | Output-token saving |
|---|---:|---:|---:|
| H-ON | +26.4% | +36.7% | +19.7% |
| C-FULL | -3.6% | -14.7% | +2.2% |
| C-BRIEF | +20.2% | +17.1% | +19.9% |
| R-ON | +16.5% | +30.1% | +8.9% |

## Headroom repeat diagnostics

| Metric | H-ON vs BASE | H-ON spread | BASE spread | Ranges overlap | Assessment |
|---|---:|---:|---:|---|---|
| Total cost | -26.4% | 25.1% | 9.8% | No | Borderline |
| Cost per turn | -29.7% | 28.5% | 21.4% | No | Borderline |
| Context per turn | -41.4% | 10.6% | 8.4% | No | Robust |
| Output tokens | -19.7% | 23.2% | 8.4% | No | Within noise |

The original single H-ON observation overstated cost saving as 35.6%. With two H-ON runs, the mean cost saving is 26.4% and the within-condition spread is 25.1%, so cost is a borderline signal.

Context per turn is the more stable mechanism metric: H-ON reduced it by 41.4%, the H-ON spread was 10.6%, and neither H-ON value overlapped the BASE range.

H-ON-02 passed the public test suite but was not run through the held-out grader. Quality 98 and critical 6/6 therefore describe H-ON-01 only, not the two-run mean.
