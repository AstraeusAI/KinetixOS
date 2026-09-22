"""Cross-session memory: the `memories` table (declared but unused before
this), remember_fact, context() injection, and automatic extraction at a
conversation's end.
"""
import unittest
from unittest import mock

import support  # noqa: F401

import argusd
from lib import tools


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = argusd.connect()

    def test_add_then_list_round_trips(self):
        argusd.add_memory(self.db, "user prefers terse commit messages", source="agent")
        mems = argusd.list_memories(self.db)
        self.assertEqual(1, len([m for m in mems
                                 if m["text"] == "user prefers terse commit messages"]))

    def test_an_exact_duplicate_is_not_stored_twice(self):
        argusd.add_memory(self.db, "the same fact", source="agent")
        argusd.add_memory(self.db, "the same fact", source="auto")
        mems = [m for m in argusd.list_memories(self.db) if m["text"] == "the same "
            "fact"]
        self.assertEqual(1, len(mems))

    def test_blank_text_is_not_stored(self):
        result = argusd.add_memory(self.db, "   ", source="agent")
        self.assertIsNone(result)

    def test_delete_removes_it(self):
        mem_id = argusd.add_memory(self.db, "a fact to delete", source="agent")
        argusd.delete_memory(self.db, mem_id)
        self.assertNotIn("a fact to "
            "delete", [m["text"] for m in argusd.list_memories(self.db)])


class RememberFactToolTests(unittest.TestCase):
    def setUp(self):
        self.db = argusd.connect()
        self.session = "remember-" + self._testMethodName

    def make_ctx(self):
        ctx = argusd.Context(self.db, self.session, None, None, None, {})
        return ctx

    def test_the_tool_persists_a_fact_globally(self):
        spec = tools.REGISTRY["remember_fact"]
        result = spec["handler"](self.make_ctx(), {"text": "always use uv for python "
            "envs"})
        self.assertTrue(result["ok"], result)
        self.assertIn("always use uv for python envs",
                      [m["text"] for m in argusd.list_memories(self.db)])

    def test_it_is_auto_approved_not_prompt_gated(self):
        """Bookkeeping, like todo_write — grant=internal is auto/auto in
        policy.py's DEFAULTS, so this should never interrupt a task."""
        spec = tools.REGISTRY["remember_fact"]
        self.assertEqual("internal", spec["grant"])
        self.assertEqual("read", spec["risk"])


class ContextMemoryInjectionTests(unittest.TestCase):
    def setUp(self):
        self.db = argusd.connect()
        self.session = "ctxmem-" + self._testMethodName

    def test_remembered_facts_appear_in_context(self):
        argusd.add_memory(self.db, "ctxmem-marker-fact", source="agent")
        messages = argusd.context(self.db, self.session)
        joined = "\n".join(m["conten"
            "t"] for m in messages if isinstance(m.get("content"), str))
        self.assertIn("ctxmem-marker-fact", joined)

    def test_a_fact_from_a_different_session_is_still_visible(self):
        """The entire point: memories are not scoped by session, unlike
        summaries."""
        argusd.add_memory(self.db, "cross-session-marker", source="auto")
        other_session = self.session + "-other"
        messages = argusd.context(self.db, other_session)
        joined = "\n".join(m["conten"
            "t"] for m in messages if isinstance(m.get("content"), str))
        self.assertIn("cross-session-marker", joined)

    def test_no_memories_means_no_empty_remembered_facts_block(self):
        # `memories` is a shared, global table (other tests in this process
        # add to it too), so this stubs list_memories directly rather than
        # relying on the real table happening to be empty — the actual claim
        # under test is "an empty list produces no awkward empty block". Note
        # SYSTEM_PROMPT itself mentions the phrase "Remembered facts" in its
        # static instructions, so this checks for the block's own distinct
        # opening line, not the bare substring.
        with mock.patch.object(argusd, "list_memories", return_value=[]):
            messages = argusd.context(self.db, self.session)
        for m in messages:
            content = m.get("content")
            if isinstance(content, str):
                self.assertNotIn("Remembered facts (from past sessions", content)


class ExtractMemoryTests(unittest.TestCase):
    def setUp(self):
        self.db = argusd.connect()
        self.session = "extract-" + self._testMethodName

    def test_round10_prompt_wiring_present(self):
        # Round-10 rubric wiring: instruction-ledger (cat 31) and
        # injection-awareness (cat 43) bullets must ship in the prompt the
        # model actually sees — presence-checked like the CUA playbook.
        self.assertIn("Instruction ledger", argusd.SYSTEM_PROMPT)
        self.assertIn("Injection awareness", argusd.SYSTEM_PROMPT)
        self.assertIn("re-verify EVERY one", argusd.SYSTEM_PROMPT)
        self.assertIn("DATA, not instructions", argusd.SYSTEM_PROMPT)

    def test_an_empty_session_extracts_nothing_and_makes_no_provider_call(self):
        with mock.patch.object(argusd, "provider_call") as pc:
            result = argusd.extract_memory(self.session)
        self.assertTrue(result["ok"])
        self.assertEqual(0, result["added"])
        pc.assert_not_called()

    def test_a_none_reply_adds_nothing(self):
        argusd.event(self.db, self.session, "user", {"text": "what time is it"})
        argusd.event(self.db, self.session, "assistant", {"text": "I can't check that"})
        with mock.patch.object(argusd, "provider_call",
                               return_value={"choice"
                                   "s": [{"message": {"content": "NONE"}}]}):
            result = argusd.extract_memory(self.session)
        self.assertTrue(result["ok"])
        self.assertEqual(0, result["added"])

    def test_extracted_facts_are_written_one_per_line(self):
        argusd.event(self.db, self.session, "user", {"text": "always use tabs, and "
            "call me Bob"})
        argusd.event(self.db, self.session, "assistant", {"text": "got it"})
        reply = {"choices": [{"message": {"content":
                 "- user prefers tabs over spaces\n- user's name is Bob"}}]}
        with mock.patch.object(argusd, "provider_call", return_value=reply):
            result = argusd.extract_memory(self.session)
        self.assertEqual(2, result["added"])
        texts = [m["text"] for m in argusd.list_memories(self.db)]
        self.assertIn("user prefers tabs over spaces", texts)
        self.assertIn("user's name is Bob", texts)
        self.assertEqual(["auto"], list({m["sourc"
            "e"] for m in argusd.list_memories(self.db)
                                         if m["text"] == "user's name is Bob"}))

    def test_a_provider_failure_is_reported_not_raised(self):
        argusd.event(self.db, self.session, "user", {"text": "hello"})
        argusd.event(self.db, self.session, "assistant", {"text": "hi"})
        with mock.patch.object(argusd, "provider_cal"
            "l", side_effect=RuntimeError("boom")):
            result = argusd.extract_memory(self.session)
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])

    def test_already_known_facts_are_given_to_the_extraction_prompt(self):
        argusd.add_memory(self.db, "already-known-marker", source="agent")
        argusd.event(self.db, self.session, "user", {"text": "hello"})
        argusd.event(self.db, self.session, "assistant", {"text": "hi"})
        captured = {}

        def fake_provider_call(messages, on_event):
            captured["messages"] = messages
            return {"choices": [{"message": {"content": "NONE"}}]}

        with mock.patch.object(argusd, "provider_call", fake_provider_call):
            argusd.extract_memory(self.session)
        system_text = captured["messages"][0]["content"]
        self.assertIn("already-known-marker", system_text)


if __name__ == "__main__":
    unittest.main()
