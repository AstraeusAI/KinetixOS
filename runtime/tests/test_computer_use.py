"""Comprehensive unit tests for the upgraded Computer Use Engine.

Covers:
- desktop_actions batch tool (action dispatch, stop_on_error, capture_after,
  focus guard)
- zoom_region tool & lossless 1:1 image payload preservation
- mouse_hover tool
- wait_for_screen_change tool
- directional scroll tool
- observe_screen stamp_cursor integration
- SYSTEM_PROMPT desktop playbook integration
"""
import json
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401

import argusd
from lib import kwin, tools


class DummyContext:
    def __init__(self, data_dir, grants=None):
        self.data_dir = Path(data_dir)
        self.grants = grants if grants is not None else {"input": True, "screen": True}
        self.db = None
        self.session = "test-comp-use"
        self.workspace = None
        self.policy = None
        self.checkpoints = None
        self.todos = []
        self.mcp_clients = {}


class ComputerUseToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = support.TMP / "comp_use_tests"
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.ctx = DummyContext(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_desktop_actions_dispatches_full_batch_sequence(self):
        calls = []

        def fake_click(x, y, button="left", clicks=1, modifiers=None):
            calls.append(("click", x, y, button, clicks, modifiers))
            return {"ok": True, "x": x, "y": y}

        def fake_move(x, y):
            calls.append(("move", x, y))
            return {"ok": True, "x": x, "y": y}

        def fake_hover(x, y, duration=0.4):
            calls.append(("hover", x, y, duration))
            return {"ok": True, "x": x, "y": y, "hovered_seconds": duration}

        def fake_drag(x1, y1, x2, y2, button="left", steps=1, smooth=True):
            calls.append(("drag", x1, y1, x2, y2, button, steps, smooth))
            return {"ok": True, "start": [x1, y1], "end": [x2, y2]}

        def fake_type(text, clear_before=False):
            calls.append(("type", text, clear_before))
            return {"ok": True, "typed": text}

        def fake_key(key):
            calls.append(("key", key))
            return {"ok": True, "key": key}

        def fake_scroll(amt, x=None, y=None, direction="down"):
            calls.append(("scroll", amt, x, y, direction))
            return {"ok": True}

        def fake_screenshot(p, mode="fullscreen", stamp_cursor=False, **kwargs):
            Path(p).write_bytes(b"fake-png-data")
            return {"ok": True, "path": str(p), "width": 1920, "heigh"
                "t": 1080, "scale": 1.0}

        with mock.patch.object(kwin, "click", fake_click), \
             mock.patch.object(kwin, "move_pointer", fake_move), \
             mock.patch.object(kwin, "hover", fake_hover), \
             mock.patch.object(kwin, "drag", fake_drag), \
             mock.patch.object(kwin, "type_text", fake_type), \
             mock.patch.object(kwin, "key_press", fake_key), \
             mock.patch.object(kwin, "scroll", fake_scroll), \
             mock.patch.object(kwin, "screenshot", fake_screenshot), \
             mock.patch("time.sleep"):

            actions = [
                {"action": "click", "x": 100, "y": 200, "button": "left"},
                {"action": "type", "text": "hello", "paste": False},
                {"action": "key", "key": "Return"},
                {"action": "hover", "x": 300, "y": 400, "duration": 0.3},
                {"action": "scroll", "amount": 5, "direction": "down"},
                {"action": "drag", "start_"
                    "x": 10, "start_y": 10, "end_x": 50, "end_y": 50},
                {"action": "wait", "duration": 0.1},
            ]
            r = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "actions": actions,
                "capture_after": True,
                "stamp_cursor": True
            })

        self.assertTrue(r["ok"], r)
        self.assertEqual(r["executed"], 7)
        self.assertEqual(r["total"], 7)
        self.assertIn("screenshot_path", r)
        self.assertEqual(len(calls), 6)  # wait doesn't call a kwin function
        self.assertEqual(calls[0], ("click", 100, 200, "left", 1, None))
        self.assertEqual(calls[1], ("type", "hello", False))
        self.assertEqual(calls[2], ("key", "Return"))
        self.assertEqual(calls[3], ("hover", 300, 400, 0.3))
        self.assertEqual(calls[4], ("scroll", 5, None, None, "down"))
        self.assertEqual(calls[5], ("drag", 10, 10, 50, 50, "left", 1, True))

    def test_desktop_actions_stop_on_error(self):
        def fake_click(x, y, **kwargs):
            return {"ok": False, "error": "target offscreen"}

        with mock.patch.object(kwin, "click", fake_click), \
             mock.patch.object(kwin, "screenshot", return_value={"ok": True}):
            actions = [
                {"action": "click", "x": 9999, "y": 9999},
                {"action": "type", "text": "should not execute"}
            ]
            r = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "actions": actions,
                "stop_on_error": True,
                "capture_after": False
            })

        self.assertFalse(r["ok"])
        self.assertEqual(r["executed"], 1)
        self.assertEqual(r["total"], 2)

    def test_desktop_actions_requires_input_grant(self):
        ctx_no_grant = DummyContext(self.tmp, grants={"input": False, "screen": True})
        r = tools.REGISTRY["desktop_actions"]["handler"](
            ctx_no_grant, {"actions": [{"action": "key", "key": "Return"}]}
        )
        self.assertFalse(r["ok"])
        self.assertIn("input grant disabled", r["error"])

    def test_zoom_region_tool_captures_uncompressed_crop(self):
        def fake_zoom(p, region):
            return {
                "ok": True,
                "path": str(p),
                "x": region[0], "y": region[1],
                "width": region[2], "height": region[3],
                "scale": 1.5
            }

        with mock.patch.object(kwin, "zoom", fake_zoom):
            r = tools.REGISTRY["zoom_region"]["handler"](self.ctx, {
                "x": 200, "y": 150, "width": 400, "height": 300
            })
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["x"], 200)
        self.assertEqual(r["width"], 400)
        self.assertIn("zoom-", r["path"])

    def test_mouse_hover_tool_delegates_to_kwin_hover(self):
        with mock.patch.object(
            kwin,
            "hover",
            return_value={"ok": True, "x": 100, "y": 200, "hovered_seconds": 0.4},
        ):
            r = tools.REGISTRY["mouse_hove"
                "r"]["handler"](self.ctx, {"x": 100, "y": 200, "duration": 0.4})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["hovered_seconds"], 0.4)

    def test_wait_for_screen_change_tool(self):
        with mock.patch.object(
            kwin,
            "wait_for_change",
            return_value={
                "ok": True,
                "changed": True,
                "reason": "screen pixels updated",
            },
        ):
            r = tools.REGISTRY["wait_for_screen_chang"
                "e"]["handler"](self.ctx, {"timeout": 2.0})
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["changed"])

    def test_mouse_down_and_up_tools(self):
        with (
            mock.patch.object(
                kwin,
                "mouse_down",
                return_value={"ok": True, "button": "left", "x": 100, "y": 100},
            ) as m_down,
            mock.patch.object(
                kwin,
                "mouse_up",
                return_value={"ok": True, "button": "left", "x": 100, "y": 100},
            ) as m_up,
        ):
            r1 = tools.REGISTRY["mouse_dow"
                "n"]["handler"](self.ctx, {"button": "left", "x": 100, "y": 100})
            r2 = tools.REGISTRY["mouse_u"
                "p"]["handler"](self.ctx, {"button": "left", "x": 100, "y": 100})
        self.assertTrue(r1["ok"])
        self.assertTrue(r2["ok"])
        m_down.assert_called_once_with(button="left", x=100, y=100)
        m_up.assert_called_once_with(button="left", x=100, y=100)

    def test_key_down_and_up_tools(self):
        with (
            mock.patch.object(
                kwin, "key_down", return_value={"ok": True, "key": "ctrl"}
            ) as k_down,
            mock.patch.object(
                kwin, "key_up", return_value={"ok": True, "key": "ctrl"}
            ) as k_up,
        ):
            r1 = tools.REGISTRY["key_down"]["handler"](self.ctx, {"key": "ctrl"})
            r2 = tools.REGISTRY["key_up"]["handler"](self.ctx, {"key": "ctrl"})
        self.assertTrue(r1["ok"])
        self.assertTrue(r2["ok"])
        k_down.assert_called_once_with("ctrl")
        k_up.assert_called_once_with("ctrl")

    def test_desktop_actions_aliases_and_new_actions(self):
        calls = []

        def fake_click(x, y, button="left", clicks=1, modifiers=None):
            calls.append(("click", x, y, button, clicks))
            return {"ok": True, "x": x, "y": y}

        def fake_key(k):
            calls.append(("key", k))
            return {"ok": True, "key": k}

        def fake_m_down(button="left", x=None, y=None):
            calls.append(("mouse_down", button, x, y))
            return {"ok": True}

        def fake_m_up(button="left", x=None, y=None):
            calls.append(("mouse_up", button, x, y))
            return {"ok": True}

        def fake_k_down(k):
            calls.append(("key_down", k))
            return {"ok": True}

        def fake_k_up(k):
            calls.append(("key_up", k))
            return {"ok": True}

        with mock.patch.object(kwin, "click", fake_click), \
             mock.patch.object(kwin, "key_press", fake_key), \
             mock.patch.object(kwin, "mouse_down", fake_m_down), \
             mock.patch.object(kwin, "mouse_up", fake_m_up), \
             mock.patch.object(kwin, "key_down", fake_k_down), \
             mock.patch.object(kwin, "key_up", fake_k_up):

            actions = [
                {"action": "double_click", "x": 10, "y": 20},
                {"action": "triple_click", "x": 30, "y": 40},
                {"action": "right_click", "x": 50, "y": 60},
                {"action": "middle_click", "x": 70, "y": 80},
                {"action": "hotkey", "key": "ctrl+c"},
                {"action": "mouse_down", "button": "left", "x": 100, "y": 100},
                {"action": "mouse_up", "button": "left", "x": 200, "y": 200},
                {"action": "key_down", "key": "shift"},
                {"action": "key_up", "key": "shift"},
            ]
            r = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "actions": actions,
                "capture_after": False
            })

        self.assertTrue(r["ok"], r)
        self.assertEqual(len(calls), 9)
        self.assertEqual(calls[0], ("click", 10, 20, "left", 2))
        self.assertEqual(calls[1], ("click", 30, 40, "left", 3))
        self.assertEqual(calls[2], ("click", 50, 60, "right", 1))
        self.assertEqual(calls[3], ("click", 70, 80, "middle", 1))
        self.assertEqual(calls[4], ("key", "ctrl+c"))
        self.assertEqual(calls[5], ("mouse_down", "left", 100, 100))
        self.assertEqual(calls[6], ("mouse_up", "left", 200, 200))
        self.assertEqual(calls[7], ("key_down", "shift"))
        self.assertEqual(calls[8], ("key_up", "shift"))

    def test_desktop_actions_window_relative_targeting(self):
        def fake_win_trans(rel, rx, ry):
            if rel == "target_win":
                return {"ok": True, "x": 500 + int(rx), "y": 300 + int(ry)}
            return {"ok": False, "error": f"window not found: {rel}"}

        called = []
        def fake_click(x, y, **kwargs):
            called.append((x, y))
            return {"ok": True, "x": x, "y": y}

        with mock.patch.object(kwin, "window_to_screen_px", fake_win_trans), \
             mock.patch.object(kwin, "click", fake_click):

            r = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "relative_to": "target_win",
                "actions": [
                    {"action": "click", "x": 50, "y": 60}
                ],
                "capture_after": False
            })

        self.assertTrue(r["ok"], r)
        self.assertEqual(called, [(550, 360)])

    def test_observe_screen_with_grid(self):
        def fake_screenshot(p, mode="fullscreen", grid=False, grid_step=100, **kwargs):
            Path(p).write_bytes(b"grid-shot")
            return {"ok": True, "path": str(p), "grid": grid, "grid_step": grid_step,
                    "width": 1920, "height": 1080, "scale": 1.0}

        with mock.patch.object(kwin, "screenshot", fake_screenshot):
            r = tools.REGISTRY["observe_scree"
                "n"]["handler"](self.ctx, {"grid": True, "grid_step": 150})
        self.assertTrue(r["ok"], r)
        self.assertTrue(r.get("grid"))
        self.assertEqual(r.get("grid_step"), 150)

    def test_list_windows_filtering(self):
        fake_list = {
            "ok": True,
            "windows": [
                {
                    "uuid": "1", "caption": "Terminal - bash", "cls": "kitty",
                    "pid": 100, "x": 0, "y": 0, "w": 800, "h": 600,
                    "active": True, "minimized": False, "fullscreen": False,
                },
                {
                    "uuid": "2", "caption": "Mozilla Firefox", "cls": "firefox",
                    "pid": 200, "x": 100, "y": 100, "w": 1200, "h": 900,
                    "active": False, "minimized": False, "fullscreen": False,
                },
            ]
        }
        with mock.patch.object(kwin, "available", return_value=True), \
             mock.patch.object(kwin, "list_windows", return_value=fake_list):
            r = tools.REGISTRY["list_windows"]["handler"](self.ctx, {"filter": "term"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["windows"][0]["cls"], "kitty")

    def test_type_text_clear_before_and_unicode_paste(self):
        calls = []
        def fake_key(k):
            calls.append(("key", k))
            return {"ok": True}

        def fake_type(text, clear_before=False):
            calls.append(("type", text, clear_before))
            return {"ok": True, "typed": text}

        def fake_clip_set(t):
            calls.append(("clip_set", t))
            return {"ok": True}

        with mock.patch.object(kwin, "key_press", fake_key), \
             mock.patch.object(kwin, "type_text", fake_type), \
             mock.patch.object(kwin, "clipboard_set", fake_clip_set), \
             mock.patch("time.sleep"):

            # Test clear_before with standard text (paste=False)
            r1 = tools.REGISTRY["type_text"]["handler"](self.ctx, {"text": "hello", "cl"
                "ear_before": True, "paste": False})
            self.assertTrue(r1["ok"])

            # Test Unicode text automatically triggering clipboard paste
            calls.clear()
            r2 = tools.REGISTRY["type_text"]["handler"](
                self.ctx, {"text": "Hello 世界 🚀", "clear_before": True}
            )
            self.assertTrue(r2["ok"])
            self.assertTrue(r2.get("pasted"))
            self.assertIn(("clip_set", "Hello 世界 🚀"), calls)
            self.assertIn(("key", "ctrl+v"), calls)

    def test_kwin_window_to_screen_px_logic(self):
        fake_win = {
            "ok": True,
            "window": {
                "uuid": "win-123", "caption": "Editor", "cls": "code",
                "x": 100, "y": 200, "w": 1000, "h": 800,
            }
        }
        with mock.patch.object(kwin, "active_window", return_value=fake_win):
            # Test pixel offset
            res_px = kwin.window_to_screen_px("active", 50, 75)
            self.assertTrue(res_px["ok"])
            self.assertEqual(res_px["x"], 150)
            self.assertEqual(res_px["y"], 275)

            res_ratio = kwin.window_to_screen_px("active", 0.5, 0.5)
            self.assertTrue(res_ratio["ok"])
            self.assertEqual(res_ratio["x"], 100 + 500)
            self.assertEqual(res_ratio["y"], 200 + 400)

    def test_find_text_tool(self):
        # Grant check
        no_grant_ctx = DummyContext(self.tmp, grants={"screen": False})
        r_nogrant = tools.REGISTRY["find_tex"
            "t"]["handler"](no_grant_ctx, {"query": "Save"})
        self.assertFalse(r_nogrant["ok"])
        self.assertEqual(r_nogrant["error"], "screen grant disabled")

        fake_res = {
            "ok": True,
            "count": 1,
            "matches": [
                {
                    "text": "Save", "x": 100, "y": 200, "w": 50, "h": 20,
                    "center": [125, 210], "confidence": 95.0,
                },
            ]
        }
        with mock.patch.object(kwin, "find_text", return_value=fake_res) as mock_find:
            r = tools.REGISTRY["find_text"]["handler"](
                self.ctx, {"query": "Save", "exact": True, "min_confidence": 80.0}
            )
            self.assertTrue(r["ok"])
            self.assertEqual(r["count"], 1)
            mock_find.assert_called_once_with(query="Sav"
                "e", region=None, exact=True, min_confidence=80.0)

    def test_click_text_tool(self):
        # Grant check
        no_grant_ctx = DummyContext(self.tmp, grants={"input": False})
        r_nogrant = tools.REGISTRY["click_tex"
            "t"]["handler"](no_grant_ctx, {"text": "Save"})
        self.assertFalse(r_nogrant["ok"])
        self.assertEqual(r_nogrant["error"], "input grant disabled")

        fake_res = {"ok": True, "matche"
            "d": "Save", "x": 125, "y": 210, "clicks": 1, "button": "left"}
        with mock.patch.object(kwin, "click_text", return_value=fake_res) as mock_click:
            r = tools.REGISTRY["click_text"]["handler"](
                self.ctx, {"text": "Save", "clicks": 1, "button": "left"}
            )
            self.assertTrue(r["ok"])
            self.assertEqual(r["matched"], "Save")
            mock_click.assert_called_once_with(
                query="Save", clicks=1, button="left", modifiers=None,
                region=None, exact=False, min_confidence=40.0, index=0,
            )

        with mock.patch.object(kwin, "click_tex"
            "t", return_value=fake_res) as mock_click_idx:
            r2 = tools.REGISTRY["click_tex"
                "t"]["handler"](self.ctx, {"text": "Save", "index": 2})
            self.assertTrue(r2["ok"])
            mock_click_idx.assert_called_once_with(
                query="Save", clicks=1, button="left", modifiers=None,
                region=None, exact=False, min_confidence=40.0, index=2,
            )

    def test_click_element_tool(self):
        # Grant check
        no_grant_ctx = DummyContext(self.tmp, grants={"input": False})
        r_nogrant = tools.REGISTRY["click_element"]["handler"](no_grant_ctx, {"id": 1})
        self.assertFalse(r_nogrant["ok"])
        self.assertEqual(r_nogrant["error"], "input grant disabled")

        fake_res = {"ok": True, "id": 1, "x": 100, "y": 150, "elemen"
            "t": {"id": 1, "text": "Submit"}}
        with mock.patch.object(kwin, "click_elemen"
            "t", return_value=fake_res) as mock_click:
            r = tools.REGISTRY["click_elemen"
                "t"]["handler"](self.ctx, {"id": 1, "button": "right", "clicks": 2})
            self.assertTrue(r["ok"])
            self.assertEqual(r["id"], 1)
            mock_click.assert_called_once_with(
                element_id=1, button="right", clicks=2, modifiers=None
            )

    def test_desktop_actions_dispatches_click_element_and_gesture_relative(self):
        def fake_click_element(element_id, button="left", clicks=1, modifiers=None):
            return {"ok": True, "id": element_id, "x": 50, "y": 60, "elemen"
                "t": {"id": element_id, "text": "OK"}}

        def fake_drag_path(points, button="left", duration=0.5, smooth=True):
            return {"ok": True, "points": points, "button": button}

        def fake_win_trans(ident, x, y):
            return {"ok": True, "x": int(x + 100), "y": int(y + 200)}

        with mock.patch.object(kwin, "click_element", fake_click_element), \
             mock.patch.object(kwin, "drag_path", fake_drag_path), \
             mock.patch.object(kwin, "window_to_screen_px", fake_win_trans):
            actions = [
                {"action": "click_element", "id": 4, "button": "left"},
                {"action": "gesture", "points": [[10, 20], [30, 40]], "relative_to": "a"
                    "ctive_window"}
            ]
            r = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "actions": actions,
                "capture_after": False
            })

        self.assertTrue(r["ok"])
        self.assertEqual(r["executed"], 2)
        res1 = r["results"][0]
        self.assertEqual(res1["action"], "click_element")
        self.assertEqual(res1["id"], 4)

        res2 = r["results"][1]
        self.assertEqual(res2["action"], "gesture")
        # Points were translated by [100, 200]: (10+100, 20+200) -> [110, 220]
        self.assertEqual(res2["points"], [[110, 220], [130, 240]])

    def test_desktop_actions_move_window_and_clipboard_and_wait_change(self):
        calls = []
        def fake_move_win(uuid, x, y, w=None, h=None):
            calls.append(("move_window", uuid, x, y, w, h))
            return {"ok": True}

        def fake_clip_set(text):
            calls.append(("clipboard_set", text))
            return {"ok": True}

        def fake_clip_get():
            calls.append(("clipboard_get",))
            return {"ok": True, "text": "copied-value"}

        def fake_wait_change(timeout=2.0, region=None):
            calls.append(("wait_for_change", timeout, region))
            return {"ok": True, "changed": True, "reason": "window activated"}

        with mock.patch.object(kwin, "move_window", fake_move_win), \
             mock.patch.object(kwin, "clipboard_set", fake_clip_set), \
             mock.patch.object(kwin, "clipboard_get", fake_clip_get), \
             mock.patch.object(kwin, "wait_for_change", fake_wait_change):
            actions = [
                {
                    "action": "move_window", "uuid": "win-123",
                    "x": 50, "y": 100, "width": 800, "height": 600,
                },
                {"action": "clipboard_copy", "text": "sample text"},
                {"action": "clipboard_paste"},
                {"action": "wait_for_chang"
                    "e", "timeout": 1.5, "region": [10, 10, 200, 200]},
            ]
            r = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "actions": actions,
                "capture_after": False
            })

        self.assertTrue(r["ok"])
        self.assertEqual(r["executed"], 4)
        self.assertEqual(calls[0], ("move_window", "win-123", 50, 100, 800, 600))
        self.assertEqual(calls[1], ("clipboard_set", "sample text"))
        self.assertEqual(calls[2], ("clipboard_get",))
        self.assertEqual(calls[3], ("wait_for_change", 1.5, [10, 10, 200, 200]))

    def test_desktop_actions_move_window_resolves_relative_to_translated_coords(
        self,
    ):
        # No 'uuid'/'id' — only 'relative_to'. This used to be passed straight
        # to kwin.move_window as a literal uuid (kwin.move_window("active", ...)),
        # which always failed with "window not found: active" since the KWin
        # script only matches an exact internalId. It should resolve to the
        # real window first, the same way window-relative coordinates do.
        active_win = {"uuid": "win-active-1", "caption": "Kate", "cls": "kate",
                      "x": 100, "y": 200, "w": 400, "h": 300}
        calls = []

        def fake_move_win(uuid, x, y, w=None, h=None):
            calls.append((uuid, x, y, w, h))
            return {"ok": True}

        with (
            mock.patch.object(
                kwin, "active_window", return_value={"ok": True, "window": active_win}
            ),
            mock.patch.object(kwin, "move_window", fake_move_win),
        ):
            actions = [{"action": "move_windo"
                "w", "relative_to": "active", "x": 20, "y": 30}]
            r = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "actions": actions, "capture_after": False})

        self.assertTrue(r["ok"], r)
        # x/y must be the window-relative-translated absolute coordinates
        # (window origin + offset), not the raw 20/30 passed in, and the
        # resolved uuid must be the active window's real uuid, not "active".
        self.assertEqual(calls, [("win-active-1", 120, 230, None, None)])

    def test_desktop_actions_move_window_unresolvable_relative_to_errors(self):
        # x/y omitted on purpose: with them present, the shared relative_to
        # coordinate translation that runs for every action type fails first
        # (a different, already-correct error path) — this isolates the
        # move_window/resize_window branch's own wid-resolution fallback.
        with mock.patch.object(kwin, "list_window"
            "s", return_value={"ok": True, "windows": []}):
            actions = [{"action": "move_window", "relative_to": "no-such-window"}]
            r = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "actions": actions, "capture_after": False})
        self.assertFalse(r["ok"])
        self.assertIn("relative_to", r["results"][0]["error"])

        # With x/y present, the earlier shared translation catches the same
        # unresolvable identifier and reports it just as clearly.
        with mock.patch.object(kwin, "list_window"
            "s", return_value={"ok": True, "windows": []}):
            actions = [{"action": "move_window", "relative_to": "no-such-windo"
                "w", "x": 0, "y": 0}]
            r2 = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "actions": actions, "capture_after": False})
        self.assertFalse(r2["ok"])
        self.assertIn("no-such-window", r2["results"][0]["error"])

    def test_list_displays_tool(self):
        no_grant_ctx = DummyContext(self.tmp, grants={"screen": False})
        r_nogrant = tools.REGISTRY["list_displays"]["handler"](no_grant_ctx, {})
        self.assertFalse(r_nogrant["ok"])
        self.assertEqual(r_nogrant["error"], "screen grant disabled")

        fake_info = {
            "ok": True,
            "displays": [
                {"name": "DP-1", "primary": True, "width": 3840, "height": 2160},
            ],
            "count": 1,
            "current_size": [3840, 2160]
        }
        with mock.patch.object(kwin, "display_info", return_value=fake_info):
            r = tools.REGISTRY["list_displays"]["handler"](self.ctx, {})
            self.assertTrue(r["ok"])
            self.assertEqual(r["count"], 1)
            self.assertEqual(r["displays"][0]["name"], "DP-1")

    def test_mouse_gesture_tool(self):
        no_grant_ctx = DummyContext(self.tmp, grants={"input": False})
        r_nogrant = tools.REGISTRY["mouse_gestur"
            "e"]["handler"](no_grant_ctx, {"points": [[0, 0], [10, 10]]})
        self.assertFalse(r_nogrant["ok"])
        self.assertEqual(r_nogrant["error"], "input grant disabled")

        fake_res = {"ok": True, "button": "left", "points_coun"
            "t": 3, "start": [10, 10], "end": [100, 100]}
        with mock.patch.object(kwin, "drag_pat"
            "h", return_value=fake_res) as mock_drag_path:
            pts = [[10, 10], [50, 50], [100, 100]]
            r = tools.REGISTRY["mouse_gestur"
                "e"]["handler"](self.ctx, {"points": pts, "duration": 0.3})
            self.assertTrue(r["ok"])
            self.assertEqual(r["points_count"], 3)
            mock_drag_path.assert_called_once_with(points=pts, button="lef"
                "t", duration=0.3, smooth=True)

    def test_assert_region_changed_tool(self):
        no_grant_ctx = DummyContext(self.tmp, grants={"screen": False})
        r_nogrant = tools.REGISTRY["assert_region_change"
            "d"]["handler"](no_grant_ctx, {"before_path": "/tmp/nonexistent.png"})
        self.assertFalse(r_nogrant["ok"])
        self.assertEqual(r_nogrant["error"], "screen grant disabled")

        # Missing file error
        r_missing = tools.REGISTRY["assert_region_changed"]["handler"](
            self.ctx, {"before_path": str(self.tmp / "nonexistent.png")}
        )
        self.assertFalse(r_missing["ok"])
        self.assertIn("not found", r_missing["error"])

        # Successful comparison
        before_file = self.tmp / "before.png"
        before_file.write_bytes(b"dummy")

        fake_shot = {"ok": True, "path": str(self.tmp / "after.png")}
        fake_compare = {
            "ok": True,
            "diff_pixels": 250,
            "total_pixels": 10000,
            "diff_ratio": 0.025,
            "diff_image_path": str(self.tmp / "diff.png")
        }
        with mock.patch.object(kwin, "screenshot", return_value=fake_shot), \
             mock.patch.object(kwin, "compare_regions", return_value=fake_compare), \
             mock.patch("time.sleep"):
            r = tools.REGISTRY["assert_region_changed"]["handler"](self.ctx, {
                "before_path": str(before_file),
                "threshold_ratio": 0.01
            })
            self.assertTrue(r["ok"])
            self.assertTrue(r["changed"])
            self.assertEqual(r["diff_ratio"], 0.025)
            self.assertEqual(r["diff_pixels"], 250)

    def test_focus_or_launch_tool(self):
        no_grant_ctx = DummyContext(self.tmp, grants={"input": False})
        r_nogrant = tools.REGISTRY["focus_or_launc"
            "h"]["handler"](no_grant_ctx, {"app_name": "dolphin"})
        self.assertFalse(r_nogrant["ok"])
        self.assertEqual(r_nogrant["error"], "input grant disabled")

        fake_res = {
            "ok": True,
            "action": "focused_existing",
            "window": {"uuid": "win-dolphin-1", "caption": "Dolphin", "cls": "dolphin"}
        }
        with mock.patch.object(kwin, "focus_or_launc"
            "h", return_value=fake_res) as mock_fol:
            r = tools.REGISTRY["focus_or_launch"]["handler"](
                self.ctx, {"app_name": "dolphin", "command": "dolphin ~"}
            )
            self.assertTrue(r["ok"])
            self.assertEqual(r["action"], "focused_existing")
            mock_fol.assert_called_once_with(
                app_name="dolphin", timeout=6.0, command="dolphin ~"
            )

    def test_focus_or_launch_resolves_command_from_desktop_entry_by_default(self):
        # No 'command' given, and the app's real id ('com.discordapp.Discord')
        # is nothing like the friendly name a caller would type ('discord').
        # kwin.focus_or_launch's own fallback only ever tries app_name as a
        # literal PATH executable or an exact gtk-launch id — neither finds a
        # Flatpak-style id — so this must resolve it the same fuzzy way
        # launch_app does and hand kwin.focus_or_launch a real command.
        entry = {"name": "Discord", "id": "com.discordapp.Discord", "file": "/x",
                 "exec": "discord %U", "terminal": False, "comment": ""}
        with mock.patch.object(tools, "_desktop_entries", return_value=[entry]), \
             mock.patch.object(kwin, "focus_or_launch",
                               return_value={"ok": True, "action": "launched_and_focuse"
                                   "d",
                                            "window": {"uuid": "w1"}}) as mock_fol:
            r = tools.REGISTRY["focus_or_launc"
                "h"]["handler"](self.ctx, {"app_name": "discord"})
        self.assertTrue(r["ok"])
        mock_fol.assert_called_once_with(app_name="discor"
            "d", timeout=6.0, command="discord")

    def test_focus_or_launch_falls_back_to_none_when_no_desktop_entry_matches(self):
        # A plain CLI tool with no .desktop file at all must still reach
        # kwin.focus_or_launch's own PATH-based fallback unchanged (command=None),
        # not an empty string that would short-circuit differently.
        with mock.patch.object(tools, "_desktop_entries", return_value=[]), \
             mock.patch.object(kwin, "focus_or_launch",
                               return_value={"ok": True, "action": "launched_and_focuse"
                                   "d",
                                            "window": {"uuid": "w1"}}) as mock_fol:
            tools.REGISTRY["focus_or_launch"]["handler"](self.ctx, {"app_name": "htop"})
        mock_fol.assert_called_once_with(app_name="htop", timeout=6.0, command=None)

    def test_desktop_actions_focus_or_launch_resolves_command_from_desktop_entry(self):
        entry = {"name": "Discord", "id": "com.discordapp.Discord", "file": "/x",
                 "exec": "discord %U", "terminal": False, "comment": ""}
        with mock.patch.object(tools, "_desktop_entries", return_value=[entry]), \
             mock.patch.object(kwin, "focus_or_launch",
                               return_value={"ok": True, "windo"
                                   "w": {"uuid": "w1"}}) as mock_fol:
            actions = [{"action": "focus_or_launch", "app_name": "discord"}]
            r = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "actions": actions, "capture_after": False})
        self.assertTrue(r["ok"], r)
        mock_fol.assert_called_once_with("discord", timeout=6.0, command="discord")

    def test_list_apps_matches_name_id_or_comment(self):
        fake_entries = [
            {"name": "Kate", "id": "org.kde.kate", "file": "/x", "exec": "kate %U",
             "terminal": False, "comment": "Advanced Text Editor"},
            {"name": "Dolphin", "id": "org.kde.dolphi"
                "n", "file": "/y", "exec": "dolphin %U",
             "terminal": False, "comment": "File Manager"},
        ]
        with mock.patch.object(tools, "_desktop_entries", return_value=fake_entries):
            # Matches on name/id even with no query change from before...
            r_all = tools.REGISTRY["list_apps"]["handler"](self.ctx, {})
            self.assertEqual(r_all["count"], 2)
            # ...but now also on the .desktop entry's Comment=, so a query
            # that doesn't appear in any app's name still finds the right one.
            r = tools.REGISTRY["list_apps"]["handler"](self.ctx, {"query": "text "
                "editor"})
            self.assertEqual(r["count"], 1)
            self.assertEqual(r["apps"][0]["id"], "org.kde.kate")
            self.assertEqual(r["apps"][0]["comment"], "Advanced Text Editor")

    def test_launch_app_resolves_flatpak_style_id_by_fuzzy_name(self):
        entry = {"name": "Discord", "id": "com.discordapp.Discor"
            "d", "file": "/x/discord.desktop",
                 "exec": "discord %U", "terminal": False, "comment": ""}
        fake_window = {"uuid": "w1", "cls": "discord", "caption": "Discord"}
        with mock.patch.object(tools, "_desktop_entries", return_value=[entry]), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch.object(kwin, "list_window"
                 "s", return_value={"ok": True, "windows": [fake_window]}):
            r = tools.REGISTRY["launch_app"]["handler"](self.ctx, {"name": "discord"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["id"], "com.discordapp.Discord")
        self.assertEqual(r["via"], "exec")
        mock_popen.assert_called_once()
        self.assertEqual(mock_popen.call_args[0][0], ["setsid", "-f", "sh", "-c", "disc"
            "ord"])

    def test_launch_app_no_match_reports_hint(self):
        with mock.patch.object(tools, "_desktop_entries", return_value=[]):
            r = tools.REGISTRY["launch_app"]["handler"](self.ctx, {"name": "nonexistent"
                "-app-xyz"})
        self.assertFalse(r["ok"])
        self.assertIn("hint", r)

    def test_desktop_actions_dispatches_new_actions(self):
        actions = [
            {"action": "click_text", "text": "OK", "button": "left"},
            {"action": "gesture", "points": [[10, 10], [50, 50], [100, 100]], "duratio"
                "n": 0.2},
            {"action": "focus_or_launch", "app_name": "dolphin"},
        ]
        fake_click_t = {"ok": True, "matched": "OK", "x": 100, "y": 100}
        fake_gesture = {"ok": True, "points_count": 3}
        fake_fol = {"ok": True, "action": "focused_existing", "window": {"uuid": "w1"}}
        fake_shot = {"ok": True, "path": "/tmp/shot.png"}

        with (
            mock.patch.object(kwin, "click_text", return_value=fake_click_t) as m_ct,
            mock.patch.object(kwin, "drag_path", return_value=fake_gesture) as m_dp,
            mock.patch.object(kwin, "focus_or_launch", return_value=fake_fol) as m_fol,
            mock.patch.object(kwin, "screenshot", return_value=fake_shot),
        ):
            r = tools.REGISTRY["desktop_action"
                "s"]["handler"](self.ctx, {"actions": actions})
            self.assertTrue(r["ok"])
            self.assertEqual(r["executed"], 3)
            m_ct.assert_called_once()
            m_dp.assert_called_once()
            m_fol.assert_called_once()

    def test_desktop_actions_with_annotate(self):
        fake_shot = {
            "ok": True,
            "path": "/tmp/annotated.png",
            "annotated": True,
            "elements": [{"id": 1, "text": "Submit", "center": [100, 200]}]
        }
        with mock.patch.object(kwin, "screenshot", return_value=fake_shot) as m_shot:
            r = tools.REGISTRY["desktop_actions"]["handler"](self.ctx, {
                "actions": [{"action": "wait", "duration": 0.01}],
                "annotate": True,
                "annotate_max": 25
            })
            self.assertTrue(r["ok"])
            self.assertTrue(r.get("annotated"))
            self.assertEqual(len(r.get("elements")), 1)
            self.assertEqual(r["elements"][0]["text"], "Submit")
            self.assertTrue(m_shot.call_args[1].get("annotate"))
            self.assertEqual(m_shot.call_args[1].get("annotate_max"), 25)

    def test_kwin_display_info_parsing(self):
        sample_json = json.dumps({
            "currentSize": {"width": 3840, "height": 2160},
            "outputs": [
                {
                    "name": "DP-1",
                    "primary": True,
                    "enabled": True,
                    "pos": {"x": 0, "y": 0},
                    "currentMode": {
                        "size": {"width": 3840, "height": 2160},
                        "refreshRate": 60000,
                    },
                    "scale": 1.0
                }
            ]
        })
        mock_proc = mock.Mock(returncode=0, stdout=sample_json, stderr="")
        with mock.patch("shutil.which", return_value="/usr/bin/kscreen-doctor"), \
             mock.patch("subprocess.run", return_value=mock_proc):
            res = kwin.display_info()
            self.assertTrue(res["ok"])
            self.assertEqual(res["count"], 1)
            self.assertEqual(res["displays"][0]["name"], "DP-1")
            self.assertTrue(res["displays"][0]["primary"])
            self.assertEqual(res["displays"][0]["width"], 3840)
            self.assertEqual(res["displays"][0]["refresh_rate"], 60.0)
            self.assertEqual(res["current_size"], [3840, 2160])

    def test_kwin_compare_regions_parsing(self):
        mock_proc = mock.Mock(returncode=1, stdout="", stderr="1200 (0.0240)")
        with (
            mock.patch("shutil.which", return_value="/usr/bin/compare"),
            mock.patch.object(kwin, "_read_image_dimensions", return_value=(1000, 500)),
            mock.patch("subprocess.run", return_value=mock_proc),
        ):
            p1 = self.tmp / "f1.png"
            p2 = self.tmp / "f2.png"
            p1.write_bytes(b"1")
            p2.write_bytes(b"2")
            res = kwin.compare_regions(p1, p2)
            self.assertTrue(res["ok"])
            self.assertEqual(res["diff_pixels"], 1200)
            self.assertEqual(res["diff_ratio"], 0.024)
            self.assertEqual(res["total_pixels"], 500000)

    def test_kwin_drag_path_safety_releases_button_on_error(self):
        click_codes = []
        def fake_ydotool(cmd):
            if cmd[0] == "click":
                click_codes.append(cmd[1])
            return {"ok": True}

        with (
            mock.patch.object(
                kwin,
                "_place_pointer",
                side_effect=[
                    {"ok": True, "x": 10, "y": 10},
                    Exception("unexpected error"),
                ],
            ),
            mock.patch.object(kwin, "_ydotool", side_effect=fake_ydotool),
            mock.patch("time.sleep"),
        ):
            try:
                kwin.drag_path([(10, 10), (100, 100)])
            except Exception:
                pass
            # 0x40 is left button down, 0x80 is left button up
            self.assertIn("0x40", click_codes)
            self.assertIn("0x80", click_codes)


class ImagePayloadAndPlaybookTests(unittest.TestCase):
    def test_image_payload_preserves_raw_quality_for_zoom_crops(self):
        tmp_dir = support.TMP / "img_test"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        zoom_file = tmp_dir / "zoom-123456.png"
        zoom_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRzoomcropdata")
        self.addCleanup(lambda: zoom_file.unlink(missing_ok=True))

        # Reset cache
        argusd._IMAGE_CACHE.clear()

        # When calling image_payload on a zoom file, it should NOT run magick resize
        with mock.patch("subprocess.run") as mock_run:
            payload = argusd.image_payload(str(zoom_file), preserve_raw=True)
        mock_run.assert_not_called()
        self.assertIsNotNone(payload)
        self.assertEqual(payload["mime"], "image/png")

    def test_desktop_playbook_contains_all_modern_computer_use_guidelines(self):
        self.assertIn("desktop_actions", argusd.SYSTEM_PROMPT)
        self.assertIn("zoom_region", argusd.SYSTEM_PROMPT)
        self.assertIn("mouse_hover", argusd.SYSTEM_PROMPT)
        self.assertIn("stamp_cursor", argusd.SYSTEM_PROMPT)
        self.assertIn("wait_for_screen_change", argusd.SYSTEM_PROMPT)
        self.assertIn("scroll supports direction", argusd.SYSTEM_PROMPT)
        self.assertIn("relative_to", argusd.SYSTEM_PROMPT)
        self.assertIn("mouse_down", argusd.SYSTEM_PROMPT)
        self.assertIn("mouse_up", argusd.SYSTEM_PROMPT)
        self.assertIn("key_down", argusd.SYSTEM_PROMPT)
        self.assertIn("key_up", argusd.SYSTEM_PROMPT)
        self.assertIn("grid=true", argusd.SYSTEM_PROMPT)
        self.assertIn("clear_before=true", argusd.SYSTEM_PROMPT)
        self.assertIn("find_text", argusd.SYSTEM_PROMPT)
        self.assertIn("click_text", argusd.SYSTEM_PROMPT)
        self.assertIn("annotate=true", argusd.SYSTEM_PROMPT)
        self.assertIn("mouse_gesture", argusd.SYSTEM_PROMPT)
        self.assertIn("focus_or_launch", argusd.SYSTEM_PROMPT)
        self.assertIn("list_displays", argusd.SYSTEM_PROMPT)
        self.assertIn("assert_region_changed", argusd.SYSTEM_PROMPT)
        self.assertIn("click_element", argusd.SYSTEM_PROMPT)

    def test_tool_detail_formatting_for_computer_use(self):
        # desktop_actions — result shapes here mirror exactly what kwin.py's
        # own functions return (see kwin.click/drag/key_press/click_element/
        # click_text/focus_or_launch/activate_window), not a fabricated
        # shape: tool_detail previously read fields (bbox, center_x/center_y,
        # "measured", a nested "screenshot" dict, "element_id") that no real
        # tool result ever contained, so every one of these lines silently
        # rendered nothing useful. This test would have caught that.
        d_res = {
            "ok": True,
            "results": [
                {"action": "click", "ok": True, "x": 100, "y": 200,
                 "requested": [100, 200], "residual": 0, "correction"
                     "s": 0, "verified": True},
                {"action": "type", "ok": True, "text_preview": "foo"},
                {"action": "click_element", "ok": True, "id": 2, "text": "Save",
                 "x": 45, "y": 95, "box": [30, 85, 30, 20],
                 "element": {"id": 2, "text": "Save"}},
                {"action": "key", "ok": True, "key": "ctrl+s"},
                {"action": "drag", "ok": True, "start": [10, 20], "end": [30, 40], "ver"
                    "ified": True},
                {"action": "scroll", "ok": True, "direction": "down", "amount": 3},
                {"action": "activate", "ok": True, "result": "activated"},
                {"action": "focus_or_launch", "ok": True, "action_kind": "launched_and_"
                    "focused",
                 "window": {"uuid": "1", "caption": "Dolphin", "cls": "dolphin"}},
                {"action": "clipboard_past"
                    "e", "ok": True, "text": "Hello clipboard", "truncated": False},
                {"action": "wait", "ok": True, "duration": 0.5},
            ],
            "screenshot_path": "/tmp/test.png", "path": "/tmp/test.png",
        }
        detail = argusd.tool_detail("desktop_actions", d_res)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["kind"], "desktop")
        text = detail["text"]
        self.assertIn("click -> (100, 200)", text)
        self.assertIn("badge [2] 'Save'", text)
        self.assertIn("key 'ctrl+s'", text)
        self.assertIn("[10, 20] -> [30, 40]", text)
        self.assertIn("down x3", text)
        self.assertIn("-> activated", text)
        self.assertIn("Dolphin", text)
        self.assertIn("Hello clipboard", text)
        self.assertIn("0.5s", text)
        self.assertIn("screenshot: /tmp/test.png", text)

        # A failed screenshot capture should surface why, not disappear.
        d_fail = {"ok": True, "result"
            "s": [{"action": "click", "ok": True, "x": 1, "y": 1}],
                  "screenshot_error": "screen grant disabled"}
        detail_fail = argusd.tool_detail("desktop_actions", d_fail)
        self.assertIn("screenshot failed: screen grant disabled", detail_fail["text"])

        # find_text — real match shape from kwin.find_text: "x"/"y"/"box",
        # never "center_x"/"center_y"/"bbox".
        ft_res = {
            "ok": True,
            "query": "Cancel",
            "matches": [{"text": "Cancel", "x": 50, "y": 60, "box": [40, 50, 20, 20],
                        "confidence": 95.0, "exact": True, "type": "word"}]
        }
        detail_ft = argusd.tool_detail("find_text", ft_res)
        self.assertIn("Found 1 match", detail_ft["text"])
        self.assertIn("center=(50, 60)", detail_ft["text"])
        self.assertIn("box=[40, 50, 20, 20]", detail_ft["text"])

        # click_text — real target shape is a find_text match (x/y, not
        # center_x/center_y).
        ct_res = {
            "ok": True,
            "index": 0,
            "matches_found": 2,
            "target": {"text": "Submit", "x": 120, "y": 80}
        }
        detail_ct = argusd.tool_detail("click_text", ct_res)
        self.assertIn("Clicked 'Submit' at (120, 80) [match 1/2]", detail_ct["text"])

        # click_element
        ce_res = {
            "ok": True,
            "id": 3,
            "x": 45,
            "y": 95,
            "element": {"id": 3, "text": "Save"}
        }
        detail_ce = argusd.tool_detail("click_element", ce_res)
        self.assertIn("Clicked mark [3] 'Save' at (45, 95)", detail_ce["text"])

        # list_displays
        ld_res = {
            "ok": True,
            "displays": [
                {
                    "name": "eDP-1", "width": 1920, "height": 1080,
                    "x": 0, "y": 0, "scale": 1.0, "refresh_rate": 60,
                },
            ]
        }
        detail_ld = argusd.tool_detail("list_displays", ld_res)
        self.assertIn("Displays (1)", detail_ld["text"])
        self.assertIn("eDP-1: 1920x1080", detail_ld["text"])

        # assert_region_changed — real return is diff_ratio/threshold_ratio
        # plus the derived diff_percent/threshold_percent, never
        # diff_percentage/threshold_percentage.
        arc_res = {
            "ok": True,
            "changed": True,
            "diff_ratio": 0.0245,
            "diff_percent": 2.45,
            "threshold_ratio": 0.005,
            "threshold_percent": 0.5,
        }
        detail_arc = argusd.tool_detail("assert_region_changed", arc_res)
        self.assertIn("Region diff: CHANGED (2.45%", detail_arc["text"])
        self.assertIn("threshold=0.5%", detail_arc["text"])

        # wait_for_screen_change
        wfsc_res = {"ok": True, "changed": True, "reason": "pixels modified"}
        detail_wfsc = argusd.tool_detail("wait_for_screen_change", wfsc_res)
        self.assertIn("Screen change: CHANGED (pixels modified)", detail_wfsc["text"])

        # clipboard_paste (the standalone tool, not a desktop_actions step)
        cp_res = {"ok": True, "text": "Hello clipboard"}
        detail_cp = argusd.tool_detail("clipboard_paste", cp_res)
        self.assertIn("Clipboard (15 chars):", detail_cp["text"])

    def test_assert_region_changed_returns_percent_fields(self):
        # tools.py's own handler must actually populate the percent fields
        # tool_detail now reads — a passing tool_detail test alone wouldn't
        # catch a drift back to ratio-only if the handler stopped emitting them.
        tmp = support.TMP / "arc_ctx"
        tmp.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        before = tmp / "arc-before.png"
        before.write_bytes(b"\x89PNG\r\n\x1a\n")
        with mock.patch.object(kwin, "screenshot", return_value={"ok": True}), \
             mock.patch.object(kwin, "compare_regions",
                               return_value={"ok": True, "diff_ratio": 0.02, "diff_pixe"
                                   "ls": 200,
                                            "total_pixels": 10000, "diff_image_pat"
                                                "h": None}):
            res = tools.REGISTRY["assert_region_changed"]["handler"](
                DummyContext(tmp), {"before_path": str(before), "threshold_rati"
                    "o": 0.01})
        self.assertTrue(res["ok"])
        self.assertAlmostEqual(res["diff_percent"], 2.0)
        self.assertAlmostEqual(res["threshold_percent"], 1.0)


if __name__ == "__main__":
    unittest.main()
