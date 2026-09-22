"""The LSP client, against a fake language server that speaks real framing.

These are the paths where the client used to report success for work that did not
happen: a timeout was returned as "no diagnostics" (a clean bill of health for a
file nothing had analysed), a server that never answered initialize was treated
as started, and server-initiated requests were dropped, which left real servers
(pyright, typescript-language-server) waiting forever before they would publish.
"""
import sys
import unittest
from pathlib import Path

import support  # noqa: F401

from lib import lsp

FAKE = str(Path(__file__).resolve().parent / "fake_lsp_server.py")


class LspClientTests(unittest.TestCase):
    def setUp(self):
        self.root = support.make_workspace("ws-lsp")
        self.file = support.write(self.root / "a.py", "import os\nval = undefined_name\n")
        self._real_find_server = lsp.find_server
        self._real_init_timeout = lsp.INIT_TIMEOUT
        lsp.INIT_TIMEOUT = 3          # keep the suite fast; the budget is not what is under test
        self.addCleanup(lambda: setattr(lsp, "find_server", self._real_find_server))
        self.addCleanup(lambda: setattr(lsp, "INIT_TIMEOUT", self._real_init_timeout))

    def serve(self, mode):
        """Point the client at the fake server in the given mode."""
        lsp.find_server = lambda language: [sys.executable, FAKE, mode]

    def test_diagnostics_are_parsed(self):
        self.serve("ok")
        result = lsp.diagnostics(self.file, self.file.read_text(), "python", self.root, timeout=10)
        self.assertTrue(result["ok"], result)
        self.assertEqual(1, len(result["diagnostics"]))
        first = result["diagnostics"][0]
        self.assertEqual(2, first["line"])
        self.assertEqual(5, first["col"])
        self.assertEqual("error", first["severity"])
        self.assertIn("undefined name", first["message"])

    def test_a_server_that_never_publishes_is_a_failure_not_a_clean_file(self):
        """Regression: this returned ok:True with diagnostics:[] — the same shape
        a genuinely clean file produces."""
        self.serve("silent")
        result = lsp.diagnostics(self.file, self.file.read_text(), "python", self.root, timeout=4)
        self.assertFalse(result["ok"], result)
        self.assertIn("was not checked", result["error"])
        self.assertEqual([], result["diagnostics"])

    def test_a_rejected_initialize_is_reported(self):
        self.serve("reject")
        result = lsp.diagnostics(self.file, self.file.read_text(), "python", self.root, timeout=10)
        self.assertFalse(result["ok"], result)
        self.assertIn("rejected initialize", result["error"])

    def test_a_server_that_never_answers_initialize_is_reported(self):
        self.serve("no-init")
        result = lsp.diagnostics(self.file, self.file.read_text(), "python", self.root, timeout=10)
        self.assertFalse(result["ok"], result)
        self.assertIn("did not answer initialize", result["error"])

    def test_a_server_initiated_configuration_request_is_answered(self):
        """The fake server refuses to publish until the client answers its
        workspace/configuration request, so a green result here means the answer
        was actually sent (before: it hung until the caller's timeout)."""
        self.serve("needs-config")
        result = lsp.diagnostics(self.file, self.file.read_text(), "python", self.root, timeout=10)
        self.assertTrue(result["ok"], result)
        self.assertEqual(1, len(result["diagnostics"]))

    def test_symbols_are_parsed(self):
        self.serve("ok")
        result = lsp.symbols(self.file, self.file.read_text(), "python", self.root, timeout=10)
        self.assertTrue(result["ok"], result)
        self.assertEqual(["a_function", "a_class"], [s["name"] for s in result["symbols"]])
        self.assertEqual(3, result["symbols"][0]["line"])

    def test_a_symbol_error_response_is_not_reported_as_success(self):
        self.serve("symbols-error")
        result = lsp.symbols(self.file, self.file.read_text(), "python", self.root, timeout=10)
        self.assertFalse(result["ok"], result)
        self.assertIn("no symbols for you", result["error"])

    def test_no_server_installed_says_so(self):
        lsp.find_server = lambda language: None
        result = lsp.diagnostics(self.file, self.file.read_text(), "python", self.root)
        self.assertFalse(result["ok"])
        self.assertIn("no language server installed", result["error"])

    def test_the_client_does_not_leave_the_server_running(self):
        self.serve("silent")
        lsp.diagnostics(self.file, self.file.read_text(), "python", self.root, timeout=3)
        # stop() ran in the finally; nothing of the fake server should be left
        # as a child of this process.
        import subprocess
        children = subprocess.run(["pgrep", "-P", str(__import__("os").getpid()), "-f", FAKE],
                                  capture_output=True, text=True)
        self.assertEqual("", children.stdout.strip())


if __name__ == "__main__":
    unittest.main()
