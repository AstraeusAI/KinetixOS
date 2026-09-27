"""Policy engine: command chaining, hard denies, and subject scoping."""
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (import first: redirects the XDG dirs)

import argusd
from lib.checkpoints import Checkpoints
from lib.policy import Policy, segments_safe
from lib.workspace import Workspace


class CommandlessExecToolPolicyTests(unittest.TestCase):
    """syntax_check, lint, format_file and run_tests share one property: none
    of them take a free-text `command` argument — each dispatches to a fixed
    command it assembles itself from trusted Python logic (auto-detected
    test/lint/format tools, a per-language syntax-check branch), never from
    model-supplied shell text. $SAFE only ever matches a command *string*, so
    with none of these tools ever having one to offer, they always fell
    through to "exec outside the auto-approved scope" and prompted on every
    call — identically to a risk="commit" action regardless of their own
    declared risk tier (read/read/soft/soft). Confirmed live twice: first
    run_tests stopped an eval task dead at "run the tests and confirm they
    pass", then — after that was fixed as a run_tests-only special case —
    syntax_check hit the exact same wall in a second, unrelated eval, which
    is why the fix generalized to every commandless exec-grant tool instead
    of staying a per-name allowlist.
    """
    def setUp(self):
        self.ws = Workspace(support.make_workspace("policy-commandless-exec"))
        self.policy = Policy(self.ws.root)

    def test_auto_approves_with_no_path(self):
        for name in ("run_tests", "syntax_check", "lint", "format_file"):
            with self.subTest(tool=name):
                spec = argusd.toolreg.REGISTRY[name]
                decision, reason = argusd.policy_decision(self.policy, spec, None, {})
                self.assertEqual("auto", decision)
                self.assertIn(name, reason)

    def test_auto_approves_with_a_path_argument(self):
        for name in ("run_tests", "syntax_check", "lint", "format_file"):
            with self.subTest(tool=name):
                spec = argusd.toolreg.REGISTRY[name]
                decision, _ = argusd.policy_decision(self.policy, spec, None, {"pat"
                    "h": "a.py"})
                self.assertEqual("auto", decision)

    def test_a_saved_deny_rule_still_wins(self):
        """The downgrade only touches the generic exec/$SAFE prompt reason —
        an explicit user deny must still be respected. A specific, unique
        pattern (not "" — every no-path/no-command tool in the whole suite
        shares that subject, and Policy's memory file is process-global, not
        per-test) so this can't leak into unrelated tests."""
        self.policy.remember("commandless-exec-policy-test-deny-me", allow=False)
        spec = argusd.toolreg.REGISTRY["run_tests"]
        decision, _ = argusd.policy_decision(self.policy, spec, None,
                                             {"path": "commandless-exec-policy-test-den"
                                                 "y-me"})
        self.assertEqual("deny", decision)

    def test_run_command_is_unaffected(self):
        """The downgrade only applies to tools with no `command` argument at
        all — run_command has one, so it still goes through the normal $SAFE
        check on the actual command text."""
        spec = argusd.toolreg.REGISTRY["run_command"]
        decision, _ = argusd.policy_decision(self.policy, spec, None, {"command": "rm "
            "-rf /tmp/x"})
        self.assertEqual("prompt", decision)


