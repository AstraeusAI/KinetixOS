"""Session history: listing past conversations and reconstructing a
human-readable transcript for the Agent Panel's History tab.
"""
import unittest

import support  # noqa: F401

import argusd


class ListSessionsTests(unittest.TestCase):
    def setUp(self):
        self.db = argusd.connect()

    def test_a_session_is_listed_with_its_first_message_as_title(self):
        session = "hist-" + self._testMethodName
        argusd.event(self.db, session, "user", {"text": "help me refactor the parser"})
        argusd.event(self.db, session, "assistant", {"text": "sure, let's look at it"})
        rows = {r["session"]: r for r in argusd.list_sessions(self.db)}
        self.assertIn(session, rows)
        self.assertEqual("help me refactor the parser", rows[session]["title"])
        self.assertEqual(2, rows[session]["events"])

    def test_newest_session_sorts_first(self):
        older, newer = ("hist-old"
            "-") + self._testMethodName, "hist-new-" + self._testMethodName
        argusd.event(self.db, older, "user", {"text": "first"})
        argusd.event(self.db, newer, "user", {"text": "second"})
        sessions = [r["session"] for r in argusd.list_sessions(self.db)]
        self.assertLess(sessions.index(newer), sessions.index(older))

    def test_a_session_with_no_user_or_assistant_events_is_not_listed(self):
        session = "hist-toolonly-" + self._testMethodName
        argusd.event(self.db, session, "tool", {"id": "t1", "name": "read_file",
                                                "result": {"ok": True}})
        sessions = [r["session"] for r in argusd.list_sessions(self.db)]
        self.assertNotIn(session, sessions)

    def test_title_falls_back_to_current_task_if_the_first_event_is_malformed(self):
        session = "hist-fallback-" + self._testMethodName
        self.db.execute("INSERT INTO events(ts,session,kind,payload) VALUES(?,?,?,?)",
                        (argusd.now(), session, "user", "not json"))
        self.db.commit()
        argusd.set_state(self.db, session, "current_task", "the real task")
        rows = {r["session"]: r for r in argusd.list_sessions(self.db)}
        self.assertEqual("the real task", rows[session]["title"])


class SessionTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.db = argusd.connect()

    def test_transcript_is_role_and_text_only_no_tool_calls(self):
        session = "hist-tx-" + self._testMethodName
        argusd.event(self.db, session, "user", {"text": "list the files"})
        argusd.event(self.db, session, "assistant", {"text": "", "tool_calls": [
            {"id": "c1", "function": {"name": "list_dir", "arguments": "{}"}}]})
        argusd.event(self.db, session, "tool", {"id": "c1", "name": "list_dir",
                                                "result": {"ok": True, "entrie"
                                                    "s": ["a.py"]}})
        argusd.event(self.db, session, "assistant", {"text": "found a.py"})
        tx = argusd.session_transcript(self.db, session)
        self.assertEqual([("user", "list the files"), ("assistant", "found a.py")],
                         [(m["role"], m["text"]) for m in tx])

    def test_an_empty_assistant_turn_is_skipped_not_a_blank_bubble(self):
        """A turn that was pure tool calls has text="" — nothing worth showing."""
        session = "hist-empty-" + self._testMethodName
        argusd.event(self.db, session, "user", {"text": "do the thing"})
        argusd.event(self.db, session, "assistant", {"text": "", "tool_calls": [
            {"id": "c1", "function": {"name": "list_dir", "arguments": "{}"}}]})
        tx = argusd.session_transcript(self.db, session)
        self.assertEqual(["user"], [m["role"] for m in tx])

    def test_a_compacted_sessions_archived_messages_still_appear(self):
        """compact() moves old rows into archived_events — the transcript
        has to read both tables, in chronological order, or resuming an old
        session would show only its most recent tail."""
        session = "hist-archived-" + self._testMethodName
        for i in range(argusd.MAX_CONTEXT_EVENTS // 2 + 1):
            argusd.event(self.db, session, "user", {"text": f"turn {i} " + "x" * 200})
            argusd.event(self.db, session, "assistant", {"text": f"reply {i}"})
        report = argusd.compact(self.db, session)
        self.assertIsNotNone(report, "seed should have been large enough to trigger "
            "compaction")
        tx = argusd.session_transcript(self.db, session)
        self.assertIn("turn 0 " + "x" * 200, [m["text"] for m in tx])
        self.assertEqual(sorted(tx, key=lambda m: m["ts"]), tx, "transcript stays "
            "chronological")


if __name__ == "__main__":
    unittest.main()
