import json
import tempfile
import unittest
from pathlib import Path

from benchmark.reports.activity_log import (
    extract_turns, is_measurable, reconcile, with_context_tax)


def usage(input_tokens=0, cache_creation=0, cache_read=0, output=0):
    return {
        "input_tokens": input_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "output_tokens": output,
    }


def assistant(message_id, use, blocks):
    return {"type": "assistant",
            "message": {"id": message_id, "usage": use, "content": blocks}}


def tool_use(name):
    return {"type": "tool_use", "id": "t-" + name, "name": name, "input": {}}


def write_transcript(rows):
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for row in rows:
        handle.write(json.dumps(row) + "\n")
    handle.close()
    return Path(handle.name)


class ExtractTurnsTest(unittest.TestCase):
    def test_repeated_message_id_counts_as_one_turn(self):
        """Claude Code writes one line per content block, repeating the usage.

        Counting lines would multiply a single turn's tokens by its block count.
        """
        shared = usage(cache_creation=100, output=10)
        path = write_transcript([
            assistant("msg-1", shared, [{"type": "thinking", "thinking": "..."}]),
            assistant("msg-1", shared, [tool_use("Bash")]),
            assistant("msg-1", shared, [tool_use("Read")]),
        ])

        turns = extract_turns(path)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].output_tokens, 10)

    def test_collects_every_tool_called_in_one_turn(self):
        """Parallel tool calls arrive as separate lines under one message id."""
        shared = usage(cache_creation=100, output=10)
        path = write_transcript([
            assistant("msg-1", shared, [tool_use("Bash")]),
            assistant("msg-1", shared, [tool_use("Read")]),
        ])

        turns = extract_turns(path)

        self.assertEqual(turns[0].tools, ("Bash", "Read"))

    def test_turn_without_tool_calls_reports_no_tools(self):
        path = write_transcript([
            assistant("msg-1", usage(output=10), [{"type": "text", "text": "done"}]),
        ])

        self.assertEqual(extract_turns(path)[0].tools, ())


class ContextAccountingTest(unittest.TestCase):
    def test_context_tokens_sum_the_three_input_categories(self):
        path = write_transcript([
            assistant("msg-1", usage(input_tokens=2, cache_creation=100,
                                     cache_read=900, output=10), []),
        ])

        self.assertEqual(extract_turns(path)[0].context_tokens, 1002)

    def test_a_result_is_charged_to_the_turn_that_called_the_tool(self):
        """The result of a call made on turn N first appears in turn N+1's
        context.  Recording it on turn N+1 would pair it with whatever tool that
        turn happened to call, which is a different call entirely.

        Between two turns the context grows by exactly what the model wrote plus
        what came back from its tools, so the size is a subtraction of
        provider-reported numbers, never an estimate.
        """
        path = write_transcript([
            assistant("msg-1", usage(cache_creation=1000, output=40), [tool_use("Bash")]),
            assistant("msg-2", usage(cache_creation=500, cache_read=1000, output=10),
                      [tool_use("Read")]),
        ])

        turns = extract_turns(path)

        self.assertEqual(turns[1].context_tokens, 1500)
        self.assertEqual(turns[0].tools, ("Bash",))
        self.assertEqual(turns[0].result_tokens, 460)

    def test_the_opening_context_is_not_charged_to_any_tool(self):
        """The opening context is the system prompt and task, not tool output."""
        path = write_transcript([
            assistant("msg-1", usage(cache_creation=30000, output=40), [tool_use("Bash")]),
        ])

        turns = extract_turns(path)

        self.assertEqual(turns[0].context_tokens, 30000)
        self.assertEqual(turns[0].result_tokens, 0)

    def test_the_last_turn_has_no_observed_result(self):
        """Nothing follows it, so its result size is unknown rather than zero-
        sized; recording a guess would be an estimate."""
        path = write_transcript([
            assistant("msg-1", usage(cache_creation=1000, output=40), [tool_use("Bash")]),
            assistant("msg-2", usage(cache_creation=500, cache_read=1000, output=10),
                      [tool_use("Read")]),
        ])

        self.assertEqual(extract_turns(path)[-1].result_tokens, 0)


class ContextTaxTest(unittest.TestCase):
    """What a tool result costs is not its size; it is its size times how many
    turns still have to carry it."""

    def test_tax_is_size_times_the_turns_that_still_reread_it(self):
        path = write_transcript([
            assistant("msg-1", usage(cache_creation=1000, output=0), [tool_use("Bash")]),
            assistant("msg-2", usage(cache_creation=100, cache_read=1000, output=0), []),
            assistant("msg-3", usage(cache_read=1100, output=0), []),
            assistant("msg-4", usage(cache_read=1100, output=0), []),
        ])

        turns = with_context_tax(extract_turns(path))

        # Turn 1's call pulled in 100 tokens; turns 2, 3 and 4 all reread them.
        self.assertEqual(turns[0].result_tokens, 100)
        self.assertEqual(turns[0].context_tax_tokens, 300)

    def test_last_turn_result_is_never_reread(self):
        path = write_transcript([
            assistant("msg-1", usage(cache_creation=1000, output=0), [tool_use("Bash")]),
            assistant("msg-2", usage(cache_creation=500, cache_read=1000, output=0), []),
        ])

        turns = with_context_tax(extract_turns(path))

        self.assertEqual(turns[-1].context_tax_tokens, 0)