class McpGrantPolicyTests(unittest.TestCase):
    """MCP tools are opaque, user-added third-party code — same posture as
    "net": prompt every call until the user explicitly saves an allow rule
    for that exact server.tool subject (see lib/tools.py's
    _register_mcp_tools and policy.py's DEFAULTS["mcp"])."""
    def setUp(self):
        self.ws = Workspace(support.make_workspace("policy-mcp"))
        self.policy = Policy(self.ws.root)

    def _spec(self, subject, risk="soft"):
        return {"name": "mcp__fs__" + subject, "grant": "mcp", "risk": risk,
                "subject": lambda ctx, args, _s=subject: ["fs." + _s]}

    def test_an_unremembered_call_prompts_regardless_of_risk_tier(self):
        # Unique subject per iteration — Policy's memory file is process-
        # global, not per-test (see CommandlessExecToolPolicyTests' own
        # warning about this above), so reusing one subject across the
        # other tests below would leak their remembered rules in here.
        for risk in ("read", "soft", "commit"):
            with self.subTest(risk=risk):
                spec = self._spec("unremembered_" + risk, risk)
                decision, reason = argusd.policy_decision(self.policy, spec, None, {})
                self.assertEqual("prompt", decision)

    def test_a_saved_allow_rule_for_that_server_tool_flows_auto(self):
        self.policy.remember("fs.mcp-policy-test-allow-me", allow=True)
        decision, _ = argusd.policy_decision(self.policy, self._spec("mcp-policy-test-a"
            "llow-me"),
                                             None, {})
        self.assertEqual("auto", decision)

    def test_a_saved_allow_rule_does_not_leak_to_a_different_tool(self):
        self.policy.remember("fs.mcp-policy-test-allow-only-me", allow=True)
        other = self._spec("mcp-policy-test-allow-only-me-NOT-this-one", "commit")
        decision, _ = argusd.policy_decision(self.policy, other, None, {})
        self.assertEqual("prompt", decision)

    def test_a_saved_deny_rule_wins_over_everything(self):
        self.policy.remember("fs.mcp-policy-test-deny-me", allow=False)
        decision, _ = argusd.policy_decision(self.policy, self._spec("mcp-policy-test-d"
            "eny-me"),
                                             None, {})
        self.assertEqual("deny", decision)


class CommandChainingTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(support.make_workspace("policy"))
        self.policy = Policy(self.ws.root)

    def decision(self, command, **kwargs):
        return self.policy.classify("exec", command=command, **kwargs)[0]

    def test_read_only_commands_run_unattended(self):
        for cmd in ("ls -la", "cat a.py", "git status", "rg foo .",
                    "python3 -m py_compile x.py", "ruff check ."):
            with self.subTest(cmd=cmd):
                self.assertEqual("auto", self.decision(cmd))

    def test_chained_safe_commands_are_allowed(self):
        for cmd in ("ls && git status",
                    "python3 -m py_compile x.py && python3 -m unittest discover",
                    "ruff check . ; ruff format ."):
            with self.subTest(cmd=cmd):
                self.assertTrue(segments_safe(cmd))
                self.assertEqual("auto", self.decision(cmd))

    def test_env_prefix_on_a_safe_command_is_allowed(self):
        """VAR=val before an otherwise-$SAFE command auto-runs.

        Regression: running a program against a temp data file
        (EXPENSES_DATA_FILE=/tmp/t.json python3 -m pytest) prompted every
        time, so verification demos stalled on approvals even though the
        underlying command was already inside $SAFE.
        """
        for cmd in ("EXPENSES_DATA_FILE=/tmp/t.json python3 -m pytest -q",
                    "A=1 B=2 pytest -q",
                    "TMPDIR=/tmp python3 -m unittest discover"):
            with self.subTest(cmd=cmd):
                self.assertTrue(segments_safe(cmd))
                self.assertEqual("auto", self.decision(cmd))

    def test_env_value_metacharacters_are_never_stripped_away(self):
        """An assignment value that could smuggle chaining/substitution fails.

        Only bare-word values are stripped: $(), backticks, quotes with
        separators, or chaining characters inside the value keep the segment
        outside $SAFE — same reasoning as the newline-chaining hole above.
        And running an arbitrary script (python3 expenses.py) stays
        prompt-gated even behind a clean env prefix: $SAFE covers the fixed
        build/inspect command set, not "any python file".
        """
        for cmd in ("FOO=$(rm -rf /tmp/x) python3 -m pytest -q",
                    "FOO='a; rm -rf /tmp/x' python3 -m pytest -q",
                    "FOO=a&&rm -rf /tmp/x python3 -m pytest -q",
                    "EXPENSES_DATA_FILE=/tmp/t.json python3 expenses.py add 8 "
                        "transport"):
            with self.subTest(cmd=cmd):
                self.assertFalse(segments_safe(cmd))
                self.assertEqual("prompt", self.decision(cmd))

    def test_unsafe_tail_after_a_safe_head_prompts(self):
        for cmd in ("ls && rm -rf /tmp/x",
                    "cat a.py; rm -rf /tmp/x",
                    "cat a.py && touch /tmp/pwned",
                    "cat a.py | sh"):
            with self.subTest(cmd=cmd):
                self.assertFalse(segments_safe(cmd))
                self.assertEqual("prompt", self.decision(cmd))

    def test_newline_chaining_is_not_a_bypass(self):
        """A newline ends a shell command exactly like `;`.

        Regression: `[^&|`$(){}]*$` matched a newline and `$` matches at the end
        of the whole string, so the whole multi-line string passed as one "safe"
        command and every line after the first ran with no approval.
        """
        for cmd in ("cat a.py\nrm -rf /tmp/x",
                    "cat a.py\r\nrm -rf /tmp/x",
                    "ls\ntouch /tmp/pwned"):
            with self.subTest(cmd=cmd):
                self.assertFalse(segments_safe(cmd))
                self.assertEqual("prompt", self.decision(cmd))

    def test_trailing_newline_is_still_fine(self):
        self.assertTrue(segments_safe("ls -la\n"))
        self.assertEqual("auto", self.decision("ls -la\n"))

    def test_fd_duplication_is_not_chaining(self):
        self.assertTrue(segments_safe("python3 -m pytest -q 2>&1"))

    def test_hard_denies_are_never_offered_for_approval(self):
        for cmd in ("sudo rm -rf /tmp/x", "pacman -S foo", "systemctl stop sshd",
                    "rm -rf /", "mkfs.ext4 /dev/sda1", "reboot"):
            with self.subTest(cmd=cmd):
                self.assertEqual("deny", self.decision(cmd))

    def test_net_requests_prompt(self):
        self.assertEqual("prompt", self.policy.classify("net", command="curl "
            "example.com")[0])

    def test_saved_rule_is_exact_not_a_wildcard(self):
        self.assertEqual("prompt", self.decision("touch /tmp/thing"))
        self.policy.remember("touch /tmp/thing")
        self.assertEqual("auto", self.decision("touch /tmp/thing"))
        self.assertEqual("prompt", self.decision("touch /tmp/thing-2"))

    def test_a_saved_deny_beats_a_saved_allow(self):
        self.policy.remember("touch /tmp/both")
        self.policy.remember("touch /tmp/both", allow=False)
        self.assertEqual("deny", self.decision("touch /tmp/both"))


