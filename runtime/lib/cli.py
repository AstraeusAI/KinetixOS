"""Command-line entry: argparse wiring plus the doctor report."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import daemon, errlog, kwin, lsp, mcp, sandbox, tools as toolreg
from .approvals import approve
from .config import DB, MAX_STEPS, MAX_TASK_SECONDS, prefs, vault
from .journal import (
    KEEP_EVENTS,
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_EVENTS,
    SUMMARY_CHARS,
    connect,
    delete_memory,
    extract_memory,
    list_memories,
    list_sessions,
    session_transcript,
)
from .loop import run
from .out import emit
from .workspace import Workspace


def doctor(workspace_root):
    """Emit environment/provider/tooling health as JSON."""
    p = prefs()
    v = vault()
    try:
        ws = Workspace(workspace_root)
        ws_info = {"root": str(ws.root), **ws.project()}
    except Exception as e:
        ws_info = {"error": str(e)}
    recent_errors = [
        e for e in errlog.tail(200) if e.get("level") in ("WARNING", "ERROR")
    ][-10:]
    emit(
        {
            "python": sys.version.split()[0],
            "database": str(DB),
            "encrypted": False,
            "sandbox": sandbox.describe(),
            "kwin": kwin.capabilities(),
            "adapters": {
                x: bool(shutil.which(x))
                for x in ["grim", "ydotool", "wtype", "gdbus", "rg", "fd"]
            },
            "lsp": {k: bool(v2) for k, v2 in lsp.available_servers().items()},
            "formatters": {
                x: bool(shutil.which(x))
                for x in [
                    "ruff",
                    "black",
                    "prettier",
                    "eslint",
                    "rustfmt",
                    "clang-format",
                    "shellcheck",
                    "shfmt",
                    "qmllint",
                    "qmlformat",
                ]
            },
            "provider": p.get("provider"),
            "model": p.get("model"),
            "limits": {
                "task_seconds": MAX_TASK_SECONDS,
                "steps": MAX_STEPS,
                "context_chars": MAX_CONTEXT_CHARS,
                "context_events": MAX_CONTEXT_EVENTS,
                "keep_events": KEEP_EVENTS,
                "summary_chars": SUMMARY_CHARS,
            },
            "credentials": sorted(k for k in v if v[k]),
            "workspace": ws_info,
            "tools": sorted(toolreg.REGISTRY.keys()),
            "log_file": str(errlog.LOG_FILE),
            "recent_errors": recent_errors,
        }
    )


def main():
    """argusd CLI entry: dispatch the run/approve/doctor/... subcommands."""
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--task", required=True)
    r.add_argument("--session", default="default")
    r.add_argument("--workspace", default=str(Path.cwd()))
    r.add_argument("--stream", action="store_true")
    x = sub.add_parser("approve")
    x.add_argument("id")
    x.add_argument("--allow", action="store_true")
    x.add_argument(
        "--always",
        action="store_true",
        help="remember this exact command/path so it auto-approves next time",
    )
    x.add_argument("--workspace", default=str(Path.cwd()))
    x.add_argument("--stream", action="store_true")
    d = sub.add_parser("doctor")
    d.add_argument("--workspace", default=str(Path.cwd()))
    s = sub.add_parser("serve", help="run the persistent Unix-socket daemon")
    s.add_argument("--socket", default=str(daemon.socket_path()))
    c = sub.add_parser("client", help="send one JSON request to the daemon")
    c.add_argument("--socket", default=str(daemon.socket_path()))
    c.add_argument("--request", required=True)
    e = sub.add_parser(
        "errors",
        help="tail the incident log (argus.log) — "
        "crashes, tool failures, budget/step-limit stops, with tracebacks",
    )
    e.add_argument("-n", "--count", type=int, default=20)
    m = sub.add_parser(
        "mcp-probe",
        help="spawn one configured MCP server, list its tools, "
        "and write the result back into mcp.json — used by the Agent Panel's "
        'MCP tab "Test" action',
    )
    m.add_argument("--name", required=True)
    sub.add_parser(
        "list-sessions",
        help="past conversations, newest first — used by the Agent Panel's History tab",
    )
    st = sub.add_parser(
        "session-transcript", help="a past session's messages, as text bubbles"
    )
    st.add_argument("--session", required=True)
    sub.add_parser(
        "list-memories",
        help="everything remembered via remember_fact or automatic extraction",
    )
    dm = sub.add_parser("delete-memory")
    dm.add_argument("--id", required=True, type=int)
    em = sub.add_parser(
        "extract-memory",
        help="one small provider call over a finished "
        "session's transcript, pulling out durable cross-session facts — "
        "used when the Agent Panel starts a new session",
    )
    em.add_argument("--session", required=True)
    a = ap.parse_args()

    if a.cmd == "doctor":
        doctor(a.workspace)
        return
    if a.cmd == "serve":
        import argusd as _facade_argusd

        daemon.serve(Path(_facade_argusd.__file__), a.socket)
        return
    if a.cmd == "client":
        daemon.client(json.loads(a.request), a.socket)
        return
    if a.cmd == "errors":
        for rec in errlog.tail(a.count):
            emit(rec)
        return
    if a.cmd == "mcp-probe":
        emit(mcp.probe_server(a.name))
        return
    if a.cmd == "list-sessions":
        emit({"ok": True, "sessions": list_sessions(connect())})
        return
    if a.cmd == "session-transcript":
        emit({"ok": True, "messages": session_transcript(connect(), a.session)})
        return
    if a.cmd == "list-memories":
        emit({"ok": True, "memories": list_memories(connect())})
        return
    if a.cmd == "delete-memory":
        delete_memory(connect(), a.id)
        emit({"ok": True})
        return
    if a.cmd == "extract-memory":
        emit(extract_memory(a.session))
        return
    if a.cmd == "approve":
        res = approve(a.id, a.allow, a.workspace, stream=a.stream, always=a.always)
        emit({"type": "result", **res} if a.stream else res)
        return
    try:
        res = run(a.task, a.session, a.workspace, stream=a.stream)
    except Exception as e:
        errlog.exception(
            "uncaught_run_exception",
            e,
            task=str(a.task)[:200],
            session=a.session,
            workspace=a.workspace,
        )
        res = {"ok": False, "text": "⚠️ " + str(e)}
    if a.stream:
        emit({"type": "result", **res})
    else:
        emit(res)
