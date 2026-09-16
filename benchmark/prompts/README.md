# Prompts

`master.md` is the prompt to use for reproduction. `token_bench prepare` copies it
verbatim and appends any `prompt_overlay` a condition declares — there is no
placeholder substitution.

## Current files

| File | sha256 | Used by |
|---|---|---|
| `master.md` | `503f19b8c936511b45bc4cfb3a8a3c8c04dfcbd381fbedc76a5fc0c0edcd8a99` | `--preset small` (default) |
| `preset-large.md` | `c8ed2a04d5872e10969b703892351fcb0be187dbcbd3295d689d2425608db886` | `--preset large` |
| `preset-very-large.md` | `4c310cb877777743a3a514d7cdb94c079f35dfe35063ae3c581769269bd0dbea` | `--preset very-large` |

## Archived variants behind the published measurements

Two variants were in use while `data/activity-log.csv` and the other published
CSVs were collected, and both texts are kept so every published run can be traced
to what it actually received.

| File | sha256 at collection time | Used by |
|---|---|---|
| `master.md` | `f7dcb57843acdb0c9572dbbc8db9b1fde5458ce936c1646cf93905c70d434c90` | HEADROOM, RTK |
| `master-2026-08-30-capped.md` | `9176443aee4fbde7d986f7f59a77ebf456eeb9c8a40d1d69aa8a57422369242d` | BASE, CAVEMAN-FULL, BE_BRIEF |

The only difference between those two is one sentence in the "Size and shape"
section:

- capped: `Aim for roughly this distribution of changed lines, and keep the total under 1,000 lines:`
- current: `Aim for roughly this distribution of changed lines. These are guidance, not a limit to spend turns trimming toward:`

The hard cap was removed because runs that tried to honour it spent their
remaining turns trimming already-passing code and ran out of turns, while the runs
that finished simply overshot it (1,082-1,123 changed lines). The cap only
penalised the runs that obeyed it.

`master.md` has changed since those runs: on 2026-09-15 the line
`You have at most {max_turns} assistant turns...` was removed, because the
installed Claude Code CLI has no flag that enforces a turn count, so the prompt
was stating a budget nothing held it to. That is why the hash above differs from
the archived one. Runs prepared from now on receive the shorter text; the
published measurements were collected with the older one.

`master-2026-08-30-capped.md` is kept as an archive of what past runs received. It
still contains the `{max_turns}` placeholder, which is no longer substituted — do
not feed it to `--prompt` expecting the old behaviour.
