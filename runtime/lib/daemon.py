import json
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
from pathlib import Path

MAX_REQUEST_BYTES = 1_000_000


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
    def __init__(self, script, path=None):
        self.script = Path(script).resolve()
        self.path = Path(path or socket_path())
        self.active = {}
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.server = None

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
            argv = request_argv(self.script, request)
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=request_env(request),
                start_new_session=True,
            )
            with self.lock:
                if request_id in self.active:
                    terminate_process(proc)
                    raise ValueError("request id is already active")
                self.active[request_id] = proc
            while True:
                chunk = proc.stdout.read(65536)
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
    daemon = Daemon(script, path)
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
