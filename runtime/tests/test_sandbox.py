"""The sandbox itself — real bwrap runs, skipped when it is not installed.

Nothing here is mocked except Path.home() in the tests that specifically
cover the $HOME bind (always redirected to an isolated fixture directory,
never the real one) — everything else exercises the real properties the
rest of the runtime's safety argument rests on: the workspace and $HOME are
the only host data visible, writes need write_workspace, and "timed out"
means the process tree is gone.
"""
import time
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401

from lib import sandbox


@unittest.skipUnless(sandbox.have_bwrap(), "bwrap is not installed")
class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.ws = support.make_workspace("ws-sandbox")

    def test_a_command_runs_and_reports_its_output(self):
        result = sandbox.run("echo hello", self.ws, timeout=60)
        self.assertTrue(result["ok"], result)
        self.assertIn("hello", result["stdout"])
        self.assertTrue(result["sandboxed"])

    def test_run_command_returns_non_zero_without_raising(self):
        result = sandbox.run("exit 3", self.ws, timeout=60)
        self.assertFalse(result["ok"])
        self.assertEqual(3, result["code"])

    def test_files_outside_the_workspace_and_home_are_not_visible(self):
        outside = support.write(support.TMP / "host-secret.txt", "secret-payload\n")
        result = sandbox.run(f"cat {outside}", self.ws, timeout=60)
        self.assertFalse(result["ok"])
        self.assertNotIn("secret-payload", result["stdout"])

    def test_home_env_var_matches_the_real_bound_home_and_keys_are_not_in_the_environment(self):
        """$HOME inside the sandbox must agree with the path that is
        actually bound (see build_argv()'s own comment on this) — a real
        regression once, caught live: $HOME pointed at a leftover synthetic
        /tmp/home while the real home was separately bound elsewhere, so
        `~` inside a sandboxed command silently resolved to the wrong,
        empty directory instead of the one that actually had the files."""
        result = sandbox.run("echo $HOME; env | wc -l", self.ws, timeout=60)
        self.assertTrue(result["ok"], result)
        self.assertIn(str(Path.home()), result["stdout"])
        self.assertNotIn("API_KEY", result["stdout"])

    def test_tilde_expansion_inside_the_sandbox_reaches_the_real_bound_home(self):
        marker = support.write(Path.home() / ".argus-sandbox-tilde-test", "found-me\n")
        try:
            result = sandbox.run("cat ~/.argus-sandbox-tilde-test", self.ws, timeout=60)
            self.assertTrue(result["ok"], result)
            self.assertIn("found-me", result["stdout"])
        finally:
            marker.unlink(missing_ok=True)

    def test_the_workspace_is_read_only_unless_write_is_requested(self):
        support.write(self.ws / "f.txt", "before\n")
        denied = sandbox.run("echo x > f.txt", self.ws, timeout=60)
        self.assertFalse(denied["ok"])
        self.assertEqual("before\n", (self.ws / "f.txt").read_text())

        allowed = sandbox.run("echo x > f.txt", self.ws, write_workspace=True, timeout=60)
        self.assertTrue(allowed["ok"], allowed)
        self.assertEqual("x\n", (self.ws / "f.txt").read_text())

    def test_a_timeout_returns_promptly_and_says_so(self):
        started = time.time()
        result = sandbox.run("(sleep 30 &) ; sleep 30", self.ws, timeout=2)
        elapsed = time.time() - started
        self.assertFalse(result["ok"])
        self.assertIn("timed out after 2s", result["error"])
        self.assertLess(elapsed, 15, "the timeout path waited for the command instead of killing it")


@unittest.skipUnless(sandbox.have_bwrap(), "bwrap is not installed")
class SandboxHomeAccessTests(unittest.TestCase):
    """Confirmed with the user: a sandboxed command should reach anywhere
    under $HOME, not just the declared workspace — matching the same
    expansion made to the file tools' own boundary (workspace.py's
    resolve()). Path.home() is mocked to an isolated fixture directory for
    every test here (never the real one), so nothing here can touch the
    actual user's real home directory."""

    def setUp(self):
        self.fake_home = support.make_workspace("sandbox-fake-home-" + self._testMethodName)
        patch = mock.patch.object(Path, "home", return_value=self.fake_home)
        patch.start()
        self.addCleanup(patch.stop)
        # The workspace is deliberately a *different* directory from
        # fake_home, so a passing read/write can only be explained by the
        # new $HOME bind, not the pre-existing workspace bind.
        self.ws = support.make_workspace("sandbox-unrelated-ws-" + self._testMethodName)

    def test_a_file_elsewhere_under_home_is_readable_by_default(self):
        elsewhere = support.write(self.fake_home / "notes" / "todo.txt", "buy milk\n")
        result = sandbox.run(f"cat {elsewhere}", self.ws, timeout=60)
        self.assertTrue(result["ok"], result)
        self.assertIn("buy milk", result["stdout"])

    def test_a_file_elsewhere_under_home_is_writable_by_default(self):
        target = support.write(self.fake_home / "notes" / "todo.txt", "before\n")
        result = sandbox.run(f"echo after > {target}", self.ws, write_workspace=True, timeout=60)
        self.assertTrue(result["ok"], result)
        self.assertEqual("after\n", target.read_text())

    def test_home_is_read_only_when_write_workspace_is_false(self):
        target = support.write(self.fake_home / "notes" / "todo.txt", "before\n")
        result = sandbox.run(f"echo after > {target}", self.ws, timeout=60)
        self.assertFalse(result["ok"])
        self.assertEqual("before\n", target.read_text())

    def test_a_file_outside_both_home_and_workspace_is_still_invisible(self):
        outside = support.write(support.TMP / "genuinely-outside.txt", "secret\n")
        result = sandbox.run(f"cat {outside}", self.ws, timeout=60)
        self.assertFalse(result["ok"])
        self.assertNotIn("secret", result["stdout"])


if __name__ == "__main__":
    unittest.main()
