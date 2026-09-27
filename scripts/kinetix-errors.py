#!/usr/bin/env python3
"""kinetix-errors.py — app-error capture for the Kinetix notification system.

  watch                 follow the systemd journal; print one JSON line per app
                        crash (coredump) or failed user service, with a log
                        already captured to $XDG_RUNTIME_DIR/kinetix-errors/
  save LOGPATH NAME     copy a captured log into ~/.local/share/kinetix/error-logs/
  save-text NAME        same, but the text comes from $KINETIX_ERR_TEXT (shell-internal errors)
  dir                   print the persistent log directory
  simulate              print one sample crash event (+ sample log) for UI previews

Capture happens at event time, so the "Save log" button is instant and never
depends on the journal still holding the lines. Runtime logs live on tmpfs and
are pruned after a day; saved logs are kept (newest 100).
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

MSG_COREDUMP = "fc2e22bc6ee647b6b90729ab34a250b1"
MSG_UNIT_FAILURE_RESULT = "d9b373ed55a64feb8242e02dbe79a49c"
UID = os.getuid()
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "kinetix-errors"
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "kinetix/error-logs"
KEEP_SAVED = 100
RATE_LIMIT_S = 10

SIGNALS = {
    "SIGSEGV": "segmentation fault", "SIGABRT": "aborted", "SIGBUS": "bus error",
    "SIGILL": "illegal instruction", "SIGFPE": "arithmetic error", "SIGTRAP": "trap",
    "SIGKILL": "killed", "SIGTERM": "terminated",
}

_out_lock = threading.Lock()
_last_seen = {}


def emit(**event):
    with _out_lock:
        print(json.dumps(event), flush=True)


def run(cmd, timeout=6):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr if r.returncode not in (0,) and not r.stdout else "")
    except Exception as exc:  # missing tool, timeout
        return f"(could not run {' '.join(cmd[:2])}: {exc})\n"


def safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:48] or "app"


def field(entry, key, default=""):
    v = entry.get(key, default)
    if isinstance(v, list):          # journald encodes binary fields as byte arrays
        try:
            return bytes(v).decode("utf-8", "replace")
        except Exception:
            return default
    return str(v)


def header(app, summary, extra):
    osr = ""
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                osr = line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    lines = [
        "KinetixOS error report",
        f"time:    {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"app:     {app}",
        f"event:   {summary}",
        f"system:  {osr}  kernel {platform.release()}  host {platform.node()}",
    ]
    lines += [f"{k}: {v}" for k, v in extra.items()]
    return "\n".join(lines) + "\n\n"


def write_runtime_log(eid, text):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    os.chmod(RUNTIME, 0o700)
    path = RUNTIME / f"{eid}.log"
    path.write_text(text[:400_000])
    os.chmod(path, 0o600)
    return str(path)


def prune_runtime():
    if not RUNTIME.is_dir():
        return
    cutoff = time.time() - 86400
    for p in RUNTIME.glob("*.log"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def handle_crash(entry):
    if (field(entry, "COREDUMP_UID") or field(entry, "COREDUMP_OWNER_UID")) != str(UID):
        return
    pid = field(entry, "COREDUMP_PID")
    comm = field(entry, "COREDUMP_COMM") or Path(field(entry, "COREDUMP_EXE")).name or "app"
    sig = field(entry, "COREDUMP_SIGNAL_NAME") or "signal"
    if comm in ("kinetix-errors",):
        return
    key = f"crash:{comm}"
    if time.time() - _last_seen.get(key, 0) < RATE_LIMIT_S:
        return
    _last_seen[key] = time.time()
    desc = SIGNALS.get(sig, "")
    summary = f"{comm} crashed"
    body = f"{sig}{' — ' + desc if desc else ''} (pid {pid}). A crash report was captured."

    def collect():
        text = header(comm, summary, {"signal": sig, "pid": pid, "exe": field(entry, "COREDUMP_EXE")})
        text += "── coredumpctl info ──\n" + run(["coredumpctl", "info", pid, "--no-pager"], 10) + "\n"
        text += "── journal (this process) ──\n" + run(
            ["journalctl", "--no-pager", "-o", "short-iso", "-n", "200", f"_PID={pid}"]) + "\n"
        eid = f"{int(time.time() * 1000)}-{safe(comm)}"
        emit(type="error", id=eid, kind="crash", app=comm, summary=summary, body=body,
             log=write_runtime_log(eid, text), ts=int(time.time() * 1000))

    threading.Thread(target=collect, daemon=True).start()


def handle_unit(entry):
    if field(entry, "_UID") != str(UID):
        return
    unit = field(entry, "USER_UNIT")
    if not unit:
        return
    key = f"unit:{unit}"
    if time.time() - _last_seen.get(key, 0) < RATE_LIMIT_S:
        return
    _last_seen[key] = time.time()
    result = field(entry, "UNIT_RESULT") or "failed"
    name = unit.rsplit(".", 1)[0]
    summary = f"{name} failed"
    body = f"{field(entry, 'MESSAGE') or unit + ' failed'}"

    def collect():
        text = header(name, summary, {"unit": unit, "result": result})
        text += "── journal (unit) ──\n" + run(
            ["journalctl", "--user", "--no-pager", "-o", "short-iso", "-n", "200", "-u", unit]) + "\n"
        eid = f"{int(time.time() * 1000)}-{safe(name)}"
        emit(type="error", id=eid, kind="service", app=name, summary=summary, body=body,
             log=write_runtime_log(eid, text), ts=int(time.time() * 1000))

    threading.Thread(target=collect, daemon=True).start()


def watch():
    prune_runtime()
    cmd = ["journalctl", "-f", "-n", "0", "-o", "json",
           f"MESSAGE_ID={MSG_COREDUMP}", f"MESSAGE_ID={MSG_UNIT_FAILURE_RESULT}"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    emit(type="ready")
    for line in proc.stdout:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        mid = field(entry, "MESSAGE_ID")
        if mid == MSG_COREDUMP:
            handle_crash(entry)
        elif mid == MSG_UNIT_FAILURE_RESULT:
            handle_unit(entry)
    return proc.wait()


def persist(text, name):
    DATA.mkdir(parents=True, exist_ok=True)
    dest = DATA / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{safe(name)}.log"
    dest.write_text(text)
    os.chmod(dest, 0o600)
    logs = sorted(DATA.glob("*.log"), key=lambda p: p.stat().st_mtime)
    for old in logs[:-KEEP_SAVED]:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def save(logpath, name):
    src = Path(logpath)
    # only ever read from our own runtime dir — the path comes from a UI event
    if src.resolve().parent != RUNTIME.resolve() or not src.is_file():
        print(json.dumps({"ok": False, "error": "log no longer available"}))
        return 1
    dest = persist(src.read_text(), name)
    print(json.dumps({"ok": True, "path": str(dest), "dir": str(DATA)}))
    return 0


def save_text(name):
    text = os.environ.get("KINETIX_ERR_TEXT", "")
    dest = persist(header(name, "shell error", {}) + text + "\n", name)
    print(json.dumps({"ok": True, "path": str(dest), "dir": str(DATA)}))
    return 0


def simulate():
    text = header("demo-app", "demo-app crashed", {"signal": "SIGSEGV", "pid": "12345"})
    text += "── sample ──\nThis is a simulated crash report generated for the notification preview.\n"
    eid = f"{int(time.time() * 1000)}-demo-app"
    emit(type="error", id=eid, kind="crash", app="demo-app", summary="demo-app crashed",
         body="SIGSEGV — segmentation fault (pid 12345). A crash report was captured.",
         log=write_runtime_log(eid, text), ts=int(time.time() * 1000))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "watch":
        sys.exit(watch())
    if cmd == "save" and len(sys.argv) >= 4:
        sys.exit(save(sys.argv[2], sys.argv[3]))
    if cmd == "save-text" and len(sys.argv) >= 3:
        sys.exit(save_text(sys.argv[2]))
    if cmd == "dir":
        print(DATA)
        return
    if cmd == "simulate":
        simulate()
        return
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
