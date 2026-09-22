"""MCP (Model Context Protocol) client: external tools over stdio.

Same shape as lib/lsp.py's client (Popen + a background reader thread onto a
queue.Queue, request()/notify()/wait_for(predicate, timeout), start()/stop())
but with newline-delimited JSON framing instead of LSP's Content-Length
framing — that's what MCP's stdio transport actually uses: one JSON object
per line, both directions.

Servers are configured in ~/.config/argus/mcp.json (stdio only for v1: a
command the runtime spawns, matching Claude Desktop's mcpServers shape) and
cache their own discovered tool list there, so a task's context() build can
know what tools exist without spawning every enabled server just to find
out — only a tool that actually gets called pays the spawn/handshake cost.
"""
import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "argus"
CONFIG_FILE = CONF / "mcp.json"

PROTOCOL_VERSION = "2024-11-05"

# npx/uvx cold starts (package resolution, sometimes a download) are slow
# compared to an already-installed LSP binary — see lib/lsp.py's INIT_TIMEOUT
# for the equivalent budget on that protocol. Module-level so a test can
# shrink it without changing the shipped default.
INIT_TIMEOUT = 15
CALL_TIMEOUT = 60


# ── config ───────────────────────────────────────────────────────────────

def load_config():
    """A missing or corrupt file behaves like an empty config — fail-soft,
    matching policy.py's own load(): a broken mcp.json must never prevent
    argusd from starting."""
    try:
        doc = json.loads(CONFIG_FILE.read_text())
        if isinstance(doc.get("servers"), dict):
            return doc
    except Exception:
        pass
    return {"servers": {}}


def save_config(doc):
    """0600, same discipline as keys.env/policy.json — a server's `env`
    block can carry secrets (API tokens for whatever it talks to)."""
    CONF.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(doc, indent=2))
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass


def _slug(name, cap=40):
    """[a-zA-Z0-9_-] only, length-capped — OpenAI-shape function names are
    constrained (^[a-zA-Z0-9_-]+$, <=64 chars total), and a server/tool name
    is free-form user input from the "add server" form."""
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", str(name)).strip("_")
    return (s or "tool")[:cap]


def tool_full_name(server, tool):
    return f"mcp__{_slug(server)}__{_slug(tool)}"


# ── protocol client ──────────────────────────────────────────────────────

class MCPError(RuntimeError):
    pass


