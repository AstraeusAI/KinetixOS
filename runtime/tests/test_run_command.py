"""run_command's workspace-writable-by-default behavior, write=false as the
deliberate opt-out, and the hint left when a command hits the read-only
wall after explicitly asking for it.

This used to default to read-only, requiring write=true on every command
that touched a file at all — including pure incidental side effects (a test
run's own __pycache__, a formatter's temp file) — and confirmed live to
misfire on the most mundane case imaginable: a plain `rm -rf __pycache__`
cleanup failed with a raw "Read-only file system" OS error and nothing
else. policy_decision() never looks at `write` at all — a destructive
command goes through the same $SAFE/approval gate regardless (see
policy.py) — so the old default added friction with no matching safety
benefit.
"""
import unittest

import support  # noqa: F401

import argusd
from lib import sandbox, tools


@unittest.skipUnless(sandbox.have_bwrap(), "bwrap is not installed")
class RunCommandDefaultWriteTests(unittest.TestCase):
    def setUp(self):
        self.ws = support.make_workspace("ws-run-command-rw")
        support.write(self.ws / "existing.txt", "hello\n")
        workspace = argusd.Workspace(self.ws)
        self.ctx = argusd.Context(argusd.connect(), "rw-default-test", workspace,
                                  argusd.Policy(workspace.root),
                                  argusd.Checkpoints("rw-default-tes"
                                      "t"), argusd.grants())

    def run_command(self, **args):
        return tools.REGISTRY["run_command"]["handler"](self.ctx, args)

    def test_a_write_attempt_with_no_write_arg_at_all_just_succeeds(self):
        """The actual point of this change: no write=true needed."""
        r = self.run_command(command="rm existing.txt")
        self.assertTrue(r["ok"], r)
        self.assertFalse((self.ws / "existing.txt").exists())
        self.assertNotIn("note", r)

    def test_write_true_is_still_accepted_and_still_writable(self):
        r = self.run_command(command="rm existing.txt", write=True)
        self.assertTrue(r["ok"], r)

    def test_write_false_deliberately_makes_it_read_only(self):
        r = self.run_command(command="rm existing.txt", write=False)
        self.assertFalse(r["ok"], r)
        self.assertIn("read-only file system", r["stderr"].lower())
        self.assertTrue((self.ws / "existing.txt").exists(),
                        "the file must survive a write=false command")

    def test_write_false_failure_gets_an_actionable_note(self):
        r = self.run_command(command="rm existing.txt", write=False)
        self.assertIn("write=false", r["note"])

    def test_a_read_only_command_gets_no_note_either_way(self):
        r = self.run_command(command="cat existing.txt")
        self.assertTrue(r["ok"], r)
        self.assertNotIn("note", r)
        r2 = self.run_command(command="cat existing.txt", write=False)
        self.assertTrue(r2["ok"], r2)
        self.assertNotIn("note", r2)

    def test_a_genuine_command_failure_unrelated_to_write_gets_no_note(self):
        r = self.run_command(command="exit 3")
        self.assertFalse(r["ok"], r)
        self.assertNotIn("note", r)


if __name__ == "__main__":
    unittest.main()
