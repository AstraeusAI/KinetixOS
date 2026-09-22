#!/usr/bin/env python3
"""A minimal language server over stdio, for testing runtime/lib/lsp.py.

Usage: fake_lsp_server.py {ok|silent|reject|no-init|needs-config|symbols-error}

It speaks real LSP framing so the client's own framing, request/response
matching and stdout reading are what is under test.
"""
import json
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "ok"

DIAGNOSTIC = {
    "range": {"start": {"line": 1, "character": 4}, "end": {"line": 1, "character": 5}},
    "severity": 1,
    "source": "fake",
    "message": "undefined name 'x'",
}
SYMBOLS = [
    {"name": "a_function", "kind": 12, "range": {"start": {"line": 2, "character": 0}}},
    {"name": "a_class", "kind": 5, "range": {"start": {"line": 10, "character": 0}}},
]

STATE = {"opened": None, "config_ok": False, "config_requested": False}


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.decode("utf-8", "replace").strip()
        if line == "":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", 0))
    if length <= 0:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8", "replace"))


def send(payload):
    data = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
    sys.stdout.buffer.flush()


def publish():
    if STATE["opened"]:
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
              "params": {"uri": STATE["opened"], "diagnostics": [DIAGNOSTIC]}})


def main():
    while True:
        msg = read_message()
        if msg is None:
            return
        method = msg.get("method")

        if method == "initialize":
            if MODE == "no-init":
                continue
            if MODE == "reject":
                send({"jsonrpc": "2.0", "id": msg["id"],
                      "error": {"code": -32600, "message": "wrong protocol version"}})
                continue
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}}})

        elif method == "initialized":
            # A server that will not analyse anything until the client answers a
            # configuration request — the shape that used to hang, because the
            # client dropped server-initiated requests on the floor.
            if MODE == "needs-config":
                STATE["config_requested"] = True
                send({"jsonrpc": "2.0", "id": 9000, "method": "workspace/configuration",
                      "params": {"items": [{"section": "python"}]}})

        elif method == "textDocument/didOpen":
            STATE["opened"] = msg["params"]["textDocument"]["uri"]
            if MODE == "silent":
                continue
            if MODE == "needs-config" and not STATE["config_ok"]:
                continue          # will publish when the configuration answer arrives
            publish()

        elif method == "textDocument/documentSymbol":
            if MODE == "symbols-error":
                send({"jsonrpc": "2.0", "id": msg["id"],
                      "error": {"code": -32601, "message": "no symbols for you"}})
            else:
                send({"jsonrpc": "2.0", "id": msg["id"], "result": SYMBOLS})

        elif method == "shutdown":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": None})

        elif method == "exit":
            return

        elif msg.get("id") is not None and method is None:
            # A response from the client. The only one this server asked for is
            # the configuration answer, and it demands a list matching its items.
            if msg.get("id") == 9000:
                result = msg.get("result")
                if isinstance(result, list) and len(result) == 1:
                    STATE["config_ok"] = True
                    publish()


if __name__ == "__main__":
    main()
