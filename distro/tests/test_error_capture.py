import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/kinetix-errors.py"


class ErrorCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.tmp.name) / "run"
        self.data = Path(self.tmp.name) / "data"
        self.runtime.mkdir()
        self.env = {**os.environ, "XDG_RUNTIME_DIR": str(self.runtime), "XDG_DATA_HOME": str(self.data)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, extra_env=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                              env={**self.env, **(extra_env or {})}, timeout=20)

    def simulate(self):
        r = self.run_script("simulate")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_simulate_emits_event_with_a_private_captured_log(self):
        ev = self.simulate()
        self.assertEqual(ev["type"], "error")
        self.assertEqual(ev["kind"], "crash")
        log = Path(ev["log"])
        self.assertTrue(log.is_file())
        self.assertEqual(log.parent, self.runtime / "kinetix-errors")
        self.assertEqual(oct(log.stat().st_mode & 0o777), "0o600")
        self.assertIn("KinetixOS error report", log.read_text())

    def test_save_copies_the_report_into_the_persistent_error_log_dir(self):
        ev = self.simulate()
        r = self.run_script("save", ev["log"], ev["app"])
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"])
        saved = Path(out["path"])
        self.assertEqual(saved.parent, self.data / "kinetix/error-logs")
        self.assertIn("KinetixOS error report", saved.read_text())

    def test_save_refuses_paths_outside_the_runtime_capture_dir(self):
        # the log path arrives from a UI event — it must never be an arbitrary file read
        outside = Path(self.tmp.name) / "secret.txt"
        outside.write_text("do not copy me")
        for target in (str(outside), "/etc/passwd", str(self.runtime / "kinetix-errors" / ".." / ".." / "data")):
            r = self.run_script("save", target, "x")
            self.assertEqual(r.returncode, 1)
            self.assertFalse(json.loads(r.stdout)["ok"])
        self.assertFalse((self.data / "kinetix/error-logs").exists())

    def test_save_text_stores_shell_internal_errors(self):
        r = self.run_script("save-text", "Kinetix Shell", extra_env={"KINETIX_ERR_TEXT": "boom\ntrace"})
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"])
        body = Path(out["path"]).read_text()
        self.assertIn("boom\ntrace", body)
        self.assertIn("Kinetix-Shell", Path(out["path"]).name)   # filename is sanitised

    def test_saved_logs_are_pruned_to_the_newest_hundred(self):
        logs = self.data / "kinetix/error-logs"
        logs.mkdir(parents=True)
        for i in range(105):
            p = logs / f"old-{i:03}.log"
            p.write_text("x")
            os.utime(p, (1_000_000 + i, 1_000_000 + i))
        r = self.run_script("save-text", "app", extra_env={"KINETIX_ERR_TEXT": "new"})
        self.assertTrue(json.loads(r.stdout)["ok"])
        remaining = sorted(logs.glob("*.log"))
        self.assertEqual(len(remaining), 100)
        self.assertFalse((logs / "old-000.log").exists())


if __name__ == "__main__":
    unittest.main()
