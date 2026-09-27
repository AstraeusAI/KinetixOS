"""The approval round trip: the history it leaves behind has to stay valid.

Regression under test: run() journals an assistant message with every tool call
of the turn, then returns as soon as one of them needs approval. The calls after
it were dropped while still declared, and the approved call's result was
journalled under the approval's own id instead of the model's tool_call id — so
the resumed turn was built from a history that declared 3 calls and answered 1
(verified before the fix), which both OpenAI and Anthropic reject.
"""
import json
import sys
import unittest
from unittest import mock

import support  # noqa: F401

import argusd


class FakeProvider:
    """Scripted provider_call: one canned reply per turn, no network."""

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
        return {"choices": [{"message": reply}]}

    def system_text(self, turn=0):
        return "\n".join(m["content"] for m in self.prompts[turn]
                         if m.get("role") == "system" and isinstance(m.get("conten"
                             "t"), str))


class ApprovalTestCase(unittest.TestCase):
    def setUp(self):
        self.ws = support.make_workspace("ws-approvals")
        support.write(self.ws / "a.py", "x = 1\n")
        self.session = "appr-" + self._testMethodName
        for patch in (mock.patch.object(argusd.kwin, "capabilitie"
            "s", support.kwin_capabilities),
                      mock.patch.object(argusd.sandbox, "run", support.sandbox_stub())):
            patch.start()
            self.addCleanup(patch.stop)

    def journal(self):
        return support.declared_and_answered(argusd.connect(), self.session)

    def journal_order(self):
        rows = argusd.connect().execute(
            "SELECT kind,payload FROM events WHERE session=? ORDER BY id",
            (self.session,),
        )
        return [(kind, json.loads(payload)) for kind, payload in rows]

    def assert_no_duplicate_answers(self):
        _declared, answered = self.journal()
        self.assertEqual(len(answered), len(set(answered)), "exactly one result per "
            "call id")

    def assert_results_follow_the_declaring_turn(self):
        """The three results must be the messages immediately after the assistant
        turn that declared the calls — that adjacency is what both providers
        validate, and the approval outcome is written over its placeholder row
        rather than appended to preserve it."""
        order = self.journal_order()
        index = next(i for i, (kind, body) in enumerate(order)
                     if kind == "assistant" and body.get("tool_calls"))
        following = order[index + 1:index + 4]
        self.assertEqual(["tool"] * 3, [kind for kind, _ in following])
        self.assertEqual(["call_"
            "1", "call_2", "call_3"], [body["id"] for _, body in following])

    def tool_result(self, call_id):
        for (payload,) in argusd.connect().execute(
                "SELECT payload FROM events WHERE session=? AND kind='tool' ORDER BY "
                    "id",
                (self.session,)):
            body = json.loads(payload)
            if body.get("id") == call_id:
                return body["result"]
        return None

    def approval_row(self, approval_id):
        return argusd.connect().execute(
            "SELECT tool,call_id,status FROM approvals WHERE "
                "id=?", (approval_id,)).fetchone()

    def assert_history_is_answerable(self):
        declared, answered = self.journal()
        self.assertTrue(declared, "the turn should have declared tool calls")
        self.assertEqual(set(declared), set(answered),
                         "every declared tool_call_id needs a tool result")


