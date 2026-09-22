import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

import support  # noqa: F401

from lib import daemon


WORKER = '''#!/usr/bin/env python3
import json, os, sys, time
op = sys.argv[1]
if op == "run":
    task = sys.argv[sys.argv.index("--task") + 1]
    if task == "wait":
        time.sleep(30)
    print(json.dumps({"type": "result", "ok": True, "text": task,
                      "grant": os.getenv("ARGUS_GRANT_INPUT")}))
elif op == "approve":
    print(json.dumps({"type": "result", "ok": True, "text": "approved"}))
'''


class SocketPathTests(unittest.TestCase):
    def test_daemon_refuses_to_replace_a_regular_file(self):
        root = Path(tempfile.mkdtemp(prefix="argus-daemon-path-test-"))
        path = root / "argusd.sock"
        path.write_text("keep me")
        server = daemon.Daemon(root / "worker.py", path)
        with self.assertRaisesRegex(RuntimeError, "refusing to replace non-socket"):
            server.serve()
        self.assertEqual("keep me", path.read_text())


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="argus-daemon-test-"))
        self.worker = self.root / "worker.py"
        self.worker.write_text(WORKER)
        self.path = self.root / "argusd.sock"
        self.server = daemon.Daemon(self.worker, self.path)
        self.thread = threading.Thread(target=self.server.serve, daemon=True)
        self.thread.start()
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                out = io.BytesIO()
                daemon.client({"op": "ping"}, self.path, out)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.01)
        else:
            self.fail("daemon did not become ready")

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)

    def call(self, request):
        out = io.BytesIO()
        daemon.client(request, self.path, out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_ping_reports_the_daemon_pid(self):
        reply = self.call({"op": "ping"})
        self.assertTrue(reply[0]["ok"])
        self.assertEqual(os.getpid(), reply[0]["pid"])

    def test_run_streams_worker_output_and_propagates_grants(self):
        reply = self.call({"op": "run", "id": "r1", "task": "hello", "session": "s",
                           "workspace": str(self.root), "grants": {"input": True}})
        self.assertEqual("hello", reply[0]["text"])
        self.assertEqual("1", reply[0]["grant"])

    def test_approve_is_forwarded(self):
        reply = self.call({"op": "approve", "id": "r2", "approval_id": "a-1",
                           "workspace": str(self.root), "allow": True})
        self.assertEqual("approved", reply[0]["text"])

    def test_cancel_terminates_the_active_worker(self):
        output = io.BytesIO()
        thread = threading.Thread(target=daemon.client,
                                  args=({"op": "run", "id": "slow", "task": "wait"},
                                        self.path, output))
        thread.start()
        deadline = time.time() + 3
        while "slow" not in self.server.active and time.time() < deadline:
            time.sleep(0.01)
        reply = self.call({"op": "cancel", "id": "slow"})
        thread.join(timeout=5)
        self.assertTrue(reply[0]["ok"])
        self.assertFalse(thread.is_alive())
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(any(m.get("type") == "transport_error" for m in messages))


if __name__ == "__main__":
    unittest.main()
