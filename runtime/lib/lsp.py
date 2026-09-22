"""Minimal LSP client: real diagnostics from real language servers.

Regex linting is the dollar-store version of "syntax checking". This speaks
the actual protocol (JSON-RPC over stdio with Content-Length framing) so the
agent sees the same errors an editor would: type errors, unresolved names,
bad imports, QML binding problems — not just "does it parse".

Servers are spawned per task and shut down with it. That keeps the runtime
stateless (no daemon required yet) at the cost of a cold start per file, which
is the right trade until the socket daemon lands.
"""
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

# language id → server argv. Binaries are looked up on PATH and in the
# agent's private LSP prefix (installed without root).
SERVERS = {
    "python":       [["pyright-langserver", "--stdio"]],
    "javascript":   [["typescript-language-server", "--stdio"]],
    "typescript":   [["typescript-language-server", "--stdio"]],
    "javascriptreact": [["typescript-language-server", "--stdio"]],
    "typescriptreact": [["typescript-language-server", "--stdio"]],
    "qml":          [["qmlls"], ["qmlls6"]],
    "c":            [["clangd"]],
    "cpp":          [["clangd"]],
    "rust":         [["rust-analyzer"]],
    "lua":          [["lua-language-server"]],
}

PRIVATE_BIN = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "argus" / "lsp" / "bin"

SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}

# How long a freshly spawned server gets to answer initialize. Module-level so a
# test can shorten it without changing the shipped budget.
INIT_TIMEOUT = 20


def find_server(language):
    """Return argv for a language's server, or None if not installed."""
    for argv in SERVERS.get(language, []):
        exe = argv[0]
        if shutil.which(exe):
            return argv
        cand = PRIVATE_BIN / exe
        if cand.exists():
            return [str(cand)] + argv[1:]
    return None


def available_servers():
    return {lang: (find_server(lang) or [None])[0] for lang in SERVERS}


