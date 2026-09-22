"""Closed-loop pointer placement: read → relative-move → re-read.

Covers _place_pointer/click/drag against a simulated cursor (including an
accelerated one that overshoots every relative move), because the whole
point of the loop is converging despite a lying first move — and because a
placement that fails must still report where the pointer really is.
"""
import unittest
from unittest import mock

import support  # noqa: F401

from lib import kwin

# This file tests the correction/convergence algorithm in KWin's own logical
# coordinate space, decoupled from the separate screenshot-pixel <-> logical
# conversion at _place_pointer's boundary (see kwin.to_logical_px/
# to_screenshot_px and test_kwin.py's ScreenScaleTests, which covers that
# conversion on its own) — pin the scale to 1.0 so FakeDesktop's positions
# stay directly comparable to the coordinates each test requests.
_scale_patch = None


def setUpModule():
    global _scale_patch
    _scale_patch = mock.patch.object(kwin, "_screen_scale", return_value=1.0)
    _scale_patch.start()


def tearDownModule():
    _scale_patch.stop()


class FakeDesktop:
    """A cursor with configurable acceleration plus a call log."""

    def __init__(self, x=100, y=100, factor=1.0):
        self.pos = [x, y]
        self.factor = factor
        self.calls = []

    def cursor_position(self, timeout=5):
        return {"ok": True, "x": self.pos[0], "y": self.pos[1]}

    def ydotool(self, args, timeout=20):
        self.calls.append(list(args))
        if args[0] == "mousemove" and args[1] in ("-x", "--absolute", "--wheel"):
            if args[1] == "--absolute":
                self.pos = [int(args[2]), int(args[3])]
            elif args[1] == "--wheel":
                return {"ok": True, "error": ""}
            else:
                dx = int(args[args.index("-x") + 1])
                dy = int(args[args.index("-y") + 1])
                self.pos[0] += round(dx * self.factor)
                self.pos[1] += round(dy * self.factor)
            return {"ok": True, "error": ""}
        if args[0] in ("click", "key"):
            return {"ok": True, "error": ""}
        return {"ok": False, "error": "unexpected"}


def patched(fake):
    return (mock.patch.object(kwin, "cursor_position", fake.cursor_position),
            mock.patch.object(kwin, "_ydotool", fake.ydotool))


class PlacePointerTests(unittest.TestCase):
    def test_already_there_makes_no_move_calls(self):
        fake = FakeDesktop(x=500, y=400)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        r = kwin._place_pointer(502, 401)
        self.assertTrue(r["ok"])
        self.assertEqual(r["corrections"], 0)
        self.assertEqual(fake.calls, [])
        self.assertEqual((r["x"], r["y"]), (500, 400))

    def test_exact_move_converges_in_one_round(self):
        fake = FakeDesktop(x=100, y=100, factor=1.0)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        r = kwin._place_pointer(300, 200)
        self.assertTrue(r["ok"])
        self.assertEqual((r["x"], r["y"]), (300, 200))
        self.assertEqual(r["corrections"], 1)
        self.assertTrue(r["verified"])

    def test_accelerated_cursor_still_converges(self):
        """1.6x acceleration overshoots every move; the loop must correct."""
        fake = FakeDesktop(x=100, y=100, factor=1.6)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        r = kwin._place_pointer(1100, 800)
        self.assertTrue(r["ok"], r)
        self.assertLessEqual(abs(r["x"] - 1100), kwin.POINTER_TOLERANCE_PX)
        self.assertLessEqual(abs(r["y"] - 800), kwin.POINTER_TOLERANCE_PX)
        self.assertGreater(r["corrections"], 1)

    def test_non_convergence_fails_closed_with_actual_position(self):
        """A cursor that never moves: ok False, but x/y say where it is."""
        fake = FakeDesktop(x=100, y=100, factor=0.0)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        r = kwin._place_pointer(900, 700)
        self.assertFalse(r["ok"])
        self.assertEqual((r["x"], r["y"]), (100, 100))
        self.assertIn("error", r)

    def test_unreadable_cursor_falls_back_to_absolute_unverified(self):
        fake = FakeDesktop()
        p2 = mock.patch.object(kwin, "_ydotool", fake.ydotool)
        p2.start(); self.addCleanup(p2.stop)
        with mock.patch.object(kwin, "cursor_position",
                               return_value={"ok": False, "error": "no bus"}):
            r = kwin._place_pointer(400, 300)
        self.assertFalse(r["verified"])
        self.assertIn("--absolute", fake.calls[0])


