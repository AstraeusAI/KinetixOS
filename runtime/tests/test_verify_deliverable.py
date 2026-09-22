"""verify_deliverable tool, test-baseline hook, orphan scrub, cache cleanup."""
import json
import unittest
from pathlib import Path

import support

import argusd
from lib import tools
from lib.checkpoints import Checkpoints
from lib.policy import Policy
from lib.workspace import Workspace, _which


class Ctx:
    def __init__(self, root):
        self.workspace = Workspace(root)
        self.policy = Policy(self.workspace.root)
        self.checkpoints = Checkpoints("test-verify")
        self.grants = {"shell": True}
        self.db = None
        self.session = "test-verify"
        self.todos = []
        self.mcp_clients = {}
        self.test_baseline = {}


GOOD_PY = '''"""Clean module."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
'''

SLOP_PY = '''"""Slop module."""


# TODO: handle negatives later
def add(a, b):
    # Now we compute the sum of the two inputs
    return a + b
'''

LONG_PY = 'x = "' + "y" * 100 + '"\n'


class BaselineHookTests(unittest.TestCase):
    def setUp(self):
        self.root = support.make_workspace("verify-deliverable")
        for p in self.root.glob("test_*.py"):
            p.unlink()
        for p in self.root.glob("*.py"):
            if p.name != "keep.py":
                p.unlink()
        self.ctx = Ctx(self.root)

    def test_first_write_of_test_file_records_baseline(self):
        r = tools.REGISTRY["write_file"]["handler"](
            self.ctx, {"path": "test_samp.py",
                       "content": "def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert True\n"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.ctx.test_baseline.get("test_samp.py"), (2, 2))

    def test_non_test_write_records_nothing(self):
        tools.REGISTRY["write_file"]["handler"](
            self.ctx, {"path": "util.py", "content": GOOD_PY})
        self.assertEqual(self.ctx.test_baseline, {})

    def test_later_writes_do_not_move_baseline(self):
        tools.REGISTRY["write_file"]["handler"](
            self.ctx, {"path": "test_samp.py", "content": "def test_a():\n    assert 1\n"})
        tools.REGISTRY["edit_file"]["handler"](
            self.ctx, {"path": "test_samp.py",
                       "old_string": "assert 1", "new_string": "assert 1\n    assert 2"})
        self.assertEqual(self.ctx.test_baseline.get("test_samp.py"), (1, 1))

    def test_weakening_detected_by_verify(self):
        tools.REGISTRY["write_file"]["handler"](
            self.ctx, {"path": "test_weak.py",
                       "content": "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 2\n"})
        tools.REGISTRY["write_file"]["handler"](
            self.ctx, {"path": "test_weak.py", "content": "def test_a():\n    pass\n"})
        r = tools.REGISTRY["verify_deliverable"]["handler"](self.ctx, {})
        weak = [f for f in r["findings"] if f.startswith("test-weakening")]
        self.assertTrue(weak, r["findings"])
        self.assertFalse(r["ok"])

    def test_growth_is_not_weakening(self):
        tools.REGISTRY["write_file"]["handler"](
            self.ctx, {"path": "test_grow.py", "content": "def test_a():\n    assert 1\n"})
        tools.REGISTRY["edit_file"]["handler"](
            self.ctx, {"path": "test_grow.py", "old_string": "assert 1",
                       "new_string": "assert 1\n\n\ndef test_b():\n    assert 2\n    assert 3"})
        r = tools.REGISTRY["verify_deliverable"]["handler"](self.ctx, {})
        weak = [f for f in r["findings"] if f.startswith("test-weakening")]
        self.assertEqual(weak, [])


class SlopAndStrayTests(unittest.TestCase):
    def setUp(self):
        self.root = support.make_workspace("verify-slop")
        for p in self.root.glob("*.py"):
            p.unlink()
        self.ctx = Ctx(self.root)

    def test_slop_markers_found(self):
        (self.root / "slop.py").write_text(SLOP_PY)
        (self.root / "clean.py").write_text(GOOD_PY)
        r = tools.REGISTRY["verify_deliverable"]["handler"](self.ctx, {})
        labels = [f for f in r["findings"] if f.startswith("slop")]
        self.assertTrue(any("placeholder marker" in f and "slop.py" in f for f in labels), labels)
        self.assertTrue(any("narration comment" in f and "slop.py" in f for f in labels), labels)
        self.assertFalse(any("clean.py" in f for f in labels), labels)

    def test_stray_artifacts_found(self):
        (self.root / "__pycache__").mkdir(exist_ok=True)
        (self.root / "scratch.tmp").write_text("x")
        (self.root / "ok.py").write_text(GOOD_PY)
        r = tools.REGISTRY["verify_deliverable"]["handler"](self.ctx, {})
        strays = [f for f in r["findings"] if f.startswith("stray artifact")]
        self.assertEqual(len(strays), 2, r["findings"])
        (self.root / "__pycache__").rmdir()
        (self.root / "scratch.tmp").unlink()

    def test_strict_lint_flags_long_lines(self):
        if not _which("ruff"):
            self.skipTest("ruff not installed")
        (self.root / "long.py").write_text(LONG_PY)
        r = tools.REGISTRY["verify_deliverable"]["handler"](self.ctx, {})
        self.assertTrue(any("E501" in f and "long.py" in f for f in r["findings"]), r["findings"])


def _have(mod=None, bin=None):
    import importlib.util
    if mod and importlib.util.find_spec(mod) is None:
        return False
    if bin:
        import shutil
        from pathlib import Path as _P
        if not shutil.which(bin) and not (_P.home() / ".local" / "bin" / bin).exists():
            return False
    return True


class TierOneGateTests(unittest.TestCase):
    def setUp(self):
        self.root = support.make_workspace("verify-tier1")
        for p in self.root.glob("*.py"):
            p.unlink()
        for p in self.root.glob(".coverage*"):
            try:
                p.chmod(0o600)
            except Exception:
                pass
            try:
                p.unlink()
            except Exception:
                pass
        self.ctx = Ctx(self.root)

    def _verify(self):
        return tools.REGISTRY["verify_deliverable"]["handler"](self.ctx, {})

    def test_bandit_flags_shell_true(self):
        if not _have(mod="bandit"):
            self.skipTest("bandit not installed")
        (self.root / "risky.py").write_text(
            '"""Risky."""\nimport subprocess\n\n\ndef run(cmd: str) -> None:\n'
            '    """Run it."""\n    subprocess.call(cmd, shell=True)\n')
        r = self._verify()
        self.assertTrue(any(f.startswith("security lint (bandit") for f in r["findings"]),
                        r["findings"])

    def test_bandit_low_only_is_not_a_finding(self):
        if not _have(mod="bandit"):
            self.skipTest("bandit not installed")
        # B404 (import subprocess) is Low: a test harness with fixed argv
        # and no shell must not fail verification over it.
        (self.root / "harness.py").write_text(
            '"""Harness."""\nimport subprocess\n\n\ndef run() -> int:\n'
            '    """Run it."""\n    return subprocess.call(["true"])\n')
        r = self._verify()
        self.assertFalse([f for f in r["findings"] if f.startswith("security lint")],
                         r["findings"])

    def test_bandit_clean_passes(self):
        if not _have(mod="bandit"):
            self.skipTest("bandit not installed")
        (self.root / "safe.py").write_text(GOOD_PY)
        r = self._verify()
        self.assertFalse([f for f in r["findings"] if f.startswith("security lint")],
                         r["findings"])

    def test_vulture_flags_dead_code(self):
        if not _have(mod="vulture"):
            self.skipTest("vulture not installed")
        (self.root / "dead.py").write_text(
            '"""Dead."""\n\n\ndef never_called() -> int:\n    """Never."""\n    return 1\n')
        r = self._verify()
        self.assertTrue(any(f.startswith("dead code (vulture)") for f in r["findings"]),
                        r["findings"])

    def test_interrogate_threshold(self):
        if not _have(mod="interrogate"):
            self.skipTest("interrogate not installed")
        (self.root / "undoc.py").write_text("def f(a, b):\n    return a + b\n")
        r = self._verify()
        self.assertTrue(any(f.startswith("docstring coverage") for f in r["findings"]),
                        r["findings"])
        (self.root / "undoc.py").unlink()
        (self.root / "docd.py").write_text(GOOD_PY)
        r = self._verify()
        self.assertFalse([f for f in r["findings"] if f.startswith("docstring coverage")],
                         r["findings"])

    def test_coverage_gate(self):
        if not _have(mod="coverage"):
            self.skipTest("coverage not installed")
        (self.root / "mod.py").write_text(
            '"""Mod."""\n\n\ndef sign(x: int) -> str:\n    """Sign."""\n'
            '    if x > 0:\n        return "pos"\n    return "neg"\n')
        (self.root / "test_mod.py").write_text(
            "from mod import sign\n\n\ndef test_pos():\n    assert sign(1) == 'pos'\n")
        r = self._verify()
        self.assertTrue(any(f.startswith("coverage:") for f in r["findings"]), r["findings"])
        (self.root / "test_mod.py").write_text(
            "from mod import sign\n\n\ndef test_pos():\n    assert sign(1) == 'pos'\n\n\n"
            "def test_neg():\n    assert sign(-1) == 'neg'\n")
        r = self._verify()
        self.assertFalse([f for f in r["findings"] if f.startswith("coverage:")],
                         r["findings"])

    def test_gitleaks_flags_fake_key(self):
        if not _have(bin="gitleaks"):
            self.skipTest("gitleaks not installed")
        # NOTE: the documented example key AKIAIOSFODNN7EXAMPLE is
        # allowlisted by gitleaks itself — use a realistic non-example
        # token (verified live: github-pat rule fires on this shape).
        (self.root / "leak.py").write_text(
            '"""Leak."""\nTOKEN = "ghp_123456789012345678901234567890123456"\n')
        r = self._verify()
        self.assertTrue(any(f.startswith("secrets scan (gitleaks)") for f in r["findings"]),
                        r["findings"])

    def test_gitleaks_clean_passes(self):
        if not _have(bin="gitleaks"):
            self.skipTest("gitleaks not installed")
        (self.root / "clean2.py").write_text(GOOD_PY)
        r = self._verify()
        self.assertFalse([f for f in r["findings"] if f.startswith("secrets scan")],
                         r["findings"])


    def test_format_check_flags_unformatted(self):
        (self.root / "ugly.py").write_text('"""U."""\nx=1\n')
        r = self._verify()
        self.assertTrue(any(f.startswith("format (ruff format") for f in r["findings"]),
                        r["findings"])

    def test_format_clean_passes(self):
        (self.root / "neat.py").write_text(GOOD_PY)
        r = self._verify()
        self.assertFalse([f for f in r["findings"] if f.startswith("format (ruff format")],
                         r["findings"])

    def test_js_and_html_todo_slop(self):
        (self.root / "app.js").write_text("// TODO: wire this up\nconsole.log(1);\n")
        (self.root / "page.html").write_text("<!doctype html><html><body><!-- TODO: content --></body></html>\n")
        (self.root / "ok.py").write_text(GOOD_PY)
        r = self._verify()
        labels = [f for f in r["findings"] if f.startswith("slop")]
        self.assertTrue(any("app.js" in f and "placeholder marker" in f for f in labels), labels)
        self.assertTrue(any("page.html" in f and "placeholder marker" in f for f in labels), labels)


class OrphanScrubTests(unittest.TestCase):
    def test_orphan_tool_result_dropped(self):
        ev = [
            ("assistant", json.dumps({"text": "go", "tool_calls": [{"id": "call-1", "name": "x"}]})),
            ("tool", json.dumps({"id": "call-1", "name": "x", "result": {"ok": True}})),
            ("tool", json.dumps({"id": "call-dead", "name": "y", "result": {"ok": True}})),
        ]
        kept = argusd._drop_orphan_tool_results(ev, "s")
        ids = [json.loads(p).get("id") for k, p in kept if k == "tool"]
        self.assertEqual(ids, ["call-1"])

    def test_history_id_and_pairs_kept(self):
        ev = [
            ("assistant", json.dumps({"text": "go", "tool_calls": [{"id": "call-1"}]})),
            ("tool", json.dumps({"id": "history", "result": {"ok": True}})),
            ("tool", json.dumps({"id": "call-1", "result": {"ok": True}})),
        ]
        self.assertEqual(len(argusd._drop_orphan_tool_results(ev, "s")), 3)

    def test_no_declarations_no_scrub(self):
        ev = [("tool", json.dumps({"id": "whatever", "result": {"ok": True}}))]
        self.assertEqual(argusd._drop_orphan_tool_results(ev, "s"), ev)


class CacheCleanupTests(unittest.TestCase):
    def test_caches_removed(self):
        root = support.make_workspace("verify-caches")
        cache = root / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "x.pyc").write_bytes(b"0")
        (root / "keep.py").write_text("x = 1\n")
        argusd._clean_workspace_caches(root)
        self.assertFalse(cache.exists())
        self.assertTrue((root / "keep.py").exists())





