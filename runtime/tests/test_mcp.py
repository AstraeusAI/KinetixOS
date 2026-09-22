"""The MCP client, against a fake server that speaks real stdio framing —
plus mcp.json config round-tripping and dynamic tool registration.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401

from lib import mcp, tools

FAKE = str(Path(__file__).resolve().parent / "fake_mcp_server.py")


def serve(mode):
    return [sys.executable, FAKE, mode]


class McpClientTests(unittest.TestCase):
    def setUp(self):
        self._real_init_timeout = mcp.INIT_TIMEOUT
        self._real_call_timeout = mcp.CALL_TIMEOUT
        mcp.INIT_TIMEOUT = 3  # keep the suite fast; the budget is not under test
        mcp.CALL_TIMEOUT = 3
        self.addCleanup(lambda: setattr(mcp, "INIT_TIMEOUT", self._real_init_timeout))
        self.addCleanup(lambda: setattr(mcp, "CALL_TIMEOUT", self._real_call_timeout))
        self.client = None

    def tearDown(self):
        if self.client:
            self.client.stop()

    def start(self, mode):
        self.client = mcp.MCPClient(sys.executable, [FAKE, mode])
        self.client.start()
        return self.client

    def test_handshake_then_list_tools(self):
        c = self.start("ok")
        tools = c.list_tools()
        self.assertEqual(["echo", "delete_thing"], [t["name"] for t in tools])

    def test_call_tool_joins_text_blocks_and_notes_non_text(self):
        c = self.start("ok")
        result = c.call_tool("echo", {"text": "hi"})
        self.assertTrue(result["ok"], result)
        self.assertEqual("echo: hi", result["content"])
        self.assertIn("1 non-text content block", result["note"])

    def test_a_tool_error_is_reported_as_not_ok_not_an_exception(self):
        c = self.start("tool-error")
        result = c.call_tool("echo", {"text": "hi"})
        self.assertFalse(result["ok"], result)
        self.assertIn("boom", result["content"])

    def test_a_rejected_initialize_raises_mcperror(self):
        client = mcp.MCPClient(sys.executable, [FAKE, "reject"])
        with self.assertRaises(mcp.MCPError) as cm:
            client.start()
        self.assertIn("rejected initialize", str(cm.exception))

    def test_a_server_that_never_answers_initialize_raises_mcperror(self):
        client = mcp.MCPClient(sys.executable, [FAKE, "no-init"])
        with self.assertRaises(mcp.MCPError) as cm:
            client.start()
        self.assertIn("did not answer initialize", str(cm.exception))

    def test_a_missing_command_raises_mcperror_not_an_unhandled_exception(self):
        client = mcp.MCPClient("this-binary-does-not-exist-argus", [])
        with self.assertRaises(mcp.MCPError) as cm:
            client.start()
        self.assertIn("not found", str(cm.exception))

    def test_a_crash_mid_call_is_reported_not_hung(self):
        c = self.start("crash")
        result = c.call_tool("echo", {"text": "hi"})
        self.assertFalse(result["ok"])

    def test_stop_all_terminates_every_client(self):
        clients = {"a": self.start("o"
            "k"), "b": mcp.MCPClient(sys.executable, [FAKE, "ok"])}
        clients["b"].start()
        self.client = None  # ownership moves to stop_all/tearDown below
        mcp.stop_all(clients)
        self.assertEqual({}, clients)


class McpConfigTests(unittest.TestCase):
    def setUp(self):
        self.ws = support.make_workspace("ws-mcp")
        self._real_conf, self._real_file = mcp.CONF, mcp.CONFIG_FILE
        mcp.CONF = self.ws
        mcp.CONFIG_FILE = self.ws / "mcp.json"
        self.addCleanup(lambda: setattr(mcp, "CONF", self._real_conf))
        self.addCleanup(lambda: setattr(mcp, "CONFIG_FILE", self._real_file))

    def test_a_missing_file_loads_as_empty_not_an_error(self):
        self.assertEqual({"servers": {}}, mcp.load_config())

    def test_a_corrupt_file_loads_as_empty_not_an_error(self):
        mcp.CONFIG_FILE.write_text("not json")
        self.assertEqual({"servers": {}}, mcp.load_config())

    def test_save_then_load_round_trips_and_is_mode_0600(self):
        doc = {"servers": {"fs": {"command": "npx", "args": ["-y", "pkg"], "env": {},
                                  "enabled": True, "tools": [], "lastProbe": None}}}
        mcp.save_config(doc)
        self.assertEqual(doc, mcp.load_config())
        self.assertEqual(0o600, mcp.CONFIG_FILE.stat().st_mode & 0o777)

    def test_probe_server_writes_back_tools_and_last_probe(self):
        mcp.save_config({"servers": {"fake": {
            "command": sys.executable, "args": [FAKE, "ok"], "env": {}, "enabled": True,
            "tools": [], "lastProbe": None}}})
        with mock.patch.object(mcp, "INIT_TIMEOUT", 3):
            result = mcp.probe_server("fake")
        self.assertTrue(result["ok"], result)
        self.assertEqual(["echo", "delete_thing"], [t["name"] for t in result["tools"]])
        saved = mcp.load_config()["servers"]["fake"]
        self.assertEqual(2, len(saved["tools"]))
        self.assertTrue(saved["lastProbe"]["ok"])

    def test_probe_server_records_the_failure_without_raising(self):
        mcp.save_config({"servers": {"broken": {
            "command": "this-binary-does-not-exist-argus", "args": [], "env": {},
            "enabled": True, "tools": [], "lastProbe": None}}})
        result = mcp.probe_server("broken")
        self.assertFalse(result["ok"])
        saved = mcp.load_config()["servers"]["broken"]
        self.assertFalse(saved["lastProbe"]["ok"])
        self.assertIn("not found", saved["lastProbe"]["error"])

    def test_probe_server_reports_an_unknown_name_without_touching_the_file(self):
        mcp.save_config({"servers": {}})
        result = mcp.probe_server("nope")
        self.assertFalse(result["ok"])
        self.assertIn("nope", result["error"])


class RegisterMcpToolsTests(unittest.TestCase):
    """_register_mcp_tools() populates lib.tools.REGISTRY from mcp.json's
    cached tool list — the same REGISTRY toolreg.schemas() builds the
    model's tool list from, so a bug here is invisible to every other test
    that only checks mcp.py in isolation."""
    def setUp(self):
        self.ws = support.make_workspace("ws-mcp-register")
        self._real_conf, self._real_file = mcp.CONF, mcp.CONFIG_FILE
        mcp.CONF = self.ws
        mcp.CONFIG_FILE = self.ws / "mcp.json"
        self.addCleanup(lambda: setattr(mcp, "CONF", self._real_conf))
        self.addCleanup(lambda: setattr(mcp, "CONFIG_FILE", self._real_file))
        self._before = set(tools.REGISTRY)
        self.addCleanup(self._restore_registry)

    def _restore_registry(self):
        for name in set(tools.REGISTRY) - self._before:
            del tools.REGISTRY[name]

    def test_an_enabled_servers_tools_are_registered(self):
        mcp.save_config({"servers": {"fs": {
            "command": "npx", "args": [], "env": {}, "enabled": True,
            "tools": [{"name": "read_file", "description": "Read a file.",
                      "inputSchema": {
                          "type": "object",
                          "properties": {"path": {"type": "string"}},
                      },
                      "annotations": {"readOnlyHint": True}}]}}})
        tools._register_mcp_tools()
        spec = tools.REGISTRY["mcp__fs__read_file"]
        self.assertEqual("Read a file.", spec["description"])
        self.assertEqual("mcp", spec["grant"])
        self.assertEqual("read", spec["risk"])
        self.assertEqual({"path"}, set(spec["parameters"]["properties"]))
        self.assertEqual(["fs.read_file"], spec["subject"](None, {}))

    def test_a_destructive_hint_maps_to_commit_risk(self):
        mcp.save_config({"servers": {"fs": {
            "command": "npx", "args": [], "env": {}, "enabled": True,
            "tools": [{"name": "delete_file", "description": "",
                      "annotations": {"destructiveHint": True}}]}}})
        tools._register_mcp_tools()
        self.assertEqual("commit", tools.REGISTRY["mcp__fs__delete_file"]["risk"])

    def test_a_disabled_servers_tools_are_not_registered(self):
        mcp.save_config({"servers": {"fs": {
            "command": "npx", "args": [], "env": {}, "enabled": False,
            "tools": [{"name": "read_file", "description": ""}]}}})
        tools._register_mcp_tools()
        self.assertNotIn("mcp__fs__read_file", tools.REGISTRY)

    def test_a_broken_config_file_does_not_raise(self):
        mcp.CONFIG_FILE.write_text("not json")
        tools._register_mcp_tools()  # must not raise


class ToolFullNameTests(unittest.TestCase):
    def test_names_are_slugged_and_namespaced(self):
        self.assertEqual("mcp__my_server__ech"
            "o", mcp.tool_full_name("my server", "echo"))

    def test_unusual_characters_do_not_produce_an_empty_slug(self):
        self.assertEqual("mcp__tool__tool", mcp.tool_full_name("!!!", "???"))


if __name__ == "__main__":
    unittest.main()
