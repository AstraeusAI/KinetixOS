"""What the model actually receives: tool-result size/shape, compaction."""
import base64
import json
import unittest
from unittest import mock

import support  # noqa: F401

import argusd
from lib.workspace import Workspace

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/AL+2QAAAABJRU5ErkJggg==")


def _blocks(message):
    """The content blocks of a message, or [] when it is a plain string."""
    content = message.get("content")
    return content if isinstance(content, list) else []


class ToolResultTextTests(unittest.TestCase):
    def test_small_results_are_unchanged(self):
        result = {"ok": True, "path": "a.py", "content": "x = 1"}
        self.assertEqual(result, json.loads(argusd.tool_result_text(result)))

    def test_a_large_result_still_parses(self):
        """Regression: json.dumps(result)[:20000] cut mid-string, so the model
        was handed invalid JSON — `json.loads` raised "Unterminated string"."""
        result = {"ok": True, "path": "big.py", "lines": 900,
                  "content": "\n".join(f"line {i} " + "x" * 80 for i in range(900))}
        text = argusd.tool_result_text(result)
        self.assertLessEqual(len(text), 20_000)
        parsed = json.loads(text)  # must not raise
        self.assertTrue(parsed["ok"])
        self.assertEqual("big.py", parsed["path"])
        self.assertEqual(900, parsed["lines"])

    def test_the_truncation_is_visible_to_the_model(self):
        result = {"ok": True, "content": "y" * 50_000}
        parsed = json.loads(argusd.tool_result_text(result))
        self.assertIn("truncated", parsed["content"])

    def test_a_result_that_cannot_be_clipped_is_replaced_by_valid_json(self):
        result = {f"k{i}": "z" * 4_000 for i in range(20)}  # no metadata keys to keep
        parsed = json.loads(argusd.tool_result_text(result))
        self.assertIsInstance(parsed, dict)


class SafeWindowStartTests(unittest.TestCase):
    """_safe_window_start in isolation — the primitive both compact() and
    context() rely on to never begin a trailing window with an orphaned
    tool result (see the module-level docstring on the function itself for
    the real production incident this fixes)."""

    def test_a_boundary_already_on_a_non_tool_event_is_unchanged(self):
        kinds = ["user", "assistant", "tool", "assistant", "tool"]
        self.assertEqual(3, argusd._safe_window_start(kinds, 3))

    def test_a_boundary_landing_on_a_tool_walks_back_to_its_assistant(self):
        kinds = ["user", "assistant", "tool", "tool", "assistant", "tool"]
        # boundary=2 lands on the first "tool" of a pair whose declaring
        # assistant is at index 1 — must walk back to 1, not stay at 2.
        self.assertEqual(1, argusd._safe_window_start(kinds, 2))

    def test_a_boundary_landing_on_the_second_of_two_tool_results_also_walks_back(self):
        kinds = ["user", "assistant", "tool", "tool", "assistant", "tool"]
        self.assertEqual(1, argusd._safe_window_start(kinds, 3))

    def test_boundary_is_clamped_into_range(self):
        kinds = ["user", "assistant", "tool"]
        self.assertEqual(0, argusd._safe_window_start(kinds, -5))
        self.assertEqual(3, argusd._safe_window_start(kinds, 99))

    def test_an_all_tool_prefix_walks_all_the_way_to_zero_without_erroring(self):
        kinds = ["tool", "tool", "tool"]
        self.assertEqual(0, argusd._safe_window_start(kinds, 2))


