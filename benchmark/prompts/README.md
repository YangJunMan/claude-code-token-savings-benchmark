# Prompts

`master.md` is the prompt to use for reproduction. `{max_turns}` is substituted by
the runner from `benchmark/config.json`, so the prompt can never state a turn
budget different from the one actually enforced.

Two variants were used while the published measurements were collected, and both
are kept here so every published run can be traced to the exact text it received.

| File | sha256 | Used by |
|---|---|---|
| `master.md` | `f7dcb57843acdb0c9572dbbc8db9b1fde5458ce936c1646cf93905c70d434c90` | H-ON, R-ON |
| `master-2026-08-30-capped.md` | `9176443aee4fbde7d986f7f59a77ebf456eeb9c8a40d1d69aa8a57422369242d` | BASE, C-FULL, C-BRIEF |

The only difference is one sentence in the "Size and shape" section:

- capped: `Aim for roughly this distribution of changed lines, and keep the total under 1,000 lines:`
- current: `Aim for roughly this distribution of changed lines. These are guidance, not a limit to spend turns trimming toward:`

The hard cap was removed because runs that tried to honour it spent their
remaining turns trimming already-passing code and were truncated at `max_turns`,
while the runs that finished simply overshot it (1,082-1,123 changed lines). The
cap only penalised the runs that obeyed it.

Because the two variants are not interchangeable, `benchmark/reports/generate.py`
prints a warning when a single report mixes runs with different prompt hashes.
