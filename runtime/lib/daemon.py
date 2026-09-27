import json
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

MAX_REQUEST_BYTES = 1_000_000


def worker_main(main):
    """Pre-started worker: imports are already done by the time this runs.

    Blocks for exactly one request line on stdin ({"argv": [...], "env":
    {...}}), applies that request's grant variables, then runs the normal CLI
    path and exits — one task per process, same isolation as a cold spawn,
    just started ahead of time so the ~100ms interpreter start + imports are
    off the critical path.
    """
    line = sys.stdin.readline()
    if not line:
        return 0
    job = json.loads(line)
    os.environ.update({str(k): str(v) for k, v in (job.get("env") or {}).items()})
    sys.argv = [sys.argv[0]] + [str(a) for a in job.get("argv") or []]
    return main()


def socket_path():
    base = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    return base / "argus" / "argusd.sock"


def request_argv(script, request):
    op = request.get("op")
    workspace = str(request.get("workspace") or Path.cwd())
    if op == "run":
        return [
            sys.executable,
            "-u",
            str(script),
            "run",
            "--stream",
            "--workspace",
            workspace,
            "--session",
            str(request.get("session") or "default"),
            "--task",
            str(request.get("task") or ""),
        ]
    if op == "approve":
        argv = [
            sys.executable,
            "-u",
            str(script),
            "approve",
            str(request.get("approval_id") or ""),
            "--stream",
            "--workspace",
            workspace,
        ]
        if request.get("allow"):
            argv.append("--allow")
        if request.get("always"):
            argv.append("--always")
        return argv
    raise ValueError("unsupported operation")


def request_env(request):
    env = os.environ.copy()
    grants = request.get("grants") or {}
    for name in ("screen", "input", "shell", "net"):
        if name in grants:
            env[f"ARGUS_GRANT_{name.upper()}"] = "1" if grants[name] else "0"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def read_request(conn):
    conn.settimeout(5)
    data = bytearray()
    while b"\n" not in data:
        chunk = conn.recv(min(65536, MAX_REQUEST_BYTES - len(data) + 1))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError("request too large")
    if not data:
        raise ValueError("empty request")
    return json.loads(bytes(data).split(b"\n", 1)[0])


def send_json(conn, payload):
    conn.sendall(json.dumps(payload, ensure_ascii=False).encode() + b"\n")


