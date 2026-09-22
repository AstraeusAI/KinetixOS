"""kwin.py is almost entirely a live D-Bus/subprocess adapter and most of it
needs a real KWin session to test meaningfully — but screenshot()'s error
handling is plain logic over subprocess.run's result, and that part is worth
covering directly: this is exactly what a live investigation found broken
(cursor mode failing with an empty, actionable-nothing error message, and a
30s timeout that let one hang eat most of a task's budget).
"""
import json
import subprocess
import unittest
from unittest import mock

from pathlib import Path
import support  # noqa: F401

from lib import kwin


class ScreenshotErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        self.path = support.TMP / "screenshot-test.png"
        if self.path.exists():
            self.path.unlink()
        patch = mock.patch("shutil.which", lambda name: "/usr/bin/spectacle" if name == "spectacle" else None)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_hang_reports_the_mode_and_a_timeout_short_enough_to_recover(self):
        """Confirmed live: window-under-cursor mode can hang spectacle
        outright. 30s let that eat most of a task's step/time budget on one
        screenshot; a normal capture measured 0.3-0.7s even under load, so
        the timeout only needs headroom for a slow system, not for a wedge."""
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="spectacle", timeout=12)):
            result = kwin.screenshot(self.path, mode="cursor")
        self.assertFalse(result["ok"])
        self.assertIn("cursor", result["error"])
        self.assertIn("mode=active", result["error"])

    def test_a_timeout_in_a_reliable_mode_has_no_cursor_specific_hint(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="spectacle", timeout=12)):
            result = kwin.screenshot(self.path, mode="active")
        self.assertFalse(result["ok"])
        self.assertNotIn("cursor", result["error"])

    def test_a_silent_failure_reports_the_exit_code_not_an_empty_string(self):
        """Confirmed live: cursor mode failed 4/4 times with returncode 2 and
        empty stderr *and* stdout. The old message was "capture failed: "
        with nothing after the colon — no exit code, no hint, nothing a
        caller could act on."""
        fake = subprocess.CompletedProcess(args=["spectacle"], returncode=2, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=fake):
            result = kwin.screenshot(self.path, mode="cursor")
        self.assertFalse(result["ok"])
        self.assertIn("exited 2", result["error"])
        self.assertIn("cursor mode", result["error"])

    def test_a_silent_failure_in_a_reliable_mode_has_no_cursor_specific_hint(self):
        fake = subprocess.CompletedProcess(args=["spectacle"], returncode=1, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=fake):
            result = kwin.screenshot(self.path, mode="fullscreen")
        self.assertFalse(result["ok"])
        self.assertIn("exited 1", result["error"])
        self.assertNotIn("cursor", result["error"])

    def test_a_failure_with_real_stderr_still_surfaces_it(self):
        fake = subprocess.CompletedProcess(args=["spectacle"], returncode=1,
                                           stdout="", stderr="some real diagnostic")
        with mock.patch("subprocess.run", return_value=fake):
            result = kwin.screenshot(self.path, mode="fullscreen")
        self.assertFalse(result["ok"])
        self.assertIn("some real diagnostic", result["error"])


