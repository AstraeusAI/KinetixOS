"""Critical-path latency fixes: the capability cache and the in-process
test-runner probe keep per-message setup off the first-token path."""
import os
import tempfile
import time
import unittest
from unittest import mock

import support  # noqa: F401

from lib import kwin, workspace


class CapabilityCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="argus-caps-")
        self.env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_fresh_cache_is_reused_without_probing(self):
        with mock.patch.object(kwin, "capabilities", return_value={"pointer": True}) as probe:
            first = kwin.capabilities_cached()
            second = kwin.capabilities_cached()
        self.assertEqual({"pointer": True}, first)
        self.assertEqual(first, second)
        self.assertEqual(1, probe.call_count)

    def test_stale_cache_probes_live_again(self):
        with mock.patch.object(kwin, "capabilities", return_value={"pointer": True}):
            kwin.capabilities_cached()
        path = kwin._caps_cache_path()
        old = time.time() - kwin.CAPS_CACHE_MAX_AGE - 5
        os.utime(path, (old, old))
        with mock.patch.object(kwin, "capabilities", return_value={"pointer": False}) as probe:
            self.assertEqual({"pointer": False}, kwin.capabilities_cached())
        self.assertEqual(1, probe.call_count)

    def test_corrupt_cache_falls_back_to_a_live_probe(self):
        path = kwin._caps_cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("{not json")
        with mock.patch.object(kwin, "capabilities", return_value={"grim": True}) as probe:
            self.assertEqual({"grim": True}, kwin.capabilities_cached())
        self.assertEqual(1, probe.call_count)


class PythonTestCommandTests(unittest.TestCase):
    def setUp(self):
        workspace.Workspace._python_test_cmd.cache_clear()

    def tearDown(self):
        workspace.Workspace._python_test_cmd.cache_clear()

    def test_same_interpreter_answers_without_spawning(self):
        import sys
        with mock.patch.object(workspace, "_which", return_value=sys.executable), \
             mock.patch("subprocess.run") as run:
            cmd = workspace.Workspace._python_test_cmd()
        run.assert_not_called()
        self.assertIn(cmd[:3], (["python3", "-m", "pytest"], ["python3", "-m", "unittest"]))

    def test_a_different_python3_still_uses_the_subprocess_probe(self):
        with mock.patch.object(workspace, "_which", return_value="/nonexistent/other/python3"), \
             mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            cmd = workspace.Workspace._python_test_cmd()
        run.assert_called()
        self.assertEqual(["python3", "-m", "pytest", "-q"], cmd)


if __name__ == "__main__":
    unittest.main()
