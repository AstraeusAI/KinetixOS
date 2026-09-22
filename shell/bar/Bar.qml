import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.SystemTray
import "../common"
import "../components"

PanelWindow {
    id: bar
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; left: true; right: true }
    margins { top: 0; left: 0; right: 0 }
    implicitHeight: 56
    color: "transparent"

    WlrLayershell.namespace: "argus:bar"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    property real enter: 0
    // Google-style choreography: bar drops first, then left → center → right cascade
    property real enterL: 0
    property real enterC: 0
    property real enterR: 0
    Component.onCompleted: { enter = 1; lTimer.start(); cTimer.start(); rTimer.start(); updatePopupOffsets(); }
    onWidthChanged: updatePopupOffsets()

    function updatePopupOffsets() {
        if (typeof appCenterCap !== "undefined" && appCenterCap && appCenterCap.width > 0 && typeof barGlass !== "undefined" && barGlass) {
            var pt = appCenterCap.mapToItem(barGlass, appCenterCap.width / 2, 0);
            AgentState.appCenterRightMargin = Math.max(16, (barGlass.width - pt.x) - 680 / 2);
        }
        if (typeof sysMonitorCap !== "undefined" && sysMonitorCap && sysMonitorCap.width > 0 && typeof barGlass !== "undefined" && barGlass) {
            var spt = sysMonitorCap.mapToItem(barGlass, sysMonitorCap.width / 2, 0);
            AgentState.sysRightMargin = Math.max(16, (barGlass.width - spt.x) - 540 / 2);
        }
    }

    Connections {
        target: AgentState
        function onAppCenterOpenChanged() {
            if (AgentState.appCenterOpen) bar.updatePopupOffsets();
        }
        function onSysOpenChanged() {
            if (AgentState.sysOpen) bar.updatePopupOffsets();
        }
    }

    Behavior on enter { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.OutQuint } }
    Behavior on enterL { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.OutQuint } }
    Behavior on enterC { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.OutQuint } }
    Behavior on enterR { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.OutQuint } }
    Timer { id: lTimer; interval: 70; onTriggered: bar.enterL = 1 }
    Timer { id: cTimer; interval: 170; onTriggered: bar.enterC = 1 }
    Timer { id: rTimer; interval: 270; onTriggered: bar.enterR = 1 }

    GlassPanel {
        id: barGlass
        anchors.fill: parent
        radius: 0
        level: 3
        baseColor: Theme.barBase
        rim: false
        sheen: true
        opacity: enter
        transform: Translate { y: -bar.height * (1 - enter) }

        // ── left ──────────────────────────────────────────
        Row {
            anchors { left: parent.left; leftMargin: Theme.s4; verticalCenter: parent.verticalCenter }
            spacing: Theme.s2
            opacity: bar.enterL
            transform: Translate { x: -14 * (1 - bar.enterL) }

            // Box 1: Brand & Workspaces Capsule
            BarBox {
                id: brandWorkspacesPill
                implicitWidth: bwRow.implicitWidth + Theme.s3 * 2
                anchors.verticalCenter: parent.verticalCenter
                HoverHandler { id: bwHov }
                readonly property bool hovered: bwHov.hovered

                Row {
                    id: bwRow
                    anchors.centerIn: parent
                    spacing: Theme.s2

                    IconButton {
                        glyph: "▦"
                        tip: "App Launcher"
                        tint: Theme.accent2
                        active: AgentState.launcherOpen
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: AgentState.toggleLauncher()
                    }
                    ArgusMark {
                        anchors.verticalCenter: parent.verticalCenter
                        live: AgentState.status !== "idle"
                    }
                    Item {
                        id: kinetixWord
                        property bool live: AgentState.status !== "idle"
                        readonly property bool activeOrHovered: live || brandWorkspacesPill.hovered || barHover.hovered
                        property real tracking: live ? 2.75 : (brandWorkspacesPill.hovered ? 2.45 : 2.2)
                        property color signalColor: Theme.statusColor(AgentState.status)
                        property real inkOpacity: live ? 1.0 : (brandWorkspacesPill.hovered ? 0.98 : 0.92)
                        property real glowOpacity: live ? 0.16 : (brandWorkspacesPill.hovered ? 0.11 : 0.055)
                        property real signalOpacity: live ? 0.88 : (brandWorkspacesPill.hovered ? 0.58 : 0.28)
                        implicitWidth: wordBase.implicitWidth
                        implicitHeight: wordBase.implicitHeight
                        anchors.verticalCenter: parent.verticalCenter
                        Behavior on tracking { NumberAnimation { duration: Theme.durMed; easing.type: Easing.InOutSine } }
                        Behavior on inkOpacity { NumberAnimation { duration: Theme.durMed; easing.type: Easing.InOutSine } }
                        Behavior on glowOpacity { NumberAnimation { duration: Theme.durMed; easing.type: Easing.InOutSine } }
                        Behavior on signalOpacity { NumberAnimation { duration: Theme.durMed; easing.type: Easing.InOutSine } }

                        // Continuous phase accumulated from real frame time
                        // and fed through sin() can't glitch on a duration change.
                        readonly property real breathCycleMs: live ? 2100 : (brandWorkspacesPill.hovered ? 3000 : 4400)
                        property real breathPhase: 0
                        readonly property real breath: 0.5 + 0.5 * Math.sin(breathPhase * 2 * Math.PI)
                        FrameAnimation {
                            running: kinetixWord.activeOrHovered
                            onTriggered: {
                                var dt = Math.min(frameTime, 0.1);
                                kinetixWord.breathPhase = (kinetixWord.breathPhase + dt * 1000 / kinetixWord.breathCycleMs) % 1;
                            }
                        }

                        // A quiet colored underprint gives the wordmark a little
                        // depth without making the idle bar look illuminated.
                        Text {
                            id: wordGlow
                            text: wordBase.text
                            color: kinetixWord.signalColor
                            opacity: kinetixWord.glowOpacity * (0.86 + kinetixWord.breath * 0.14)
                            font: wordBase.font
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Text {
                            id: wordBase
                            text: "KINETIX"
                            color: Theme.text
                            opacity: kinetixWord.inkOpacity
                            font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.DemiBold; letterSpacing: kinetixWord.tracking }
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        // A narrow reflected-light pass travels across the
                        // letters. It is quiet at rest and becomes more legible
                        // while the agent is active.
                        Item {
                            id: wordSweep
                            width: 13
                            height: parent.height
                            clip: true

                            // Same restart-on-status-change glitch as the
                            // breath pulse above (a SequentialAnimation whose
                            // leg durations were bound to `live`), fixed the
                            // same way: one continuous phase over the whole
                            // travel+pause cycle, replayed by a plain
                            // function instead of QML Animation objects that
                            // could themselves be restarted by a duration
                            // change.
                            readonly property real moveMs: kinetixWord.live ? 2500 : (brandWorkspacesPill.hovered ? 3600 : 7200)
                            readonly property real pauseMs: kinetixWord.live ? 700 : (brandWorkspacesPill.hovered ? 1200 : 3000)
                            readonly property real cycleMs: moveMs + pauseMs
                            property real cyclePhase: 0
                            readonly property real travelX: kinetixWord.width - (-width)
                            x: {
                                var elapsed = cyclePhase * cycleMs;
                                if (elapsed >= moveMs) return kinetixWord.width;
                                var u = elapsed / moveMs;
                                var eased = 0.5 - 0.5 * Math.cos(Math.PI * u); // InOutSine
                                return -width + eased * travelX;
                            }
                            FrameAnimation {
                                running: kinetixWord.activeOrHovered
                                onTriggered: {
                                    var dt = Math.min(frameTime, 0.1);
                                    wordSweep.cyclePhase = (wordSweep.cyclePhase + dt * 1000 / wordSweep.cycleMs) % 1;
                                }
                            }

                            Text {
                                text: wordBase.text
                                x: -wordSweep.x
                                color: kinetixWord.signalColor
                                opacity: kinetixWord.signalOpacity * (0.92 + kinetixWord.breath * 0.08)
                                font: wordBase.font
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }

                    Rectangle {
                        width: 1; height: 14
                        anchors.verticalCenter: parent.verticalCenter
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "transparent" }
                            GradientStop { position: 0.25; color: Theme.alpha(Theme.crimson, 0.22) }
                            GradientStop { position: 0.75; color: Theme.alpha(Theme.crimson, 0.22) }
                            GradientStop { position: 1.0; color: "transparent" }
                        }
                    }

                    Workspaces {
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }

            // Box 2: Active Window Capsule
            ActiveWindow {
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // A restrained inner keyline gives the bar a machined, precision edge
        // without competing with the bottom laser rail. Warmed to a faint
        // anodized-red hairline so the edge reads as part of the bar's own
        // deep-red glass rather than a leftover neutral outline.
        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: 0
            color: "transparent"
            border.width: 1
            border.color: Theme.barStroke
            z: 20

            // Overhead grazing light on upper inner bevel
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                height: 1
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 0.15; color: Qt.rgba(1, 1, 1, 0.12) }
                    GradientStop { position: 0.50; color: Qt.rgba(1, 1, 1, 0.22) }
                    GradientStop { position: 0.85; color: Qt.rgba(1, 1, 1, 0.12) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }
        }

        // ── center: Luxury Glass Time & Search Island ──
        BarBox {
            id: centerPill
            anchors.centerIn: parent
            implicitWidth: centerContentRow.implicitWidth + Theme.s4 * 2
            interactive: true
            active: AgentState.paletteOpen
            opacity: bar.enterC
            transform: Translate { y: 8 * (1 - bar.enterC) }
            onClicked: AgentState.togglePalette()

            Row {
                id: centerContentRow
                anchors.centerIn: parent
                spacing: Theme.s2

                Rectangle {
                    width: 17
                    height: 17
                    radius: 4
                    color: centerPill.hovered ? Theme.alpha(Theme.crimson, 0.16) : Qt.rgba(1, 1, 1, 0.05)
                    border.width: 1
                    border.color: centerPill.hovered ? Theme.alpha(Theme.crimson, 0.45) : Qt.rgba(1, 1, 1, 0.10)
                    anchors.verticalCenter: parent.verticalCenter
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                    Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                    Text {
                        anchors.centerIn: parent
                        text: "⌘"
                        color: centerPill.hovered ? Theme.crimsonText : Theme.textDim
                        font.pixelSize: 10
                        font.family: Theme.fontMono
                        font.weight: Font.DemiBold
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                    }
                }

                ClockWidget {
                    id: clockItem
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }

        // ── right ─────────────────────────────────────────
        Row {
            anchors { right: parent.right; rightMargin: Theme.s4; verticalCenter: parent.verticalCenter }
            spacing: Theme.s2
            opacity: bar.enterR
            transform: Translate { x: 14 * (1 - bar.enterR) }

            // App Center & Package Hub Capsule
            AppCenterCapsule {
                id: appCenterCap
                anchors.verticalCenter: parent.verticalCenter
            }

            // Box 5: System Telemetry Capsule
            SysMonitor {
                id: sysMonitorCap
                anchors.verticalCenter: parent.verticalCenter
            }

            // Box 6: Media / Now Playing Capsule
            NowPlaying {
                anchors.verticalCenter: parent.verticalCenter
            }

            // Box 7: Unified Status & System Tray Capsule
            BarBox {
                id: statusTrayPill
                implicitWidth: stRow.implicitWidth + Theme.s3 * 2
                anchors.verticalCenter: parent.verticalCenter

                Row {
                    id: stRow
                    anchors.centerIn: parent
                    spacing: Theme.s2

                    SysTray {
                        id: sysTray
                        anchors.verticalCenter: parent.verticalCenter
                        window: bar
                    }

                    Rectangle {
                        visible: sysTray.count > 0
                        width: 1; height: 14
                        anchors.verticalCenter: parent.verticalCenter
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "transparent" }
                            GradientStop { position: 0.25; color: Theme.alpha(Theme.crimson, 0.22) }
                            GradientStop { position: 0.75; color: Theme.alpha(Theme.crimson, 0.22) }
                            GradientStop { position: 1.0; color: "transparent" }
                        }
                    }

                    StatusCluster {
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }

            // Box 8: Agent Pill Capsule
            BarBox {
                id: agentPill
                implicitWidth: pillRow.implicitWidth + Theme.s4 * 2
                interactive: true
                active: AgentState.panelOpen
                activeColor: Theme.crimson
                anchors.verticalCenter: parent.verticalCenter
                onClicked: AgentState.togglePanel()

                // Google-assistant listening pulse
                property real pulse: 0
                SequentialAnimation on pulse {
                    running: AgentState.status === "working"
                    loops: Animation.Infinite
                    NumberAnimation { to: 1; duration: 850; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 0.2; duration: 850; easing.type: Easing.InOutSine }
                }
                // Agent-authority pulse in the panel's crimson family — now
                // one glowing accent among the bar's own red glass, rather
                // than the bar's only red element.
                Rectangle {
                    anchors.fill: parent
                    radius: agentPill.radius
                    opacity: AgentState.status === "working" ? (0.22 + 0.45 * agentPill.pulse) : 0.0
                    Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Theme.glowDeep }
                        GradientStop { position: 0.45; color: Theme.crimson }
                        GradientStop { position: 1.0; color: Theme.alarm }
                    }
                }

                Row {
                    id: pillRow
                    anchors.centerIn: parent
                    spacing: Theme.s2
                    StatusOrb {
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.statusColor(AgentState.status)
                        live: AgentState.status !== "idle"
                    }
                    Text {
                        text: "AGENT"
                        color: agentPill.active ? Theme.crimsonText : (agentPill.hovered ? Theme.text : Theme.textDim)
                        font { family: Theme.fontMono; pixelSize: Theme.tCaption; letterSpacing: agentPill.active ? 1.8 : 1.5; weight: Font.DemiBold }
                        anchors.verticalCenter: parent.verticalCenter
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                    }
                }
            }
        }
    }

    // Edge-to-edge chromatic laser rail along the bottom boundary:
    // continuous flowing 4-brand light-pipe with dual orbiting photon glints,
    // volumetric atmospheric bloom, and status harmonics.
    FlowBand {
        anchors.fill: parent
        mode: "bottomEdge"
        z: 40
        amplitude: 0.96
        periodMs: 10000
        boosted: AgentState.status === "working"
        status: AgentState.status
        hovered: barHover.hovered
        opacity: bar.enter
        transform: Translate { y: -bar.height * (1 - bar.enter) }
    }

    HoverHandler {
        id: barHover
    }
}