class ClickDragTests(unittest.TestCase):
    def test_click_places_then_clicks_at_current_position(self):
        fake = FakeDesktop(x=0, y=0, factor=1.0)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        r = kwin.click(640, 480, "left", 1)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["x"], r["y"]), (640, 480))
        kinds = [c[0] for c in fake.calls]
        self.assertEqual(kinds, ["mousemove", "click"])
        self.assertEqual(fake.calls[1][-1], "0xC0")

    def test_click_reports_placement_failure_without_clicking(self):
        fake = FakeDesktop(x=0, y=0, factor=0.0)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        r = kwin.click(640, 480, "left", 1)
        self.assertFalse(r["ok"])
        self.assertNotIn("click", [c[0] for c in fake.calls])

    def test_drag_is_down_move_up_with_measured_ends(self):
        fake = FakeDesktop(x=0, y=0, factor=1.0)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        with mock.patch("time.sleep"):
            r = kwin.drag(100, 100, 400, 300)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["start"], [100, 100])
        self.assertEqual(r["end"], [400, 300])
        codes = [c[-1] for c in fake.calls if c[0] == "click"]
        self.assertEqual(codes, ["0x40", "0x80"])

    def test_failed_end_of_drag_still_releases(self):
        """Start places fine, end never converges: button must come back up."""
        fake = FakeDesktop(x=100, y=100, factor=1.0)
        calls = []

        def flaky_ydotool(args, timeout=20):
            calls.append(list(args))
            if args[0] == "mousemove" and "-x" in args:
                # Freeze the cursor once the button is down: every end
                # correction lands nowhere, so end placement must fail.
                down_done = any(c[0] == "click" and c[-1] == "0x40" for c in calls)
                if not down_done:
                    fake.pos[0] += int(args[args.index("-x") + 1])
                    fake.pos[1] += int(args[args.index("-y") + 1])
            return {"ok": True, "error": ""}

        p1 = mock.patch.object(kwin, "cursor_position", fake.cursor_position)
        p2 = mock.patch.object(kwin, "_ydotool", flaky_ydotool)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        with mock.patch("time.sleep"):
            r = kwin.drag(100, 100, 900, 700)
        self.assertFalse(r["ok"])
        codes = [c[-1] for c in calls if c[0] == "click"]
        self.assertEqual(codes, ["0x40", "0x80"])

    def test_click_with_modifiers_presses_and_releases_modifier_keys(self):
        fake = FakeDesktop(x=0, y=0, factor=1.0)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        r = kwin.click(100, 100, "left", 1, modifiers=["ctrl", "shift"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["modifiers"], ["ctrl", "shift"])
        key_calls = [c for c in fake.calls if c[0] == "key"]
        self.assertEqual(key_calls, [["key", "29:1"], ["key", "42:1"], ["key", "42:0"], ["key", "29:0"]])

    def test_drag_with_steps_emits_intermediate_motion_ticks(self):
        fake = FakeDesktop(x=0, y=0, factor=1.0)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        with mock.patch("time.sleep"):
            r = kwin.drag(0, 0, 100, 100, steps=5)
        self.assertTrue(r["ok"], r)
        # Verify intermediate relative moves occurred while mouse was held down
        down_idx = next(i for i, c in enumerate(fake.calls) if c[0] == "click" and c[-1] == "0x40")
        up_idx = next(i for i, c in enumerate(fake.calls) if c[0] == "click" and c[-1] == "0x80")
        mid_moves = [c for c in fake.calls[down_idx + 1:up_idx] if c[0] == "mousemove" and "-x" in c]
        self.assertGreaterEqual(len(mid_moves), 4)


class CursorPositionTests(unittest.TestCase):
    def test_parses_the_script_reply(self):
        with mock.patch.object(kwin, "run_script", return_value='{"x": 12, "y": 34}'):
            r = kwin.cursor_position()
        self.assertEqual(r, {"ok": True, "x": 12, "y": 34})

    def test_empty_reply_is_an_explicit_failure(self):
        with mock.patch.object(kwin, "run_script", return_value=None):
            r = kwin.cursor_position()
        self.assertFalse(r["ok"])


class HoverAndScrollTests(unittest.TestCase):
    def test_hover_dwells_at_target_position(self):
        fake = FakeDesktop(x=0, y=0, factor=1.0)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        with mock.patch("time.sleep") as mock_sleep:
            r = kwin.hover(150, 250, duration=0.5)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["x"], r["y"]), (150, 250))
        self.assertEqual(r["hovered_seconds"], 0.5)
        mock_sleep.assert_called_with(0.5)

    def test_scroll_directional_delts(self):
        fake = FakeDesktop(x=50, y=50, factor=1.0)
        p1, p2 = patched(fake)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

        # Down scroll (default)
        r_down = kwin.scroll(4, direction="down")
        self.assertTrue(r_down["ok"], r_down)
        self.assertEqual(fake.calls[-1], ["mousemove", "--wheel", "0", "4"])

        # Up scroll
        r_up = kwin.scroll(3, direction="up")
        self.assertTrue(r_up["ok"], r_up)
        self.assertEqual(fake.calls[-1], ["mousemove", "--wheel", "0", "-3"])

        # Left scroll
        r_left = kwin.scroll(2, direction="left")
        self.assertTrue(r_left["ok"], r_left)
        self.assertEqual(fake.calls[-1], ["mousemove", "--wheel", "-2", "0"])

        # Right scroll
        r_right = kwin.scroll(5, direction="right")
        self.assertTrue(r_right["ok"], r_right)
        self.assertEqual(fake.calls[-1], ["mousemove", "--wheel", "5", "0"])

        # Negative amount backward-compatibility
        r_neg = kwin.scroll(-3, direction="down")
        self.assertTrue(r_neg["ok"], r_neg)
        self.assertEqual(fake.calls[-1], ["mousemove", "--wheel", "0", "-3"])


if __name__ == "__main__":
    unittest.main()