class ReconcileTest(unittest.TestCase):
    """The split into opening / output / tool-result must add up to what the
    provider actually charged, or the page would be showing invented shares."""

    def test_the_three_shares_equal_the_context_the_provider_reread(self):
        path = write_transcript([
            assistant("msg-1", usage(cache_creation=1000, output=40), [tool_use("Bash")]),
            assistant("msg-2", usage(cache_creation=460, cache_read=1000, output=25), [tool_use("Read")]),
            assistant("msg-3", usage(cache_creation=75, cache_read=1460, output=10), []),
        ])
        turns = with_context_tax(extract_turns(path))

        shares = reconcile(turns)

        self.assertEqual(
            shares["opening"] + shares["output"] + shares["tool_result"],
            sum(turn.context_tokens for turn in turns[1:]),
        )

    def test_reconcile_attributes_the_opening_context_to_every_later_turn(self):
        path = write_transcript([
            assistant("msg-1", usage(cache_creation=1000, output=0), []),
            assistant("msg-2", usage(cache_read=1000, output=0), []),
            assistant("msg-3", usage(cache_read=1000, output=0), []),
        ])

        self.assertEqual(reconcile(with_context_tax(extract_turns(path)))["opening"], 2000)


class ValidityTest(unittest.TestCase):
    """The page's whole claim is that its breakdown equals what was charged.
    A run that cannot support that claim must be excluded, not smoothed over."""

    def test_a_clean_run_is_measurable(self):
        path = write_transcript([
            assistant("msg-1", usage(cache_creation=1000, output=40), [tool_use("Bash")]),
            assistant("msg-2", usage(cache_creation=460, cache_read=1000, output=25), []),
            assistant("msg-3", usage(cache_creation=25, cache_read=1460, output=10), []),
        ])

        turns = with_context_tax(extract_turns(path))

        self.assertTrue(reconcile(turns)["balanced"])
        self.assertTrue(is_measurable(turns))

    def test_discarded_context_is_accounted_for_rather_than_left_as_a_gap(self):
        """A shrinking context must appear as its own share.  Leaving it out
        would show a breakdown that silently disagrees with the provider, which
        is exactly the kind of unverifiable number this repository exists to
        reject."""
        path = write_transcript([
            assistant("msg-1", usage(cache_creation=100000, output=500), [tool_use("Bash")]),
            assistant("msg-2", usage(cache_read=100000, cache_creation=2000, output=400), []),
            assistant("msg-3", usage(cache_read=20000, cache_creation=500, output=300), []),
            assistant("msg-4", usage(cache_read=20500, cache_creation=300, output=200), []),
        ])

        shares = reconcile(with_context_tax(extract_turns(path)))

        self.assertTrue(shares["balanced"])
        self.assertLess(shares["discarded"], 0)

    def test_compaction_is_flagged_instead_of_being_clamped_away(self):
        """The breakdown still balances, but context tax cannot be trusted: a
        result that was discarded mid-run was not reread by the turns that
        follow it, so its tax is overstated and unrecoverable."""
        path = write_transcript([
            assistant("msg-1", usage(cache_creation=100000, output=500), [tool_use("Bash")]),
            assistant("msg-2", usage(cache_read=100000, cache_creation=2000, output=400), []),
            assistant("msg-3", usage(cache_read=20000, cache_creation=500, output=300), []),
            assistant("msg-4", usage(cache_read=20500, cache_creation=300, output=200), []),
        ])

        turns = with_context_tax(extract_turns(path))

        self.assertTrue(turns[1].compacted)
        self.assertFalse(is_measurable(turns))

    def test_subagent_turns_are_excluded_from_the_main_context(self):
        """A sub-agent runs on its own context; counting its prompt as growth
        would charge it to whichever tool the main thread called next."""
        main_only = write_transcript([
            assistant("msg-1", usage(cache_creation=1000, output=100), [tool_use("Task")]),
            assistant("msg-2", usage(cache_read=1000, cache_creation=200, output=100), []),
        ])
        with_sidechain = write_transcript([
            assistant("msg-1", usage(cache_creation=1000, output=100), [tool_use("Task")]),
            dict(assistant("sub-1", usage(cache_creation=50000, output=100), []),
                 isSidechain=True),
            assistant("msg-2", usage(cache_read=1000, cache_creation=200, output=100), []),
        ])

        self.assertEqual(
            [turn.result_tokens for turn in extract_turns(with_sidechain)],
            [turn.result_tokens for turn in extract_turns(main_only)],
        )


if __name__ == "__main__":
    unittest.main()
