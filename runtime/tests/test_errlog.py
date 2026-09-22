"""Incident logging: the errlog module itself, and that argusd.run() actually
feeds it — a crashed tool, a failed tool, a stuck loop, a provider failure and
a budget/step-limit stop should all leave a record behind with enough context
to diagnose after the fact, not just a one-line message in the journal.
"""
import time
import unittest
from unittest import mock

import support  # noqa: F401

import argusd
from lib import errlog


class ErrlogUnitTests(unittest.TestCase):
    def test_records_round_trip_as_json_with_the_given_fields(self):
        errlog.warning("unit_test_event", foo="bar", n=3)
        rec = errlog.tail(1)[0]
        self.assertEqual("unit_test_event", rec["event"])
        self.assertEqual("WARNING", rec["level"])
        self.assertEqual("bar", rec["foo"])
        self.assertEqual(3, rec["n"])
        self.assertIn("ts", rec)

    def test_exception_captures_type_message_and_traceback(self):
        try:
            raise ValueError("boom")
        except ValueError as e:
            errlog.exception("unit_test_exception", e, tool="whatever")
        rec = errlog.tail(1)[0]
        self.assertEqual("unit_test_exception", rec["event"])
        self.assertEqual("ValueError", rec["error_type"])
        self.assertEqual("boom", rec["error"])
        self.assertIn("Traceback", rec["traceback"])
        self.assertIn("whatever", rec["tool"])

    def test_a_value_that_cannot_be_json_encoded_is_still_logged(self):
        errlog.warning("unit_test_unserializable", obj=object())
        rec = errlog.tail(1)[0]
        self.assertEqual("unit_test_unserializable", rec["event"])

    def test_malformed_lines_come_back_as_raw_instead_of_being_dropped(self):
        errlog.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(errlog.LOG_FILE, "a", encoding="utf-8") as f:
            f.write("not json at all\n")
        rec = errlog.tail(1)[0]
        self.assertEqual("not json at all", rec["raw"])


class FakeProvider:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, messages, on_event):
        self.calls += 1
        if not self.replies:
            raise AssertionError("provider was called more times than scripted")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"choices": [{"message": reply}]}


def _events_since(marker, event_name, session=None):
    """`marker` alone isn't enough to isolate one test's records: errlog.tail
    reads one real, cumulative, on-disk log shared by the whole test run, and
    two fast tests (sub-10ms, easily achieved here) landing within the same
    window can both see each other's entries. Every record here carries the
    session name it was logged under (see run()'s errlog.warning calls), and
    sessions are already unique per test method — filtering on it as well
    makes this race-proof instead of merely unlikely."""
    return [r for r in errlog.tail(500)
            if r.get("ts", 0) >= marker and r.get("event") == event_name
            and (session is None or r.get("session") == session)]