class ScreenScaleTests(unittest.TestCase):
    """spectacle's screenshots (and observe_screen's images) are physical
    pixels; KWin's own coordinate space (cursorPos, frameGeometry, ydotool)
    is logical pixels, which differ by the output's scale factor on a
    fractionally-scaled display. Confirmed live on a 3840x2160 output at a
    1.7 scale (2259x1271 logical): requesting a pointer placement at a raw
    screenshot-pixel coordinate walked the cursor 1.7x too far and pinned
    it at the logical screen's edge, never converging."""

    def setUp(self):
        kwin._SCREEN_SCALE.clear()
        self.addCleanup(kwin._SCREEN_SCALE.clear)

    def test_scale_is_parsed_from_the_enabled_connected_output(self):
        doc = {"outputs": [
            {"connected": False, "enabled": False, "scale": 2.0},
            {"connected": True, "enabled": True, "scale": 1.7},
        ]}
        fake = subprocess.CompletedProcess(args=["kscreen-doctor"], returncode=0,
                                           stdout=json.dumps(doc), stderr="")
        with mock.patch("subprocess.run", return_value=fake):
            self.assertEqual(1.7, kwin._screen_scale())

    def test_scale_is_cached_not_reprobed_every_call(self):
        doc = {"outputs": [{"connected": True, "enabled": True, "scale": 1.5}]}
        fake = subprocess.CompletedProcess(args=["kscreen-doctor"], returncode=0,
                                           stdout=json.dumps(doc), stderr="")
        with mock.patch("subprocess.run", return_value=fake) as run:
            kwin._screen_scale()
            kwin._screen_scale()
        self.assertEqual(1, run.call_count)

    def test_an_unprobeable_scale_falls_back_to_1_not_a_guess(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertEqual(1.0, kwin._screen_scale())

    def test_to_screenshot_and_to_logical_are_inverses(self):
        """Round-tripping through an integer-pixel logical coordinate can be
        off by a rounding unit at a non-integer scale like 1.7 — that's fine,
        it's well within _place_pointer's own POINTER_TOLERANCE_PX; what
        matters is it stays a rounding artifact, not the original bug's
        ~1.7x-magnitude error."""
        with mock.patch.object(kwin, "_screen_scale", return_value=1.7):
            lx, ly = kwin.to_logical_px(3709, 244)
            sx, sy = kwin.to_screenshot_px(lx, ly)
        self.assertLessEqual(abs(sx - 3709), 2)
        self.assertLessEqual(abs(sy - 244), 2)

    def test_window_geometry_is_reported_in_screenshot_pixels(self):
        with mock.patch.object(kwin, "_screen_scale", return_value=1.7):
            w = kwin._win_to_screenshot_space({"x": 100, "y": 50, "w": 400, "h": 300, "caption": "x"})
        self.assertEqual({"x": 170, "y": 85, "w": 680, "h": 510, "caption": "x"}, w)

    def test_place_pointer_converts_the_request_to_logical_before_moving(self):
        """The actual bug: requesting a screenshot-pixel coordinate used to
        go straight to the (logical) cursor-correction loop unconverted."""
        moves = []

        def fake_cursor_position(timeout=5):
            return {"ok": True, "x": 100, "y": 100}

        def fake_ydotool(args, timeout=20):
            moves.append(list(args))
            return {"ok": True, "error": ""}

        with mock.patch.object(kwin, "_screen_scale", return_value=2.0), \
             mock.patch.object(kwin, "cursor_position", fake_cursor_position), \
             mock.patch.object(kwin, "_ydotool", fake_ydotool):
            kwin._place_pointer(400, 300)  # screenshot px -> logical (200, 150)
        dx = int(moves[0][moves[0].index("-x") + 1])
        dy = int(moves[0][moves[0].index("-y") + 1])
        self.assertEqual((100, 50), (dx, dy))  # logical (200,150) - (100,100)

    def test_place_pointer_reports_the_measured_position_in_screenshot_pixels(self):
        def fake_cursor_position(timeout=5):
            return {"ok": True, "x": 200, "y": 150}  # already at the (converted) target

        with mock.patch.object(kwin, "_screen_scale", return_value=2.0), \
             mock.patch.object(kwin, "cursor_position", fake_cursor_position):
            r = kwin._place_pointer(400, 300)
        self.assertTrue(r["ok"], r)
        self.assertEqual((400, 300), (r["x"], r["y"]))
        self.assertEqual([400, 300], r["requested"])


class WindowActionTests(unittest.TestCase):
    def test_maximize_window_emits_correct_script(self):
        scripts = []

        def fake_window_action(uuid, body, marker="ARGUS_ACTION_"):
            scripts.append((uuid, body))
            return {"ok": True, "result": "maximized"}

        with mock.patch.object(kwin, "_window_action", fake_window_action):
            r1 = kwin.maximize_window("win-123", state=True)
            r2 = kwin.maximize_window("win-123", state=False)
        self.assertTrue(r1["ok"])
        self.assertIn("target.setMaximize(true, true)", scripts[0][1])
        self.assertTrue(r2["ok"])
        self.assertIn("target.setMaximize(false, false)", scripts[1][1])

    def test_minimize_window_emits_correct_script(self):
        scripts = []

        def fake_window_action(uuid, body, marker="ARGUS_ACTION_"):
            scripts.append((uuid, body))
            return {"ok": True, "result": "minimized"}

        with mock.patch.object(kwin, "_window_action", fake_window_action):
            r1 = kwin.minimize_window("win-456", state=True)
            r2 = kwin.minimize_window("win-456", state=False)
        self.assertTrue(r1["ok"])
        self.assertIn("target.minimized = true", scripts[0][1])
        self.assertTrue(r2["ok"])
        self.assertIn("target.minimized = false", scripts[1][1])


class ImageDimensionTests(unittest.TestCase):
    def test_read_png_dimensions_from_header(self):
        import struct
        png_hdr = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", 3840, 2160)
        path = support.TMP / "test_dim.png"
        path.write_bytes(png_hdr)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        w, h = kwin._read_image_dimensions(path)
        self.assertEqual((3840, 2160), (w, h))

    def test_screenshot_result_carries_dimensions_and_scale(self):
        import struct
        path = support.TMP / "test_screen.png"
        png_hdr = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", 1920, 1080)
        path.write_bytes(png_hdr)
        self.addCleanup(lambda: path.unlink(missing_ok=True))

        fake = subprocess.CompletedProcess(args=["spectacle"], returncode=0, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=fake), \
             mock.patch("shutil.which", return_value="/usr/bin/spectacle"), \
             mock.patch.object(kwin, "_screen_scale", return_value=1.5):
            res = kwin.screenshot(path, mode="fullscreen")
        self.assertTrue(res["ok"])
        self.assertEqual(res["width"], 1920)
        self.assertEqual(res["height"], 1080)
        self.assertEqual(res["scale"], 1.5)


class TypeTextSafetyTests(unittest.TestCase):
    def test_ydotool_type_uses_double_dash_flag_protection(self):
        calls = []

        def fake_ydotool(args, timeout=20):
            calls.append(list(args))
            return {"ok": True, "error": ""}

        with mock.patch.object(kwin, "input_backend", return_value=("ydotool", "ok")), \
             mock.patch.object(kwin, "_ydotool", fake_ydotool):
            r = kwin.type_text("-rf --help")
        self.assertTrue(r["ok"])
        self.assertEqual(calls[0], ["type", "--", "-rf --help"])


class ZoomAndScreenChangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = support.TMP
        self.src = self.tmp / "test_zoom_src.png"
        import struct
        hdr = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", 1920, 1080)
        self.src.write_bytes(hdr)
        self.addCleanup(lambda: self.src.unlink(missing_ok=True))

    def test_zoom_crops_and_reports_dimensions(self):
        dst = self.tmp / "test_zoom_dst.png"
        import struct
        dst_hdr = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", 300, 200)

        def fake_run(cmd, capture_output=True, text=True, timeout=20):
            dst.write_bytes(dst_hdr)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        self.addCleanup(lambda: dst.unlink(missing_ok=True))
        with mock.patch("subprocess.run", fake_run), \
             mock.patch("shutil.which", return_value="/usr/bin/magick"), \
             mock.patch.object(kwin, "_screen_scale", return_value=1.5):
            r = kwin.zoom(self.src, (100, 200, 300, 200), out_path=dst)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["x"], 100)
        self.assertEqual(r["y"], 200)
        self.assertEqual(r["width"], 300)
        self.assertEqual(r["height"], 200)
        self.assertEqual(r["scale"], 1.5)

    def test_wait_for_change_detects_window_change(self):
        uuids = ["win-1", "win-2"]
        with mock.patch.object(kwin, "_active_uuid", side_effect=lambda: uuids.pop(0) if uuids else "win-2"), \
             mock.patch("time.sleep"):
            r = kwin.wait_for_change(timeout=1.0, poll_interval=0.1)
        self.assertTrue(r["ok"])
        self.assertTrue(r["changed"])
        self.assertIn("active window changed", r.get("reason", ""))

    def test_wait_for_change_detects_pixel_change(self):
        call_count = 0
        def fake_screenshot(p, **kwargs):
            nonlocal call_count
            call_count += 1
            Path(p).write_bytes(b"initial" if call_count == 1 else b"updated" + b" " * 100)
            return {"ok": True, "path": str(p)}

        with mock.patch.object(kwin, "_active_uuid", return_value="win-constant"), \
             mock.patch.object(kwin, "screenshot", side_effect=fake_screenshot), \
             mock.patch("time.sleep"):
            r = kwin.wait_for_change(timeout=1.0, poll_interval=0.1)
        self.assertTrue(r["ok"])
        self.assertTrue(r["changed"])
        self.assertIn("screen pixels updated", r.get("reason", ""))


