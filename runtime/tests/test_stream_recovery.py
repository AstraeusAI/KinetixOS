"""run()'s handling of a mid-stream connection drop that
_stream_openai_chat/_stream_anthropic already salvaged into a
`_stream_truncated` partial reply (see test_providers.py for the salvage
logic itself, one layer down) — the partial text must be journaled, the
task must continue automatically instead of ending, and a persistently
flaky connection must still give up rather than loop forever.
"""
import json
import unittest
from unittest import mock

import support  # noqa: F401

import argusd


class FakeStreamingProvider:
    """Like test_errlog.py's FakeProvider, but returns each scripted reply
    dict as-is instead of always wrapping it under {"choices":[{"message":
    ...}]} — needed here because a truncated reply also carries top-level
    _stream_truncated/_truncation_reason keys alongside "choices"."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0
        self.prompts = []

    def __call__(self, messages, on_event):
        self.calls += 1
        self.prompts.append(messages)
        if not self.replies:
            raise AssertionError("provider was called more times than scripted")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def truncated(text, reason="connection reset"):
    return {"choices": [{"message": {"content": text, "tool_calls": []}}],
            "_stream_truncated": True, "_truncation_reason": reason}


def ok(text="", tool_calls=None):
    return {"choices": [{"message": {"content": text, "tool_calls": tool_calls or []}}]}


def _assistant_texts(session):
    db = argusd.connect()
    rows = db.execute("SELECT payload FROM events WHERE session=? AND kind='assistant' "
                      "ORDER BY id", (session,)).fetchall()
    return [json.loads(p).get("text", "") for (p,) in rows]


class StreamTruncationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.ws = support.make_workspace("ws-stream-recovery")
        self.session = "trunc-" + self._testMethodName

    def test_a_truncated_replys_partial_text_is_journaled(self):
        provider = FakeStreamingProvider(
            truncated("Here is the partial ans"),
            ok("Here is the partial answer, completed."),
        )
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("write something", self.session, str(self.ws))
        self.assertTrue(result["ok"], result)
        self.assertEqual(2, provider.calls)
        self.assertIn("Here is the partial ans", _assistant_texts(self.session))

    def test_the_task_finishes_normally_after_recovering(self):
        provider = FakeStreamingProvider(truncated("partial"), ok("all done"))
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("do the thing", self.session, str(self.ws))
        self.assertTrue(result["ok"])
        self.assertEqual("all done", result["text"])

    def test_the_model_is_told_to_continue_not_given_a_bare_repeat(self):
        provider = FakeStreamingProvider(truncated("partial"), ok("done"))
        with mock.patch.object(argusd, "provider_call", provider):
            argusd.run("do the thing", self.session, str(self.ws))
        # The second call's context must contain a continuation instruction,
        # not just silently resend the original task as if nothing happened.
        second_prompt = provider.prompts[1]
        joined = "\n".join(m["content"] for m in second_prompt
                           if isinstance(m.get("content"), str))
        self.assertIn("cut off", joined.lower())

    def test_multiple_recoveries_in_one_task_all_get_journaled(self):
        provider = FakeStreamingProvider(
            truncated("first chunk"), truncated("second chunk"), ok("final"))
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("a long task", self.session, str(self.ws))
        self.assertTrue(result["ok"])
        self.assertEqual(3, provider.calls)
        texts = _assistant_texts(self.session)
        self.assertIn("first chunk", texts)
        self.assertIn("second chunk", texts)

    def test_a_persistently_flaky_connection_gives_up_instead_of_looping_forever(self):
        with mock.patch.object(argusd, "MAX_STREAM_TRUNCATIONS", 2):
            provider = FakeStreamingProvider(
                truncated("a"), truncated("b"), truncated("c"))
            with mock.patch.object(argusd, "provider_call", provider):
                result = argusd.run("do the thing", self.session, str(self.ws))
        self.assertFalse(result["ok"])
        self.assertEqual(3, provider.calls)
        self.assertIn("kept dropping", result["text"])

    def test_an_empty_truncated_reply_journals_nothing_but_still_continues(self):
        """A drop before even the first token streamed still salvages
        (nothing to salvage means _stream_openai_chat raises instead — this
        covers the case where the *text* itself is empty but the marker is
        set some other way; run() must not choke on an empty string)."""
        provider = FakeStreamingProvider(truncated(""), ok("done"))
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("do the thing", self.session, str(self.ws))
        self.assertTrue(result["ok"])
        self.assertEqual(2, provider.calls)


if __name__ == "__main__":
    unittest.main()