class RuntimeIncidentLoggingTests(unittest.TestCase):
    def setUp(self):
        self.ws = support.make_workspace("ws-errlog")
        support.write(self.ws / "a.py", "x = 1\n")
        self.session = "errlog-" + self._testMethodName
        self.marker = time.time() - 0.01
        for patch in (mock.patch.object(argusd.kwin, "capabilitie"
            "s", support.kwin_capabilities),
                      mock.patch.object(argusd.sandbox, "run", support.sandbox_stub())):
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_tool_that_raises_is_logged_with_its_traceback(self):
        def boom(ctx, args):
            raise RuntimeError("handler exploded")

        provider = FakeProvider(
            {"content": "", "tool_call"
                "s": [support.call("c1", "read_file", {"path": "a.py"})]},
            {"content": "done"},
        )
        with mock.patch.dict(argusd.toolreg.REGISTRY["read_file"], {"handler": boom}), \
             mock.patch.object(argusd, "provider_call", provider):
            argusd.run("crash it", self.session, str(self.ws))

        recs = _events_since(self.marker, "tool_crashed", session=self.session)
        self.assertEqual(1, len(recs))
        self.assertEqual("read_file", recs[0]["tool"])
        self.assertEqual("RuntimeError", recs[0]["error_type"])
        self.assertIn("handler exploded", recs[0]["error"])
        self.assertIn("Traceback", recs[0]["traceback"])

    def test_a_tool_that_returns_ok_false_is_logged_without_a_traceback(self):
        provider = FakeProvider(
            {"content": "", "tool_call"
                "s": [support.call("c1", "read_file", {"path": "missing.py"})]},
            {"content": "done"},
        )
        with mock.patch.object(argusd, "provider_call", provider):
            argusd.run("read a missing file", self.session, str(self.ws))

        recs = _events_since(self.marker, "tool_failed", session=self.session)
        self.assertEqual(1, len(recs))
        self.assertEqual("read_file", recs[0]["tool"])
        self.assertNotIn("traceback", recs[0])

    def test_a_command_failure_logs_the_real_stderr_not_the_literal_string_none(self):
        """run_tests/run_command exit non-zero with no "error" key at all —
        their failure lives in stdout/stderr (see _failure_detail's own
        docstring). Logging str(result.get("error")) for those logged the
        literal string "None" for every single one, which is exactly the
        case this log exists to make diagnosable — caught chasing a stuck
        run_tests loop through this log during a real eval and getting
        nothing but "error: None" for it."""
        provider = FakeProvider(
            {"content": "", "tool_calls": [support.call("c1", "run_comman"
                "d", {"command": "false"})]},
            {"content": "done"},
        )
        failing = {"ok": False, "code": 1, "stdout": "", "stderr": "boom: assertion "
            "failed"}
        with mock.patch.object(argusd.sandbox, "run", support.sandbox_stub(failing)), \
             mock.patch.object(argusd, "provider_call", provider):
            argusd.run("run something that fails", self.session, str(self.ws))

        recs = _events_since(self.marker, "tool_failed", session=self.session)
        self.assertEqual(1, len(recs))
        self.assertEqual("run_command", recs[0]["tool"])
        self.assertIn("boom: assertion failed", recs[0]["error"])
        self.assertNotEqual("None", recs[0]["error"])

    def test_a_stuck_loop_is_logged_before_the_task_is_abandoned(self):
        provider = FakeProvider(*[
            {"content": "", "tool_call"
                "s": [support.call(f"c{i}", "read_file", {"path": "a.py"})]}
            for i in range(1, 6)
        ])
        with mock.patch.object(argusd, "provider_call", provider):
            argusd.run("loop forever", self.session, str(self.ws))

        recs = _events_since(self.marker, "task_stuck_repeat", session=self.session)
        self.assertEqual(1, len(recs))
        self.assertEqual("read_file", recs[0]["tool"])
        self.assertGreaterEqual(recs[0]["repeats"], 5)

    def test_a_provider_failure_is_logged_with_its_traceback(self):
        provider = FakeProvider(RuntimeError("Provider request failed: HTTP 500 boom"))
        with mock.patch.object(argusd, "provider_call", provider):
            argusd.run("anything", self.session, str(self.ws))

        recs = _events_since(self.marker, "provider_call_failed", session=self.session)
        self.assertEqual(1, len(recs))
        self.assertIn("HTTP 500", recs[0]["error"])
        self.assertIn("Traceback", recs[0]["traceback"])

    def test_hitting_the_task_time_budget_logs_a_diagnostic_breakdown(self):
        provider = FakeProvider(
            {"content": "", "tool_call"
                "s": [support.call("c1", "read_file", {"path": "a.py"})]},
            {"content": "", "tool_call"
                "s": [support.call("c2", "read_file", {"path": "a.py"})]},
        )
        with mock.patch.object(argusd, "MAX_TASK_SECONDS", 0), \
             mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("do something slow", self.session, str(self.ws))

        self.assertFalse(result["ok"])
        recs = _events_since(self.marker, "task_budget_exceeded", session=self.session)
        self.assertEqual(1, len(recs))
        self.assertIn("tool_durations", recs[0])
        self.assertIn("elapsed", recs[0])

    def test_an_image_unsupported_provider_error_self_heals_instead_of_failing_the_task(
        self,
    ):
        """Confirmed live: running a computer-use task against a free
        OpenRouter model with no vision support died on the very first
        observe_screen call — provider_call raised HTTP 404 "No endpoints
        found that support image input" and the whole task aborted, even
        though the model had already made real progress. run() should
        recognize this specific, non-retryable rejection, drop images from
        context, and continue the same task instead of giving up."""
        provider = FakeProvider(
            {"content": "", "tool_call"
                "s": [support.call("c1", "read_file", {"path": "a.py"})]},
            RuntimeError('Provider request failed: HTTP 404 {"error":{"message":'
                         '"No endpoints found that support image input"}}'),
            {"content": "done"},
        )
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("look at the screen", self.session, str(self.ws))

        self.assertTrue(result["ok"])
        self.assertEqual(3, provider.calls)
        self.assertEqual("1", argusd.get_state(
            argusd.connect(), self.session, "no_image_support"))
        recs = _events_since(self.marker, "model_lacks_image_suppor"
            "t", session=self.session)
        self.assertEqual(1, len(recs))
        self.assertIn("image input", recs[0]["detail"])

    def test_a_different_provider_failure_still_fails_the_task_not_looping(self):
        """The self-heal above is a one-shot, narrowly-matched exception —
        a genuinely fatal error (bad credentials, real 500) must still stop
        the task rather than retrying forever."""
        provider = FakeProvider(RuntimeError("Provider request failed: HTTP 401 "
            "invalid key"))
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("anything", self.session, str(self.ws))

        self.assertFalse(result["ok"])
        self.assertEqual(1, provider.calls)

    def test_hitting_the_step_limit_logs_a_diagnostic_breakdown(self):
        provider = FakeProvider(*[
            {"content": "", "tool_calls": [support.call(f"c{i}", "list_dir", {})]}
            for i in range(1, 4)
        ])
        with mock.patch.object(argusd, "MAX_STEPS", 3), \
             mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("wander forever", self.session, str(self.ws))

        self.assertFalse(result["ok"])
        recs = _events_since(self.marker, "task_step_limit_exceede"
            "d", session=self.session)
        self.assertEqual(1, len(recs))
        self.assertIn("list_dir", recs[0]["tool_durations"])


if __name__ == "__main__":
    unittest.main()