class StampCursorTests(unittest.TestCase):
    def test_stamp_cursor_marker_invokes_magick_draw(self):
        src = support.TMP / "test_stamp_src.png"
        dst = support.TMP / "test_stamp_dst.png"
        src.write_bytes(b"dummy")
        self.addCleanup(lambda: src.unlink(missing_ok=True))
        self.addCleanup(lambda: dst.unlink(missing_ok=True))

        commands = []
        def fake_run(cmd, capture_output=True, text=True, timeout=20):
            commands.append(list(cmd))
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        with mock.patch("subprocess.run", fake_run), \
             mock.patch("shutil.which", return_value="/usr/bin/magick"):
            ok = kwin.stamp_cursor_marker(src, 500, 300, dst)
        self.assertTrue(ok)
        self.assertEqual(len(commands), 1)
        cmd_str = " ".join(commands[0])
        self.assertIn("circle 500,300", cmd_str)
        self.assertIn("line 500,286 500,314", cmd_str)


class ClickElementAndAnnotationTests(unittest.TestCase):
    def setUp(self):
        self._orig_elements = dict(kwin._LAST_ANNOTATED_ELEMENTS)
        kwin._LAST_ANNOTATED_ELEMENTS.clear()

    def tearDown(self):
        kwin._LAST_ANNOTATED_ELEMENTS.clear()
        kwin._LAST_ANNOTATED_ELEMENTS.update(self._orig_elements)

    def test_click_element_with_valid_cached_badge(self):
        kwin._LAST_ANNOTATED_ELEMENTS[1] = {
            "id": 1, "text": "Save", "x": 250, "y": 350, "box": [200, 340, 100, 20]
        }
        with mock.patch.object(kwin, "click", return_value={"ok": True, "measured": {"x": 250, "y": 350}}) as mock_click:
            res = kwin.click_element(1, button="left", clicks=1)
        self.assertTrue(res["ok"])
        self.assertEqual(res["id"], 1)
        self.assertEqual(res["text"], "Save")
        self.assertEqual(res["x"], 250)
        self.assertEqual(res["y"], 350)
        mock_click.assert_called_once_with(250, 350, button="left", clicks=1, modifiers=None)

    def test_click_element_empty_cache_reports_observe_screen_hint(self):
        res = kwin.click_element(1)
        self.assertFalse(res["ok"])
        self.assertIn("observe_screen(annotate=true)", res["error"])

    def test_click_element_missing_id_lists_available_badges(self):
        kwin._LAST_ANNOTATED_ELEMENTS[1] = {"id": 1, "text": "OK", "x": 100, "y": 100}
        kwin._LAST_ANNOTATED_ELEMENTS[2] = {"id": 2, "text": "Cancel", "x": 200, "y": 200}
        res = kwin.click_element(5)
        self.assertFalse(res["ok"])
        self.assertIn("element [5] not found", res["error"])
        self.assertIn("available IDs: [1, 2]", res["error"])

    def test_click_element_invalid_id_type(self):
        res = kwin.click_element("not-a-number")
        self.assertFalse(res["ok"])
        self.assertIn("invalid element id", res["error"])

    def test_annotate_screen_auto_groups_short_lines(self):
        fake_ocr = {
            "ok": True,
            "lines": [
                {"text": "Save Changes", "box": (10, 10, 80, 20), "left": 10, "top": 10, "width": 80, "height": 20},
            ],
            "words": [
                {"text": "Save", "box": (10, 10, 35, 20), "left": 10, "top": 10, "width": 35, "height": 20},
                {"text": "Changes", "box": (50, 10, 40, 20), "left": 50, "top": 10, "width": 40, "height": 20},
            ]
        }
        src = support.TMP / "test_annotate_src.png"
        dst = support.TMP / "test_annotate_dst.png"
        src.write_bytes(b"dummy")
        self.addCleanup(lambda: src.unlink(missing_ok=True))
        self.addCleanup(lambda: dst.unlink(missing_ok=True))

        def fake_run(cmd, capture_output=True, timeout=20):
            return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

        with mock.patch("shutil.which", return_value="/usr/bin/magick"), \
             mock.patch.object(kwin, "ocr_screen", return_value=fake_ocr), \
             mock.patch("subprocess.run", fake_run):
            res = kwin.annotate_screen(src, output_path=dst, mode="auto")

        self.assertTrue(res["ok"])
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["elements"][0]["text"], "Save Changes")

    def test_activate_window_unminimizes_before_activating(self):
        captured_script = []
        def fake_window_action(uuid, script):
            captured_script.append(script)
            return {"ok": True}

        with mock.patch.object(kwin, "_window_action", side_effect=fake_window_action), \
             mock.patch.object(kwin, "_wait_until_active", return_value=True):
            res = kwin.activate_window("test-uuid")

        self.assertTrue(res["ok"])
        self.assertEqual(len(captured_script), 1)
        self.assertIn("target.minimized = false", captured_script[0])

    def test_click_text_forwards_parameters_and_returns_rich_payload(self):
        fake_matches = [
            {"text": "Submit", "x": 120, "y": 240, "box": [100, 230, 40, 20], "confidence": 92.0, "exact": True},
            {"text": "Submit", "x": 120, "y": 480, "box": [100, 470, 40, 20], "confidence": 88.0, "exact": True}
        ]
        with mock.patch.object(kwin, "find_text", return_value={"ok": True, "matches": fake_matches}) as mock_find, \
             mock.patch.object(kwin, "click", return_value={"ok": True, "measured": {"x": 120, "y": 480}}) as mock_click:
            res = kwin.click_text("Submit", button="left", clicks=2, index=1, exact=True, min_confidence=50.0)

        self.assertTrue(res["ok"])
        self.assertEqual(res["index"], 1)
        self.assertEqual(res["matches_found"], 2)
        self.assertEqual(res["target"]["y"], 480)
        mock_find.assert_called_once_with("Submit", region=None, exact=True, min_confidence=50.0)
        mock_click.assert_called_once_with(120, 480, button="left", clicks=2, modifiers=None)

    def test_click_text_index_out_of_bounds_returns_error(self):
        fake_matches = [{"text": "OK", "x": 50, "y": 50}]
        with mock.patch.object(kwin, "find_text", return_value={"ok": True, "matches": fake_matches}):
            res = kwin.click_text("OK", index=5)
        self.assertFalse(res["ok"])
        self.assertIn("requested match index 5 out of range", res["error"])

    def test_key_press_single_modifier_super(self):
        calls = []
        def fake_ydotool(cmd):
            calls.append(list(cmd))
            return {"ok": True}

        with mock.patch.object(kwin, "input_backend", return_value=("ydotool", "ok")), \
             mock.patch.object(kwin, "_ydotool", fake_ydotool):
            res = kwin.key_press("Super")
        self.assertTrue(res["ok"])
        self.assertEqual(len(calls), 1)
        # Logo / Super keycode is 125
        self.assertEqual(calls[0], ["key", "125:1", "125:0"])

    def test_parse_chord_keeps_hyphenated_key_intact_after_a_modifier(self):
        # 'Page-Down' alone always worked (no modifier to trigger '-' as a
        # separator). Combined with a modifier, the old implementation
        # blanket-replaced every '-' with '+' once the chord started with
        # one, splitting 'Page-Down' into 'Page' + 'Down' and keeping only
        # 'Page' — not a real key on its own, and 'Down' silently vanished.
        self.assertEqual(kwin.parse_chord("Page-Down"), ([], "page-down"))
        self.assertEqual(kwin.parse_chord("shift+Page-Down"), (["shift"], "page-down"))
        self.assertEqual(kwin.parse_chord("ctrl-shift-t"), (["ctrl", "shift"], "t"))
        self.assertEqual(kwin.parse_chord("ctrl-shift+Page-Up"), (["ctrl", "shift"], "page-up"))

    def test_key_press_modifier_plus_hyphenated_key_resolves(self):
        calls = []
        def fake_ydotool(cmd):
            calls.append(list(cmd))
            return {"ok": True}

        with mock.patch.object(kwin, "input_backend", return_value=("ydotool", "ok")), \
             mock.patch.object(kwin, "_ydotool", fake_ydotool):
            res = kwin.key_press("shift+Page-Down")
        self.assertTrue(res["ok"], res)
        # shift=42, PageDown=109
        self.assertEqual(calls[0], ["key", "42:1", "109:1", "109:0", "42:0"])

    def test_annotate_screen_empty_candidates_returns_cleanly(self):
        fake_ocr = {"ok": True, "lines": [], "words": []}
        src = support.TMP / "test_empty_src.png"
        src.write_bytes(b"dummy")
        self.addCleanup(lambda: src.unlink(missing_ok=True))

        with mock.patch("shutil.which", return_value="/usr/bin/magick"), \
             mock.patch.object(kwin, "ocr_screen", return_value=fake_ocr), \
             mock.patch("subprocess.run") as mock_run:
            res = kwin.annotate_screen(src)
        self.assertTrue(res["ok"])
        self.assertEqual(res["count"], 0)
        self.assertEqual(res["elements"], [])
        mock_run.assert_not_called()