class MCPClient:
    """One server process. Long enough-lived to be cached across the tool
    calls of a single task (see argusd.py's ctx.mcp_clients) — unlike
    lib/lsp.py's per-call client, an npx-launched server is expensive enough
    to start that re-spawning it on every single tool call would dominate a
    multi-call task's latency."""

    def __init__(self, command, args=None, env=None):
        self.command = command
        self.args = list(args or [])
        self.extra_env = dict(env or {})
        self.proc = None
        self.msgs = queue.Queue()
        self.next_id = 1
        self._write_lock = threading.Lock()
        self._reader = None
        self.stderr_tail = []

    # ── framing: one JSON object per line, both directions ────────────
    def _read_loop(self):
        stream = self.proc.stdout
        try:
            while True:
                line = stream.readline()
                if not line:
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", "replace"))
                except Exception:
                    continue
                # A server-initiated request (has both "method" and "id")
                # is out of scope for v1's simple tool servers — skip
                # rather than hang trying to answer something we don't
                # implement, or crash the reader thread on an unmatched
                # response.
                if msg.get("method") and msg.get("id") is not None:
                    continue
                self.msgs.put(msg)
        except Exception:
            return

    def _read_stderr(self):
        try:
            for raw in self.proc.stderr:
                text = raw.decode("utf-8", "replace").rstrip()
                if text:
                    self.stderr_tail.append(text)
                    del self.stderr_tail[:-20]
        except Exception:
            return

    def _send(self, payload):
        data = json.dumps(payload).encode("utf-8") + b"\n"
        with self._write_lock:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def request(self, method, params=None):
        rid = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        return rid

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def wait_for(self, predicate, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = self.msgs.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            if predicate(msg):
                return msg
        return None

    # ── lifecycle ────────────────────────────────────────────────────
    def start(self, init_timeout=None):
        env = dict(os.environ)
        env.update(self.extra_env)
        try:
            self.proc = subprocess.Popen(
                [self.command, *self.args], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        except FileNotFoundError:
            raise MCPError(f"command not found: {self.command}")
        except OSError as e:
            raise MCPError(f"failed to start {self.command}: {e}")
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        rid = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "argus", "version": "1"},
        })
        timeout = init_timeout if init_timeout is not None else INIT_TIMEOUT
        resp = self.wait_for(lambda m: m.get("id") == rid, timeout=timeout)
        if resp is None:
            self._force_kill()
            detail = (" — " + self.stderr_tail[-1]) if self.stderr_tail else ""
            raise MCPError(f"MCP server did not answer initialize within {timeout}s{detail}")
        if resp.get("error"):
            self._force_kill()
            raise MCPError("MCP server rejected initialize: " + str(resp["error"])[:200])
        self.notify("notifications/initialized")

    def list_tools(self):
        rid = self.request("tools/list")
        resp = self.wait_for(lambda m: m.get("id") == rid, timeout=CALL_TIMEOUT)
        if resp is None:
            raise MCPError("tools/list timed out")
        if resp.get("error"):
            raise MCPError("tools/list failed: " + str(resp["error"])[:200])
        return (resp.get("result") or {}).get("tools", [])

    def call_tool(self, name, arguments, timeout=None):
        rid = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        resp = self.wait_for(lambda m: m.get("id") == rid,
                             timeout=timeout if timeout is not None else CALL_TIMEOUT)
        if resp is None:
            return {"ok": False, "error": f"{name} timed out"}
        if resp.get("error"):
            return {"ok": False, "error": str(resp["error"])[:600]}
        result = resp.get("result") or {}
        texts, other = [], 0
        for block in result.get("content") or []:
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
            else:
                other += 1
        out = {"ok": not result.get("isError", False), "content": "\n".join(texts)}
        if other:
            out["note"] = f"response included {other} non-text content block(s), not shown"
        return out

    def _force_kill(self):
        try:
            self.proc.kill()
            self.proc.wait(timeout=3)
        except Exception:
            pass
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                if stream: stream.close()
            except Exception:
                pass

    def stop(self):
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
                self.proc.wait(timeout=3)
            except Exception:
                pass
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                if stream: stream.close()
            except Exception:
                pass


def stop_all(clients):
    """Terminate every live client in a {name: MCPClient} dict, in place."""
    for client in clients.values():
        try:
            client.stop()
        except Exception:
            pass
    clients.clear()


def probe(command, args=None, env=None, timeout=None):
    """One-shot start -> tools/list -> stop, for the panel's "Test" action
    and the mcp-probe CLI subcommand. Never raises."""
    client = MCPClient(command, args, env)
    try:
        client.start(init_timeout=timeout)
        tools = client.list_tools()
        return {"ok": True, "tools": tools}
    except MCPError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"probe failed: {e}"}
    finally:
        client.stop()


def probe_server(name, timeout=None):
    """Probe one server named in mcp.json, write back tools/lastProbe, and
    return the updated entry. Used by both the mcp-probe CLI subcommand and
    directly by tests — the single place that owns the read-modify-write of
    a server's cached tool list, so the QML side never has to race it."""
    doc = load_config()
    entry = doc["servers"].get(name)
    if entry is None:
        return {"ok": False, "error": f"no server named {name!r} in {CONFIG_FILE}"}
    result = probe(entry.get("command", ""), entry.get("args"), entry.get("env"), timeout)
    entry["lastProbe"] = {"ok": result["ok"], "ts": int(time.time() * 1000),
                          "error": result.get("error")}
    if result["ok"]:
        entry["tools"] = result["tools"]
    save_config(doc)
    return {"ok": result["ok"], "name": name, "tools": entry.get("tools", []),
            "error": result.get("error")}