class _Client:
    """One server process, one file. Deliberately short-lived."""

    def __init__(self, argv, root):
        self.argv = argv
        self.root = Path(root).resolve()
        self.proc = None
        self.msgs = queue.Queue()
        self.next_id = 1
        self._reader = None
        self._write_lock = threading.Lock()

    # ── framing ──────────────────────────────────────────────────────────
    def _read_loop(self):
        stream = self.proc.stdout
        try:
            while True:
                headers = {}
                while True:
                    line = stream.readline()
                    if not line:
                        return
                    line = line.decode("utf-8", "replace").strip()
                    if line == "":
                        break
                    if ":" in line:
                        k, v = line.split(":", 1)
                        headers[k.strip().lower()] = v.strip()
                length = int(headers.get("content-length", 0))
                if length <= 0:
                    continue
                body = stream.read(length)
                try:
                    msg = json.loads(body.decode("utf-8", "replace"))
                except Exception:
                    continue
                if msg.get("id") is not None and msg.get("method"):
                    self._answer(msg)
                    continue
                self.msgs.put(msg)
        except Exception:
            return

    def _answer(self, msg):
        """Reply to a request the *server* sent us.

        Language servers ask the client things while starting up —
        workspace/configuration, client/registerCapability,
        window/workDoneProgress/create, workspace/workspaceFolders — and several
        (pyright and typescript-language-server among them) will not publish
        diagnostics until they get an answer. Those requests used to be dropped
        on the floor: wait_for() consumes the queue and discards anything that
        does not match its predicate, so nothing ever replied. The server then
        waited out the client's whole timeout and the caller was told the file
        was clean (see diagnostics()).
        """
        params = msg.get("params") or {}
        result = None
        if msg.get("method") == "workspace/configuration":
            result = [None for _ in (params.get("items") or [])]
        elif msg.get("method") == "workspace/workspaceFolders":
            result = [{"uri": self.root.as_uri(), "name": self.root.name}]
        try:
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})
        except Exception:
            pass

    def _send(self, payload):
        data = json.dumps(payload).encode("utf-8")
        with self._write_lock:
            self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
            self.proc.stdin.flush()

    def request(self, method, params):
        rid = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return rid

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def wait_for(self, predicate, timeout):
        """Collect messages until predicate(msg) is true or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = self.msgs.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            if predicate(msg):
                return msg
        return None

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self, init_timeout=None):
        self.proc = subprocess.Popen(
            self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, cwd=str(self.root))
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        rid = self.request("initialize", {
            "processId": os.getpid(),
            "rootUri": self.root.as_uri(),
            "capabilities": {
                "textDocument": {
                    "publishDiagnostics": {"relatedInformation": True},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                },
            },
            "initializationOptions": {},
        })
        resp = self.wait_for(lambda m: m.get("id") == rid,
                             timeout=INIT_TIMEOUT if init_timeout is None else init_timeout)
        # A server that never answers (cold pyright under load, a dead process,
        # a protocol mismatch) is not an initialized server: continuing used to
        # make every later call run against nothing and be reported as a clean
        # file. Fail here, where the reason is still knowable.
        if resp is None:
            raise RuntimeError(f"language server did not answer initialize within "
                               f"{INIT_TIMEOUT if init_timeout is None else init_timeout}s")
        if resp.get("error"):
            raise RuntimeError("language server rejected initialize: " + str(resp["error"])[:200])
        self.notify("initialized", {})

    def stop(self):
        try:
            rid = self.request("shutdown", None)
            self.wait_for(lambda m: m.get("id") == rid, timeout=2)
            self.notify("exit", None)
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
            # Reap: without this a server that ignored SIGTERM for 3s stays a
            # zombie child for the rest of the agent process, one per call.
            try:
                self.proc.wait(timeout=5)
            except Exception:
                pass
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass


def _uri(path):
    return Path(path).resolve().as_uri()


def _utf16_to_col(line_text, utf16_units):
    """LSP positions are UTF-16 code-unit offsets by spec default (this
    client never negotiates `positionEncoding: utf-8`), but were being
    reported straight through as 1-based character columns. Identical for
    plain ASCII/BMP text; wrong — understated — on any line with a character
    outside the BMP (most emoji, some CJK extension characters) before the
    diagnostic, since those take 2 UTF-16 units but 1 Python string index."""
    units = 0
    for i, ch in enumerate(line_text):
        if units >= utf16_units:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(line_text)


def diagnostics(path, text, language, root, timeout=25):
    """Return {ok, language, server, diagnostics:[...], error?}."""
    argv = find_server(language)
    if not argv:
        return {"ok": False, "language": language, "server": None,
                "error": f"no language server installed for {language}",
                "diagnostics": []}
    client = _Client(argv, root)
    try:
        client.start()
        uri = _uri(path)
        client.notify("textDocument/didOpen", {"textDocument": {
            "uri": uri, "languageId": language, "version": 1, "text": text}})
        msg = client.wait_for(
            lambda m: m.get("method") == "textDocument/publishDiagnostics"
                      and m.get("params", {}).get("uri") == uri,
            timeout=timeout)
        if msg is None:
            # Not a clean file — no answer at all. Reporting ok:True with an
            # empty list here was indistinguishable from "the server checked and
            # found nothing", which handed the model a clean bill of health for
            # a file no server had analysed (symbols() already returned ok:False
            # in the same situation, so the two halves of this module disagreed
            # about what failure looks like).
            return {"ok": False, "language": language, "server": argv[0], "diagnostics": [],
                    "error": f"language server published no diagnostics within {timeout}s "
                             "(timed out, or it never started) — the file was not checked"}
        src_lines = text.splitlines()
        out = []
        for d in msg["params"].get("diagnostics", []):
            rng = d.get("range", {}).get("start", {})
            line0 = rng.get("line", 0)
            char16 = rng.get("character", 0)
            col = (_utf16_to_col(src_lines[line0], char16) + 1
                   if 0 <= line0 < len(src_lines) else char16 + 1)
            out.append({
                "line": line0 + 1,
                "col": col,
                "severity": SEVERITY.get(d.get("severity", 1), "error"),
                "message": (d.get("message") or "").strip()[:400],
                "source": d.get("source", ""),
            })
        return {"ok": True, "language": language, "server": argv[0], "diagnostics": out}
    except Exception as e:
        return {"ok": False, "language": language, "server": argv[0] if argv else None,
                "error": str(e), "diagnostics": []}
    finally:
        client.stop()


def symbols(path, text, language, root, timeout=25):
    """Document symbols — the file's structure, for navigation."""
    argv = find_server(language)
    if not argv:
        return {"ok": False, "error": f"no language server installed for {language}"}
    client = _Client(argv, root)
    try:
        client.start()
        uri = _uri(path)
        client.notify("textDocument/didOpen", {"textDocument": {
            "uri": uri, "languageId": language, "version": 1, "text": text}})
        rid = client.request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
        msg = client.wait_for(lambda m: m.get("id") == rid, timeout=timeout)
        if not msg:
            return {"ok": False, "error": "no symbol response"}
        if msg.get("error"):
            return {"ok": False, "error": "documentSymbol failed: " + str(msg["error"])[:200]}
        out = []
        def walk(items, depth=0):
            for it in items or []:
                name = it.get("name")
                if name:
                    rng = (it.get("range") or it.get("location", {}).get("range") or {}).get("start", {})
                    out.append({"name": name, "kind": it.get("kind"),
                                "line": rng.get("line", 0) + 1, "depth": depth})
                if it.get("children"):
                    walk(it["children"], depth + 1)
        walk(msg.get("result"))
        return {"ok": True, "symbols": out[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        client.stop()
