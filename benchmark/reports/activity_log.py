"""Turn-level token accounting extracted from a Claude Code transcript.

The published CSV records one row per run, which cannot answer "which activity
spent the tokens".  Every number here is read from the provider-reported
``usage`` block; nothing is estimated.
"""

from dataclasses import dataclass, replace
import json
from pathlib import Path


@dataclass(frozen=True)
class Turn:
    index: int
    tools: tuple
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int
    context_tokens: int
    result_tokens: int
    discarded_tokens: int = 0
    compacted: bool = False
    context_tax_tokens: int = 0


def _int(mapping, key):
    return int(mapping.get(key, 0) or 0)


def _assistant_messages(path):
    """Collapse the transcript into one usage record per assistant message.

    Claude Code writes one JSONL line per content block and repeats the whole
    ``usage`` object on each of them.  Sub-agent turns are skipped: they run on
    their own context, so mixing them into this one's growth would attribute a
    sub-agent's prompt to whichever tool the main thread called next.
    """
    usages = {}
    tools = {}
    order = []
    for line in Path(path).read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        message = row.get("message", {})
        message_id = message.get("id")
        usage = message.get("usage")
        if not message_id or not usage:
            continue
        if message_id not in usages:
            usages[message_id] = usage
            tools[message_id] = []
            order.append(message_id)
        for block in message.get("content", []):
            if block.get("type") == "tool_use":
                tools[message_id].append(block.get("name"))
    return [(usages[key], tuple(tools[key])) for key in order]


def extract_turns(path):
    """Return one Turn per assistant message, in transcript order.

    A tool called on turn N has its result appear in turn N+1's context, so the
    size is charged back to turn N -- the turn that caused it.  Recording it on
    N+1 would pair it with whatever tool that turn happened to call.
    """
    messages = _assistant_messages(path)
    contexts = [
        _int(usage, "input_tokens")
        + _int(usage, "cache_creation_input_tokens")
        + _int(usage, "cache_read_input_tokens")
        for usage, _ in messages
    ]
    turns = []
    for position, (usage, tools) in enumerate(messages):
        output = _int(usage, "output_tokens")
        following = position + 1
        result = 0
        discarded = 0
        compacted = False
        if following < len(messages):
            growth = contexts[following] - contexts[position]
            result = max(0, growth - output)
            # Whatever the two known causes cannot explain is recorded as its own
            # share instead of being clamped away, so the breakdown always adds
            # up to what the provider charged.  A negative remainder means the
            # context shrank -- context was dropped mid-run.
            discarded = growth - output - result
            compacted = discarded < 0
        turns.append(Turn(
            index=position + 1,
            tools=tools,
            input_tokens=_int(usage, "input_tokens"),
            cache_creation_tokens=_int(usage, "cache_creation_input_tokens"),
            cache_read_tokens=_int(usage, "cache_read_input_tokens"),
            output_tokens=output,
            context_tokens=contexts[position],
            result_tokens=result,
            discarded_tokens=discarded,
            compacted=compacted,
        ))
    return turns


def with_context_tax(turns):
    """Charge each tool result for every later turn that has to reread it.

    A 3,000-token command output on turn 20 of a 40-turn run is not a
    3,000-token event.  It is reloaded as cache-read input on all 20 remaining
    turns, so the run pays 60,000.  This is the quantity the context-trimming
    tools actually attack, and the run total hides it completely.
    """
    total = len(turns)
    return [
        replace(turn, context_tax_tokens=turn.result_tokens * (total - turn.index))
        for turn in turns
    ]


def reconcile(turns):
    """Split the reread context into the three things that can cause it.

    Returns the shares plus what the provider actually reread.  ``balanced``
    says whether they agree: a run where they do not is not merely approximate,
    it is a run whose per-activity breakdown cannot be published.
    """
    total = len(turns)
    shares = {
        "opening": turns[0].context_tokens * (total - 1) if turns else 0,
        "output": sum(turn.output_tokens * (total - turn.index) for turn in turns[:-1]),
        "tool_result": sum(turn.result_tokens * (total - turn.index) for turn in turns),
        "discarded": sum(turn.discarded_tokens * (total - turn.index) for turn in turns),
    }
    observed = sum(turn.context_tokens for turn in turns[1:])
    shares["observed"] = observed
    shares["balanced"] = sum(
        shares[name] for name in ("opening", "output", "tool_result", "discarded")
    ) == observed
    return shares


def is_measurable(turns):
    """A run is publishable only if its breakdown adds up and nothing compacted.

    The breakdown balances either way, but context tax does not survive
    compaction: a result discarded mid-run is not reread by the turns that
    follow it, so its tax is overstated and cannot be recovered from the
    transcript.  Publishing it would overstate exactly the number the page
    is built around.
    """
    return bool(turns) and reconcile(turns)["balanced"] and not any(
        turn.compacted for turn in turns
    )


ACTIVITY_COLUMNS = (
    "run_date", "run_id", "condition", "turn", "tools", "input_tokens",
    "cache_creation_tokens", "cache_read_tokens", "output_tokens",
    "context_tokens", "result_tokens", "discarded_tokens",
    "context_tax_tokens", "compacted",
)


def activity_rows(run_date, run_id, condition, turns):
    return [
        [run_date, run_id, condition, turn.index, " ".join(turn.tools),
         turn.input_tokens, turn.cache_creation_tokens, turn.cache_read_tokens,
         turn.output_tokens, turn.context_tokens, turn.result_tokens,
         turn.discarded_tokens, turn.context_tax_tokens, int(turn.compacted)]
        for turn in turns
    ]
