#!/usr/bin/env python3
"""A minimal MCP server over stdio, for testing runtime/lib/mcp.py.

Usage: fake_mcp_server.py {ok|reject|no-init|tool-error|crash}

Speaks real MCP stdio framing (newline-delimited JSON-RPC) so the client's
own framing, request/response matching and process lifecycle are what is
under test, not a mock.
"""
import json
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "ok"

TOOLS = [
    {"name": "echo", "description": "Echo the given text back.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "delete_thing", "description": "Delete something.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
     "annotations": {"destructiveHint": True}},
]


def send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")

        if method == "initialize":
            if MODE == "no-init":
                continue
            if MODE == "reject":
                send({"jsonrpc": "2.0", "id": msg["id"],
                      "error": {"code": -32600, "message": "unsupported protocol version"}})
                continue
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"protocolVersion": "2024-11-05", "capabilities": {},
                            "serverInfo": {"name": "fake", "version": "1"}}})

        elif method == "notifications/initialized":
            continue

        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": TOOLS}})

        elif method == "tools/call":
            if MODE == "crash":
                sys.exit(1)
            params = msg.get("params") or {}
            if MODE == "tool-error":
                send({"jsonrpc": "2.0", "id": msg["id"],
                      "result": {"isError": True,
                                "content": [{"type": "text", "text": "boom: it failed"}]}})
                continue
            text = "echo: " + str((params.get("arguments") or {}).get("text", ""))
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"isError": False, "content": [
                      {"type": "text", "text": text},
                      {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"},
                  ]}})

        elif msg.get("id") is not None and method is None:
            continue  # a response to something we sent the client — none in v1


if __name__ == "__main__":
    main()
