import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.SystemTray
import "../common"
import "../components"

PanelWindow {
    id: bar
    required property ShellScreen modelData
    screen: modelData

    readonly property bool compactLayout: width < 1500
    readonly property bool ultraCompactLayout: width < 1400

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
        var sysCap = typeof sysMonitorCap !== "undefined" && sysMonitorCap ? sysMonitorCap.item : null;
        if (sysCap && sysCap.width > 0 && typeof barGlass !== "undefined" && barGlass) {
            var spt = sysCap.mapToItem(barGlass, sysCap.width / 2, 0);
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
        sheen: false
        opacity: enter
        transform: Translate { y: -bar.height * (1 - enter) }

        function centerIslandX(centerWidth) {
            var minX = leftGroup.x + leftGroup.width + Theme.s2;
            var maxX = rightGroup.x - Theme.s2 - centerWidth;
            var preferredX = (width - centerWidth) / 2;
            if (maxX < minX) return minX;
            return Math.max(minX, Math.min(preferredX, maxX));
        }

        // ── High-Fidelity Glassmorphism Optical Substrate ─────────────
        // 1. Restrained smoked-wine depth wash. The translucent base lets KWin's
        // backdrop blur do the heavy lifting; this adds a soft tint, not an opaque fill.
        Rectangle {
            anchors.fill: parent
            z: 0
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Qt.rgba(1, 0.94, 0.96, 0.055) }
                GradientStop { position: 0.20; color: Qt.rgba(0.20, 0.055, 0.075, 0.10) }
                GradientStop { position: 0.72; color: Qt.rgba(0.025, 0.018, 0.026, 0.12) }
                GradientStop { position: 1.0; color: Qt.rgba(0.34, 0.045, 0.075, 0.22) }
            }
        }

        // 2. Sub-surface optical meniscus (inner top bevel): creates the 3D
        // optical refraction of a polished glass slab's top chamfer.
        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right }
                height: 4
            z: 1
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.18) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // 3. Soft edge falloff keeps the full-width strip distinct without crushing
        // wallpaper detail or making both ends look like opaque blocks.
        Rectangle {
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 150
            z: 1
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(0.035, 0.012, 0.020, 0.34) }
                GradientStop { position: 0.40; color: Qt.rgba(0.035, 0.012, 0.020, 0.12) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
        Rectangle {
            anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
            width: 150
            z: 1
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.60; color: Qt.rgba(0.035, 0.012, 0.020, 0.12) }
                GradientStop { position: 1.0; color: Qt.rgba(0.035, 0.012, 0.020, 0.34) }
            }
        }

        // 4. Multi-stop overhead Fresnel specular hairline (y = 0): diamond-bright center crest.
        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right }
            height: 1
            z: 2
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.15; color: Qt.rgba(1, 1, 1, 0.08) }
                GradientStop { position: 0.35; color: Qt.rgba(1, 1, 1, 0.11) }
                GradientStop { position: 0.50; color: Qt.rgba(1, 1, 1, 0.22) }
                GradientStop { position: 0.65; color: Qt.rgba(1, 1, 1, 0.11) }
                GradientStop { position: 0.85; color: Qt.rgba(1, 1, 1, 0.08) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // 5. Secondary machined inner bevel line (y = 1): simulates double-pass bevel refraction.
        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right; topMargin: 1 }
            height: 1
            z: 2
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.25; color: Qt.rgba(1, 1, 1, 0.04) }
                GradientStop { position: 0.50; color: Qt.rgba(1, 1, 1, 0.12) }
                GradientStop { position: 0.75; color: Qt.rgba(1, 1, 1, 0.04) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // 6. Sub-surface ambient laser bounce reflex: light-piped reflex from the FlowBand laser rail.
        Rectangle {
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
            height: 10
            z: 1
            opacity: 0.72 + 0.10 * Theme.heartbeatSin
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.55; color: Theme.alpha(Theme.crimson, 0.045) }
                GradientStop { position: 1.0; color: Theme.alpha(Theme.crimson, 0.13) }
            }
        }

        // 7. Luxury dual-beam caustic glass sweep: wide diffuse wave paired with a sharp crystalline micro-filament.
        Item {
            anchors.fill: parent
            clip: true
            z: 0

            Item {
                id: glossSweep
                width: 160
                height: 200
                y: (bar.height - height) / 2
                rotation: 24

                // Pass 1: Wide diffuse atmospheric caustic sheen
                Rectangle {
                    anchors.fill: parent
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: 0.35; color: Qt.rgba(1, 1, 1, 0.02) }
                        GradientStop { position: 0.50; color: Qt.rgba(1, 1, 1, 0.05) }
                        GradientStop { position: 0.65; color: Qt.rgba(1, 1, 1, 0.02) }
                        GradientStop { position: 1.0; color: "transparent" }
                    }
                }

                // Pass 2: High-definition crystalline specular core filament
                Rectangle {
                    anchors.centerIn: parent
                    width: 10
                    height: parent.height
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: 0.50; color: Qt.rgba(1, 1, 1, 0.10) }
                        GradientStop { position: 1.0; color: "transparent" }
                    }
                }

                SequentialAnimation on x {
                    loops: Animation.Infinite
                    PauseAnimation { duration: 14000 }
                    NumberAnimation {
                        from: -glossSweep.width
                        to: bar.width + glossSweep.width
                        duration: 2200
                        easing.type: Easing.InOutQuad
                    }
                }
            }
        }

        // Animated red / green / blue light filling the whole bar (the same
        // light as the dock, components/RgbFlow.qml). It lives inside the
        // glass and is declared before the pill groups, so every pill draws
        // on top of it; it inherits the glass's entry fade/slide.
        RgbFlow {
            anchors.fill: parent
            horizontal: true
            radius: 0
            amplitude: 1.15
            boosted: AgentState.status === "working"
            status: AgentState.status
            hovered: barHover.hovered
        }

        // ── left ──────────────────────────────────────────
        Row {
            id: leftGroup
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

                    ArgusMark {
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.crimson
                        liveColor: Theme.crimsonText
                        live: AgentState.status !== "idle"
                    }
                    Item {
                        id: kinetixWord
                        property bool live: AgentState.status !== "idle"
                        readonly property bool activeOrHovered: live || brandWorkspacesPill.hovered || barHover.hovered
                        property real tracking: live ? 2.75 : (brandWorkspacesPill.hovered ? 2.45 : 2.2)
                        property color signalColor: AgentState.status === "working" ? Theme.crimsonText
                                                  : AgentState.status === "watching" ? Theme.gilded
                                                  : AgentState.status === "blocked" ? Theme.alarm : Theme.crimson
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

                        // Drop shadow for crisp laser-engraved typography contrast
                        Text {
                            text: wordBase.text
                            color: Qt.rgba(0, 0, 0, 0.68)
                            font: wordBase.font
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.verticalCenterOffset: 1
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
                                color: kinetixWord.live ? Theme.alarm : Theme.crimsonText
                                opacity: kinetixWord.signalOpacity * (0.94 + kinetixWord.breath * 0.06)
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
                            GradientStop { position: 0.25; color: Theme.alpha(Theme.crimson, 0.40) }
                            GradientStop { position: 0.75; color: Theme.alpha(Theme.crimson, 0.40) }
                            GradientStop { position: 1.0; color: "transparent" }
                        }
                    }

                    Workspaces {
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }


        // ── center: Luxury Glass Time & Search Island ──
        BarBox {
            id: centerPill
            x: barGlass.centerIslandX(width)
            anchors.verticalCenter: parent.verticalCenter
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
                // Micro vertical center alignment
                anchors.verticalCenter: parent.verticalCenter

                Rectangle {
                    width: 18
                    height: 18
                    radius: 4.5
                    color: centerPill.hovered ? Theme.alpha(Theme.crimson, 0.28) : Theme.alpha(Theme.crimson, 0.10)
                    border.width: 1
                    border.color: centerPill.hovered ? Theme.alpha(Theme.crimson, 0.65) : Theme.alpha(Theme.crimson, 0.26)
                    anchors.verticalCenter: parent.verticalCenter
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                    Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                    // Upper micro-sheen on keycap
                    Rectangle {
                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
                        height: 1
                        radius: 4
                        color: Qt.rgba(1, 1, 1, centerPill.hovered ? 0.30 : 0.14)
                    }

                    KxIcon {
                        anchors.centerIn: parent
                        name: "command"
                        size: 12
                        stroke: 1.8
                        color: centerPill.hovered ? Theme.crimsonText : Theme.alpha(Theme.crimsonText, 0.90)
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                    }
                }

                ClockWidget {
                    id: clockItem
                    compact: bar.ultraCompactLayout
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }

        // ── right ─────────────────────────────────────────
        Row {
            id: rightGroup
            anchors { right: parent.right; rightMargin: Theme.s4; verticalCenter: parent.verticalCenter }
            spacing: Theme.s2
            opacity: bar.enterR
            transform: Translate { x: 14 * (1 - bar.enterR) }

            // App Center & Package Hub Capsule
            AppCenterCapsule {
                id: appCenterCap
                compact: bar.compactLayout
                anchors.verticalCenter: parent.verticalCenter
                onXChanged: bar.updatePopupOffsets()
                onWidthChanged: bar.updatePopupOffsets()
            }

            // Box 5: System telemetry capsule. The compact component keeps the
            // popup action while moving dense graphs into the existing detail view.
            Component {
                id: compactTelemetryComponent
                CompactTelemetry {}
            }
            Component {
                id: detailedTelemetryComponent
                SysMonitor {}
            }
            Loader {
                id: sysMonitorCap
                sourceComponent: bar.compactLayout ? compactTelemetryComponent : detailedTelemetryComponent
                anchors.verticalCenter: parent.verticalCenter
                onXChanged: bar.updatePopupOffsets()
                onWidthChanged: bar.updatePopupOffsets()
            }

            // Box 6: Media / Now Playing Capsule
            NowPlaying {
                compact: bar.compactLayout
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
                            GradientStop { position: 0.20; color: Theme.alpha(Theme.crimson, 0.35) }
                            GradientStop { position: 0.50; color: Qt.rgba(1, 1, 1, 0.25) }
                            GradientStop { position: 0.80; color: Theme.alpha(Theme.crimson, 0.35) }
                            GradientStop { position: 1.0; color: "transparent" }
                        }
                    }

                    StatusCluster {
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }

            // Box 7a: Update capsule — a badge when `kinetix check` reports
            // updates, click to run `kinetix update` in a terminal. New
            // addition borrowed from Omarchy; every capsule around it is
            // unchanged.
            UpdateCapsule {
                id: updateCap
                anchors.verticalCenter: parent.verticalCenter
            }

            // Box 7b: Notification bell — opens the Notification Center. Badge
            // shows the live count, a slash marks do-not-disturb, and the bell
            // rocks when something arrives.
            BarBox {
                id: notifBell
                implicitWidth: 44
                interactive: true
                active: AgentState.notifOpen
                activeColor: Theme.crimson
                anchors.verticalCenter: parent.verticalCenter
                onClicked: AgentState.toggleNotifs()
                HoverTip { target: notifBell; hovered: notifBell.hovered; text: Notif.dnd ? "Notifications (do not disturb)" : "Notifications" }

                Item {
                    id: bellArt
                    anchors.centerIn: parent
                    width: 18; height: 18
                    transformOrigin: Item.Top
                    SequentialAnimation {
                        id: ring
                        NumberAnimation { target: bellArt; property: "rotation"; to: 16; duration: 90; easing.type: Easing.OutQuad }
                        NumberAnimation { target: bellArt; property: "rotation"; to: -13; duration: 130; easing.type: Easing.InOutQuad }
                        NumberAnimation { target: bellArt; property: "rotation"; to: 9; duration: 120; easing.type: Easing.InOutQuad }
                        NumberAnimation { target: bellArt; property: "rotation"; to: -5; duration: 110; easing.type: Easing.InOutQuad }
                        NumberAnimation { target: bellArt; property: "rotation"; to: 0; duration: 140; easing.type: Easing.OutQuad }
                    }
                    Connections {
                        target: typeof Notif !== "undefined" ? Notif : null
                        ignoreUnknownSignals: true
                        function onArrived(nid, toasted) { ring.restart(); }
                    }
                    KxIcon {
                        id: bellCanvas
                        anchors.centerIn: parent
                        size: 18
                        name: (typeof Notif !== "undefined" && Notif && Notif.dnd) ? "bell-off" : "bell"
                        accent: Theme.warn
                        color: AgentState.notifOpen ? Theme.crimsonText
                             : (notifBell.hovered ? Theme.text : Theme.textDim)
                    }
                }
                Rectangle {
                    visible: Notif.count > 0
                    anchors { top: parent.top; right: parent.right; topMargin: 4; rightMargin: 5 }
                    width: Math.max(16, badgeText.implicitWidth + 8); height: 16; radius: 8
                    color: Theme.crimson
                    border.width: 1.5
                    border.color: Qt.rgba(0.06, 0.02, 0.03, 0.9)
                    scale: Notif.count > 0 ? 1 : 0
                    Behavior on scale { NumberAnimation { duration: 260; easing.type: Easing.OutBack } }
                    Text {
                        id: badgeText
                        anchors.centerIn: parent
                        text: (typeof Notif !== "undefined" && Notif && Notif.count > 9) ? "9+" : (typeof Notif !== "undefined" && Notif ? String(Notif.count) : "")
                        color: "white"
                        font { family: Theme.fontMono; pixelSize: 9; weight: Font.Bold }
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
                HoverTip { target: agentPill; hovered: bar.compactLayout && agentPill.hovered; text: "Kinetix agent" }

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
                    opacity: AgentState.status === "working" ? (0.35 + 0.45 * agentPill.pulse) : (agentPill.active ? 0.35 : (agentPill.hovered ? 0.18 : 0.0))
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
                    Item {
                        visible: !bar.compactLayout
                        implicitWidth: agentText.implicitWidth
                        implicitHeight: agentText.implicitHeight
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                            text: agentText.text
                            color: Qt.rgba(0, 0, 0, 0.65)
                            font: agentText.font
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: 1
                        }

                        Text {
                            id: agentText
                            text: "AGENT"
                            visible: !bar.compactLayout
                            color: agentPill.active ? Theme.crimsonText : (agentPill.hovered ? Theme.text : Theme.textDim)
                            font { family: Theme.fontMono; pixelSize: Theme.tCaption; letterSpacing: agentPill.active ? 1.8 : 1.5; weight: Font.DemiBold }
                            anchors.centerIn: parent
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        }
                    }
                }
            }
        }
    }

    HoverHandler {
        id: barHover
    }
}