class SubjectScopingTests(unittest.TestCase):
    """Which argument the policy judges is declared by each tool, not guessed."""

    def setUp(self):
        self.ws = Workspace(support.make_workspace("policy-subjects"))
        self.policy = Policy(self.ws.root)
        self.ctx = argusd.Context(argusd.connect(), "policy-subjects", self.ws,
                                  self.policy, Checkpoints("policy-subjects"),
                                  argusd.grants())

    def decision(self, tool, args):
        spec_doc = dict(argusd.toolreg.REGISTRY[tool])
        return argusd.policy_decision(self.policy, spec_doc, self.ctx, args)

    def test_workspace_paths_are_automatic(self):
        inside = str(self.ws.root / "a.py")
        for tool, args in (("read_file", {"path": inside}),
                           ("write_file", {"path": inside, "content": "x"}),
                           ("edit_file", {"path": inside, "old_strin"
                               "g": "a", "new_string": "b"}),
                           ("glob", {"pattern": "**/*.py"}),
                           ("grep", {"pattern": "x"}),
                           ("list_dir", {})):
            with self.subTest(tool=tool):
                self.assertEqual("auto", self.decision(tool, args)[0])

    def test_paths_outside_the_workspace_prompt(self):
        for tool, args in (("read_file", {"path": "/etc/passwd"}),
                           ("write_file", {"path": "/etc/pwn", "content": "x"}),
                           ("edit_file", {"path": "../up.py", "old_strin"
                               "g": "a", "new_string": "b"})):
            with self.subTest(tool=tool):
                self.assertEqual("prompt", self.decision(tool, args)[0])

    def test_move_file_judges_both_ends(self):
        """move_file's paths are src/dst — not `path` — and used to be
        classified with no subject at all, i.e. auto-approved unchecked."""
        inside = str(self.ws.root / "a.py")
        self.assertEqual("auto", self.decision("move_fil"
            "e", {"src": inside, "dst": inside + "2"})[0])
        self.assertEqual("prompt", self.decision("move_fil"
            "e", {"src": inside, "dst": "/tmp/pwn"})[0])
        self.assertEqual("prompt", self.decision("move_file", {"src": "/etc/passw"
            "d", "dst": inside})[0])

    def test_a_path_scoped_tool_with_no_path_fails_closed(self):
        decision, reason = self.decision("write_file", {"content": "x"})
        self.assertEqual("prompt", decision)
        self.assertIn("no path to check", reason)

    def test_checkpoint_restore_judges_the_restored_path(self):
        """An unknown checkpoint id yields no subject, which is refused rather
        than treated as inside the workspace."""
        self.assertEqual("prompt", self.decision("checkpoint_restor"
            "e", {"id": "c-nope"})[0])

    def test_restoring_a_real_checkpoint_is_still_automatic(self):
        target = support.write(self.ws.root / "a.py", "x = 1\n")
        cid = self.ctx.checkpoints.save(target, self.ws.root, "edit_file")
        self.assertEqual("auto", self.decision("checkpoint_restore", {"id": cid})[0])

    def test_non_path_tools_are_not_judged_as_paths(self):
        for tool, args in (("todo_writ"
            "e", {"todos": [{"content": "x", "status": "pending"}]}),
                           ("checkpoint_list", {})):
            with self.subTest(tool=tool):
                self.assertEqual("auto", self.decision(tool, args)[0])

    def test_run_command_net_escalates_but_never_downgrades(self):
        self.assertEqual("auto", self.decision("run_command", {"command": "ls"})[0])
        self.assertEqual("prompt", self.decision("run_comman"
            "d", {"command": "ls", "net": True})[0])
        self.assertEqual("deny", self.decision("run_comman"
            "d", {"command": "sudo ls", "net": True})[0])

    def test_commit_tier_input_actions_still_prompt(self):
        for tool, args in (("type_tex"
            "t", {"text": "hi"}), ("key_press", {"key": "Return"})):
            with self.subTest(tool=tool):
                self.assertEqual("prompt", self.decision(tool, args)[0])


