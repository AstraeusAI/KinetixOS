"""Regression contracts for bar layout and retained controls."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BarPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bar = (ROOT / "shell/bar/Bar.qml").read_text()
        cls.sys_monitor = (ROOT / "shell/bar/SysMonitor.qml").read_text()
        cls.sys_tray = (ROOT / "shell/bar/SysTray.qml").read_text()
        cls.sys_popup = (ROOT / "shell/overlay/SysPopup.qml").read_text()
        cls.app_center = (ROOT / "shell/bar/AppCenterCapsule.qml").read_text()
        cls.now_playing = (ROOT / "shell/bar/NowPlaying.qml").read_text()
        cls.workspaces = (ROOT / "shell/bar/Workspaces.qml").read_text()
        cls.status_cluster = (ROOT / "shell/bar/StatusCluster.qml").read_text()
        cls.compact_telemetry = (ROOT / "shell/bar/CompactTelemetry.qml").read_text()
        cls.icon_button = (ROOT / "shell/components/IconButton.qml").read_text()
        cls.close_button = (ROOT / "shell/components/CloseButton.qml").read_text()
        cls.agent_panel = (ROOT / "shell/agent/AgentPanel.qml").read_text()
        cls.widget_frame = (ROOT / "shell/widgets/WidgetFrame.qml").read_text()

    def test_center_island_is_clamped_between_the_side_groups(self):
        self.assertIn("function centerIslandX", self.bar)
        self.assertIn("leftGroup.x + leftGroup.width", self.bar)
        self.assertIn("rightGroup.x -", self.bar)
        self.assertIn("x: barGlass.centerIslandX(width)", self.bar)

    def test_narrow_layout_compacts_display_without_removing_actions(self):
        self.assertIn("readonly property bool compactLayout: width < 1500", self.bar)
        self.assertIn("readonly property bool ultraCompactLayout: width < 1400", self.bar)
        self.assertIn("compact: bar.compactLayout", self.bar)
        self.assertIn("sourceComponent: bar.compactLayout ? compactTelemetryComponent : detailedTelemetryComponent", self.bar)
        self.assertNotIn("implicitWidth: item ? item.implicitWidth : 0", self.bar)
        # the launcher button was removed from the bar by request
        self.assertNotIn("onClicked: AgentState.toggleLauncher()", self.bar)
        # the terminal button was removed from the bar by request
        self.assertNotIn("onClicked: AgentState.toggleTerminal()", self.bar)
        self.assertIn("onClicked: AgentState.togglePalette()", self.bar)
        self.assertIn("onClicked: AgentState.toggleAppCenter()", self.app_center)
        self.assertIn("onClicked: AgentState.toggleSys()", self.sys_monitor)
        self.assertIn("onClicked: AgentState.togglePanel()", self.bar)
        self.assertIn("root.switchTo(parent.modelData.id)", self.workspaces)
        self.assertIn("s.audio.muted = !s.audio.muted", self.status_cluster)
        self.assertIn("s.audio.volume = Math.max", self.status_cluster)
        # SysTray's QsMenuAnchor now anchors by item, not by a `window` property.
        self.assertIn("anchor.item: root.menuItem", self.sys_tray)
        self.assertIn("root.player.previous()", self.now_playing)
        self.assertIn("root.player.togglePlaying()", self.now_playing)
        self.assertIn("root.player.next()", self.now_playing)

    def test_iconbutton_tips_are_rendered_as_hover_tooltips(self):
        # Round 19: the built-in QtQuick.Controls ToolTip attached property
        # this test used to require positions itself assuming a normal
        # top-level window. IconButton lives inside PanelWindow (wlr-layer-
        # shell) surfaces (the bar's own launcher/terminal buttons, App
        # Center's header buttons) where that control instead rendered on
        # top of the button and ate the click meant for it — confirmed
        # live first in the taskbar's launcher button. Fixed with a real
        # Quickshell PopupWindow anchored above the button via Edges.Top,
        # anchored to root.Window.window so it works generically wherever
        # IconButton is used.
        self.assertNotIn("ToolTip.visible:", self.icon_button)
        self.assertIn("PopupWindow {", self.icon_button)
        self.assertIn("anchor.edges: Edges.Top", self.icon_button)
        self.assertIn("anchor.window: root.Window.window", self.icon_button)
        self.assertIn("text: root.tip", self.icon_button)
        self.assertIn("ma.containsMouse", self.icon_button)

    def test_close_button_tooltip_is_wired_and_layershell_safe(self):
        # Round 19: CloseButton — its own header comment calls it "the
        # shared exit control for every Argus surface" — declared a `tip`
        # property that four call sites already passed custom text to
        # (e.g. "Hide preview", "Remove server"), but the component never
        # actually rendered a tooltip at all: no ToolTip/PopupWindow
        # existed anywhere in the file. Wired it up the same layer-shell-
        # safe way as IconButton: a Quickshell PopupWindow, not the
        # built-in ToolTip (see that fix's own comment for why).
        self.assertNotIn("ToolTip.visible:", self.close_button)
        self.assertIn("PopupWindow {", self.close_button)
        self.assertIn("anchor.edges: Edges.Top", self.close_button)
        self.assertIn("anchor.window: root.Window.window", self.close_button)
        self.assertIn("text: root.tip", self.close_button)

    def test_panel_and_widget_close_buttons_use_the_shared_component(self):
        # Round 19: AgentPanel's own top-level close and WidgetFrame's
        # widget-remove close were each a hand-rolled duplicate of
        # CloseButton (Rectangle + "✕" Text + MouseArea) rather than the
        # shared component — functionally fine, but inconsistent styling/
        # animation, and each would have needed its own layer-shell-safe
        # tooltip fix separately. Unified onto CloseButton.
        agent_panel_collapsed = " ".join(self.agent_panel.split())
        widget_frame_collapsed = " ".join(self.widget_frame.split())
        self.assertIn("CloseButton { box: 28", agent_panel_collapsed)
        self.assertIn("onClicked: AgentState.panelOpen = false", self.agent_panel)
        self.assertIn("CloseButton { box: 24", widget_frame_collapsed)
        self.assertIn("onClicked: WidgetStore.remove(frame.widget.id)", self.widget_frame)

    def test_compact_telemetry_still_opens_the_full_system_popup(self):
        self.assertIn("onClicked: AgentState.toggleSys()", self.compact_telemetry)
        self.assertIn("SysInfo.cpu", self.compact_telemetry)
        self.assertIn("SysInfo.memPct", self.compact_telemetry)

    def test_system_popup_overview_exposes_more_metrics_with_eased_updates(self):
        for metric in (
            "LOAD AVG · 1 / 5 / 15",
            "MEMORY AVAILABLE",
            "ROOT VOLUME FREE",
            "pop.load15Visual",
            "pop.memAvailVisual",
            "pop.diskFreeVisual",
        ):
            self.assertIn(metric, self.sys_popup)
        self.assertIn("LIVE · 1s", self.sys_popup)
        self.assertIn("Behavior on width { NumberAnimation { duration: 550", self.sys_popup)
        self.assertIn("modelData.name || (\"GPU \" + index)", self.sys_popup)

    def test_bar_has_no_active_window_pill(self):
        # Removed at the user's request: the focused window's title already
        # shows on the taskbar's focused tab.
        self.assertNotIn("ActiveWindow {", self.bar)

    def test_bar_retains_one_signature_rail_without_pulsing_surface_washes(self):
        self.assertNotIn("0.84 + 0.16 * Theme.heartbeatSin", self.bar)
        self.assertNotIn("Bottom rail crimson upward bloom", self.bar)
        # the bar's one signature light is the full-bar RGB flow
        self.assertIn("RgbFlow {", self.bar)
        self.assertNotIn("FlowBand {", self.bar)
        self.assertNotIn("GoogleGlow {", self.bar)
        self.assertEqual(self.bar.count("RgbFlow {"), 1)

    def test_rgb_flow_fills_every_shell_surface_from_one_current_shader(self):
        flow = (ROOT / "shell/components/RgbFlow.qml").read_text()
        self.assertIn('"../shaders/rgbflow.frag.qsb"', flow)
        src = ROOT / "shell/shaders/rgbflow.frag"
        qsb = ROOT / "shell/shaders/rgbflow.frag.qsb"
        self.assertTrue(qsb.exists(), "run qsb on rgbflow.frag")
        self.assertGreaterEqual(qsb.stat().st_mtime, src.stat().st_mtime,
                                "rgbflow.frag.qsb is older than its source; recompile it")
        # Google red / green / blue as OKLab constants
        shader = src.read_text()
        for lab in ("0.6257,  0.1799,  0.1000", "0.6475, -0.1367,  0.0838", "0.6304, -0.0314, -0.1773"):
            self.assertIn(lab, shader)
        for surface in ("bar/Bar.qml", "taskbar/Taskbar.qml", "dock/Dock.qml"):
            self.assertIn("RgbFlow {", (ROOT / "shell" / surface).read_text(), surface)
        self.assertIn("running: root.visible", flow)   # no animation cost when hidden

    def test_google_glow_reacts_to_agent_status_and_uses_google_palette(self):
        glow = (ROOT / "shell/components/GoogleGlow.qml").read_text()
        self.assertIn("status: AgentState.status", self.bar)
        self.assertIn("hovered: barHover.hovered", self.bar)
        for prop in ("property string status", "property bool hovered", "property bool boosted", "function flash()"):
            self.assertIn(prop, glow)
        shader = (ROOT / "shell/shaders/googlebeam.frag").read_text()
        # Google blue / red / yellow / green, as OKLab constants in the shader
        for lab in ("0.6304, -0.0314, -0.1773", "0.6257,  0.1799,  0.1000",
                    "0.8304,  0.0177,  0.1690", "0.6475, -0.1367,  0.0838"):
            self.assertIn(lab, shader)
        self.assertIn("running: root.visible", glow)   # no animation cost when hidden

    def test_google_glow_shader_is_compiled_and_current(self):
        src = ROOT / "shell/shaders/googlebeam.frag"
        qsb = ROOT / "shell/shaders/googlebeam.frag.qsb"
        glow = (ROOT / "shell/components/GoogleGlow.qml").read_text()
        self.assertIn('"../shaders/googlebeam.frag.qsb"', glow)
        self.assertTrue(qsb.exists(), "run qsb on googlebeam.frag")
        self.assertGreaterEqual(qsb.stat().st_mtime, src.stat().st_mtime,
                                "googlebeam.frag.qsb is older than its source; recompile it")
        self.assertIn("ShaderEffect.Error", glow)       # fallback rail when shaders are unavailable

    def test_bar_action_icons_use_thematic_vector_drawings(self):
        # the launcher and terminal buttons were removed from the bar by request
        self.assertNotIn('iconName: "grid"', self.bar)
        self.assertNotIn('iconName: "terminal"', self.bar)
        self.assertIn("property string iconName", self.icon_button)
        self.assertIn("Canvas {", self.icon_button)

    def test_selection_and_brand_accents_stay_in_the_crimson_family(self):
        self.assertIn("liveColor: Theme.crimsonText", self.bar)
        self.assertIn("Theme.crimsonText", self.workspaces)
        self.assertNotIn("Theme.accent", self.workspaces)
        self.assertNotIn("Theme.accent", self.app_center)


if __name__ == "__main__":
    unittest.main()
