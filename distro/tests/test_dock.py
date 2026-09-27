"""Contracts for the left app dock."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dock = (ROOT / "shell/dock/Dock.qml").read_text()
        cls.item = (ROOT / "shell/dock/DockItem.qml").read_text()
        cls.shell = (ROOT / "shell/shell.qml").read_text()

    def test_dock_is_mounted_on_every_screen(self):
        self.assertIn('import "dock"', self.shell)
        self.assertIn("Dock {}", self.shell)

    def test_dock_sits_on_the_left_and_reserves_its_strip(self):
        self.assertIn("anchors { left: true }", self.dock)
        # the surface hugs the rail (it redraws every frame for the light rail)
        self.assertIn("implicitHeight: Math.max(300, baseRailH + 120)", self.dock)
        self.assertIn("exclusiveZone:", self.dock)
        # the wide transparent surface must stay click-through outside the dock
        self.assertIn("mask: Region {", self.dock)

    def test_label_and_menu_are_drawn_in_the_dock_surface(self):
        # xdg popups were composited translucent here (text behind showed
        # through the menu), so neither may come back as a PopupWindow
        self.assertNotIn("PopupWindow", self.dock)
        self.assertNotIn("PopupWindow", self.item)

    def test_an_empty_dock_hides_and_releases_its_strip(self):
        # a fresh live account has no pins and no windows: the dock used to
        # draw a squashed empty pill (seen on the live ISO)
        self.assertIn("readonly property bool empty: dockModel.count === 0", self.dock)
        self.assertIn("exclusiveZone: empty ? 0 :", self.dock)
        self.assertIn("opacity: enter * dock.shown", self.dock)

    def test_pinned_apps_are_the_shared_favourites(self):
        self.assertIn("AppIndex.favorites", self.dock)
        self.assertIn("AppIndex.toggleFav(", self.dock)
        self.assertIn("AppIndex.launch(", self.dock)

    def test_running_windows_come_from_the_kwin_task_daemon(self):
        # Quickshell's ToplevelManager is permanently empty under KWin
        self.assertIn("TaskRunner.windows", self.dock)
        self.assertNotIn("ToplevelManager", self.dock)

    def test_model_is_keyed_so_tiles_keep_state_across_updates(self):
        self.assertIn("ListModel { id: dockModel }", self.dock)
        self.assertIn("dockModel.move(", self.dock)

    def test_rail_background_is_the_animated_rgb_shader(self):
        self.assertIn("RgbFlow {", self.dock)
        self.assertIn("horizontal: false", self.dock)
        # tiles stay still; the focused tile's turning RGB rim lives in the
        # shared GlowRim and only runs while shown in RGB mode
        self.assertNotIn("Animation.Infinite", self.item)
        self.assertNotIn("FrameAnimation", self.item)

    def test_tiles_and_tabs_share_the_logo_rim(self):
        rim = (ROOT / "shell/components/GlowRim.qml").read_text()
        tab = (ROOT / "shell/taskbar/TaskButton.qml").read_text()
        self.assertIn("running: root.rgb && root.visible", rim)
        self.assertEqual(rim.count("Animation.Infinite"), 1)
        self.assertIn("PathRectangle", rim)          # follows the rounded tile
        for src in (self.item, tab):
            self.assertIn("GlowRim {", src)
            self.assertIn("drawRim: false", src)     # glow behind the glass
            self.assertIn("drawGlow: false", src)    # crisp rim on top

    def test_icons_render_once_at_max_size_and_scale(self):
        self.assertIn("implicitSize: 64", self.item)
        self.assertIn("scale: (root.size * 0.74) / 64", self.item)


if __name__ == "__main__":
    unittest.main()
