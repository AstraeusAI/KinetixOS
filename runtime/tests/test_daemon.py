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
if sys.argv[1:2] == ["worker"]:
    # mirrors argusd.py: a pre-started spare takes one job on stdin
    job = json.loads(sys.stdin.readline())
    os.environ.update(job.get("env") or {})
    sys.argv = [sys.argv[0]] + job["argv"]
op = sys.argv[1]
if op == "run":
    task = sys.argv[sys.argv.index("--task") + 1]
    if task == "wait":
        time.sleep(30)
    if task == "stream":
        for i in range(3):
            print(json.dumps({"type": "delta", "text": str(i), "t": time.time()}), flush=True)
            time.sleep(0.3)
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


    def test_tokens_stream_through_as_they_are_produced(self):
        # Regression: the daemon used BufferedReader.read(65536), which
        # blocks until 64KB or EOF, so the panel received every streamed
        # token at once when the worker exited.
        import socket as _socket
        conn = _socket.socket(_socket.AF_UNIX)
        conn.connect(str(self.path))
        conn.sendall(json.dumps({"op": "run", "id": "st", "task": "stream",
                                 "workspace": str(self.root)}).encode() + b"\n")
        buf, arrivals = b"", []
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                msg = json.loads(line)
                if msg.get("type") == "delta":
                    arrivals.append(time.time() - msg["t"])
        conn.close()
        self.assertEqual(3, len(arrivals))
        # each token reaches the client right after it was printed, not ~0.6s
        # later when the worker finishes
        self.assertLess(max(arrivals), 0.2, arrivals)

    def test_a_prestarted_spare_worker_serves_requests(self):
        deadline = time.time() + 5
        while time.time() < deadline:
            with self.server._spare_lock:
                spare = self.server._spare
            if spare is not None and spare.poll() is None:
                break
            time.sleep(0.02)
        else:
            self.fail("no spare worker was started")
        reply = self.call({"op": "run", "id": "sp", "task": "via-spare",
                           "workspace": str(self.root), "grants": {"input": True}})
        self.assertEqual("via-spare", reply[0]["text"])
        self.assertEqual("1", reply[0]["grant"])
        # it was consumed, and a replacement is started for the next request
        deadline = time.time() + 5
        while time.time() < deadline:
            with self.server._spare_lock:
                nxt = self.server._spare
            if nxt is not None and nxt is not spare and nxt.poll() is None:
                break
            time.sleep(0.02)
        else:
            self.fail("spare worker was not replaced")

    def test_prewarm_is_a_noop_answer_without_probing_in_tests(self):
        reply = self.call({"op": "prewarm"})
        self.assertTrue(reply[0]["ok"])
        self.assertFalse(self.server.warm_caps)


if __name__ == "__main__":
    unittest.main()