def terminate_process(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=3)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class Daemon:
    def __init__(self, script, path=None, warm_caps=False):
        self.script = Path(script).resolve()
        # Background KWin capability probing is for the real daemon only
        # (serve() below); constructing a Daemon in tests must not probe the
        # live desktop or write the shared cache.
        self.warm_caps = warm_caps
        self.path = Path(path or socket_path())
        self.active = {}
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.server = None
        self._warm_lock = threading.Lock()
        self._spare = None
        self._spare_lock = threading.Lock()

    def _spawn_spare(self):
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        return subprocess.Popen(
            [sys.executable, "-u", str(self.script), "worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

    def _refill_spare(self):
        if self.stopping.is_set():
            return
        with self._spare_lock:
            if self._spare is None or self._spare.poll() is not None:
                try:
                    self._spare = self._spawn_spare()
                except OSError:
                    self._spare = None

    def start_worker(self, request):
        """A process running this request: the warm spare when one is ready
        (then a replacement is started in the background), else a cold spawn
        exactly as before."""
        argv = request_argv(self.script, request)
        with self._spare_lock:
            spare, self._spare = self._spare, None
        if spare is not None and spare.poll() is None:
            grants = {k: v for k, v in request_env(request).items()
                      if k.startswith("ARGUS_GRANT_")}
            try:
                spare.stdin.write(json.dumps({"argv": argv[3:], "env": grants}).encode() + b"\n")
                spare.stdin.close()
                threading.Thread(target=self._refill_spare, daemon=True).start()
                return spare
            except OSError:
                terminate_process(spare)
        threading.Thread(target=self._refill_spare, daemon=True).start()
        return subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=request_env(request),
            start_new_session=True,
        )

    def prewarm(self, min_age=30.0):
        """Refresh the desktop-capability cache in the background.

        Workers read it via kwin.capabilities_cached(); keeping it warm moves
        a ~120ms live probe off the critical path of the next message. Runs
        at most one refresh at a time and skips a cache younger than min_age,
        so it never turns into polling.
        """
        if not self.warm_caps:
            return

        def work():
            if not self._warm_lock.acquire(blocking=False):
                return
            try:
                from . import kwin
                try:
                    age = time.time() - os.path.getmtime(kwin._caps_cache_path())
                except OSError:
                    age = None
                if age is None or age >= min_age:
                    kwin.refresh_capabilities_cache()
            except Exception:
                pass
            finally:
                self._warm_lock.release()

        threading.Thread(target=work, daemon=True).start()

    def cancel(self, request_id):
        with self.lock:
            proc = self.active.get(request_id)
        if not proc:
            return False
        terminate_process(proc)
        return True

    def handle(self, conn):
        request_id = None
        proc = None
        try:
            request = read_request(conn)
            request_id = str(request.get("id") or "")
            if request.get("op") == "ping":
                send_json(conn, {"type": "daemon", "ok": True, "pid": os.getpid()})
                return
            if request.get("op") == "prewarm":
                # sent by the shell when the agent panel opens
                self.prewarm()
                send_json(conn, {"type": "prewarmed", "ok": True})
                return
            if request.get("op") == "cancel":
                send_json(
                    conn,
                    {
                        "type": "cancelled",
                        "ok": self.cancel(request_id),
                        "id": request_id,
                    },
                )
                return
            if not request_id:
                raise ValueError("request id is required")
            request_argv(self.script, request)  # validates op before anything starts
            proc = self.start_worker(request)
            with self.lock:
                if request_id in self.active:
                    terminate_process(proc)
                    raise ValueError("request id is already active")
                self.active[request_id] = proc
            # read1, not read: BufferedReader.read(n) blocks until n bytes or
            # EOF, which held every streamed token back until the worker
            # exited — the panel got the whole reply at once at the end.
            # read1 returns whatever the pipe has as soon as it has it.
            while True:
                chunk = proc.stdout.read1(65536)
                if not chunk:
                    break
                conn.sendall(chunk)
            code = proc.wait()
            proc.stdout.close()
            if code and not self.stopping.is_set():
                send_json(
                    conn,
                    {
                        "type": "transport_error",
                        "ok": False,
                        "text": f"Runtime worker exited with code {code}.",
                    },
                )
            send_json(conn, {"type": "transport_done", "code": code, "id": request_id})
            # keep the next message's preamble probe off its critical path
            self.prewarm()
        except (BrokenPipeError, ConnectionResetError):
            if proc:
                terminate_process(proc)
        except Exception as exc:
            try:
                send_json(
                    conn, {"type": "transport_error", "ok": False, "text": str(exc)}
                )
            except OSError:
                pass
        finally:
            if request_id:
                with self.lock:
                    if self.active.get(request_id) is proc:
                        self.active.pop(request_id, None)
            conn.close()

    def shutdown(self):
        self.stopping.set()
        if self.server:
            self.server.close()
        with self.lock:
            processes = list(self.active.values())
        with self._spare_lock:
            if self._spare is not None:
                processes.append(self._spare)
                self._spare = None
        for proc in processes:
            terminate_process(proc)

    def serve(self):
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        try:
            mode = self.path.lstat().st_mode
            if not stat.S_ISSOCK(mode):
                raise RuntimeError(f"refusing to replace non-socket path: {self.path}")
            self.path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server = server
        server.bind(str(self.path))
        os.chmod(self.path, 0o600)
        server.listen(16)
        server.settimeout(1)
        self.prewarm(min_age=0)
        self._refill_spare()
        try:
            while not self.stopping.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self.stopping.is_set():
                        break
                    raise
                threading.Thread(target=self.handle, args=(conn,), daemon=True).start()
        finally:
            self.shutdown()
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def serve(script, path=None):
    daemon = Daemon(script, path, warm_caps=True)
    signal.signal(signal.SIGTERM, lambda *_: daemon.shutdown())
    signal.signal(signal.SIGINT, lambda *_: daemon.shutdown())
    daemon.serve()


def client(request, path=None, output=None):
    path = Path(path or socket_path())
    output = output or sys.stdout.buffer
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(str(path))
        conn.sendall(json.dumps(request, ensure_ascii=False).encode() + b"\n")
        conn.shutdown(socket.SHUT_WR)
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            output.write(chunk)
            output.flush()
