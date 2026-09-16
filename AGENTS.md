# Agent Rules

Respond in Korean; retain technical terms, commands, and identifiers.
Be brief. No preamble, repeated summary, or reasoning transcript in the output.
Follow the user's requested scope. Review-only requests do not authorize edits.
Commit and push only when requested; obtain the user's review before pushing.

These rules bias toward caution over speed. For a trivial task, use judgment.

## Think Before Coding
- State material assumptions. Ask when ambiguity changes the result or risks
  losing user work; proceed with routine choices within the agreed scope.
- If the request has more than one reading, present them; do not pick silently.
- Explain consequential alternatives and simpler options before committing to one.
- If evidence contradicts the approach, surface it and revise the approach.

## Simplicity First
- Write the minimum code that solves the requested problem.
- No speculative features, single-use abstractions, unrequested flexibility,
  or handling for impossible scenarios.
- Reread what you wrote. If it could be a quarter of the size, rewrite it.

## Surgical Changes
- Touch only what the task requires; every changed line must trace to the
  request. Match the existing style even where you would do it differently.
- Preserve unrelated user changes, code, comments, and formatting. Do not
  refactor what is not broken.
- Remove only unused code your own changes created. Mention pre-existing dead
  code instead of deleting it.

## Goal-Driven Execution
- Define observable success criteria, then loop until they are met. Weak
  criteria ("make it work") force clarification later; strong ones do not.
- For a bug fix, reproduce the failure, fix it, and repeat the check.
- For refactoring, verify behavior before and after.
- Use tests proportionate to the change; report checks not run.
- For multi-step work, state a short plan with a verify step per item; do not
  narrate routine steps.

## Read When Relevant
- Only when the user explicitly asks for a critique, design review, or debate:
  read `.agent/DISCUSSION_RULES.md`. A request to "토론해라" invokes its Codex +
  Claude review workflow. Never enter it for ordinary coding work, and never
  start multi-agent work on your own judgment.
- Creating a document, changing its structure, or writing an engineering
  record: read `.agent/DOCUMENTATION_RULES.md`. Small edits within an existing
  document do not need it.
- Record meaningful investigation, failed experiments, explicit user decisions,
  and design reversals in `.agent/ENGINEERING_LOG/`. Skip routine edits.
  Read-only requests get a proposed entry in the response instead. Logging does
  not authorize commit or push.