class CompactionTests(unittest.TestCase):
    def setUp(self):
        self.db = argusd.connect()
        self.session = f"compact-{id(self)}"

    def seed(self, count=25, tool_ok=True):
        for i in range(count):
            argusd.event(self.db, self.session, "assistant",
                         {"text": f"turn {i} " + "a" * 200})
            argusd.event(self.db, self.session, "tool",
                         {"id": f"t{i}", "name": "edit_file",
                          "result": {"ok": tool_ok, "path": f"f{i}.py",
                                     "error": None if tool_ok else "syntax error"}})

    def test_nothing_is_archived_below_the_threshold(self):
        self.seed(5)
        self.assertIsNone(argusd.compact(self.db, self.session))

    def test_a_long_session_is_archived_and_summarized(self):
        self.seed(argusd.MAX_CONTEXT_EVENTS // 2 + 1)
        report = argusd.compact(self.db, self.session)
        self.assertIsNotNone(report)
        self.assertGreater(report["archivedEvents"], 0)
        kept = self.db.execute("SELECT COUNT(*) FROM events WHERE session=?",
                               (self.session,)).fetchone()[0]
        archived = self.db.execute("SELECT COUNT(*) FROM archived_events WHERE session=?",
                                   (self.session,)).fetchone()[0]
        self.assertEqual(report["archivedEvents"], archived)
        self.assertLessEqual(kept, argusd.KEEP_EVENTS)

    def test_the_summary_keeps_outcomes_not_just_tool_names(self):
        """The old summary stored the event kind and the tool's name, so after a
        compaction the model could not tell a successful edit from a failed one."""
        self.seed(argusd.MAX_CONTEXT_EVENTS // 2 + 1, tool_ok=False)
        argusd.compact(self.db, self.session)
        text = self.db.execute("SELECT text FROM summaries WHERE session=? ORDER BY id DESC LIMIT 1",
                               (self.session,)).fetchone()[0]
        self.assertIn("edit_file FAILED", text)
        self.assertIn("syntax error", text)

    def test_summaries_are_bounded(self):
        self.seed(120)
        for _ in range(3):
            argusd.compact(self.db, self.session)
        for (text,) in self.db.execute("SELECT text FROM summaries WHERE session=?", (self.session,)):
            self.assertLessEqual(len(text), argusd.SUMMARY_CHARS)

    def test_raw_chars_is_tracked_incrementally_not_refetched(self):
        """compact()'s cheap path reads a running counter that event() updates
        in the same transaction as each insert, rather than re-fetching and
        re-joining every event payload in the session on every call — that
        full rejoin made every step of a long task a little slower than the
        last. Confirm the counter actually tracks reality: it should equal a
        length computed the old way (full fetch + join), not just happen to
        produce the same compact()/None outcome by coincidence."""
        self.seed(5)
        rows = self.db.execute("SELECT kind,payload FROM events WHERE session=? ORDER BY id",
                               (self.session,)).fetchall()
        expected = sum(len(k) + 2 + len(p) for k, p in rows)
        tracked = int(argusd.get_state(self.db, self.session, "raw_chars") or 0)
        self.assertEqual(expected, tracked)

    def test_raw_chars_resyncs_after_a_real_compaction(self):
        self.seed(50)
        argusd.compact(self.db, self.session)
        rows = self.db.execute("SELECT kind,payload FROM events WHERE session=? ORDER BY id",
                               (self.session,)).fetchall()
        expected = sum(len(k) + 2 + len(p) for k, p in rows)  # only the kept tail remains
        tracked = int(argusd.get_state(self.db, self.session, "raw_chars") or 0)
        self.assertEqual(expected, tracked)

    def test_the_injected_summaries_count_towards_the_budget(self):
        """compact() used to measure only the events table, while context()
        re-injects the last three summaries on every turn — so the real ceiling
        was MAX_CONTEXT_CHARS plus summary text no trigger could see."""
        self.seed(25)
        self.assertIsNone(argusd.compact(self.db, self.session),
                          "25 small events alone should not trigger compaction")
        oversized = "x" * (argusd.MAX_CONTEXT_CHARS + 1)
        self.db.execute("INSERT INTO summaries(ts,session,until_id,text) VALUES(?,?,?,?)",
                        (argusd.now(), self.session, 0, oversized))
        self.db.commit()
        self.assertIsNotNone(argusd.compact(self.db, self.session),
                             "a summary larger than the whole budget must trigger compaction")

    def test_compaction_never_orphans_a_tool_result_from_its_assistant_call(self):
        """The actual production incident this fixes: compact() archived an
        assistant's tool_calls declaration while leaving its own tool
        results in the kept tail. Every later turn of that session then
        failed identically — "No function call found for function call
        output with call_id ..." — because the provider correctly rejects a
        tool result with no matching call in the same request, and the
        orphaned pair had nowhere to go: it just stayed pinned as the
        permanent head of the window forever.

        Reproduced here by sizing the seed so the naive KEEP_EVENTS-sized
        tail boundary lands exactly between a two-call assistant turn and
        its first tool result — precisely where it landed live.
        """
        with mock.patch.object(argusd, "KEEP_EVENTS", 5), \
             mock.patch.object(argusd, "MAX_CONTEXT_EVENTS", 10):
            for i in range(3):
                argusd.event(self.db, self.session, "user", {"text": f"filler {i}"})
                argusd.event(self.db, self.session, "assistant", {"text": f"ok {i}"})
            argusd.event(self.db, self.session, "assistant", {"text": "", "tool_calls": [
                {"id": "callA", "function": {"name": "read_file", "arguments": "{}"}},
                {"id": "callB", "function": {"name": "read_file", "arguments": "{}"}}]})
            argusd.event(self.db, self.session, "tool",
                         {"id": "callA", "name": "read_file", "result": {"ok": True}})
            argusd.event(self.db, self.session, "tool",
                         {"id": "callB", "name": "read_file", "result": {"ok": True}})
            for i in range(3):
                argusd.event(self.db, self.session, "user", {"text": f"after {i}"})

            report = argusd.compact(self.db, self.session)
            self.assertIsNotNone(report, "this seed must actually trigger archiving")

            kept = self.db.execute(
                "SELECT kind,payload FROM events WHERE session=? ORDER BY id",
                (self.session,)).fetchall()
            declared_ids = set()
            answered_ids = set()
            for kind, payload in kept:
                p = json.loads(payload)
                if kind == "assistant":
                    declared_ids |= {c["id"] for c in (p.get("tool_calls") or [])}
                elif kind == "tool":
                    answered_ids.add(p["id"])
            self.assertTrue(answered_ids <= declared_ids,
                            f"tool result(s) {answered_ids - declared_ids} kept with no "
                            "matching tool_calls declaration in the kept events")
            self.assertIn("callA", declared_ids,
                          "the two-call assistant message must not have been archived "
                          "while its own tool results were kept")


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.db = argusd.connect()
        self.session = f"context-{id(self)}"
        self.ws = Workspace(support.make_workspace("ws-context"))

    def test_only_the_newest_capture_is_attached(self):
        """Every step used to re-attach the last two screenshots, aged or not."""
        for i in range(3):
            p = support.TMP / f"cap{i}.png"
            p.write_bytes(PNG_1PX)
            argusd.event(self.db, self.session, "tool",
                         {"id": f"s{i}", "name": "observe_screen",
                          "result": {"ok": True, "path": str(p)}})
        messages = argusd.context(self.db, self.session)
        images = [block for message in messages
                  for block in _blocks(message) if block.get("type") == "image"]
        self.assertEqual(argusd.MAX_IMAGES, len(images))

    def test_observe_screen_images_are_dropped_once_the_model_is_known_to_lack_vision(self):
        """Companion to argusd's provider_call self-heal: once no_image_support is
        set, context() must stop attaching images (the thing that caused the
        original failure) rather than re-triggering it on every subsequent step."""
        p = support.TMP / "cap-no-vision.png"
        p.write_bytes(PNG_1PX)
        argusd.event(self.db, self.session, "tool",
                     {"id": "s0", "name": "observe_screen", "result": {"ok": True, "path": str(p)}})
        argusd.set_state(self.db, self.session, "no_image_support", "1")
        messages = argusd.context(self.db, self.session)
        images = [block for message in messages
                  for block in _blocks(message) if block.get("type") == "image"]
        self.assertEqual(0, len(images))
        joined = "\n".join(m["content"] for m in messages if isinstance(m.get("content"), str))
        self.assertIn("does not accept image input", joined)

    def test_pinned_task_and_plan_survive_outside_the_event_window(self):
        argusd.set_state(self.db, self.session, "current_task", "ship the parser fix")
        argusd.set_state(self.db, self.session, "todos", json.dumps(
            [{"content": "step one", "status": "pending"}]))
        messages = argusd.context(self.db, self.session)
        joined = "\n".join(m["content"] for m in messages if isinstance(m.get("content"), str))
        self.assertIn("ship the parser fix", joined)
        self.assertIn("step one", joined)

    def test_every_declared_tool_call_in_the_window_has_a_result(self):
        """The invariant both OpenAI and Anthropic enforce."""
        calls = [{"id": "c1", "type": "function",
                  "function": {"name": "read_file", "arguments": "{}"}}]
        argusd.event(self.db, self.session, "assistant", {"text": "", "tool_calls": calls})
        argusd.event(self.db, self.session, "tool", {"id": "c1", "name": "read_file",
                                                     "result": {"ok": True}})
        messages = argusd.context(self.db, self.session)
        declared = {c["id"] for message in messages
                    for c in (message.get("tool_calls") or [])}
        answered = {message["tool_call_id"] for message in messages
                    if message.get("role") == "tool"}
        self.assertEqual(declared, answered)

    def test_the_context_window_itself_never_orphans_a_tool_result(self):
        """Same invariant as the test above, but forcing the actual failure
        shape: context()'s own `ORDER BY id DESC LIMIT MAX_CONTEXT_EVENTS`
        can cut between a multi-call assistant turn and its tool results
        exactly like compact()'s old KEEP_EVENTS boundary did — a separate
        vulnerability (context() doesn't call compact()) needing its own
        fix (_safe_window_start, reused by both)."""
        with mock.patch.object(argusd, "MAX_CONTEXT_EVENTS", 5):
            argusd.event(self.db, self.session, "user", {"text": "u0"})
            argusd.event(self.db, self.session, "assistant", {"text": "a0"})
            argusd.event(self.db, self.session, "user", {"text": "u1"})
            argusd.event(self.db, self.session, "assistant", {"text": "a1"})
            argusd.event(self.db, self.session, "assistant", {"text": "", "tool_calls": [
                {"id": "callX", "function": {"name": "read_file", "arguments": "{}"}},
                {"id": "callY", "function": {"name": "read_file", "arguments": "{}"}}]})
            argusd.event(self.db, self.session, "tool",
                         {"id": "callX", "name": "read_file", "result": {"ok": True}})
            argusd.event(self.db, self.session, "tool",
                         {"id": "callY", "name": "read_file", "result": {"ok": True}})
            argusd.event(self.db, self.session, "user", {"text": "u2"})
            argusd.event(self.db, self.session, "assistant", {"text": "a2"})
            argusd.event(self.db, self.session, "user", {"text": "u3"})

            messages = argusd.context(self.db, self.session)
        declared = {c["id"] for message in messages for c in (message.get("tool_calls") or [])}
        answered = {message["tool_call_id"] for message in messages
                    if message.get("role") == "tool"}
        self.assertTrue(answered <= declared,
                        f"tool result(s) {answered - declared} in the window with no "
                        "matching tool_calls declaration also in it")
        self.assertIn("callX", declared)

    def test_an_error_terminated_turn_is_not_fed_back_as_the_models_own_words(self):
        """finish() journals its own "⚠️ ..." error/status text so the panel
        never looks like it silently died — but that text is diagnostic,
        not something the model said. Confirmed live: a session whose
        provider call failed once kept restating that exact error back to
        itself as "its own previous reply" on every later turn, forever,
        instead of ever getting a clean look at the task again."""
        argusd.event(self.db, self.session, "user", {"text": "do the thing"})
        argusd.event(self.db, self.session, "assistant",
                     {"text": "⚠️ Provider request failed: HTTP 400 something broke"})
        argusd.event(self.db, self.session, "user", {"text": "a brand new unrelated task"})
        messages = argusd.context(self.db, self.session)
        for m in messages:
            content = m.get("content")
            if isinstance(content, str):
                self.assertNotIn("Provider request failed", content)

    def test_a_real_assistant_reply_that_merely_mentions_a_warning_is_kept(self):
        """The filter is on the message being finish()'s own status text
        (identified by starting with the marker and carrying no tool_calls
        of its own), not on the mere presence of the emoji somewhere in a
        real reply."""
        argusd.event(self.db, self.session, "user", {"text": "explain the bug"})
        argusd.event(self.db, self.session, "assistant",
                     {"text": "Careful — ⚠️ this function has a race condition."})
        messages = argusd.context(self.db, self.session)
        joined = "\n".join(m["content"] for m in messages if isinstance(m.get("content"), str))
        self.assertIn("race condition", joined)


if __name__ == "__main__":
    unittest.main()