class OcrRegionOffsetTests(unittest.TestCase):
    """ocr_screen(region=...) with no explicit image_path takes a fresh
    screenshot that screenshot() itself crops to `region` on disk — so
    tesseract only ever sees the cropped sub-image, and its own (0,0) is the
    region's corner, not the screen's. find_text/click_text then hand those
    coordinates straight to click(), which expects full-screen coordinates —
    so getting this offset wrong doesn't error, it just clicks the wrong
    spot while reporting success."""

    TSV = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t15\t25\t40\t12\t92.5\tHello\n")

    def _run(self, region, region_applied):
        with mock.patch("shutil.which", return_value="/usr/bin/tesseract"), \
             mock.patch.object(kwin, "screenshot",
                               return_value={"ok": True, "path": "/tmp/x.png",
                                             "region_applied": region_applied}), \
             mock.patch("subprocess.run",
                        return_value=subprocess.CompletedProcess([], 0, stdout=self.TSV, stderr="")), \
             mock.patch.object(Path, "unlink", return_value=None):
            return kwin.ocr_screen(region=region, min_confidence=0)

    def test_offset_added_when_region_crop_actually_applied(self):
        res = self._run(region=(100, 200, 300, 300), region_applied=True)
        self.assertTrue(res["ok"])
        w = res["words"][0]
        self.assertEqual((w["left"], w["top"]), (115, 225))

    def test_no_offset_when_region_crop_failed_and_fell_back_to_full_screen(self):
        # screenshot() reports region_applied=False when e.g. ImageMagick is
        # missing — the file on disk is then the uncropped full screen, so
        # tesseract's own (0,0) already IS the screen's (0,0); adding the
        # region's offset here would double-count it and misplace every
        # match by (region_x, region_y) instead of fixing anything.
        res = self._run(region=(100, 200, 300, 300), region_applied=False)
        self.assertTrue(res["ok"])
        w = res["words"][0]
        self.assertEqual((w["left"], w["top"]), (15, 25))

    def test_no_offset_without_a_region(self):
        res = self._run(region=None, region_applied=False)
        self.assertTrue(res["ok"])
        w = res["words"][0]
        self.assertEqual((w["left"], w["top"]), (15, 25))


if __name__ == "__main__":
    unittest.main()