class HomeDirectoryPolicyTests(unittest.TestCase):
    """Confirmed with the user: file tools auto-approve anywhere under
    $HOME, not just the declared workspace. Path.home() is mocked to an
    isolated fixture directory (never the real one), matching
    WorkspaceHomeAccessTests in test_workspace_and_checkpoints.py."""

    def setUp(self):
        self.fake_home = support.make_workspace("policy-fake-home"
            "-" + self._testMethodName)
        patch = mock.patch.object(Path, "home", return_value=self.fake_home)
        patch.start()
        self.addCleanup(patch.stop)
        self.root = self.fake_home / "projects" / "myapp"
        self.root.mkdir(parents=True, exist_ok=True)
        self.ws = Workspace(self.root)
        self.policy = Policy(self.ws.root)
        self.ctx = argusd.Context(argusd.connect(), "policy-home"
            "-" + self._testMethodName,
                                  self.ws, self.policy, Checkpoints("policy-hom"
                                      "e"), argusd.grants())

    def decision(self, tool, args):
        spec_doc = dict(argusd.toolreg.REGISTRY[tool])
        return argusd.policy_decision(self.policy, spec_doc, self.ctx, args)

    def test_a_home_write_outside_the_workspace_prompts(self):
        elsewhere = str(self.fake_home / "projects" / "other-app" / "notes.md")
        self.assertEqual("auto", self.decision("read_file", {"path": elsewhere})[0])
        self.assertEqual("prompt", self.decision("write_file",
                         {"path": elsewhere, "content": "x"})[0])

    def test_a_path_outside_home_entirely_still_prompts(self):
        self.assertEqual("prompt", self.decision("read_file", {"path": "/etc/passw"
            "d"})[0])
        self.assertEqual("prompt", self.decision("read_file",
                         {"path": str(support.TMP / "outside-everything.txt")})[0])


if __name__ == "__main__":
    unittest.main()
