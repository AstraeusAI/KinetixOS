"""Workspace containment and the checkpoint/undo layer."""
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401

from lib.checkpoints import Checkpoints
from lib.workspace import Workspace


class WorkspaceContainmentTests(unittest.TestCase):
    def setUp(self):
        self.root = support.make_workspace("ws-contain")
        support.write(self.root / "a.py", "x = 1\n")
        self.ws = Workspace(self.root)

    def test_relative_and_absolute_paths_inside(self):
        self.assertEqual(self.root / "a.py", self.ws.resolve("a.py"))
        self.assertEqual(self.root / "a.py", self.ws.resolve(str(self.root / "a.py")))
        self.assertEqual(self.root / "new" / "file.py",
                         self.ws.resolve("new/file.py"))  # need not exist yet

    def test_parent_traversal_is_refused(self):
        with self.assertRaises(PermissionError):
            self.ws.resolve("../outside.py")

    def test_symlinks_are_resolved_before_the_check(self):
        outside = support.TMP / "outside.txt"
        support.write(outside, "secret\n")
        (self.root / "file-link").symlink_to(outside)
        (self.root / "dir-link").symlink_to(support.TMP)
        for path in ("file-link", "dir-link/outside.txt"):
            with self.subTest(path=path):
                with self.assertRaises(PermissionError):
                    self.ws.resolve(path)

    def test_must_exist(self):
        with self.assertRaises(FileNotFoundError):
            self.ws.resolve("nope.py", must_exist=True)

    def test_walk_skips_vendor_dirs(self):
        support.write(self.root / "node_modules" / "pkg" / "index.js", "x")
        names = [p.name for p in self.ws.walk()]
        self.assertIn("a.py", names)
        self.assertNotIn("index.js", names)


class WorkspaceHomeAccessTests(unittest.TestCase):
    """Confirmed with the user: every file tool should reach anywhere under
    $HOME, not just the declared workspace — while paths outside both stay
    refused. Path.home() is mocked to an isolated fixture directory here
    (never the real one) so these tests cannot touch the actual user's
    real home directory."""

    def setUp(self):
        self.fake_home = support.make_workspace("ws-fake-home-" + self._testMethodName)
        patch = mock.patch.object(Path, "home", return_value=self.fake_home)
        patch.start()
        self.addCleanup(patch.stop)
        self.root = self.fake_home / "projects" / "myapp"
        self.root.mkdir(parents=True, exist_ok=True)
        self.ws = Workspace(self.root)

    def test_a_path_elsewhere_under_home_is_now_allowed(self):
        other_project = self.fake_home / "projects" / "other-app" / "readme.md"
        other_project.parent.mkdir(parents=True)
        other_project.write_text("hello\n")
        self.assertEqual(other_project, self.ws.resolve(str(other_project)))

    def test_a_dotfile_directly_under_home_is_allowed(self):
        dotfile = self.fake_home / ".bashrc"
        dotfile.write_text("# stuff\n")
        self.assertEqual(dotfile, self.ws.resolve(str(dotfile)))

    def test_something_outside_both_the_workspace_and_home_is_still_refused(self):
        with self.assertRaises(PermissionError):
            self.ws.resolve(str(support.TMP / "definitely-outside.txt"))

    def test_a_symlink_from_home_pointing_further_outside_is_still_refused(self):
        outside = support.TMP / "real-outside.txt"
        support.write(outside, "secret\n")
        link = self.fake_home / "escape-link"
        link.symlink_to(outside)
        with self.assertRaises(PermissionError):
            self.ws.resolve(str(link))

    def test_the_declared_workspace_itself_stays_allowed_even_outside_home(self):
        """The common case in this very test suite: fixtures live under
        /tmp, never under the (here, faked) home directory at all."""
        outside_ws = Workspace(support.make_workspace("ws-outside-home"))
        p = outside_ws.root / "f.py"
        support.write(p, "x = 1\n")
        self.assertEqual(p, outside_ws.resolve(str(p)))


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.root = support.make_workspace("ws-cp")
        self.ws = Workspace(self.root)
        self.cps = Checkpoints("cp-tests")

    def test_restore_brings_back_a_modified_file(self):
        target = support.write(self.root / "a.py", "original\n")
        cid = self.cps.save(target, self.ws.root, "edit_file")
        target.write_text("changed\n")
        self.assertEqual("restore"
            "d", self.cps.restore(cid, workspace=self.ws.root)["action"])
        self.assertEqual("original\n", target.read_text())

    def test_restore_removes_a_file_the_agent_created(self):
        target = self.root / "created.py"
        cid = self.cps.save(target, self.ws.root, "write_file")
        target.write_text("new\n")
        self.assertEqual("remove"
            "d", self.cps.restore(cid, workspace=self.ws.root)["action"])
        self.assertFalse(target.exists())

    def test_rapid_saves_get_distinct_ids(self):
        target = support.write(self.root / "b.py", "one\n")
        ids = [self.cps.save(target, self.ws.root, "t") for _ in range(3)]
        self.assertEqual(3, len(set(ids)))

    def test_a_move_is_undone_by_restoring_both_checkpoints(self):
        src = support.write(self.root / "src.py", "body\n")
        dst = self.root / "dst.py"
        cid_src = self.cps.save(src, self.ws.root, "move_file:src")
        cid_dst = self.cps.save(dst, self.ws.root, "move_file:dst")
        src.rename(dst)
        self.cps.restore(cid_dst, workspace=self.ws.root)
        self.assertFalse(dst.exists())
        self.cps.restore(cid_src, workspace=self.ws.root)
        self.assertEqual("body\n", src.read_text())

    def test_restore_refuses_a_path_outside_the_workspace(self):
        """The target comes out of the manifest, not from the caller, so it is
        re-checked rather than trusted."""
        outside = support.write(support.TMP / "elsewhere.txt", "host content\n")
        cid = self.cps.save(outside, self.ws.root, "write_file")
        outside.write_text("clobbered\n")
        result = self.cps.restore(cid, workspace=self.ws.root)
        self.assertFalse(result["ok"])
        self.assertIn("outside the workspace", result["error"])
        self.assertEqual("clobbered\n", outside.read_text())

    def test_unknown_checkpoint_is_reported(self):
        self.assertFalse(self.cps.restore("c-does-not-exis"
            "t", workspace=self.ws.root)["ok"])


if __name__ == "__main__":
    unittest.main()