GOOD_HTML = '''<!doctype html>
<html lang="en">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Good</title>
<style>:focus-visible { outline: 2px solid blue; }</style>
</head>
<body><main><h1>Good page</h1>
<form><label for="name">Name</label><input id="name" name="name">
<button type="submit">Save changes now</button></form>
<div class="grid grid-cols-1 md:grid-cols-2"><p>Enough body text here to clear the blank-page threshold comfortably.</p></div>
</main></body></html>
'''

BAD_HTML = '''<!doctype html>
<html><head><title>Bad</title></head>
<body><h1>One</h1><h1>Two</h1>
<div onclick="go()">click me</div>
<form><input name="q"></form>
</body></html>
'''


class VerifyUIStaticTests(unittest.TestCase):
    def setUp(self):
        self.root = support.make_workspace("verify-ui")
        for p in self.root.glob("*.html"):
            p.unlink()
        self.ctx = Ctx(self.root)

    def _verify(self, name="index.html"):
        return tools.REGISTRY["verify_ui"]["handler"](self.ctx, {"path": name})

    def test_rejects_non_html(self):
        (self.root / "app.js").write_text("console.log(1);\n")
        r = tools.REGISTRY["verify_ui"]["handler"](self.ctx, {"path": "app.js"})
        self.assertFalse(r["ok"])
        self.assertIn("HTML entry", r["error"])

    def test_static_findings_on_bad_page(self):
        (self.root / "bad.html").write_text(BAD_HTML)
        import shutil as _sh
        has_chrome = tools._which_chromium() is not None
        r = tools.REGISTRY["verify_ui"]["handler"](
            Ctx(self.root) if has_chrome else self.ctx, {"path": "bad.html"})
        joined = " ".join(r["findings"])
        for needle in ("exactly 1", "lang attribute", "viewport meta",
                       "without programmatic label", "clickable <div>",
                       "focus styles", "responsive prefixes"):
            self.assertIn(needle, joined, r["findings"])
        self.assertFalse(r["ok"])

    def test_static_clean_on_good_page(self):
        (self.root / "good.html").write_text(GOOD_HTML)
        # Static-only assertion path: exercise the parser directly so this
        # test does not depend on a chromium binary being installed.
        sp = tools._UIStaticParse()
        sp.feed(GOOD_HTML)
        self.assertEqual(sp.h1, 1)
        self.assertEqual(sp.lang, "en")
        self.assertTrue(sp.viewport)
        self.assertEqual(sp.clickable_divs, 0)
        unlabeled = [t for t in sp.inputs if not t[3] and (not t[1] or t[1] not in sp.labels_for)]
        self.assertEqual(unlabeled, [])

    def test_live_load_good_page(self):
        if tools._which_chromium() is None:
            self.skipTest("no chromium binary")
        (self.root / "good.html").write_text(GOOD_HTML)
        r = self._verify("good.html")
        self.assertFalse([f for f in r["findings"] if f.startswith("ui (live)")],
                         r["findings"])
        self.assertIn("mobile", r["summary"]["metrics"])
        self.assertTrue(r["summary"]["screenshots"], r["summary"])

    def test_aria_live_required_when_dynamic(self):
        (self.root / "dyn.html").write_text(
            '<!doctype html><html lang="en"><head><title>D</title></head>'
            '<body><h1>D</h1><div id="t"></div></body></html>')
        (self.root / "app.js").write_text(
            'fetch("data.json").then(r => r.json()).then(d => { '
            'document.getElementById("t").textContent = d.length; });\n')
        r = tools.REGISTRY["verify_ui"]["handler"](self.ctx, {"path": "dyn.html"})
        live = [f for f in r["findings"] if "aria-live" in f]
        self.assertTrue(live, r["findings"])
        (self.root / "dyn.html").write_text(
            '<!doctype html><html lang="en"><head><title>D</title></head>'
            '<body><h1>D</h1><div id="t" aria-live="polite"></div></body></html>')
        r = tools.REGISTRY["verify_ui"]["handler"](self.ctx, {"path": "dyn.html"})
        self.assertFalse([f for f in r["findings"] if "aria-live" in f], r["findings"])

    def test_skip_link_and_dark_mode_are_notes(self):
        (self.root / "plain.html").write_text(
            '<!doctype html><html lang="en"><head><meta name="viewport" content="x">'
            '<title>P</title></head><body><h1>P</h1><p>Text here, plenty of it.</p></body></html>')
        r = tools.REGISTRY["verify_ui"]["handler"](self.ctx, {"path": "plain.html"})
        notes = " ".join(r["summary"].get("notes", []))
        self.assertIn("skip link", notes, r["summary"])
        self.assertIn("dark-mode", notes, r["summary"])

