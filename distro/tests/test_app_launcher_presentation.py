"""Regression contracts for the application launcher's presentation."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class AppLauncherPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = (ROOT / "shell/overlay/AppLauncher.qml").read_text()

    def test_card_surface_is_opaque_enough_to_read_against_the_desktop(self):
        # The panel body and the category-row edge fades must come from one
        # token, or the fades show up as a differently-colored band.
        self.assertIn("property color cardBase", self.launcher)
        self.assertIn("baseColor: win.cardBase", self.launcher)

    def test_section_headers_rule_across_the_unused_width(self):
        self.assertIn("component SectionRule", self.launcher)
        self.assertGreaterEqual(self.launcher.count("SectionRule {"), 2)

    def test_category_row_has_scroll_edge_fades(self):
        self.assertIn("id: catFadeLeft", self.launcher)
        self.assertIn("id: catFadeRight", self.launcher)
        self.assertIn("contentWidth > width", self.launcher)

    def test_grid_shows_a_scroll_indicator(self):
        self.assertIn("id: gridScroll", self.launcher)
        self.assertIn("grid.contentHeight > grid.height", self.launcher)

    def test_grid_drops_the_developer_grid_readout(self):
        self.assertNotIn("× GRID", self.launcher)

    def test_grid_tiles_stay_dark_glass_not_washed_white(self):
        # Theme.alpha() REPLACES the alpha channel, so
        # alpha(surfaceLow, 0.34) is white at 34%, not 34% of a 4.5% wash —
        # that is what made every resting tile read as a light-gray slab.
        self.assertNotIn("Theme.alpha(Theme.surfaceLow, 0.34)", self.launcher)
        self.assertNotIn("Theme.alpha(Theme.stroke, 0.7)", self.launcher)
        self.assertNotIn("Theme.alpha(Theme.strokeStrong, 0.62)", self.launcher)

    def test_grid_labels_reserve_a_two_line_slot_for_row_alignment(self):
        self.assertIn("id: cellLabel", self.launcher)
        self.assertIn("verticalAlignment: Text.AlignTop", self.launcher)

    def test_entrance_stagger_is_driven_per_cell(self):
        self.assertIn("id: cellIn", self.launcher)
        self.assertIn("PauseAnimation", self.launcher)
        self.assertIn("onPendingEntranceChanged", self.launcher)
        self.assertNotIn("index > 23 ? 1 : win.appear", self.launcher)

    def test_open_initialization_runs_when_the_window_is_created(self):
        self.assertIn("function initOnOpen", self.launcher)
        self.assertIn("Component.onCompleted: win.initOnOpen()", self.launcher)

    def test_footer_hint_is_separated_from_the_grid_by_a_rule(self):
        self.assertIn("id: footerRule", self.launcher)
        self.assertIn("height: footerCol.implicitHeight", self.launcher)
        self.assertNotIn("Item {\n                visible: false\n            }", self.launcher)

    def test_launcher_keeps_its_launch_pin_search_and_keyboard_actions(self):
        self.assertIn("AppIndex.launch(", self.launcher)
        self.assertIn("AppIndex.toggleFav(", self.launcher)
        self.assertIn("AppIndex.rescan()", self.launcher)
        self.assertIn("Keys.onEscapePressed", self.launcher)
        self.assertIn("grid.moveCurrentIndexDown()", self.launcher)
        self.assertIn("AgentState.launcherOpen = false", self.launcher)
        self.assertIn('text: "CLEAR SEARCH"', self.launcher)


if __name__ == "__main__":
    unittest.main()
