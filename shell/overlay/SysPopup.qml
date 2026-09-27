import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"
import "../components"

// Master-class System Resource & Telemetry Dropdown for Argus OS.
// Clickable dropdown from the quickshell bar's SysMonitor capsule with deep hardware insights,
// 24-core thread equalizer, detailed RAM/Swap breakdown, real-time Network I/O, Dual GPUs, and Top Processes.
// Designed with StyleX atomic tokens, physical glass specular reflections, and buttery 60fps animations.
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "argus:syspopup"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    visible: AgentState.sysOpen || pop.popProgress > 0.01

    // Fullscreen backdrop to cleanly dismiss dropdown on click-outside.
    // Explicitly geometry-checked against `pop` rather than relying on the
    // popup's own absorbing MouseArea (below) to out-stack this one — that
    // depends on sibling paint order, and a click squarely on a real control
    // inside the popup (verified: the "CPU & Cores" tab pill) was reaching
    // this handler and dismissing the whole popup instead of being consumed
    // by the tab's own MouseArea. Checking containment here removes the
    // dependency on that stacking behavior entirely.
    MouseArea {
        id: dismissArea
        anchors.fill: parent
        onClicked: function(mouse) {
            var p = mapToItem(pop, mouse.x, mouse.y);
            if (p.x >= 0 && p.x <= pop.width && p.y >= 0 && p.y <= pop.height) return;
            AgentState.sysOpen = false;
        }
    }

    // StyleX Design System Tokens — deep ominous crimson cockpit (docs/02,
    // "System Telemetry palette"), the same authority-surface treatment as
    // the Agent Panel / App Center. Every color in this whole file routes
    // through this one object, so this is the only place that needed to
    // change to retint the entire popup.
    QtObject {
        id: sx
        // Colors
        readonly property color bgGlass: Qt.rgba(0.086, 0.016, 0.022, 0.90)
        readonly property color surface0: Qt.rgba(1, 1, 1, 0.03)
        readonly property color surface1: Qt.rgba(1, 1, 1, 0.06)
        readonly property color surface2: Qt.rgba(1, 1, 1, 0.09)
        readonly property color surfaceCard: Qt.rgba(0.09, 0.043, 0.05, 0.75)
        readonly property color borderMuted: Qt.rgba(1, 1, 1, 0.07)
        readonly property color borderCard: Qt.rgba(1, 1, 1, 0.10)
        readonly property color borderActive: Theme.alpha(Theme.crimson, 0.40)
        readonly property color textPrimary: Theme.text
        readonly property color textSecondary: Theme.textDim
        readonly property color textTertiary: Theme.textFaint

        // Semantic Accent Colors — all one crimson family now, reusing the
        // exact roles docs/02 already defines for it (ember = calm/"ok",
        // gilded = elevated/caution, alarm = critical/error) rather than
        // inventing a second scale. Two metrics that sit side by side
        // (CPU/Memory in the Overview tab) keep distinct calm-state hues
        // (ember vs crimsonText) purely so the eye can tell them apart at a
        // glance — RX/TX keep the same ember/gilded pairing for the same
        // reason, which also happens to preserve the original "good vs
        // elevated" download/upload distinction.
        readonly property color cyan: Theme.ember          // CPU / primary metrics (calm)
        readonly property color violet: Theme.crimsonText  // Memory / Agent (calm)
        readonly property color emerald: Theme.ember       // Network RX / optimal state
        readonly property color amber: Theme.gilded        // Network TX / elevated
        readonly property color rose: Theme.alarm          // Critical load / high temp
        readonly property color indigo: Theme.gilded       // Cached memory (secondary)
        readonly property color sky: Theme.ember           // Storage (calm)

        // Direct family aliases — a few call sites reference these names
        // directly (storage IO beacon, disk R/W rates); without them the
        // runtime logs "Unable to assign [undefined] to QColor".
        readonly property color ember: Theme.ember
        readonly property color gilded: Theme.gilded

        // Spacing scale (4-point grid)
        readonly property int sp2: 2
        readonly property int sp4: 4
        readonly property int sp6: 6
        readonly property int sp8: 8
        readonly property int sp10: 10
        readonly property int sp12: 12
        readonly property int sp16: 16
        readonly property int sp20: 20
        readonly property int sp24: 24

        // Border Radii
        readonly property int rSm: 6
        readonly property int rMd: 10
        readonly property int rLg: 14
        readonly property int rXl: 18
        readonly property int rPill: 9999
    }

    GlassPanel {
        id: pop
        anchors {
            top: parent.top
            topMargin: 62
            right: parent.right
            rightMargin: Math.max(16, Math.min(parent.width - pop.width - 16, AgentState.sysRightMargin))
        }
        width: 540
        height: Math.min(680, mainCol.implicitHeight + sx.sp16 * 2)
        radius: sx.rXl
        level: 3
        baseColor: "#0F0709"   // deep ominous maroon base — matches the agent panel / App Center

        property real popProgress: AgentState.sysOpen ? 1.0 : 0.0
        opacity: popProgress
        scale: 0.96 + 0.04 * popProgress
        transform: Translate { y: -8 * (1.0 - pop.popProgress) }
        Behavior on popProgress { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

        // Eased headline numbers — the sampler updates once per second, and
        // without this every big % readout (Overview/CPU/Memory hero
        // numbers) snapped a full digit at a time on a 1s tick, while the
        // bar capsule right above it already glides smoothly between
        // samples. Tier/escalation colors below deliberately still key off
        // the raw SysInfo value, not these — a real spike into the critical
        // band should flag immediately, not wait out an ease curve.
        property real cpuVisual: SysInfo.cpu
        property real memVisual: SysInfo.memPct
        property real load1Visual: SysInfo.load1
        property real load5Visual: SysInfo.load5
        property real load15Visual: SysInfo.load15
        property real memAvailVisual: SysInfo.memAvail
        property real diskFreeVisual: SysInfo.diskFreeGb
        Behavior on cpuVisual { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
        Behavior on memVisual { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
        Behavior on load1Visual { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }
        Behavior on load5Visual { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }
        Behavior on load15Visual { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }
        Behavior on memAvailVisual { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }
        Behavior on diskFreeVisual { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }

        // Absorb clicks inside the popup so they never trigger dismissArea
        MouseArea {
            anchors.fill: parent
            onClicked: {}
        }

        // Top specular physical highlight
        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
            height: 1
            radius: sx.rXl
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.2; color: Qt.rgba(1, 1, 1, 0.18) }
                GradientStop { position: 0.8; color: Qt.rgba(1, 1, 1, 0.18) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // Active tab property (overview | cpu | memory | network | processes)
        property string currentTab: "overview"

        Column {
            id: mainCol
            anchors {
                left: parent.left; right: parent.right; top: parent.top
                margins: sx.sp16
            }
            spacing: sx.sp12

            // ── Top Header ──────────────────────────────────────────
            Row {
                width: parent.width
                spacing: sx.sp10

                // Heartbeat pulsating orb
                Item {
                    width: 10; height: 10
                    anchors.verticalCenter: parent.verticalCenter

                    Rectangle {
                        anchors.centerIn: parent
                        width: parent.width + 6; height: parent.height + 6
                        radius: width / 2
                        color: Theme.alpha(sx.cyan, 0.3)
                        SequentialAnimation on scale {
                            loops: Animation.Infinite
                            NumberAnimation { from: 0.8; to: 1.4; duration: 1200; easing.type: Easing.OutSine }
                            NumberAnimation { from: 1.4; to: 0.8; duration: 1200; easing.type: Easing.InSine }
                        }
                    }

                    Rectangle {
                        anchors.centerIn: parent
                        width: 8; height: 8
                        radius: 4
                        color: sx.cyan
                    }
                }

                Column {
                    spacing: 1
                    anchors.verticalCenter: parent.verticalCenter

                    Row {
                        spacing: sx.sp6
                        Text {
                            text: "SYSTEM TELEMETRY"
                            color: sx.textPrimary
                            font { family: Theme.fontMono; pixelSize: 11; weight: Font.Bold; letterSpacing: 1.5 }
                        }
                        Rectangle {
                            height: 14
                            implicitWidth: hostTxt.implicitWidth + 8
                            radius: sx.rPill
                            color: sx.surface2
                            border.width: 1
                            border.color: sx.borderCard
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                id: hostTxt
                                anchors.centerIn: parent
                                text: SysInfo.ready ? "LIVE · 1s" : "CONNECTING"
                                color: sx.cyan
                                font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold; letterSpacing: 0.8 }
                            }
                        }
                        // Only appears on a host that actually has a battery —
                        // most desktops (and this one) don't, and a permanent
                        // "no battery" badge would be exactly the kind of
                        // placeholder metric worth leaving out.
                        Rectangle {
                            visible: !!(typeof SysInfo !== "undefined" && SysInfo && SysInfo.batteryPresent)
                            height: 14
                            implicitWidth: battTxt.implicitWidth + 8
                            radius: sx.rPill
                            color: SysInfo.batteryPct < 20 && !SysInfo.batteryCharging ? Theme.alpha(sx.rose, 0.18) : sx.surface2
                            border.width: 1
                            border.color: SysInfo.batteryPct < 20 && !SysInfo.batteryCharging ? Theme.alpha(sx.rose, 0.5) : sx.borderCard
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                id: battTxt
                                anchors.centerIn: parent
                                text: (SysInfo.batteryCharging ? "⚡ " : "") + SysInfo.batteryPct + "%"
                                color: SysInfo.batteryPct < 20 && !SysInfo.batteryCharging ? sx.rose : sx.textSecondary
                                font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold; letterSpacing: 0.8 }
                            }
                        }
                    }

                    Text {
                        text: (SysInfo.hostname ? SysInfo.hostname + " · " : "") + SysInfo.kernel + " · " + (SysInfo.cpuCores > 0 ? (SysInfo.cpuCores + "T CPU · ") : "") + "Up " + SysInfo.uptime
                        color: sx.textTertiary
                        font { family: Theme.fontMono; pixelSize: 9 }
                    }
                }

                Item { width: Math.max(1, parent.width - x - closeBtn.width); height: 1 }

                CloseButton {
                    id: closeBtn
                    box: 24
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: AgentState.sysOpen = false
                }
            }

            // ── StyleX Sliding Tab Pill Selector ─────────────────────
            Rectangle {
                width: parent.width
                height: 30
                radius: sx.rPill
                color: sx.surface0
                border.width: 1
                border.color: sx.borderMuted

                readonly property var tabs: [
                    { id: "overview", label: "Overview" },
                    { id: "cpu", label: "CPU & Cores" },
                    { id: "memory", label: "Memory" },
                    { id: "network", label: "Network" },
                    { id: "processes", label: "Processes" }
                ]

                readonly property real tabWidth: (width - 4) / tabs.length
                readonly property int activeIdx: {
                    for (var i = 0; i < tabs.length; i++)
                        if (tabs[i].id === pop.currentTab) return i;
                    return 0;
                }

                // Sliding highlight pill
                Rectangle {
                    y: 2
                    x: 2 + parent.activeIdx * parent.tabWidth
                    width: parent.tabWidth
                    height: parent.height - 4
                    radius: sx.rPill
                    color: Theme.alpha(sx.cyan, 0.20)
                    border.width: 1
                    border.color: Theme.alpha(sx.cyan, 0.55)
                    Behavior on x { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutQuint } }

                    Rectangle {
                        anchors { top: parent.top; left: parent.left; right: parent.right; margins: 1 }
                        height: 1
                        radius: parent.radius
                        color: Qt.rgba(1, 1, 1, 0.20)
                    }
                }

                Row {
                    anchors.fill: parent
                    anchors.margins: 2

                    Repeater {
                        model: parent.parent.tabs
                        delegate: Item {
                            width: pop.width > 0 ? (pop.width - sx.sp16 * 2 - 4) / 5 : 100
                            height: parent.height

                            Text {
                                anchors.centerIn: parent
                                text: modelData.label
                                color: pop.currentTab === modelData.id ? sx.textPrimary : sx.textSecondary
                                font {
                                    family: Theme.fontUi
                                    pixelSize: Theme.tCaption
                                    weight: pop.currentTab === modelData.id ? Font.DemiBold : Font.Normal
                                }
                                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: pop.currentTab = modelData.id
                            }
                        }
                    }
                }
            }

            Rectangle { width: parent.width; height: 1; color: sx.borderMuted }

            // ── Dynamic Tab Content Container ─────────────────────────
            Item {
                width: parent.width
                implicitHeight: tabLoader.item ? tabLoader.item.implicitHeight : 380
                Behavior on implicitHeight { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

                Loader {
                    id: tabLoader
                    width: parent.width
                    active: AgentState.sysOpen || pop.popProgress > 0.01
                    opacity: 1
                    // A fresh tab's content fades and settles in rather than
                    // snapping into place — onLoaded fires every time the
                    // switch below actually swaps in a new component
                    // (including the very first tab), so this covers every
                    // tab change with no extra state to track.
                    Behavior on opacity { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
                    transform: Translate { y: (1 - tabLoader.opacity) * 6 }
                    onLoaded: { tabLoader.opacity = 0; tabRevealTimer.restart(); }
                    sourceComponent: {
                        switch (pop.currentTab) {
                        case "cpu": return cpuTabComp;
                        case "memory": return memTabComp;
                        case "network": return netTabComp;
                        case "processes": return procTabComp;
                        default: return overviewTabComp;
                        }
                    }
                }
                // Deferred one tick past onLoaded: setting opacity back to 1
                // in the very same handler that just set it to 0 collapses
                // into a single binding update with no visible transition —
                // the Behavior needs a frame boundary between the two writes
                // to actually animate anything.
                Timer { id: tabRevealTimer; interval: 1; onTriggered: tabLoader.opacity = 1 }
            }
        }

        // shared panel finish: rim, inner glass edge, the system's top light
        PopupChrome { anchors.fill: parent; radius: pop.radius }
    }

    // ═════════════════════════════════════════════════════════════════════════
    // TAB 1: OVERVIEW COCKPIT
    // ═════════════════════════════════════════════════════════════════════════
    Component {
        id: overviewTabComp
        Column {
            width: parent.width
            spacing: sx.sp10

            // Top Row: CPU Hero & RAM Hero
            Row {
                width: parent.width
                spacing: sx.sp10

                // CPU Summary Card
                Rectangle {
                    width: (parent.width - sx.sp10) / 2
                    height: 130
                    radius: sx.rLg
                    color: sx.surfaceCard
                    border.width: 1
                    border.color: SysInfo.cpu > 85 ? Theme.alpha(sx.rose, 0.55) : sx.borderCard
                    Behavior on border.color { ColorAnimation { duration: Theme.durMed } }

                    // Critical-load heartbeat: a slow, shared pulse (the same
                    // oscillator every other beacon in the shell uses, not a
                    // bespoke loop) rather than a static red border, so a
                    // pinned CPU actually reads as "alive and worth looking
                    // at" instead of just permanently red.
                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        color: "transparent"
                        border.width: 1
                        border.color: sx.rose
                        visible: SysInfo.cpu > 85
                        opacity: 0.18 + 0.24 * Theme.heartbeatSin
                    }

                    Column {
                        anchors.fill: parent
                        anchors.margins: sx.sp12
                        spacing: sx.sp6

                        Row {
                            width: parent.width
                            Text {
                                text: "PROCESSOR"
                                color: sx.textTertiary
                                font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1 }
                            }
                            Item { width: Math.max(1, parent.width - x - cpuExtra.width); height: 1 }
                            Row {
                                id: cpuExtra
                                spacing: 4
                                Text {
                                    visible: SysInfo.cpuFreq > 0
                                    text: SysInfo.cpuFreq.toFixed(1) + " GHz"
                                    color: sx.cyan
                                    font { family: Theme.fontMono; pixelSize: 9 }
                                }
                                Text {
                                    visible: SysInfo.cpuTemp > 0
                                    text: "· " + Math.round(SysInfo.cpuTemp) + "°C"
                                    color: SysInfo.cpuTemp > 80 ? sx.rose : (SysInfo.cpuTemp > 65 ? sx.amber : sx.textSecondary)
                                    font { family: Theme.fontMono; pixelSize: 9 }
                                }
                            }
                        }

                        Row {
                            spacing: sx.sp8
                            Text {
                                text: Math.round(pop.cpuVisual) + "%"
                                color: SysInfo.cpu > 85 ? sx.rose : (SysInfo.cpu > 55 ? sx.amber : sx.cyan)
                                font { family: Theme.fontMono; pixelSize: 26; weight: Font.Bold }
                                Behavior on color { ColorAnimation { duration: Theme.durMed } }
                            }
                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 1
                                Text {
                                    text: SysInfo.cpuCores > 0 ? (SysInfo.cpuCores + " Threads") : "Active"
                                    color: sx.textSecondary
                                    font { family: Theme.fontMono; pixelSize: 9; weight: Font.Medium }
                                }
                                Text {
                                    text: "Load " + pop.load1Visual.toFixed(1) + " / " + pop.load5Visual.toFixed(1) + " / " + pop.load15Visual.toFixed(1)
                                    color: sx.textTertiary
                                    font { family: Theme.fontMono; pixelSize: 8 }
                                }
                            }
                        }

                        Sparkline {
                            width: parent.width
                            height: 28
                            values: SysInfo.cpuHist
                            lineColor: SysInfo.cpu > 85 ? sx.rose : (SysInfo.cpu > 55 ? sx.amber : sx.cyan)
                            fillColor: Theme.alpha(lineColor, 0.25)
                            ceiling: 100
                            showDot: true
                        }
                    }
                }

                // RAM Summary Card
                Rectangle {
                    width: (parent.width - sx.sp10) / 2
                    height: 130
                    radius: sx.rLg
                    color: sx.surfaceCard
                    border.width: 1
                    border.color: SysInfo.memPct > 85 ? Theme.alpha(sx.rose, 0.55) : sx.borderCard
                    Behavior on border.color { ColorAnimation { duration: Theme.durMed } }

                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        color: "transparent"
                        border.width: 1
                        border.color: sx.rose
                        visible: SysInfo.memPct > 85
                        opacity: 0.18 + 0.24 * Theme.heartbeatSin
                    }

                    Column {
                        anchors.fill: parent
                        anchors.margins: sx.sp12
                        spacing: sx.sp6

                        Row {
                            width: parent.width
                            Text {
                                text: "MEMORY"
                                color: sx.textTertiary
                                font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1 }
                            }
                            Item { width: Math.max(1, parent.width - x - memRatio.width); height: 1 }
                            Text {
                                id: memRatio
                                text: SysInfo.fmtGB(SysInfo.memUsed) + " / " + SysInfo.fmtGB(SysInfo.memTotal) + " GB"
                                color: sx.textSecondary
                                font { family: Theme.fontMono; pixelSize: 9 }
                            }
                        }

                        Row {
                            spacing: sx.sp8
                            Text {
                                text: Math.round(pop.memVisual) + "%"
                                color: SysInfo.memPct > 85 ? sx.rose : (SysInfo.memPct > 65 ? sx.amber : sx.violet)
                                font { family: Theme.fontMono; pixelSize: 26; weight: Font.Bold }
                                Behavior on color { ColorAnimation { duration: Theme.durMed } }
                            }
                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 1
                                Text {
                                    text: "Swap " + Math.round(SysInfo.swapPct) + "% (" + SysInfo.fmtGB(SysInfo.swapUsed) + "G)"
                                    color: sx.textSecondary
                                    font { family: Theme.fontMono; pixelSize: 9; weight: Font.Medium }
                                }
                                Text {
                                    text: "Cached " + SysInfo.fmtGB(SysInfo.memCached) + " GB"
                                    color: sx.textTertiary
                                    font { family: Theme.fontMono; pixelSize: 8 }
                                }
                            }
                        }

                        Sparkline {
                            width: parent.width
                            height: 28
                            values: SysInfo.memHist
                            lineColor: SysInfo.memPct > 85 ? sx.rose : (SysInfo.memPct > 65 ? sx.amber : sx.violet)
                            fillColor: Theme.alpha(lineColor, 0.25)
                            ceiling: 100
                            showDot: true
                        }
                    }
                }
            }

            // Middle Row: Network Throughput Card
            Rectangle {
                width: parent.width
                height: 82
                radius: sx.rLg
                color: sx.surfaceCard
                border.width: 1
                border.color: sx.borderCard

                Row {
                    anchors.fill: parent
                    anchors.margins: sx.sp12
                    spacing: sx.sp12

                    Column {
                        width: 160
                        spacing: 4
                        Row {
                            spacing: sx.sp4
                            Rectangle {
                                width: 6; height: 6; radius: 3
                                color: sx.emerald
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: "NETWORK (" + SysInfo.netIface + ")"
                                color: sx.textTertiary
                                font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1 }
                            }
                        }
                        Row {
                            spacing: sx.sp6
                            Text {
                                text: "↓ " + SysInfo.fmtNet(SysInfo.rx)
                                color: sx.emerald
                                font { family: Theme.fontMono; pixelSize: 13; weight: Font.DemiBold }
                            }
                        }
                        Text {
                            text: "↑ " + SysInfo.fmtNet(SysInfo.tx) + " · " + SysInfo.rxTotalGb.toFixed(1) + " GB total"
                            color: sx.textSecondary
                            font { family: Theme.fontMono; pixelSize: 9 }
                        }
                    }

                    Item { width: Math.max(1, parent.width - x - netSpark.width); height: 1 }

                    Sparkline {
                        id: netSpark
                        width: parent.width - 180
                        height: 52
                        anchors.verticalCenter: parent.verticalCenter
                        values: SysInfo.netHist
                        lineColor: sx.emerald
                        fillColor: Theme.alpha(sx.emerald, 0.22)
                        ceiling: 0
                        showDot: true
                    }
                }
            }

            // Bottom Dual Cards: Dual GPU & Storage
            Row {
                width: parent.width
                spacing: sx.sp10

                // GPU Card
                Rectangle {
                    width: (parent.width - sx.sp10) / 2
                    height: 100
                    radius: sx.rLg
                    color: sx.surfaceCard
                    border.width: 1
                    border.color: sx.borderCard

                    Column {
                        anchors.fill: parent
                        anchors.margins: sx.sp12
                        spacing: 4

                        Text {
                            text: "GRAPHICS ACCELERATION"
                            color: sx.textTertiary
                            font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 }
                        }

                        Repeater {
                            model: (SysInfo.gpus && SysInfo.gpus.length > 0) ? SysInfo.gpus.slice(0, 2) : [{ name: "GPU", load: SysInfo.gpu, temp: SysInfo.gpuTemp, vram_used: 0, vram_total: 0, power_draw: 0 }]
                            delegate: Column {
                                required property var modelData
                                required property int index
                                width: parent.width
                                spacing: 1

                                Row {
                                    width: parent.width
                                    spacing: 4

                                    Text {
                                        width: 90
                                        text: modelData.name || ("GPU " + index)
                                        color: sx.textSecondary
                                        font { family: Theme.fontUi; pixelSize: 9; weight: Font.DemiBold }
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        text: Math.round(modelData.load) + "%"
                                        // GPU was the one metric in this popup with only two
                                        // tiers (elevated/normal) where CPU, memory, per-core
                                        // and the process table all escalate through three
                                        // (calm/elevated/critical) — added the missing
                                        // critical tier for consistency.
                                        color: modelData.load > 92 ? sx.rose : (modelData.load > 70 ? sx.amber : sx.textPrimary)
                                        font { family: Theme.fontMono; pixelSize: 9; weight: Font.DemiBold }
                                    }
                                    Item { width: Math.max(1, parent.width - x - gpuRightTxt.width); height: 1 }
                                    Text {
                                        id: gpuRightTxt
                                        text: (modelData.vram_total > 0 ? (Math.round(modelData.vram_used / 1024) + "/" + Math.round(modelData.vram_total / 1024) + "G · ") : "") + (modelData.temp > 0 ? Math.round(modelData.temp) + "°C" : "—")
                                        color: sx.textTertiary
                                        font { family: Theme.fontMono; pixelSize: 9 }
                                    }
                                }

                                // Power draw only when the driver actually reports
                                // one (nvidia-smi, or an AMD hwmon power1_average) —
                                // absent rather than a fake "0 W" on hosts that don't.
                                Text {
                                    visible: modelData.power_draw > 0
                                    text: modelData.power_draw.toFixed(0) + " W"
                                    color: sx.textTertiary
                                    font { family: Theme.fontMono; pixelSize: 8 }
                                }
                            }
                        }
                    }
                }

                // Storage Card
                Rectangle {
                    id: storageCard
                    width: (parent.width - sx.sp10) / 2
                    height: 100
                    radius: sx.rLg
                    color: sx.surfaceCard
                    border.width: 1
                    border.color: sx.borderCard

                    readonly property bool ioActive: (SysInfo.diskReadKbps + SysInfo.diskWriteKbps) > 20

                    Column {
                        anchors.fill: parent
                        anchors.margins: sx.sp12
                        spacing: 5

                        Row {
                            width: parent.width
                            spacing: 4
                            Rectangle {
                                width: 5; height: 5; radius: 2.5
                                anchors.verticalCenter: parent.verticalCenter
                                color: sx.ember
                                visible: storageCard.ioActive
                                opacity: 0.5 + 0.5 * Theme.heartbeatSin
                            }
                            Text {
                                text: "STORAGE (/)"
                                color: sx.textTertiary
                                font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 }
                            }
                            Item { width: Math.max(1, parent.width - x - diskVal.width); height: 1 }
                            Text {
                                id: diskVal
                                text: Math.round(SysInfo.disk) + "% Used"
                                color: SysInfo.disk > 90 ? sx.rose : sx.textPrimary
                                font { family: Theme.fontMono; pixelSize: 9; weight: Font.DemiBold }
                            }
                        }

                        // Storage bar
                        Rectangle {
                            width: parent.width
                            height: 6
                            radius: 3
                            color: sx.surface0
                            Rectangle {
                                width: parent.width * (Math.min(100, Math.max(0, SysInfo.disk)) / 100)
                                height: parent.height
                                radius: 3
                                color: SysInfo.disk > 90 ? sx.rose : sx.sky
                                Behavior on width { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }
                            }
                        }

                        Text {
                            text: (SysInfo.diskTotalGb > 0 ? pop.diskFreeVisual.toFixed(0) : "—") + " GB free · " + (SysInfo.diskTotalGb > 0 ? SysInfo.diskTotalGb.toFixed(0) : "—") + " GB total"
                            color: sx.textTertiary
                            font { family: Theme.fontMono; pixelSize: 9 }
                        }

                        // Live read/write throughput — the one storage signal
                        // this card was missing entirely: %used says nothing
                        // about whether the disk is doing anything right now.
                        Row {
                            spacing: sx.sp10
                            Text {
                                text: "R " + SysInfo.fmtNet(SysInfo.diskReadKbps)
                                color: sx.ember
                                font { family: Theme.fontMono; pixelSize: 8; weight: Font.DemiBold }
                            }
                            Text {
                                text: "W " + SysInfo.fmtNet(SysInfo.diskWriteKbps)
                                color: sx.gilded
                                font { family: Theme.fontMono; pixelSize: 8; weight: Font.DemiBold }
                            }
                        }
                    }
                }
            }

            // Supporting capacity metrics stay on the Overview tab instead
            // of requiring a drill-down. The slender accent rail and eased
            // utilization tracks make this read as one intentional status
            // strip rather than another row of generic cards.
            Row {
                width: parent.width
                spacing: sx.sp8

                Repeater {
                    model: [
                        { label: "LOAD AVG · 1 / 5 / 15", value: SysInfo.ready ? pop.load1Visual.toFixed(1) + " · " + pop.load5Visual.toFixed(1) + " · " + pop.load15Visual.toFixed(1) : "—", ratio: Math.min(100, SysInfo.cpuCores > 0 ? SysInfo.load1 * 100 / SysInfo.cpuCores : SysInfo.load1 * 10), tone: sx.cyan },
                        { label: "MEMORY AVAILABLE", value: SysInfo.ready ? pop.memAvailVisual.toFixed(1) + " GB" : "—", ratio: SysInfo.memTotal > 0 ? SysInfo.memAvail / SysInfo.memTotal * 100 : 0, tone: sx.violet },
                        { label: "ROOT VOLUME FREE", value: SysInfo.diskTotalGb > 0 ? pop.diskFreeVisual.toFixed(1) + " GB" : "—", ratio: SysInfo.diskTotalGb > 0 ? SysInfo.diskFreeGb / SysInfo.diskTotalGb * 100 : 0, tone: sx.sky }
                    ]
                    delegate: Rectangle {
                        required property var modelData
                        width: (parent.width - sx.sp8 * 2) / 3
                        height: 62
                        radius: sx.rMd
                        color: sx.surfaceCard
                        border.width: 1
                        border.color: sx.borderCard
                        clip: true

                        Rectangle {
                            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                            width: 2
                            color: modelData.tone
                            opacity: 0.72
                        }

                        Column {
                            anchors.fill: parent
                            anchors.leftMargin: sx.sp10
                            anchors.rightMargin: sx.sp8
                            anchors.topMargin: sx.sp8
                            anchors.bottomMargin: sx.sp6
                            spacing: 5

                            Text {
                                width: parent.width
                                text: modelData.label
                                color: sx.textTertiary
                                font { family: Theme.fontMono; pixelSize: 7; letterSpacing: 0.55; weight: Font.DemiBold }
                                elide: Text.ElideRight
                            }
                            Text {
                                width: parent.width
                                text: modelData.value
                                color: sx.textPrimary
                                font { family: Theme.fontMono; pixelSize: 12; weight: Font.DemiBold }
                                elide: Text.ElideRight
                            }
                        }

                        Rectangle {
                            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                            height: 2
                            color: sx.surface1
                            Rectangle {
                                width: parent.width * Math.max(0, Math.min(100, modelData.ratio)) / 100
                                height: parent.height
                                color: modelData.tone
                                Behavior on width { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }
                            }
                        }
                    }
                }
            }
        }
    }

    // ═════════════════════════════════════════════════════════════════════════
    // TAB 2: CPU & MULTI-CORE EQUALIZER
    // ═════════════════════════════════════════════════════════════════════════
    Component {
        id: cpuTabComp
        Column {
            width: parent.width
            spacing: sx.sp12

            // Processor identity — absent entirely until now; a telemetry
            // cockpit that never names the actual chip it's watching is
            // missing the one fact that doesn't change every second.
            Text {
                visible: SysInfo.cpuModel !== ""
                text: SysInfo.cpuModel
                color: sx.textSecondary
                font { family: Theme.fontMono; pixelSize: 10; weight: Font.Medium }
                elide: Text.ElideRight
                width: parent.width
            }

            // Top Status Bar
            Rectangle {
                width: parent.width
                height: 60
                radius: sx.rMd
                color: sx.surfaceCard
                border.width: 1
                border.color: sx.borderCard

                Row {
                    anchors.fill: parent
                    anchors.margins: sx.sp12
                    spacing: sx.sp16

                    Column {
                        spacing: 1
                        Text {
                            text: "OVERALL LOAD"
                            color: sx.textTertiary
                            font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 }
                        }
                        Text {
                            text: Math.round(pop.cpuVisual) + "%"
                            color: SysInfo.cpu > 85 ? sx.rose : (SysInfo.cpu > 55 ? sx.amber : sx.cyan)
                            font { family: Theme.fontMono; pixelSize: 18; weight: Font.Bold }
                            Behavior on color { ColorAnimation { duration: Theme.durMed } }
                        }
                    }

                    Rectangle { width: 1; height: 32; color: sx.borderMuted; anchors.verticalCenter: parent.verticalCenter }

                    Column {
                        spacing: 1
                        Text {
                            text: "FREQUENCY"
                            color: sx.textTertiary
                            font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 }
                        }
                        Text {
                            text: SysInfo.cpuFreq > 0 ? (SysInfo.cpuFreq.toFixed(2) + " GHz") : "—"
                            color: sx.cyan
                            font { family: Theme.fontMono; pixelSize: 14; weight: Font.DemiBold }
                        }
                    }

                    Rectangle { width: 1; height: 32; color: sx.borderMuted; anchors.verticalCenter: parent.verticalCenter }

                    Column {
                        spacing: 1
                        Text {
                            text: "PACKAGE TEMP"
                            color: sx.textTertiary
                            font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 }
                        }
                        Text {
                            text: SysInfo.cpuTemp > 0 ? (Math.round(SysInfo.cpuTemp) + "°C") : "—"
                            color: SysInfo.cpuTemp > 80 ? sx.rose : (SysInfo.cpuTemp > 65 ? sx.amber : sx.emerald)
                            font { family: Theme.fontMono; pixelSize: 14; weight: Font.DemiBold }
                        }
                    }

                    Rectangle { width: 1; height: 32; color: sx.borderMuted; anchors.verticalCenter: parent.verticalCenter }

                    Column {
                        spacing: 1
                        Text {
                            text: "LOAD AVERAGE"
                            color: sx.textTertiary
                            font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 }
                        }
                        Text {
                            text: SysInfo.load1.toFixed(2) + " · " + SysInfo.load5.toFixed(2) + " · " + SysInfo.load15.toFixed(2)
                            color: sx.textSecondary
                            font { family: Theme.fontMono; pixelSize: 11; weight: Font.Medium }
                        }
                    }

                    // Only appears when the host actually exposes a working
                    // fan sensor — most desktops/VMs don't, and a permanent
                    // "FAN: —" would be exactly the kind of placeholder
                    // metric worth leaving out entirely.
                    Rectangle {
                        width: 1; height: 32; color: sx.borderMuted
                        anchors.verticalCenter: parent.verticalCenter
                        visible: SysInfo.fans && SysInfo.fans.length > 0
                    }
                    Column {
                        spacing: 1
                        visible: SysInfo.fans && SysInfo.fans.length > 0
                        Text {
                            text: "FAN SPEED"
                            color: sx.textTertiary
                            font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 }
                        }
                        Text {
                            text: (SysInfo.fans && SysInfo.fans.length > 0)
                                  ? SysInfo.fans.map(function(f) { return f.rpm; }).join(" · ") + " RPM"
                                  : "—"
                            color: sx.textSecondary
                            font { family: Theme.fontMono; pixelSize: 11; weight: Font.Medium }
                        }
                    }
                }
            }

            // 24-Core Thread Activity Equalizer
            Rectangle {
                width: parent.width
                implicitHeight: coreGridCol.implicitHeight + sx.sp12 * 2
                radius: sx.rLg
                color: sx.surfaceCard
                border.width: 1
                border.color: sx.borderCard

                Column {
                    id: coreGridCol
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: sx.sp12 }
                    spacing: sx.sp8

                    Row {
                        width: parent.width
                        Text {
                            text: "LOGICAL THREADS EQUALIZER (" + (SysInfo.coreLoads ? SysInfo.coreLoads.length : 0) + " CORES)"
                            color: sx.textTertiary
                            font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                        }
                    }

                    Grid {
                        width: parent.width
                        columns: 6
                        spacing: 6

                        Repeater {
                            model: SysInfo.coreLoads || []
                            delegate: Rectangle {
                                id: coreCell
                                required property real modelData
                                required property int index
                                readonly property real coreFreq: (SysInfo.coreFreqs && SysInfo.coreFreqs.length > index) ? SysInfo.coreFreqs[index] : 0
                                width: Math.floor((coreGridCol.width - 30) / 6)
                                height: coreFreq > 0 ? 48 : 38
                                radius: sx.rSm
                                color: sx.surface1
                                border.width: 1
                                border.color: modelData > 70 ? Theme.alpha(sx.amber, 0.4) : sx.borderMuted

                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 4
                                    spacing: 3

                                    Row {
                                        width: parent.width
                                        Text {
                                            text: "C" + (index < 9 ? "0" : "") + (index + 1)
                                            color: sx.textTertiary
                                            font { family: Theme.fontMono; pixelSize: 8 }
                                        }
                                        Item { width: Math.max(1, parent.width - x - cPct.width); height: 1 }
                                        Text {
                                            id: cPct
                                            text: Math.round(modelData) + "%"
                                            color: modelData > 85 ? sx.rose : (modelData > 55 ? sx.amber : sx.cyan)
                                            font { family: Theme.fontMono; pixelSize: 8; weight: Font.DemiBold }
                                        }
                                    }

                                    Rectangle {
                                        width: parent.width
                                        height: 4
                                        radius: 2
                                        color: sx.surface0
                                        Rectangle {
                                            width: parent.width * (Math.min(100, Math.max(0, modelData)) / 100)
                                            height: parent.height
                                            radius: 2
                                            color: modelData > 85 ? sx.rose : (modelData > 55 ? sx.amber : sx.cyan)
                                            Behavior on width { NumberAnimation { duration: 350; easing.type: Easing.OutCubic } }
                                        }
                                    }

                                    // Per-core clock — makes turbo boost and core
                                    // parking actually visible instead of just an
                                    // aggregate GHz number for the whole package.
                                    Text {
                                        visible: coreCell.coreFreq > 0
                                        text: coreCell.coreFreq.toFixed(2) + " GHz"
                                        color: sx.textTertiary
                                        font { family: Theme.fontMono; pixelSize: 7 }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // CPU Load History Sparkline
            Rectangle {
                width: parent.width
                height: 80
                radius: sx.rMd
                color: sx.surfaceCard
                border.width: 1
                border.color: sx.borderCard

                Column {
                    anchors.fill: parent
                    anchors.margins: sx.sp10
                    spacing: 4
                    Text {
                        text: "CPU ACTIVITY TIMELINE (48s BUFFER)"
                        color: sx.textTertiary
                        font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 }
                    }
                    Sparkline {
                        width: parent.width
                        height: 42
                        values: SysInfo.cpuHist
                        lineColor: SysInfo.cpu > 85 ? sx.rose : (SysInfo.cpu > 55 ? sx.amber : sx.cyan)
                        fillColor: Theme.alpha(lineColor, 0.28)
                        ceiling: 100
                        showDot: true
                    }
                }
            }
        }
    }

    // ═════════════════════════════════════════════════════════════════════════
    // TAB 3: MEMORY & SWAP
    // ═════════════════════════════════════════════════════════════════════════
    Component {
        id: memTabComp
        Column {
            width: parent.width
            spacing: sx.sp12

            // Memory Hero Overview
            Rectangle {
                width: parent.width
                implicitHeight: memHeroCol.implicitHeight + sx.sp12 * 2
                radius: sx.rLg
                color: sx.surfaceCard
                border.width: 1
                border.color: sx.borderCard

                Column {
                    id: memHeroCol
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: sx.sp12 }
                    spacing: sx.sp10

                    Row {
                        width: parent.width
                        Text {
                            text: "PHYSICAL MEMORY DISTRIBUTION"
                            color: sx.textTertiary
                            font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                        }
                        Item { width: Math.max(1, parent.width - x - memTotalText.width); height: 1 }
                        Text {
                            id: memTotalText
                            text: SysInfo.fmtGB(SysInfo.memUsed) + " GB used of " + SysInfo.fmtGB(SysInfo.memTotal) + " GB (" + Math.round(SysInfo.memPct) + "%)"
                            color: sx.violet
                            font { family: Theme.fontMono; pixelSize: 10; weight: Font.DemiBold }
                        }
                    }

                    // Multi-Segment RAM Allocation Rail
                    Rectangle {
                        width: parent.width
                        height: 12
                        radius: 6
                        color: sx.surface0
                        clip: true

                        Row {
                            anchors.fill: parent

                            // Active Used Segment
                            Rectangle {
                                height: parent.height
                                width: parent.width * (Math.min(100, Math.max(0, SysInfo.memPct)) / 100)
                                color: sx.violet
                                Behavior on width { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }
                            }

                            // Cached Segment
                            Rectangle {
                                height: parent.height
                                width: SysInfo.memTotal > 0 ? (parent.width * (SysInfo.memCached / SysInfo.memTotal)) : 0
                                color: sx.indigo
                                Behavior on width { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }
                            }
                        }
                    }

                    // Memory Legend
                    Row {
                        width: parent.width
                        spacing: sx.sp16

                        Row {
                            spacing: 4
                            Rectangle { width: 8; height: 8; radius: 2; color: sx.violet; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: "Active Used: " + SysInfo.fmtGB(SysInfo.memUsed) + " GB"; color: sx.textSecondary; font { family: Theme.fontMono; pixelSize: 9 } }
                        }
                        Row {
                            spacing: 4
                            Rectangle { width: 8; height: 8; radius: 2; color: sx.indigo; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: "Page Cache: " + SysInfo.fmtGB(SysInfo.memCached) + " GB"; color: sx.textSecondary; font { family: Theme.fontMono; pixelSize: 9 } }
                        }
                        Row {
                            spacing: 4
                            Rectangle { width: 8; height: 8; radius: 2; color: sx.surface2; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: "Free: " + SysInfo.fmtGB(SysInfo.memFree) + " GB"; color: sx.textSecondary; font { family: Theme.fontMono; pixelSize: 9 } }
                        }
                    }
                }
            }

            // Memory Breakdown Details Cards
            Row {
                width: parent.width
                spacing: sx.sp10

                Rectangle {
                    width: (parent.width - sx.sp10) / 2
                    height: 86
                    radius: sx.rMd
                    color: sx.surfaceCard
                    border.width: 1
                    border.color: sx.borderCard

                    Column {
                        anchors.fill: parent
                        anchors.margins: sx.sp10
                        spacing: 4
                        Text { text: "ALLOCATION AVAILABILITY"; color: sx.textTertiary; font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 } }
                        Text {
                            text: SysInfo.fmtGB(SysInfo.memAvail) + " GB Available"; color: sx.emerald
                            font { family: Theme.fontMono; pixelSize: 14; weight: Font.Bold }
                        }
                        Text { text: "Apps can allocate without swapping"; color: sx.textSecondary; font { family: Theme.fontUi; pixelSize: 9 } }
                    }
                }

                // Swap Space Card
                Rectangle {
                    width: (parent.width - sx.sp10) / 2
                    height: 86
                    radius: sx.rMd
                    color: sx.surfaceCard
                    border.width: 1
                    border.color: sx.borderCard

                    Column {
                        anchors.fill: parent
                        anchors.margins: sx.sp10
                        spacing: 4
                        Text { text: "VIRTUAL SWAP SPACE"; color: sx.textTertiary; font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 } }
                        Row {
                            spacing: 6
                            Text {
                                text: Math.round(SysInfo.swapPct) + "%"; color: SysInfo.swapPct > 50 ? sx.amber : sx.textPrimary
                                font { family: Theme.fontMono; pixelSize: 14; weight: Font.Bold }
                            }
                            Text {
                                text: "(" + SysInfo.fmtGB(SysInfo.swapUsed) + "G / " + SysInfo.fmtGB(SysInfo.swapTotal) + "G)"; color: sx.textSecondary
                                font { family: Theme.fontMono; pixelSize: 10 }
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        Rectangle {
                            width: parent.width; height: 4; radius: 2; color: sx.surface0
                            Rectangle {
                                width: parent.width * (Math.min(100, Math.max(0, SysInfo.swapPct)) / 100)
                                height: parent.height; radius: 2; color: SysInfo.swapPct > 50 ? sx.amber : sx.violet
                                Behavior on width { NumberAnimation { duration: 550; easing.type: Easing.OutCubic } }
                            }
                        }
                    }
                }
            }

            // RAM Activity Sparkline
            Rectangle {
                width: parent.width
                height: 80
                radius: sx.rMd
                color: sx.surfaceCard
                border.width: 1
                border.color: sx.borderCard

                Column {
                    anchors.fill: parent
                    anchors.margins: sx.sp10
                    spacing: 4
                    Text { text: "MEMORY UTILIZATION TIMELINE"; color: sx.textTertiary; font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 } }
                    Sparkline {
                        width: parent.width
                        height: 42
                        values: SysInfo.memHist
                        lineColor: sx.violet
                        fillColor: Theme.alpha(sx.violet, 0.25)
                        ceiling: 100
                        showDot: true
                    }
                }
            }
        }
    }

    // ═════════════════════════════════════════════════════════════════════════
    // TAB 4: NETWORK TELEMETRY
    // ═════════════════════════════════════════════════════════════════════════
    Component {
        id: netTabComp
        Column {
            width: parent.width
            spacing: sx.sp12

            // Active Interface Banner
            Rectangle {
                width: parent.width
                height: 48
                radius: sx.rMd
                color: sx.surfaceCard
                border.width: 1
                border.color: sx.borderCard

                Row {
                    anchors.fill: parent
                    anchors.margins: sx.sp12
                    spacing: sx.sp8

                    Rectangle {
                        width: 8; height: 8; radius: 4; color: sx.emerald
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Text {
                        text: "PRIMARY INTERFACE:"
                        color: sx.textTertiary
                        font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1 }
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Text {
                        text: SysInfo.netIface
                        color: sx.textPrimary
                        font { family: Theme.fontMono; pixelSize: 11; weight: Font.Bold }
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Rectangle {
                        height: 16
                        implicitWidth: linkStateTxt.implicitWidth + 8
                        radius: sx.rPill
                        color: Theme.alpha(sx.emerald, 0.15)
                        border.width: 1
                        border.color: Theme.alpha(sx.emerald, 0.4)
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            id: linkStateTxt
                            anchors.centerIn: parent
                            text: "LINK ACTIVE"
                            color: sx.emerald
                            font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                        }
                    }

                    Text {
                        visible: SysInfo.netIp !== ""
                        text: SysInfo.netIp
                        color: sx.textSecondary
                        font { family: Theme.fontMono; pixelSize: 9 }
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Item { width: Math.max(1, parent.width - x - totalTransTxt.width); height: 1 }

                    Text {
                        id: totalTransTxt
                        text: "Session: ↓" + SysInfo.rxTotalGb.toFixed(2) + "G  ↑" + SysInfo.txTotalGb.toFixed(2) + "G"
                        color: sx.textSecondary
                        font { family: Theme.fontMono; pixelSize: 9 }
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }

            // Dual Real-Time Throughput Gauges (RX & TX)
            Row {
                width: parent.width
                spacing: sx.sp10

                // Download Card
                Rectangle {
                    width: (parent.width - sx.sp10) / 2
                    height: 120
                    radius: sx.rLg
                    color: sx.surfaceCard
                    border.width: 1
                    border.color: sx.borderCard

                    Column {
                        anchors.fill: parent
                        anchors.margins: sx.sp12
                        spacing: 4

                        Text { text: "DOWNLOAD SPEED (RX)"; color: sx.textTertiary; font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 } }
                        Text {
                            text: "↓ " + SysInfo.fmtNet(SysInfo.rx)
                            color: sx.emerald
                            font { family: Theme.fontMono; pixelSize: 18; weight: Font.Bold }
                        }
                        Text {
                            text: "Total Downloaded: " + SysInfo.rxTotalGb.toFixed(2) + " GB"
                            color: sx.textSecondary
                            font { family: Theme.fontMono; pixelSize: 8 }
                        }
                        Sparkline {
                            width: parent.width
                            height: 32
                            values: SysInfo.rxHist
                            lineColor: sx.emerald
                            fillColor: Theme.alpha(sx.emerald, 0.25)
                            ceiling: 0
                            showDot: true
                        }
                    }
                }

                // Upload Card
                Rectangle {
                    width: (parent.width - sx.sp10) / 2
                    height: 120
                    radius: sx.rLg
                    color: sx.surfaceCard
                    border.width: 1
                    border.color: sx.borderCard

                    Column {
                        anchors.fill: parent
                        anchors.margins: sx.sp12
                        spacing: 4

                        Text { text: "UPLOAD SPEED (TX)"; color: sx.textTertiary; font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1 } }
                        Text {
                            text: "↑ " + SysInfo.fmtNet(SysInfo.tx)
                            color: sx.amber
                            font { family: Theme.fontMono; pixelSize: 18; weight: Font.Bold }
                        }
                        Text {
                            text: "Total Uploaded: " + SysInfo.txTotalGb.toFixed(2) + " GB"
                            color: sx.textSecondary
                            font { family: Theme.fontMono; pixelSize: 8 }
                        }
                        Sparkline {
                            width: parent.width
                            height: 32
                            values: SysInfo.txHist
                            lineColor: sx.amber
                            fillColor: Theme.alpha(sx.amber, 0.25)
                            ceiling: 0
                            showDot: true
                        }
                    }
                }
            }

            // Interface Inventory Table
            Rectangle {
                width: parent.width
                implicitHeight: ifaceCol.implicitHeight + sx.sp12 * 2
                radius: sx.rMd
                color: sx.surfaceCard
                border.width: 1
                border.color: sx.borderCard

                Column {
                    id: ifaceCol
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: sx.sp12 }
                    spacing: 6

                    Text {
                        text: "DETECTED PHYSICAL & WIRELESS ADAPTERS"
                        color: sx.textTertiary
                        font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1.2 }
                    }

                    Repeater {
                        model: SysInfo.netInterfaces || []
                        delegate: Rectangle {
                            required property var modelData
                            width: ifaceCol.width
                            height: 28
                            radius: sx.rSm
                            color: sx.surface0

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: 8; anchors.rightMargin: 8
                                spacing: 8
                                Text {
                                    text: modelData.name
                                    color: sx.textPrimary
                                    font { family: Theme.fontMono; pixelSize: 9; weight: Font.Bold }
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    visible: !!modelData.ip
                                    text: modelData.ip || ""
                                    color: sx.textTertiary
                                    font { family: Theme.fontMono; pixelSize: 8 }
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: modelData.name === SysInfo.netIface ? "(Default Gateway)" : ""
                                    color: sx.emerald
                                    font { family: Theme.fontMono; pixelSize: 8 }
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Item { width: Math.max(1, parent.width - x - ifaceSpeeds.width); height: 1 }
                                Row {
                                    id: ifaceSpeeds
                                    spacing: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text {
                                        text: "↓ " + (modelData.rx_kbps ? SysInfo.fmtNet(modelData.rx_kbps) : "0 KB/s")
                                        color: sx.emerald
                                        font { family: Theme.fontMono; pixelSize: 9 }
                                    }
                                    Text {
                                        text: "↑ " + (modelData.tx_kbps ? SysInfo.fmtNet(modelData.tx_kbps) : "0 KB/s")
                                        color: sx.amber
                                        font { family: Theme.fontMono; pixelSize: 9 }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ═════════════════════════════════════════════════════════════════════════
    // TAB 5: TOP ACTIVE PROCESSES
    // ═════════════════════════════════════════════════════════════════════════
    Component {
        id: procTabComp
        Column {
            width: parent.width
            spacing: sx.sp10

            Rectangle {
                width: parent.width
                implicitHeight: procTableCol.implicitHeight + sx.sp12 * 2
                radius: sx.rLg
                color: sx.surfaceCard
                border.width: 1
                border.color: sx.borderCard

                Column {
                    id: procTableCol
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: sx.sp12 }
                    spacing: 6

                    Row {
                        width: parent.width
                        Text {
                            text: "TOP RESOURCE-CONSUMING PROCESSES"
                            color: sx.textTertiary
                            font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                        }
                        Item { width: Math.max(1, parent.width - x - procLiveRate.width); height: 1 }
                        Text {
                            id: procLiveRate
                            text: "Live 1s Refresh"
                            color: sx.emerald
                            font { family: Theme.fontMono; pixelSize: 8 }
                        }
                    }

                    // Table Header
                    Rectangle {
                        width: parent.width
                        height: 22
                        radius: sx.rSm
                        color: sx.surface1
                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 8; anchors.rightMargin: 8
                            Text { width: 56; text: "PID"; color: sx.textTertiary; font { family: Theme.fontMono; pixelSize: 8 } anchors.verticalCenter: parent.verticalCenter }
                            Text { width: 180; text: "COMMAND"; color: sx.textTertiary; font { family: Theme.fontMono; pixelSize: 8 } anchors.verticalCenter: parent.verticalCenter }
                            Text { width: 90; text: "CPU USAGE"; color: sx.textTertiary; font { family: Theme.fontMono; pixelSize: 8 } anchors.verticalCenter: parent.verticalCenter }
                            Text { width: 70; text: "MEM %"; color: sx.textTertiary; font { family: Theme.fontMono; pixelSize: 8 } anchors.verticalCenter: parent.verticalCenter }
                            Text { text: "ACTIVITY"; color: sx.textTertiary; font { family: Theme.fontMono; pixelSize: 8 } anchors.verticalCenter: parent.verticalCenter }
                        }
                    }

                    // Table Rows
                    Repeater {
                        model: SysInfo.topProcs || []
                        delegate: Rectangle {
                            required property var modelData
                            width: procTableCol.width
                            height: 30
                            radius: sx.rSm
                            color: pMa.containsMouse ? sx.surface2 : sx.surface0

                            MouseArea {
                                id: pMa
                                anchors.fill: parent
                                hoverEnabled: true
                            }

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: 8; anchors.rightMargin: 8

                                Text {
                                    width: 56
                                    text: String(modelData.pid)
                                    color: sx.textSecondary
                                    font { family: Theme.fontMono; pixelSize: 9 }
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Text {
                                    width: 180
                                    text: modelData.name
                                    color: sx.textPrimary
                                    font { family: Theme.fontMono; pixelSize: 9; weight: Font.DemiBold }
                                    elide: Text.ElideRight
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Text {
                                    width: 90
                                    text: modelData.cpu.toFixed(1) + "%"
                                    color: modelData.cpu > 80 ? sx.rose : (modelData.cpu > 20 ? sx.amber : sx.cyan)
                                    font { family: Theme.fontMono; pixelSize: 9; weight: Font.DemiBold }
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Text {
                                    width: 70
                                    text: modelData.mem.toFixed(1) + "%"
                                    color: sx.violet
                                    font { family: Theme.fontMono; pixelSize: 9 }
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                // Micro Activity Level Bar
                                Rectangle {
                                    width: 80
                                    height: 5
                                    radius: 2.5
                                    color: sx.surface1
                                    anchors.verticalCenter: parent.verticalCenter

                                    Rectangle {
                                        width: parent.width * (Math.min(100, Math.max(0, modelData.cpu)) / 100)
                                        height: parent.height
                                        radius: 2.5
                                        color: modelData.cpu > 80 ? sx.rose : (modelData.cpu > 20 ? sx.amber : sx.cyan)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
