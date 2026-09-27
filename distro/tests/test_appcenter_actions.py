import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/argus-appcenter.py"


def load():
    spec = importlib.util.spec_from_file_location("argus_appcenter", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AppCenterActionTests(unittest.TestCase):
    def setUp(self):
        self.ac = load()
        self.real_which = self.ac.shutil.which

    def which_without(self, *missing):
        return lambda name: None if name in missing else self.real_which(name)

    def captured_install(self, source, pkg, missing=()):
        cap = []
        with mock.patch.object(self.ac.shutil, "which", self.which_without(*missing)), \
             mock.patch.object(self.ac, "launch_in_terminal", lambda t, c: cap.append(c) or 0):
            self.ac.execute_install(source, pkg)
        return cap[0]

    def test_aur_without_helper_bootstraps_paru_instead_of_pacman(self):
        cmd = self.captured_install("aur", "zen-browser-bin", missing=("paru", "yay"))
        self.assertIn("paru-bin", cmd)
        self.assertIn("paru -S --noconfirm zen-browser-bin", cmd)
        self.assertNotIn("sudo pacman -S --noconfirm zen-browser-bin", cmd)

    def test_flatpak_install_adds_user_remote_and_needs_no_aur_helper(self):
        cmd = self.captured_install("flatpak", "org.mozilla.firefox", missing=("paru", "yay"))
        self.assertIn("remote-add --user --if-not-exists flathub", cmd)
        self.assertIn("flatpak install --user -y flathub org.mozilla.firefox", cmd)
        self.assertNotIn("paru", cmd)

    def test_generated_commands_are_valid_bash(self):
        for src, pkg in (("arch", "zed"), ("aur", "cursor-bin"), ("flatpak", "com.spotify.Client")):
            cmd = self.captured_install(src, pkg, missing=("paru", "yay"))
            self.assertEqual(subprocess.run(["bash", "-n", "-c", cmd]).returncode, 0, cmd)

    def test_bad_package_ids_are_refused_before_any_shell(self):
        for args in (["install", "aur", "x'; touch /tmp/kx-pwn; '"], ["uninstall", "arch", "a b"],
                     ["install", "snap", "zed"]):
            r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("error", json.loads(r.stdout))
        self.assertFalse(Path("/tmp/kx-pwn").exists())

    def test_terminal_job_blocks_and_reports_failure_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "xterm"
            fake.write_text('#!/bin/bash\nexec bash -c "$6" < /dev/null > /dev/null 2>&1\n')
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            which = lambda n: str(fake) if n == "xterm" else None  # noqa: E731
            with mock.patch.object(self.ac.shutil, "which", which), \
                 mock.patch.dict(os.environ, {"TERMINAL": ""}):
                self.assertEqual(self.ac.launch_in_terminal("t", "true"), 0)
                self.assertEqual(self.ac.launch_in_terminal("t", "exit 3"), 3)

    def test_no_terminal_returns_127(self):
        with mock.patch.object(self.ac.shutil, "which", lambda n: None), \
             mock.patch.object(self.ac.subprocess, "Popen") as popen:
            self.assertEqual(self.ac.launch_in_terminal("t", "true"), 127)
            self.assertEqual(popen.call_args[0][0][0], "notify-send")


if __name__ == "__main__":
    unittest.main()