class VerificationNudgeTests(ApprovalTestCase):
    """The system prompt tells the model to run_tests after any change with
    real logic, but that's just text — nothing before this actually caught a
    model that mutated a file and then finished without ever verifying it."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(
            argusd.Workspace, "tooling",
            lambda self, path: {"languag"
                "e": "python", "commands": {"test": ["pytest", "-q"]}})
        patch.start()
        self.addCleanup(patch.stop)

    def test_finishing_after_a_write_with_no_test_run_gets_nudged_once(self):
        provider = FakeProvider(
            {"content": "", "tool_calls": [
                support.call("c1", "write_fil"
                    "e", {"path": "a.py", "content": "x = 2\n"})]},
            {"content": "Done, changed "
                "a.py."},   # tries to finish without verifying — nudged
            {"content": "This was a trivial change, no test "
                "needed."},   # declines the tests nudge
            {"content": "No review needed either, nothing else "
                "changed."},   # declines the gate nudge too — third attempt sticks
        )
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("change a.py", self.session, str(self.ws))
        self.assertTrue(result["ok"])
        self.assertEqual(4, provider.calls, "the nudge should have bought exactly one "
            "more turn, and the gate nudge one after that")
        self.assertEqual(
            "No review needed either, nothing else changed.", result["text"]
        )
        prompts = [m for m in self.journal_order() if m[0] == "user"]
        self.assertTrue(any("never ran "
            "run_tests" in body.get("text", "") for _, body in prompts))
        # Both one-shot gates fired, in order, and the model was allowed to
        # decline each — a gate it cannot satisfy must not strand the task.
        self.assertTrue(any("verify_deliverable" in body.get("text", "")
                            for _, body in prompts))

    def test_a_second_finish_attempt_is_not_nudged_again(self):
        """Confirms the one-shot flag actually gates the *second* attempt —
        not just that some later reply happens to be accepted."""
        provider = FakeProvider(
            {"content": "", "tool_calls": [
                support.call("c1", "write_fil"
                    "e", {"path": "a.py", "content": "x = 2\n"})]},
            {"content": "Still not verifying, first attempt."},
            {"content": "Still not verifying, second attempt."},
            {"content": "Still not verifying, third attempt."},
        )
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("change a.py", self.session, str(self.ws))
        self.assertTrue(result["ok"])
        self.assertEqual(4, provider.calls, "each one-shot gate nudges exactly once: "
            "the tests gate, then the review gate, then the reply sticks")
        self.assertEqual("Still not verifying, third attempt.", result["text"])

    def test_running_tests_before_finishing_needs_no_nudge(self):
        provider = FakeProvider(
            {"content": "", "tool_calls": [
                support.call("c1", "write_fil"
                    "e", {"path": "a.py", "content": "x = 2\n"})]},
            {"content": "", "tool_calls": [support.call("c2", "run_tests", {})]},
            {"content": "Tests pass, but I have not reviewed it "
                "mechanically."},   # the review gate is separate
            {"content": "", "tool_calls": [
                support.call("c3", "verify_deliverable", {})]},
            {"content": "Done and verified."},
        )
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("change a.py", self.session, str(self.ws))
        self.assertTrue(result["ok"])
        self.assertEqual(5, provider.calls, "run_tests satisfies the tests gate only, "
            "so the review gate is the one that buys the extra turns here")
        self.assertEqual("Done and verified.", result["text"])
        self.assertTrue(any("verify_deliverable" in body.get("text", "")
                            for _, body in self.journal_order() if body.get("text")))

    def test_a_read_only_task_is_never_nudged(self):
        provider = FakeProvider(
            {"content": "", "tool_calls": [
                support.call("c1", "read_file", {"path": "a.py"})]},
            {"content": "It says x = 1."},
        )
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("what does a.py say", self.session, str(self.ws))
        self.assertTrue(result["ok"])
        self.assertEqual(2, provider.calls)


class ApprovalHistoryTests(ApprovalTestCase):
    def test_a_sibling_call_after_a_prompting_call_is_still_answered(self):
        provider = FakeProvider(
            {"content": "", "tool_calls": [
                support.call("call_1", "read_file", {"path": "a.py"}),
                support.call("call_2", "run_command", {"command": "touch "
                    "/tmp/argus-x"}),
                support.call("call_3", "glob", {"pattern": "*.py"}),
            ]},
            {"content": "All done."},
        )
        with mock.patch.object(argusd, "provider_call", provider):
            paused = argusd.run("do three things", self.session, str(self.ws))

        self.assertIn("approval", paused)
        self.assert_history_is_answerable()
        self.assert_no_duplicate_answers()
        self.assert_results_follow_the_declaring_turn()
        self.assertEqual(["call_1", "call_2", "call_3"], self.journal()[0])
        self.assertIn("not executed", self.tool_result("call_3")["error"])

        # the prompting call is answered by a placeholder until the user decides
        placeholder = self.tool_result("call_2")
        self.assertTrue(placeholder["pending_approval"])
        self.assertIn("awaiting user approval", placeholder["error"])

        approval_id = paused["approval"]["id"]
        self.assertEqual(("run_comman"
            "d", "call_2", "pending"), self.approval_row(approval_id))

        with mock.patch.object(argusd, "provider_call", provider):
            done = argusd.approve(approval_id, True, str(self.ws))

        self.assertTrue(done["ok"])
        self.assertEqual("All done.", done["text"])
        self.assertEqual(2, provider.calls, "the task should have resumed after "
            "approval")
        self.assertEqual(("run_comman"
            "d", "call_2", "executed"), self.approval_row(approval_id))
        self.assertTrue(self.tool_result("call_2")["ok"])
        self.assert_history_is_answerable()
        self.assert_no_duplicate_answers()
        self.assert_results_follow_the_declaring_turn()

    def test_a_denied_approval_answers_the_call_it_denied(self):
        provider = FakeProvider({"content": "", "tool_calls": [
            support.call("c1", "run_command", {"command": "touch /tmp/argus-y"})]})
        with mock.patch.object(argusd, "provider_call", provider):
            paused = argusd.run("touch something", self.session, str(self.ws))
        with mock.patch.object(argusd, "provider_call", provider):
            denied = argusd.approve(paused["approval"]["id"], False, str(self.ws))
        self.assertIn("denied", denied["text"])
        self.assert_history_is_answerable()
        self.assertIn("denied by user", self.tool_result("c1")["error"])
        self.assertEqual(1, provider.calls, "a denied action must not resume the task")

    def test_a_task_stopped_as_stuck_answers_the_call_it_abandoned(self):
        provider = FakeProvider(*[
            {"content": "", "tool_calls": [
                support.call(f"c{i}", "read_file", {"path": "a.py"})]}
            for i in range(1, 6)
        ])
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("loop forever", self.session, str(self.ws))
        self.assertFalse(result["ok"])
        self.assertIn("Stopped:", result["text"])
        self.assert_history_is_answerable()
        self.assertEqual(5, len(self.journal()[0]))

    def test_a_provider_failure_ends_the_journal_with_the_assistant_words(self):
        provider = FakeProvider(RuntimeError("Provider request failed: HTTP 500 boom"))
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("anything", self.session, str(self.ws))
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["text"])
        last = argusd.connect().execute(
            "SELECT kind,payload FROM events WHERE session=? ORDER BY id DESC LIMIT 1",
            (self.session,)).fetchone()
        self.assertEqual("assistant", last[0])
        self.assertIn("boom", json.loads(last[1])["text"])

    def test_a_continuation_keeps_the_task_and_plan_anchors(self):
        db = argusd.connect()
        argusd.set_state(db, self.session, "current_task", "the original task")
        provider = FakeProvider({"content": "finished"})
        with mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("Continue the previous "
                "task.", self.session, str(self.ws),
                                is_continuation=True)
        self.assertTrue(result["ok"])
        self.assertEqual("the original "
            "task", argusd.get_state(db, self.session, "current_task"))
        self.assertIn("the original task", provider.system_text())

    def test_a_continuation_uses_the_original_tasks_step_budget(self):
        db = argusd.connect()
        argusd.set_state(db, self.session, "task_started", argusd.time.time())
        argusd.set_state(db, self.session, "task_steps", 2)
        provider = FakeProvider({"content": "should not be reached"})
        with mock.patch.object(argusd, "MAX_STEPS", 2), \
             mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("Continue the previous "
                "task.", self.session, str(self.ws),
                                is_continuation=True)
        self.assertFalse(result["ok"])
        self.assertIn("2 tool steps", result["text"])
        self.assertEqual(0, provider.calls)

    def test_a_continuation_uses_the_original_tasks_time_budget(self):
        db = argusd.connect()
        argusd.set_state(db, self.session, "task_started", argusd.time.time() - 10)
        argusd.set_state(db, self.session, "task_steps", 0)
        provider = FakeProvider({"content": "should not be reached"})
        with mock.patch.object(argusd, "MAX_TASK_SECONDS", 1), \
             mock.patch.object(argusd, "provider_call", provider):
            result = argusd.run("Continue the previous "
                "task.", self.session, str(self.ws),
                                is_continuation=True)
        self.assertFalse(result["ok"])
        self.assertIn("cumulative task budget", result["text"])
        self.assertEqual(0, provider.calls)

    def test_a_new_task_replaces_the_anchors(self):
        db = argusd.connect()
        argusd.set_state(db, self.session, "current_task", "the old task")
        provider = FakeProvider({"content": "ok"})
        with mock.patch.object(argusd, "provider_call", provider):
            argusd.run("a brand new task", self.session, str(self.ws))
        self.assertEqual("a brand new "
            "task", argusd.get_state(db, self.session, "current_task"))
        self.assertIn("a brand new task", provider.system_text())
        self.assertNotIn("the old task", provider.system_text())


class AlwaysApprovalSubjectTests(ApprovalTestCase):
    """approve(..., always=True) has to persist a rule keyed on the tool's
    own declared subject (_policy_subjects — the same derivation
    policy_decision() itself judges the call against), not just
    args["command"]/args["path"]. Caught live running a real MCP tool
    through this exact path: approving with --always executed the call but
    left no rule behind, because an MCP tool's subject is a callable
    producing "server.tool" — neither literal argument name matches it — so
    the very next identical call prompted again as if `always` had done
    nothing."""

    def setUp(self):
        super().setUp()
        # A unique subject per test — policy.json is one process-global file
        # (see CommandlessExecToolPolicyTests' own note on this above), so a
        # subject shared between these two test methods would let whichever
        # runs first (alphabetically, test_a_second... before
        # test_always_allow...) silently pre-approve the other.
        self.subject = "fake." + self._testMethodName
        fake_tool = {
            "name": "mcp__fake__echo", "description": "", "grant": "mcp",
            "parameter"
                "s": {"type": "object", "properties": {"message": {"type": "string"}}},
            "risk": "soft", "mutates": False, "verify": [], "needs_grant": None,
            "sandboxed": False,
            "subject": lambda ctx, args: [self.subject],
            "handler": lambda ctx, args: {
                "ok": True,
                "content": "echo: " + args.get("message", ""),
            },
        }
        patch = mock.patch.dict(argusd.toolreg.REGISTRY, {"mcp__fake__echo": fake_tool})
        patch.start()
        self.addCleanup(patch.stop)

    def test_always_allow_persists_a_rule_keyed_on_the_tools_declared_subject(self):
        provider = FakeProvider(
            {"content": "", "tool_calls": [support.call("c1", "mcp__fake__ech"
                "o", {"message": "hi"})]},
            {"content": "done"},
        )
        with mock.patch.object(argusd, "provider_call", provider):
            paused = argusd.run("call the echo tool", self.session, str(self.ws))
        self.assertIn("approval", paused, "an mcp-grant tool should prompt by default")
        approval_id = paused["approval"]["id"]

        with mock.patch.object(argusd, "provider_call", provider):
            done = argusd.approve(approval_id, True, str(self.ws), always=True)
        self.assertTrue(done["ok"], done)

        policy = argusd.Policy(self.ws.root)
        self.assertIn(self.subject, policy.memory["allow"])

    def test_a_second_identical_call_auto_approves_after_always(self):
        first = FakeProvider(
            {"content": "", "tool_calls": [support.call("c1", "mcp__fake__ech"
                "o", {"message": "hi"})]})
        with mock.patch.object(argusd, "provider_call", first):
            paused = argusd.run("call the echo tool", self.session, str(self.ws))
        approval_id = paused["approval"]["id"]
        with mock.patch.object(argusd, "provider_call", first):
            argusd.approve(approval_id, True, str(self.ws), always=True)

        second = FakeProvider(
            {"content": "", "tool_calls": [support.call("c2", "mcp__fake__ech"
                "o", {"message": "again"})]},
            {"content": "done"},
        )
        with mock.patch.object(argusd, "provider_call", second):
            result = argusd.run("call the echo tool "
                "again", self.session + "-2", str(self.ws))
        self.assertNotIn("approval", result, "the remembered rule should have "
            "auto-approved this call")
        self.assertTrue(result["ok"], result)


class TaskFlagsSurviveResumeTests(ApprovalTestCase):
    """A task's stop-time gates must remember work done before an approval.

    Found by running the strict-01 fixture end to end: the agent wrote
    wordfreq.py, its suite, README and CHANGELOG, then hit an approval on its
    run_command. approve() resumes via run(is_continuation=True), which built
    a *fresh* flag bag — so mutated_testable, ran_tests and ran_gate were all
    false again in the resumed turn, and the task reported completion with
    every gate blind to the work that had just happened. Only `todos`
    survived the pause, because it is persisted in session_state; these flags
    were not.
    """

    def flags_in_session(self, session):
        return {
            k: argusd.get_state(argusd.connect(), session, k)
            for k in argusd._loop._TASK_FLAGS
        }

    def test_a_gate_survives_the_approval_pause(self):
        provider = FakeProvider(
            {"content": "", "tool_calls": [
                support.call("c1", "write_file",
                             {"path": "a.py", "content": "x = 2\n"})]},
            {"content": "", "tool_calls": [
                support.call("c2", "run_command",
                             {"command": "touch /tmp/argus-x"})]},
            # resumed turn: tries to finish immediately
            {"content": "All done."},
            # the tests nudge (this workspace has a detectable test command)
            {"content": "No logic worth testing here."},
            # then the review gate
            {"content": "Reviewed, nothing outstanding."},
        )
        with mock.patch.object(argusd, "provider_call", provider):
            paused = argusd.run("change a.py", self.session, str(self.ws))
        self.assertIsNotNone(paused.get("approval"), "expected the run to pause")
        with mock.patch.object(argusd, "provider_call", provider):
            done = argusd.approve(paused["approval"]["id"], True, str(self.ws))
        prompts = [b.get("text", "") for _, b in self.journal_order() if b.get("text")]
        self.assertTrue(
            any("verify_deliverable" in t for t in prompts),
            "the review gate was skipped after the approval "
            "resume",
        )
        self.assertTrue(done["ok"])

    def test_a_continuation_inherits_the_flags_and_a_new_task_resets_them(self):
        db = argusd.connect()
        bag = argusd._loop._flag_bag()
        bag["mutated_any"] = True
        bag["ran_gate"] = True
        argusd._loop._save_task_flags(db, self.session, bag)
        self.assertEqual("1", argusd.get_state(db, self.session, "mutated_any"))

        fresh = argusd._loop._flag_bag()
        argusd._loop._load_task_flags(db, self.session, fresh)
        self.assertTrue(fresh["mutated_any"], "a continuation must inherit")
        self.assertTrue(fresh["ran_gate"])

        # A brand-new task clears them, so a stale flag cannot leak forward
        # into unrelated work.
        for k in argusd._loop._TASK_FLAGS:
            argusd.set_state(db, self.session, k, "0")
        other = argusd._loop._flag_bag()
        argusd._loop._load_task_flags(db, self.session, other)
        self.assertFalse(other["mutated_any"])
        self.assertFalse(other["ran_gate"])

    def test_only_changed_flags_are_written(self):
        # Called once per step, so an unconditional 7-row write per step would
        # add seven commits to every step of every task.
        db = argusd.connect()
        bag = argusd._loop._flag_bag()
        target = sys.modules["lib.loop"]
        real = target.set_state
        with mock.patch.object(target, "set_state", wraps=real) as spy:
            argusd._loop._save_task_flags(db, self.session, bag)
            self.assertEqual(0, spy.call_count, "an unchanged bag writes nothing")
            bag["mutated_any"] = True
            argusd._loop._save_task_flags(db, self.session, bag)
            self.assertEqual(1, spy.call_count)
            argusd._loop._save_task_flags(db, self.session, bag)
            self.assertEqual(1, spy.call_count, "a repeat write is suppressed")


if __name__ == "__main__":
    unittest.main()
