import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "../common"
import "../components"
import "Markdown.js" as MD

PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; bottom: true; right: true }
    margins { top: 62; bottom: 14; right: 14 }
    implicitWidth: 440
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "argus:agent"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: (AgentState.panelOpen && AgentState.status === "idle")
                                 ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    // No custom input mask: none of this shell's other slide-in overlays
    // (CommandPalette, AppLauncher, SysPopup — all use the same `transform:
    // Translate` slide-animation pattern as `panel` below) define one
    // either, and they all take real clicks correctly. `Region { item:
    // panel }` looked like the more precise choice (restrict input to the
    // actual glass card, not this window's full reserved column) but it
    // silently broke every button in the panel: confirmed live — a
    // pixel-verified, fully-converged click (kwin.click() reporting
    // residual 0) on the close button, a header tab, and a mid-panel
    // toggle switch all did nothing, on a freshly restarted shell process,
    // while the exact same click coordinates worked instantly on the top
    // bar and its popups. Losing the mask means a click in this window's
    // ~16px Theme.s4 margin around the card (not the card itself) is
    // swallowed instead of passing through — a minor, barely-visible
    // tradeoff against a panel whose buttons work at all.
    visible: AgentState.panelOpen || panel.progress > 0.01

    // ── Ominous red identity — this panel only ──────────────────────────
    // The rest of the OS (bar, launcher, palette, widgets) keeps the
    // purple/teal accent defined in Theme.qml; the agent panel gets its own
    // deliberately different, darker, single-hue-family palette so it reads
    // as a distinct, heavier presence — the one surface where the agent's
    // full authority (computer-use, shell, destructive actions) lives.
    // Same restraint rule as the rest of the design system still applies:
    // one hue family, varying only in value/saturation, never a rainbow.
    readonly property color pAccent: Theme.crimson      // crimson — primary identity: borders, focus, bars, hovers
    readonly property color pAccentText: Theme.crimsonText // crimson lifted for text/glyphs — AA on both washes
    readonly property color pAccent2: Theme.ember       // ember — glow, live pulses, "ok" state (warm, reads as resolved)
    readonly property color pDanger: Theme.alarm        // alarm — blocked/error, the coldest, most saturated red here
    readonly property color pWarn: Theme.gilded         // gilded amber — caution, reasoning/thinking (yellow-shifted so it can't be mistaken for ember at pip size)
    readonly property color pGlowDeep: Theme.glowDeep   // near-black maroon — deepest gradient/shadow stop
    readonly property color pWell: "#1C0A0E"      // warm-dark inset fill — plan cards, idle pills (vs cool Theme.surface)
    readonly property color pAct: "#E03222"       // hot vermilion — "act" step in the perceive→verify feed
    readonly property color pVerify: "#D46033"    // rust — "verify" step; lifted from #8C2F1F for 4.6:1 legibility
    readonly property color pBubbleTop: "#220B11"    // agent text bubble — top of the wash gradient
    readonly property color pBubbleBottom: "#110407" // agent text bubble — bottom of the wash gradient

    property bool settingsOpen: AgentState.settingsOpen
    property string keyDraft: ""
    property bool keyVisible: false
    property string modelQuery: ""

    // Wayland system clipboard process helper
    Process {
        id: clipProc
    }

    function copyToClipboard(txt) {
        if (!txt) return;
        clipProc.command = ["wl-copy", txt];
        clipProc.running = true;
    }

    readonly property string secretVar: ProviderConfig.isSub(ProviderConfig.provider)
        ? ProviderConfig.current().subTokenVar : ProviderConfig.current().envKey

    readonly property var browserModels: {
        var all = ProviderConfig.modelsFor(ProviderConfig.provider);
        var q = modelQuery.trim().toLowerCase();
        if (q === "") return all;
        var out = [];
        for (var i = 0; i < all.length; i++)
            if (String(all[i]).toLowerCase().indexOf(q) >= 0) out.push(all[i]);
        return out;
    }

    function kickModels(key) {
        var p = ProviderConfig.byKey(key);
        var sub = ProviderConfig.isSub(key);
        var ok = sub ? ProviderConfig.hasKey(p.subTokenVar)
                     : ProviderConfig.hasKey(p.envKey);
        if (ok) ArgusBridge.refreshModels(key);
    }

    onSettingsOpenChanged: {
        if (settingsOpen) { keyDraft = ""; keyVisible = false; }
    }

    GlassPanel {
        id: panel
        anchors.fill: parent
        radius: Theme.rL
        level: 3
        clipContent: true
        baseColor: "#0F0709"

        property real progress: AgentState.panelOpen ? 1.0 : 0.0
        opacity: progress
        transform: Translate { x: (1.0 - panel.progress) * 440 }

        Behavior on progress { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.OutQuint } }

        // Futuristic left-edge dual-layer laser keyline
        Rectangle {
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 5
            z: 24
            opacity: 0.35
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.25; color: pAccent }
                GradientStop { position: 0.75; color: pAccent2 }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
        Rectangle {
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 1.5
            z: 25
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.15; color: Theme.alpha(pAccent, 0.65) }
                GradientStop { position: 0.50; color: Theme.alpha(pAccent2, 0.45) }
                GradientStop { position: 0.85; color: Theme.alpha(pAccent, 0.35) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        Column {
            anchors { fill: parent; margins: Theme.s4 }
            spacing: Theme.s3

            // ── Header Bar ──────────────────────────────────────────
            Item {
                width: parent.width
                height: 38

                // Header Left Controls: Tab Switcher OR Back-to-Chat Button
                Item {
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    width: parent.width - 80
                    height: 32

                    // Normal Tab Switcher (Chat vs Actions)
                    Row {
                        anchors.fill: parent
                        spacing: Theme.s3
                        visible: !AgentState.settingsOpen

                        // Argus Brand Badge — icon only: the wordmark already lives in the
                        // top bar (Bar.qml's kinetixWord), and the 4-way tab pill (Chat/
                        // Actions/MCP/History) needs the horizontal room the "KINETIX" text
                        // used to take here.
                        Rectangle {
                            width: 20; height: 20; radius: 10
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.alpha(pAccent, 0.15)
                            border.width: 1
                            border.color: Theme.alpha(pAccent, 0.45)

                            Text {
                                anchors.centerIn: parent
                                text: "▲"
                                color: pAccentText
                                font.pixelSize: 8
                            }
                        }

                        // Sliding Tab Pill Selector
                        Rectangle {
                            id: tabPill
                            readonly property var tabIds: ["chat", "actions", "mcp", "history"]
                            readonly property int tabIndex: Math.max(0, tabIds.indexOf(AgentState.activeTab))
                            width: 68 * tabIds.length
                            height: 28
                            radius: Theme.rPill
                            color: Theme.surfaceLow
                            border.width: 1
                            border.color: Theme.stroke
                            anchors.verticalCenter: parent.verticalCenter

                            // Sliding active indicator pill
                            Rectangle {
                                y: 2; height: parent.height - 4
                                width: parent.width / tabPill.tabIds.length - 4
                                radius: Theme.rPill
                                x: 3 + tabPill.tabIndex * (parent.width / tabPill.tabIds.length)
                                color: Theme.alpha(pAccent, 0.22)
                                border.width: 1
                                border.color: Theme.alpha(pAccent, 0.55)
                                Behavior on x { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutQuint } }

                                Rectangle {
                                    anchors { top: parent.top; left: parent.left; right: parent.right; margins: 1 }
                                    height: 1
                                    radius: parent.radius
                                    color: Qt.rgba(1, 1, 1, 0.2)
                                }
                            }

                            Row {
                                anchors.fill: parent

                                // Tab: Chat
                                Item {
                                    width: parent.width / tabPill.tabIds.length
                                    height: parent.height

                                    Row {
                                        anchors.centerIn: parent
                                        spacing: 4
                                        Text {
                                            text: "Chat"
                                            color: AgentState.activeTab === "chat" ? Theme.text : Theme.textFaint
                                            font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: AgentState.activeTab === "chat" ? Font.DemiBold : Font.Normal }
                                        }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            AgentState.setTab("chat");
                                            AgentState.settingsOpen = false;
                                        }
                                    }
                                }

                                // Tab: Actions
                                Item {
                                    width: parent.width / tabPill.tabIds.length
                                    height: parent.height

                                    Row {
                                        anchors.centerIn: parent
                                        spacing: 4

                                        Text {
                                            text: "Actions"
                                            color: AgentState.activeTab === "actions" ? Theme.text : Theme.textFaint
                                            font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: AgentState.activeTab === "actions" ? Font.DemiBold : Font.Normal }
                                        }

                                        // Badge count for actions
                                        Rectangle {
                                            visible: ArgusBridge.actions.length > 0
                                            height: 14
                                            implicitWidth: Math.max(14, actBadgeT.implicitWidth + 6)
                                            radius: 7
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: AgentState.activeTab === "actions" ? pAccent : Theme.surfaceHigh

                                            Text {
                                                id: actBadgeT
                                                anchors.centerIn: parent
                                                text: String(ArgusBridge.actions.length)
                                                color: AgentState.activeTab === "actions" ? Theme.text : Theme.textDim
                                                font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                                            }
                                        }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            AgentState.setTab("actions");
                                            AgentState.settingsOpen = false;
                                        }
                                    }
                                }

                                // Tab: MCP
                                Item {
                                    width: parent.width / tabPill.tabIds.length
                                    height: parent.height

                                    Row {
                                        anchors.centerIn: parent
                                        spacing: 4

                                        Text {
                                            text: "MCP"
                                            color: AgentState.activeTab === "mcp" ? Theme.text : Theme.textFaint
                                            font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: AgentState.activeTab === "mcp" ? Font.DemiBold : Font.Normal }
                                        }

                                        // Badge count for enabled MCP servers
                                        Rectangle {
                                            visible: McpConfig.enabledCount > 0
                                            height: 14
                                            implicitWidth: Math.max(14, mcpBadgeT.implicitWidth + 6)
                                            radius: 7
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: AgentState.activeTab === "mcp" ? pAccent : Theme.surfaceHigh

                                            Text {
                                                id: mcpBadgeT
                                                anchors.centerIn: parent
                                                text: String(McpConfig.enabledCount)
                                                color: AgentState.activeTab === "mcp" ? Theme.text : Theme.textDim
                                                font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                                            }
                                        }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            AgentState.setTab("mcp");
                                            AgentState.settingsOpen = false;
                                        }
                                    }
                                }

                                // Tab: History
                                Item {
                                    width: parent.width / tabPill.tabIds.length
                                    height: parent.height

                                    Text {
                                        anchors.centerIn: parent
                                        text: "History"
                                        color: AgentState.activeTab === "history" ? Theme.text : Theme.textFaint
                                        font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: AgentState.activeTab === "history" ? Font.DemiBold : Font.Normal }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            AgentState.setTab("history");
                                            AgentState.settingsOpen = false;
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Settings View Return Bar
                    Row {
                        anchors.fill: parent
                        spacing: Theme.s2
                        visible: AgentState.settingsOpen

                        Rectangle {
                            height: 28
                            implicitWidth: backBtnRow.implicitWidth + 16
                            radius: Theme.rPill
                            color: backMa.containsMouse ? Theme.surfaceHigh : Theme.surfaceLow
                            border.width: 1
                            border.color: backMa.containsMouse ? Theme.alpha(pAccent, 0.45) : Theme.stroke
                            anchors.verticalCenter: parent.verticalCenter
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }

                            Row {
                                id: backBtnRow
                                anchors.centerIn: parent
                                spacing: 5
                                Text {
                                    text: "←"
                                    color: pAccentText
                                    font { family: Theme.fontMono; pixelSize: 11; weight: Font.Bold }
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: "Back to Chat"
                                    color: Theme.text
                                    font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }

                            MouseArea {
                                id: backMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: AgentState.settingsOpen = false
                            }
                        }

                        Text {
                            text: "SETTINGS & VAULT"
                            color: Theme.textDim
                            font { family: Theme.fontMono; pixelSize: 10; letterSpacing: 1.2; weight: Font.Bold }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }

                // Header Right Actions: Settings Gear + Close Button
                Row {
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: Theme.s2

                    // Settings Toggle Button
                    Rectangle {
                        width: 28; height: 28
                        radius: 14
                        color: AgentState.settingsOpen ? Theme.alpha(pAccent, 0.22)
                                                       : (gearMa.containsMouse ? Theme.surfaceHigh : "transparent")
                        border.width: 1
                        border.color: AgentState.settingsOpen ? Theme.alpha(pAccent, 0.45) : Theme.stroke
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }

                        Text {
                            anchors.centerIn: parent
                            text: "⚙"
                            font.pixelSize: 13
                            color: AgentState.settingsOpen ? pAccent : (gearMa.containsMouse ? Theme.text : Theme.textDim)
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            rotation: AgentState.settingsOpen ? 90 : 0
                            Behavior on rotation { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
                        }

                        MouseArea {
                            id: gearMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: AgentState.toggleSettings()
                        }
                    }

                    // Panel Close Button
                    CloseButton {
                        box: 28
                        tip: "Close panel"
                        onClicked: AgentState.panelOpen = false
                    }
                }
            }

            // ── Primary View Container (Chat / Actions / Settings) ──
            Item {
                id: tabContainer
                width: parent.width
                height: parent.height - 38 - Theme.s3
                clip: true

                // ─────────────────────────────────────────────────────
                // 1. CHAT TAB
                // ─────────────────────────────────────────────────────
                Item {
                    id: chatTab
                    anchors.fill: parent
                    visible: !AgentState.settingsOpen && AgentState.activeTab === "chat"

                    // Input warning banner
                    Rectangle {
                        id: capWarn
                        anchors { top: parent.top; left: parent.left; right: parent.right }
                        visible: ArgusBridge.inputWarning !== ""
                        height: visible ? capWarnCol.implicitHeight + Theme.s3 * 2 : 0
                        radius: Theme.rM
                        color: Theme.alpha(pWarn, 0.12)
                        border.width: 1
                        border.color: Theme.alpha(pWarn, 0.45)

                        Column {
                            id: capWarnCol
                            anchors { fill: parent; margins: Theme.s3 }
                            spacing: 2
                            Row {
                                width: parent.width
                                spacing: Theme.s2
                                Text { text: "⚠"; color: pWarn; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                                Text {
                                    text: "INPUT CONTROL DEGRADED"
                                    color: pWarn
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Item { width: Math.max(0, parent.width - x - capRefresh.width); height: 1 }
                                Text {
                                    id: capRefresh
                                    text: "↻"
                                    color: capRefreshMa.containsMouse ? Theme.text : Theme.textFaint
                                    font.pixelSize: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                    MouseArea {
                                        id: capRefreshMa
                                        anchors.fill: parent; anchors.margins: -6
                                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: ArgusBridge.refreshCaps()
                                    }
                                }
                            }
                            Text {
                                width: parent.width
                                text: ArgusBridge.inputWarning
                                color: Theme.textDim
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    // High-Tech Computer-Use Control Cockpit Card
                    Repeater {
                        model: Theme.shadowFor(1)
                        delegate: Rectangle {
                            required property var modelData
                            anchors.fill: grantCard
                            anchors.margins: -modelData.grow
                            anchors.topMargin: -modelData.grow + modelData.dy
                            radius: grantCard.radius + modelData.grow
                            color: Qt.rgba(0, 0, 0, modelData.a)
                        }
                    }
                    Rectangle {
                        id: grantCard
                        anchors {
                            top: capWarn.visible ? capWarn.bottom : parent.top
                            topMargin: capWarn.visible ? Theme.s2 : 0
                            left: parent.left; right: parent.right
                        }
                        height: grantCol.implicitHeight + Theme.s3 * 2
                        radius: Theme.rM
                        color: AgentState.computerUse ? Theme.alpha(pAccent, 0.10) : Theme.surfaceLow
                        border.width: 1
                        border.color: AgentState.computerUse ? Theme.alpha(pAccent, 0.42) : Theme.stroke
                        Behavior on color { ColorAnimation { duration: Theme.durMed } }
                        Behavior on border.color { ColorAnimation { duration: Theme.durMed } }

                        // Top specular highlight
                        Rectangle {
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
                            height: 1
                            radius: parent.radius
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: "transparent" }
                                GradientStop { position: 0.3; color: AgentState.computerUse ? Theme.alpha(pAccent, 0.35) : Qt.rgba(1, 1, 1, 0.10) }
                                GradientStop { position: 1.0; color: "transparent" }
                            }
                        }

                        Column {
                            id: grantCol
                            anchors { fill: parent; margins: Theme.s3 }
                            spacing: Theme.s2

                            Row {
                                width: parent.width
                                Column {
                                    width: parent.width - 48
                                    spacing: 2
                                    Row {
                                        spacing: 6
                                        Text {
                                            text: "✦"
                                            color: AgentState.computerUse ? pAccent : Theme.textFaint
                                            font.pixelSize: 11
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                        Text {
                                            text: "Computer Use Engine"
                                            color: Theme.text
                                            font { family: Theme.fontUi; pixelSize: Theme.tLabel; weight: Font.DemiBold }
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                    }
                                    Text {
                                        text: AgentState.computerUse
                                              ? "Autonomous vision, window navigation, and direct input control"
                                              : "Read-only inspection mode (input control paused)"
                                        color: Theme.textFaint
                                        font.pixelSize: Theme.tCaption
                                    }
                                }
                                Toggle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    checked: AgentState.computerUse
                                    tint: pAccent
                                    onToggled: function(c) { AgentState.computerUse = c }
                                }
                            }

                            // Interactive LED Capability Toggle Chips
                            Row {
                                width: parent.width
                                spacing: Theme.s2
                                opacity: AgentState.computerUse ? 1 : 0.40
                                Behavior on opacity { NumberAnimation { duration: Theme.durMed } }

                                Repeater {
                                    model: [
                                        { "id": "screen", "l": "SCREEN", "prop": "grantScreen" },
                                        { "id": "input", "l": "INPUT", "prop": "grantInput" },
                                        { "id": "shell", "l": "SHELL", "prop": "grantShell" },
                                        { "id": "net", "l": "NET", "prop": "grantNet" }
                                    ]
                                    delegate: Rectangle {
                                        id: chipDelegate
                                        required property var modelData
                                        readonly property bool active: !!(modelData && ProviderConfig[modelData.prop])
                                        implicitWidth: chipRow.implicitWidth + 14
                                        implicitHeight: 22
                                        radius: Theme.rPill
                                        color: chipMa.containsMouse
                                               ? (active ? Theme.alpha(pAccent2, 0.24) : Theme.surfaceHigh)
                                               : (active ? Theme.alpha(pAccent2, 0.14) : Theme.surfaceLow)
                                        border.width: 1
                                        border.color: active
                                                      ? (chipMa.containsMouse ? pAccent2 : Theme.alpha(pAccent2, 0.42))
                                                      : (chipMa.containsMouse ? Theme.strokeStrong : Theme.stroke)
                                        scale: chipMa.pressed ? 0.94 : (chipMa.containsMouse ? 1.04 : 1.0)
                                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                                        Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutQuint } }

                                        Row {
                                            id: chipRow
                                            anchors.centerIn: parent
                                            spacing: 5
                                            Rectangle {
                                                width: 5; height: 5; radius: 2.5
                                                anchors.verticalCenter: parent.verticalCenter
                                                color: chipDelegate.active ? pAccent2 : Theme.textFaint
                                                SequentialAnimation on opacity {
                                                    running: chipDelegate.active && AgentState.computerUse
                                                    loops: Animation.Infinite
                                                    NumberAnimation { from: 0.5; to: 1.0; duration: 800; easing.type: Easing.InOutSine }
                                                    NumberAnimation { from: 1.0; to: 0.5; duration: 800; easing.type: Easing.InOutSine }
                                                }
                                            }
                                            Text {
                                                anchors.verticalCenter: parent.verticalCenter
                                                text: chipDelegate.modelData.l
                                                color: chipDelegate.active ? Theme.text : Theme.textFaint
                                                font { family: Theme.fontMono; pixelSize: 9; weight: Font.Bold; letterSpacing: 0.8 }
                                            }
                                        }

                                        MouseArea {
                                            id: chipMa
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                var p = modelData.prop;
                                                ProviderConfig[p] = !ProviderConfig[p];
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // ── Mission Plan / Checklist HUD ─────────────────────
                    Repeater {
                        model: Theme.shadowFor(1)
                        delegate: Rectangle {
                            required property var modelData
                            visible: planHud.visible
                            anchors.fill: planHud
                            anchors.margins: -modelData.grow
                            anchors.topMargin: -modelData.grow + modelData.dy
                            radius: planHud.radius + modelData.grow
                            color: Qt.rgba(0, 0, 0, modelData.a)
                        }
                    }
                    Rectangle {
                        id: planHud
                        anchors {
                            top: grantCard.bottom
                            topMargin: visible ? Theme.s2 : 0
                            left: parent.left; right: parent.right
                        }
                        visible: AgentState.todos && AgentState.todos.length > 0
                        property bool collapsed: false

                        readonly property int totalTodos: AgentState.todos ? AgentState.todos.length : 0
                        readonly property int completedTodos: {
                            if (!AgentState.todos) return 0;
                            var c = 0;
                            for (var i = 0; i < AgentState.todos.length; i++)
                                if (AgentState.todos[i].status === "completed") c++;
                            return c;
                        }

                        height: visible ? (collapsed ? planHeader.height + 14 : planCol.implicitHeight + Theme.s3 * 2) : 0
                        radius: Theme.rM
                        color: pWell
                        border.width: 1
                        border.color: Theme.alpha(pAccent, 0.35)
                        clip: true
                        Behavior on height { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutQuint } }

                        // Top rim sheen
                        Rectangle {
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
                            height: 1
                            radius: parent.radius
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: "transparent" }
                                GradientStop { position: 0.25; color: Theme.alpha(pAccent, 0.3) }
                                GradientStop { position: 1.0; color: "transparent" }
                            }
                        }

                        Column {
                            id: planCol
                            anchors { fill: parent; margins: Theme.s3 }
                            spacing: Theme.s2

                            // Header Bar of Plan HUD
                            Item {
                                id: planHeader
                                width: parent.width
                                height: 18

                                Row {
                                    anchors.fill: parent
                                    spacing: 6

                                    Text {
                                        text: "✦"
                                        color: pAccentText
                                        font.pixelSize: 10
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Text {
                                        text: "MISSION PLAN"
                                        color: Theme.text
                                        font { family: Theme.fontMono; pixelSize: 9; weight: Font.Bold; letterSpacing: 1.2 }
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Item { width: Math.max(0, parent.width - x - progBadge.width - chevronText.width - 12); height: 1 }

                                    // Completed badge
                                    Rectangle {
                                        id: progBadge
                                        height: 16
                                        implicitWidth: progBadgeT.implicitWidth + 10
                                        radius: 8
                                        color: Theme.alpha(pAccent, 0.16)
                                        border.width: 1
                                        border.color: Theme.alpha(pAccent, 0.38)
                                        anchors.verticalCenter: parent.verticalCenter

                                        Text {
                                            id: progBadgeT
                                            anchors.centerIn: parent
                                            text: planHud.completedTodos + " / " + planHud.totalTodos + " DONE"
                                            color: pAccentText
                                            font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                                        }
                                    }

                                    Text {
                                        id: chevronText
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: planHud.collapsed ? "▸" : "▾"
                                        color: Theme.textDim
                                        font.pixelSize: 10
                                    }
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: planHud.collapsed = !planHud.collapsed
                                }
                            }

                            // Horizontal Progress Bar
                            Rectangle {
                                width: parent.width
                                height: 3
                                radius: 1.5
                                color: Theme.surfaceHigh
                                visible: !planHud.collapsed

                                Rectangle {
                                    height: parent.height
                                    radius: parent.radius
                                    width: Math.max(0, Math.min(parent.width, (planHud.completedTodos / Math.max(planHud.totalTodos, 1)) * parent.width))
                                    gradient: Gradient {
                                        orientation: Gradient.Horizontal
                                        GradientStop { position: 0.0; color: pAccent }
                                        GradientStop { position: 1.0; color: pAccent2 }
                                    }
                                    Behavior on width { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
                                }
                            }

                            // Checklist Tasks
                            Column {
                                width: parent.width
                                spacing: 4
                                visible: !planHud.collapsed

                                Repeater {
                                    model: AgentState.todos
                                    delegate: Row {
                                        required property var modelData
                                        required property int index
                                        width: planCol.width
                                        spacing: 7

                                        // Status Glyph Node
                                        Rectangle {
                                            width: 14; height: 14; radius: 7
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: modelData.status === "completed" ? Theme.alpha(pAccent2, 0.20)
                                                 : modelData.status === "in_progress" ? Theme.alpha(pAccent, 0.25)
                                                 : Theme.surfaceHigh
                                            border.width: 1
                                            border.color: modelData.status === "completed" ? pAccent2
                                                        : modelData.status === "in_progress" ? pAccent
                                                        : Theme.stroke

                                            Text {
                                                anchors.centerIn: parent
                                                text: modelData.status === "completed" ? "✓"
                                                    : modelData.status === "in_progress" ? "⚡" : "○"
                                                color: modelData.status === "completed" ? pAccent2
                                                     : modelData.status === "in_progress" ? pAccent : Theme.textFaint
                                                font { family: Theme.fontMono; pixelSize: 8; bold: true }
                                            }
                                        }

                                        Text {
                                            width: parent.width - 24
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: modelData.content || ""
                                            color: modelData.status === "completed" ? Theme.textDim
                                                 : modelData.status === "in_progress" ? Theme.text : Theme.textFaint
                                            font {
                                                family: Theme.fontUi
                                                pixelSize: Theme.tCaption
                                                weight: modelData.status === "in_progress" ? Font.DemiBold : Font.Normal
                                                strikeout: modelData.status === "completed"
                                            }
                                            wrapMode: Text.WordWrap
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Utility Micro-Bar (Session Status + Retry / Clear)
                    Row {
                        id: utilRow
                        anchors {
                            top: planHud.visible ? planHud.bottom : grantCard.bottom
                            topMargin: Theme.s2
                            left: parent.left; right: parent.right
                        }
                        height: 22

                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6
                            Rectangle {
                                width: 5; height: 5; radius: 2.5
                                anchors.verticalCenter: parent.verticalCenter
                                color: AgentState.messages.count > 0 ? pAccent2 : Theme.textFaint
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: AgentState.messages.count > 0 ? (AgentState.messages.count + " MESSAGES") : "SESSION READY"
                                color: Theme.textFaint
                                font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2 }
                            }
                        }

                        Item { width: Math.max(0, parent.width - x - retryPill.width - clearPill.width - Theme.s2); height: 1 }

                        Rectangle {
                            id: retryPill
                            visible: AgentState.messages.count > 0
                            anchors.verticalCenter: parent.verticalCenter
                            implicitWidth: retryT.implicitWidth + 14
                            height: 20
                            radius: Theme.rPill
                            color: retryMa.containsMouse ? Theme.surfaceHigh : "transparent"
                            border.width: 1
                            border.color: retryMa.containsMouse ? Theme.strokeStrong : "transparent"
                            Text {
                                id: retryT
                                anchors.centerIn: parent
                                text: "↻ Retry"
                                color: retryMa.containsMouse ? Theme.text : Theme.textFaint
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                            }
                            MouseArea {
                                id: retryMa
                                anchors.fill: parent
                                hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: ArgusBridge.retry()
                            }
                        }

                        Rectangle {
                            id: clearPill
                            visible: AgentState.messages.count > 0
                            anchors.verticalCenter: parent.verticalCenter
                            implicitWidth: clearT2.implicitWidth + 14
                            height: 20
                            radius: Theme.rPill
                            color: clearMa2.containsMouse ? Theme.alpha(pDanger, 0.16) : "transparent"
                            border.width: 1
                            border.color: clearMa2.containsMouse ? Theme.alpha(pDanger, 0.35) : "transparent"
                            Text {
                                id: clearT2
                                anchors.centerIn: parent
                                text: "✕ Clear"
                                color: clearMa2.containsMouse ? pDanger : Theme.textFaint
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                            }
                            MouseArea {
                                id: clearMa2
                                anchors.fill: parent
                                hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: AgentState.clearMessages()
                            }
                        }
                    }

                    // Empty State Prompt Starters & System Hero Greeting
                    Item {
                        id: emptyPromptState
                        anchors {
                            top: utilRow.bottom
                            topMargin: Theme.s2
                            bottom: composer.top
                            bottomMargin: Theme.s2
                            left: parent.left
                            right: parent.right
                        }
                        visible: AgentState.messages.count === 0 && !ArgusBridge.busy

                        Flickable {
                            anchors.fill: parent
                            contentHeight: emptyHeroCol.implicitHeight
                            contentWidth: width
                            clip: true

                            Column {
                                id: emptyHeroCol
                                width: parent.width
                                y: Math.max(0, (parent.height - implicitHeight) / 2)
                                spacing: 14

                                // Breathing ArgusMark with iris aura
                                Item {
                                    width: 68; height: 68
                                    anchors.horizontalCenter: parent.horizontalCenter

                                    // Faint outer glow — a soft second ring on the shared
                                    // heartbeat oscillator, so the whole aura reads as one
                                    // slow, alive pulse rather than a static badge.
                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: 68; height: 68; radius: 34
                                        color: "transparent"
                                        border.width: 1
                                        border.color: Theme.alpha(pAccent, 0.05 + 0.06 * Theme.heartbeatSin)
                                    }

                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: 58; height: 58; radius: 29
                                        color: Theme.alpha(pAccent, 0.08)
                                        border.width: 1
                                        border.color: Theme.alpha(pAccent, 0.28)

                                        SequentialAnimation on scale {
                                            running: emptyPromptState.visible && win.visible   // item visibility ignores the hidden window; without this it ran forever off-screen
                                            loops: Animation.Infinite
                                            NumberAnimation { from: 0.95; to: 1.06; duration: 2400; easing.type: Easing.InOutSine }
                                            NumberAnimation { from: 1.06; to: 0.95; duration: 2400; easing.type: Easing.InOutSine }
                                        }
                                    }

                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: 38; height: 38; radius: 19
                                        color: Theme.alpha(pAccent, 0.14)
                                        border.width: 1
                                        border.color: Theme.alpha(pAccent, 0.45)
                                    }

                                    ArgusMark {
                                        anchors.centerIn: parent
                                        scale: 1.4
                                        live: true
                                        animate: win.visible
                                    }
                                }

                                // Typography
                                Column {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    spacing: 4

                                    Row {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        spacing: 8
                                        Text {
                                            text: "KINETIX AI"
                                            color: Theme.text
                                            font { family: Theme.fontUi; pixelSize: 16; weight: Font.Bold; letterSpacing: 1.2 }
                                        }
                                        Rectangle {
                                            height: 16; width: 44; radius: Theme.rPill
                                            color: Theme.alpha(pAccent, 0.15)
                                            border.width: 1
                                            border.color: Theme.alpha(pAccent, 0.38)
                                            anchors.verticalCenter: parent.verticalCenter
                                            Text {
                                                anchors.centerIn: parent
                                                text: "ONLINE"
                                                color: pAccentText
                                                font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold; letterSpacing: 0.8 }
                                            }
                                        }
                                    }

                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: "Autonomous Operating System Agent"
                                        color: Theme.textFaint
                                        font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                                    }
                                }

                                // Capability status pills
                                Row {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    spacing: 6

                                    Repeater {
                                        model: [
                                            { "icon": "👁", "label": "Vision" },
                                            { "icon": "⚙", "label": "Desktop Control" },
                                            { "icon": "⚡", "label": "Shell & Code" },
                                            { "icon": "⊞", "label": "Workspaces" }
                                        ]
                                        delegate: Rectangle {
                                            height: 20
                                            implicitWidth: capBadgeRow.implicitWidth + 12
                                            radius: Theme.rPill
                                            color: Theme.surfaceLow
                                            border.width: 1
                                            border.color: Theme.stroke

                                            Row {
                                                id: capBadgeRow
                                                anchors.centerIn: parent
                                                spacing: 4
                                                Text {
                                                    text: modelData.icon
                                                    font.pixelSize: 9
                                                    color: pAccentText
                                                    anchors.verticalCenter: parent.verticalCenter
                                                }
                                                Text {
                                                    text: modelData.label
                                                    color: Theme.textDim
                                                    font { family: Theme.fontUi; pixelSize: 9; weight: Font.Medium }
                                                    anchors.verticalCenter: parent.verticalCenter
                                                }
                                            }
                                        }
                                    }
                                }

                                // 4 Rich Starter Prompt Cards
                                Column {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: parent.width
                                    spacing: 8

                                    Repeater {
                                        model: [
                                            {
                                                "icon": "🩺",
                                                "title": "System Diagnostics",
                                                "desc": "Check adapter health, tools, and engine status",
                                                "prompt": "Run argusd doctor to check adapter health and system status"
                                            },
                                            {
                                                "icon": "🖥",
                                                "title": "Inspect Desktop",
                                                "desc": "Analyze active windows, workspace layout, and focus",
                                                "prompt": "Inspect open windows, desktop state, and current workspace configuration"
                                            },
                                            {
                                                "icon": "⚡",
                                                "title": "Codebase Architecture",
                                                "desc": "Summarize project structure and daemon topology",
                                                "prompt": "Examine the project structure and summarize the architecture and services"
                                            },
                                            {
                                                "icon": "❯_",
                                                "title": "Quick Shell Check",
                                                "desc": "Stream autonomous bash execution and resource stats",
                                                "prompt": "Run a quick check of CPU, memory, and top active processes via bash"
                                            }
                                        ]
                                        delegate: Item {
                                            id: promptCardRoot
                                            required property var modelData
                                            width: parent.width
                                            height: 48
                                            scale: promptCardMa.containsMouse ? 1.015 : 1.0
                                            Behavior on scale { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

                                            Repeater {
                                                model: Theme.shadowFor(promptCardMa.containsMouse ? 1 : 0)
                                                delegate: Rectangle {
                                                    required property var modelData
                                                    anchors.fill: promptCard
                                                    anchors.margins: -modelData.grow
                                                    anchors.topMargin: -modelData.grow + modelData.dy
                                                    radius: promptCard.radius + modelData.grow
                                                    color: Qt.rgba(0, 0, 0, modelData.a)
                                                    Behavior on color { ColorAnimation { duration: Theme.durMed } }
                                                }
                                            }

                                        Rectangle {
                                            id: promptCard
                                            property var modelData: promptCardRoot.modelData
                                            anchors.fill: parent
                                            radius: Theme.rM
                                            color: promptCardMa.containsMouse ? Theme.surfaceHigh : Theme.surfaceLow
                                            border.width: 1
                                            border.color: promptCardMa.containsMouse ? Theme.alpha(pAccent, 0.45) : Theme.stroke
                                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                                            // Left highlight pip on hover
                                            Rectangle {
                                                width: 3
                                                height: 18
                                                radius: 1.5
                                                anchors { left: parent.left; leftMargin: 5; verticalCenter: parent.verticalCenter }
                                                color: pAccent
                                                opacity: promptCardMa.containsMouse ? 1.0 : 0.0
                                                Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
                                            }

                                            Row {
                                                anchors {
                                                    fill: parent
                                                    leftMargin: 14
                                                    rightMargin: 12
                                                }
                                                spacing: 10

                                                // Icon badge
                                                Rectangle {
                                                    width: 30; height: 30; radius: 6
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    color: promptCardMa.containsMouse ? Theme.alpha(pAccent, 0.20) : Theme.surface
                                                    border.width: 1
                                                    border.color: promptCardMa.containsMouse ? Theme.alpha(pAccent, 0.35) : Theme.stroke
                                                    Behavior on color { ColorAnimation { duration: Theme.durFast } }

                                                    Text {
                                                        anchors.centerIn: parent
                                                        text: promptCard.modelData.icon
                                                        font.pixelSize: 13
                                                    }
                                                }

                                                // Title & Description
                                                Column {
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    width: parent.width - 30 - 10 - 20 - 10
                                                    spacing: 1

                                                    Text {
                                                        text: promptCard.modelData.title
                                                        color: promptCardMa.containsMouse ? Theme.text : Theme.textDim
                                                        font { family: Theme.fontUi; pixelSize: 11; weight: Font.DemiBold }
                                                        elide: Text.ElideRight
                                                        width: parent.width
                                                    }
                                                    Text {
                                                        text: promptCard.modelData.desc
                                                        color: Theme.textFaint
                                                        font { family: Theme.fontUi; pixelSize: 9 }
                                                        elide: Text.ElideRight
                                                        width: parent.width
                                                    }
                                                }

                                                // Action Arrow Glyph
                                                Text {
                                                    text: "→"
                                                    color: promptCardMa.containsMouse ? pAccent : Theme.textFaint
                                                    font { family: Theme.fontMono; pixelSize: 12 }
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    opacity: promptCardMa.containsMouse ? 1.0 : 0.4
                                                    x: promptCardMa.containsMouse ? 2 : 0
                                                    Behavior on x { NumberAnimation { duration: Theme.durFast } }
                                                }
                                            }

                                            MouseArea {
                                                id: promptCardMa
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    input.text = promptCard.modelData.prompt;
                                                    input.forceActiveFocus();
                                                }
                                            }
                                        }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Chat Message Feed
                    ListView {
                        id: feed
                        visible: AgentState.messages.count > 0
                        anchors {
                            top: utilRow.bottom
                            topMargin: Theme.s2
                            left: parent.left
                            right: parent.right
                            bottom: compactionStrip.visible ? compactionStrip.top
                                    : approvalBanner.visible ? approvalBanner.top
                                    : composer.top
                            bottomMargin: Theme.s2
                        }
                        clip: true
                        spacing: Theme.s3
                        model: AgentState.messages

                        // Stick-to-bottom auto-scroll. Reacting to `rev` (a
                        // per-delta data signal) and calling positionViewAtEnd()
                        // right away raced the layout: a wrapped Text's
                        // implicitHeight — and so this ListView's contentHeight —
                        // only settles a beat after the property change that
                        // caused it, so positioning "now" often landed short of
                        // the real end during fast streaming. contentHeight is
                        // the settled signal instead of the triggering one.
                        // autoFollow tracks intent: a user-initiated drag turns
                        // it off so reading back through history isn't yanked
                        // out from under them; scrolling back to the bottom (or
                        // a new message arriving) turns it back on.
                        property bool autoFollow: true
                        onMovementStarted: autoFollow = false
                        onAtYEndChanged: if (atYEnd) autoFollow = true
                        onContentHeightChanged: if (autoFollow) Qt.callLater(positionViewAtEnd)
                        onCountChanged: {
                            autoFollow = true;
                            Qt.callLater(positionViewAtEnd);
                        }

                        add: Transition {
                            ParallelAnimation {
                                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durMed }
                                NumberAnimation { property: "scale"; from: 0.94; to: 1; duration: Theme.durMed; easing.type: Easing.OutQuint }
                            }
                        }
                        displaced: Transition {
                            NumberAnimation { properties: "x,y"; duration: Theme.durMed; easing.type: Easing.OutQuint }
                        }

                        delegate: Item {
                            id: msgItem
                            required property int index
                            required property string role
                            required property string text
                            required property string time
                            // A live nested ListModel (see AgentState.liveSegmentsModel), not
                            // JSON text — mutated in place so streaming a delta updates exactly
                            // the one row that changed instead of tearing down every delegate
                            // below it. May have count 0 for a plain/historical message, which
                            // falls back to `text` below.
                            required property var segments
                            property bool mine: role === "user"
                            readonly property bool hasSegs: segments && segments.count > 0
                            // Only the trailing text segment of the message currently being
                            // streamed gets the "live" pulse — never a historical reply that
                            // happens to end in a text segment too.
                            readonly property bool isLastMessage: index === AgentState.messages.count - 1

                            // Plain text representation for one-click copying
                            readonly property string rawProseText: {
                                if (hasSegs) {
                                    var out = "";
                                    for (var k = 0; k < segments.count; k++) {
                                        var s = segments.get(k);
                                        if (s.type === "text") out += s.text + "\n";
                                    }
                                    var trimmed = out.trim();
                                    if (trimmed !== "") return trimmed;
                                }
                                return text || "";
                            }

                            property bool copied: false
                            Timer {
                                id: copiedTimer
                                interval: 1600
                                onTriggered: msgItem.copied = false
                            }

                            width: feed.width
                            height: col.height + 8

                            Column {
                                id: col
                                x: msgItem.mine ? parent.width - width : 0
                                width: msgItem.mine ? Math.min(340, feed.width - 16)
                                                    : Math.min(400, feed.width - 8)
                                spacing: 4

                                // Message Header Tag with One-Click Copy Button
                                Row {
                                    x: msgItem.mine ? parent.width - width : 6
                                    width: msgItem.mine ? implicitWidth : col.width - 12
                                    spacing: 6

                                    StatusOrb {
                                        implicitWidth: 8; implicitHeight: 8
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: msgItem.mine ? pAccent : pAccent2
                                        live: !msgItem.mine && msgItem.isLastMessage && AgentState.turnLive
                                    }

                                    Text {
                                        text: msgItem.mine ? "YOU" : "KINETIX"
                                        color: msgItem.mine ? pAccent : pAccent2
                                        font { family: Theme.fontMono; pixelSize: 9; weight: Font.Bold; letterSpacing: 1.1 }
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Text {
                                        text: msgItem.time
                                        color: Theme.textFaint
                                        font { family: Theme.fontMono; pixelSize: 9 }
                                        anchors.verticalCenter: parent.verticalCenter
                                    }

                                    Item {
                                        width: Math.max(0, parent.width - x - copyBtn.width)
                                        height: 1
                                        visible: !msgItem.mine
                                    }

                                    // Quick Copy Action Pill
                                    Rectangle {
                                        id: copyBtn
                                        anchors.verticalCenter: parent.verticalCenter
                                        height: 16
                                        implicitWidth: copyT.implicitWidth + 10
                                        radius: 8
                                        color: msgItem.copied ? Theme.alpha(pAccent2, 0.22)
                                             : (copyMa.containsMouse ? Theme.surfaceHigh : "transparent")
                                        border.width: 1
                                        border.color: msgItem.copied ? pAccent2
                                                    : (copyMa.containsMouse ? Theme.strokeStrong : "transparent")
                                        opacity: (copyMa.containsMouse || msgItem.copied) ? 1.0 : 0.45
                                        Behavior on opacity { NumberAnimation { duration: Theme.durFast } }

                                        Row {
                                            id: copyT
                                            anchors.centerIn: parent
                                            spacing: 3
                                            Text {
                                                text: msgItem.copied ? "✓" : "📋"
                                                color: msgItem.copied ? pAccent2 : Theme.textDim
                                                font.pixelSize: 8
                                                anchors.verticalCenter: parent.verticalCenter
                                            }
                                            Text {
                                                text: msgItem.copied ? "COPIED" : "COPY"
                                                color: msgItem.copied ? pAccent2 : Theme.textDim
                                                font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                                                anchors.verticalCenter: parent.verticalCenter
                                            }
                                        }

                                        MouseArea {
                                            id: copyMa
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                copyToClipboard(msgItem.rawProseText);
                                                msgItem.copied = true;
                                                copiedTimer.restart();
                                            }
                                        }
                                    }
                                }

                                // Plain/historical message with no live segments: one bubble.
                                Loader {
                                    width: col.width
                                    active: !msgItem.hasSegs
                                    sourceComponent: textBubbleComp
                                    property var seg: ({ "type": "text", "text": msgItem.text || "", "isLiveTail": false })
                                }

                                // Live-turn segments, bound directly to the nested ListModel so a
                                // streamed delta updates one row in place — see the comment on
                                // AgentState.liveSegmentsModel for why this matters.
                                Repeater {
                                    model: msgItem.hasSegs ? msgItem.segments : null
                                    delegate: Loader {
                                        id: segLoader
                                        required property int index
                                        required property string type
                                        required property string text
                                        required property string id
                                        required property string name
                                        required property string argsText
                                        required property string argsJson
                                        required property string status
                                        required property string summary
                                        required property string detailJson
                                        width: col.width
                                        active: !((type === "text" || type === "reasoning") && text === "")
                                        sourceComponent: type === "tool" ? toolCardComp
                                                         : type === "reasoning" ? reasoningComp
                                                         : textBubbleComp
                                        // The one segment currently receiving tokens: drives the
                                        // live pulse on the text bubble's accent bar. Cheap to
                                        // recompute per delta — just int/bool comparisons, no
                                        // parsing — unlike the args/detail JSON below.
                                        readonly property bool isLiveTail: AgentState.turnLive && !msgItem.mine
                                            && msgItem.isLastMessage && type === "text"
                                            && index === msgItem.segments.count - 1
                                        // Reassembled for the (unchanged) inner Components below,
                                        // which just read seg.foo — argsJson/detailJson are only
                                        // ever non-empty once per tool call, so parsing them here
                                        // is not a per-delta cost.
                                        property var seg: ({
                                            "type": type, "id": id, "name": name, "text": text,
                                            "argsText": argsText, "status": status, "summary": summary,
                                            "args": argsJson ? JSON.parse(argsJson) : null,
                                            "detail": detailJson ? JSON.parse(detailJson) : null,
                                            "isLiveTail": isLiveTail
                                        })
                                    }
                                }
                            }

                            // Prose message bubble
                            Component {
                                id: textBubbleComp
                                Item {
                                    id: bubbleRoot
                                    readonly property var seg: parent ? parent.seg : ({})
                                    width: col.width
                                    height: bubble.height
                                    Behavior on height { NumberAnimation { duration: Theme.durFast; easing.type: Theme.easeOut } }

                                    // Soft multi-layer elevation — see Theme.shadowFor. Level 0:
                                    // bubbles are dense in a scrolling feed, so this stays a
                                    // close, quiet lift rather than a dramatic card shadow.
                                    Repeater {
                                        model: Theme.shadowFor(0)
                                        delegate: Rectangle {
                                            required property var modelData
                                            anchors.fill: bubble
                                            anchors.margins: -modelData.grow
                                            anchors.topMargin: -modelData.grow + modelData.dy
                                            radius: bubble.radius + modelData.grow
                                            color: Qt.rgba(0, 0, 0, modelData.a)
                                        }
                                    }

                                    Rectangle {
                                        id: bubble
                                        width: parent.width
                                        height: txt.implicitHeight + Theme.s3 * 2
                                        radius: Theme.rM
                                        border.width: 1
                                        border.color: msgItem.mine
                                                      ? Theme.alpha(pAccent, 0.40)
                                                      : Theme.stroke
                                        gradient: Gradient {
                                            GradientStop { position: 0.0; color: msgItem.mine ? Theme.alpha(pAccent, 0.24) : pBubbleTop }
                                            GradientStop { position: 1.0; color: msgItem.mine ? Theme.alpha(pAccent, 0.14) : pBubbleBottom }
                                        }

                                        // Specular sheen — diagonal highlight from upper-left,
                                        // same recipe as GlassPanel, toned down for a small surface.
                                        Rectangle {
                                            anchors.fill: parent
                                            radius: parent.radius
                                            gradient: Gradient {
                                                orientation: Gradient.Horizontal
                                                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, msgItem.mine ? 0.05 : 0.04) }
                                                GradientStop { position: 0.45; color: "transparent" }
                                            }
                                        }

                                        // Top rim specular highlight
                                        Rectangle {
                                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
                                            height: 1
                                            radius: parent.radius
                                            gradient: Gradient {
                                                orientation: Gradient.Horizontal
                                                GradientStop { position: 0.0; color: "transparent" }
                                                GradientStop { position: 0.18; color: msgItem.mine ? Theme.alpha(pAccent, 0.55) : Theme.rimTop }
                                                GradientStop { position: 0.8; color: Qt.rgba(1, 1, 1, 0.03) }
                                                GradientStop { position: 1.0; color: "transparent" }
                                            }
                                        }

                                        // Integrated left accent beacon for assistant messages —
                                        // pulses gently (shared heartbeat oscillator, no extra
                                        // timer) while this is the segment actively receiving
                                        // tokens, so liveness reads at a glance, not just in the
                                        // composer footer.
                                        Rectangle {
                                            visible: !msgItem.mine
                                            anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 6 }
                                            width: 3
                                            radius: 1.5
                                            opacity: seg.isLiveTail ? (0.55 + 0.45 * Theme.heartbeatSin) : 1.0
                                            gradient: Gradient {
                                                GradientStop { position: 0; color: pAccent }
                                                GradientStop { position: 1; color: pAccent2 }
                                            }
                                        }

                                        Text {
                                            id: txt
                                            anchors {
                                                left: parent.left; leftMargin: msgItem.mine ? Theme.s3 : (Theme.s3 + 10)
                                                right: parent.right; rightMargin: Theme.s3
                                                top: parent.top; topMargin: Theme.s3
                                            }
                                            wrapMode: Text.WordWrap
                                            lineHeight: 1.36
                                            textFormat: Text.RichText
                                            text: MD.toRich(seg ? (seg.text || "") : "")
                                            onLinkActivated: function (link) { Qt.openUrlExternally(link); }
                                            color: Theme.text
                                            font { family: Theme.fontUi; pixelSize: Theme.tBody }
                                        }
                                    }
                                }
                            }

                            // Reasoning / Chain-of-thought segment
                            Component {
                                id: reasoningComp
                                Item {
                                    id: reasoningRoot
                                    readonly property var seg: parent ? parent.seg : ({})
                                    width: col.width
                                    height: reasoningCard.height
                                    Behavior on height { NumberAnimation { duration: Theme.durFast; easing.type: Theme.easeOut } }

                                    Repeater {
                                        model: Theme.shadowFor(0)
                                        delegate: Rectangle {
                                            required property var modelData
                                            anchors.fill: reasoningCard
                                            anchors.margins: -modelData.grow
                                            anchors.topMargin: -modelData.grow + modelData.dy
                                            radius: reasoningCard.radius + modelData.grow
                                            color: Qt.rgba(0, 0, 0, modelData.a)
                                        }
                                    }

                                    Rectangle {
                                        id: reasoningCard
                                        width: parent.width
                                        property bool expanded: seg ? (seg.status !== "done") : false
                                        property bool stillThinking: seg ? (seg.status !== "done") : false
                                        height: head.height + (expanded ? bodyText.implicitHeight + Theme.s2 : 0) + Theme.s2 * 2
                                        radius: Theme.rM
                                        color: Theme.surfaceLow
                                        border.width: 1
                                        border.color: stillThinking ? Theme.alpha(pWarn, 0.40) : Theme.stroke
                                        Behavior on height { NumberAnimation { duration: Theme.durFast } }
                                        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: reasoningCard.expanded = !reasoningCard.expanded
                                        }

                                        Row {
                                            id: head
                                            x: Theme.s3; y: Theme.s2
                                            spacing: 6
                                            Text {
                                                text: reasoningCard.stillThinking ? "◌" : "○"
                                                color: reasoningCard.stillThinking ? pWarn : Theme.textFaint
                                                font { family: Theme.fontMono; pixelSize: 11 }
                                                SequentialAnimation on rotation {
                                                    running: reasoningCard.stillThinking
                                                    loops: Animation.Infinite
                                                    NumberAnimation { from: 0; to: 360; duration: 900 }
                                                }
                                            }
                                            Text {
                                                text: reasoningCard.stillThinking ? "Thinking through problem…" : "Thought process"
                                                color: reasoningCard.stillThinking ? pWarn : Theme.textDim
                                                font { family: Theme.fontUi; pixelSize: Theme.tCaption; italic: true; weight: Font.DemiBold }
                                            }
                                            Text {
                                                text: reasoningCard.expanded ? "▾" : "▸"
                                                color: Theme.textFaint
                                                font { family: Theme.fontMono; pixelSize: 9 }
                                            }
                                        }

                                        Text {
                                            id: bodyText
                                            visible: reasoningCard.expanded
                                            x: Theme.s3; y: head.height + Theme.s2
                                            width: parent.width - Theme.s3 * 2
                                            wrapMode: Text.WordWrap
                                            lineHeight: 1.30
                                            text: seg ? (seg.text || "") : ""
                                            color: Theme.textDim
                                            font { family: Theme.fontMono; pixelSize: Theme.tCaption }
                                        }
                                    }
                                }
                            }

                            // Tool call card
                            Component {
                                id: toolCardComp
                                Item {
                                    id: cardRoot
                                    readonly property var seg: parent ? parent.seg : ({})
                                    width: col.width
                                    height: card.height
                                    Behavior on height { NumberAnimation { duration: Theme.durFast; easing.type: Theme.easeOut } }

                                    readonly property color statusColor: {
                                        var st = seg ? seg.status : "";
                                        if (st === "ok") return pAccent2;
                                        if (st === "blocked") return pDanger;
                                        if (st === "running") return pAccentText;
                                        return Theme.textFaint;
                                    }
                                    readonly property string statusGlyph: {
                                        var st = seg ? seg.status : "";
                                        if (st === "ok") return "✓";
                                        if (st === "blocked") return "✗";
                                        if (st === "running") return "▸";
                                        return "…";
                                    }
                                    readonly property bool hasDetail: !!(seg && seg.detail && seg.detail.text)
                                    readonly property bool isActive: seg && (seg.status === "running" || seg.status === "building")

                                    Repeater {
                                        model: Theme.shadowFor(0)
                                        delegate: Rectangle {
                                            required property var modelData
                                            anchors.fill: card
                                            anchors.margins: -modelData.grow
                                            anchors.topMargin: -modelData.grow + modelData.dy
                                            radius: card.radius + modelData.grow
                                            color: Qt.rgba(0, 0, 0, modelData.a)
                                        }
                                    }

                                    Rectangle {
                                        id: card
                                        width: parent.width
                                        height: toolCol.height + Theme.s3 * 2
                                        radius: Theme.rM
                                        color: Theme.surfaceLow
                                        border.width: 1
                                        border.color: cardRoot.isActive ? Theme.alpha(cardRoot.statusColor, 0.35) : Theme.stroke
                                        Behavior on border.color { ColorAnimation { duration: Theme.durMed } }

                                        // Status-colored left accent bar, mirroring the prose
                                        // bubble's beacon — one consistent "what's this row about"
                                        // language across every segment type.
                                        Rectangle {
                                            anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 6 }
                                            width: 3
                                            radius: 1.5
                                            color: cardRoot.statusColor
                                            opacity: cardRoot.isActive ? (0.55 + 0.45 * Theme.heartbeatSin) : 0.85
                                        }

                                        Column {
                                            id: toolCol
                                            x: Theme.s3 + 6; y: Theme.s2
                                            width: parent.width - Theme.s3 * 2 - 6
                                            spacing: 5

                                            Row {
                                                width: parent.width
                                                spacing: 6
                                                Rectangle {
                                                    id: statusDot
                                                    width: 16; height: 16; radius: 8
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    color: Theme.alpha(cardRoot.statusColor, 0.18)
                                                    border.width: 1
                                                    border.color: Theme.alpha(cardRoot.statusColor, 0.40)

                                                    // Soft glow behind the status dot while the tool
                                                    // is actually doing something — reuses the
                                                    // shared heartbeat oscillator, no per-card timer.
                                                    Rectangle {
                                                        anchors.centerIn: parent
                                                        width: parent.width + 10; height: parent.height + 10
                                                        radius: width / 2
                                                        visible: cardRoot.isActive
                                                        color: "transparent"
                                                        border.width: 4
                                                        border.color: Theme.alpha(cardRoot.statusColor, 0.12 + 0.14 * Theme.heartbeatSin)
                                                        z: -1
                                                    }

                                                    Text {
                                                        anchors.centerIn: parent
                                                        text: cardRoot.statusGlyph
                                                        color: cardRoot.statusColor
                                                        font { family: Theme.fontMono; pixelSize: 9; bold: true }
                                                    }
                                                }

                                                Text {
                                                    text: (seg && seg.name) ? seg.name : "tool"
                                                    color: Theme.text
                                                    font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                                                    anchors.verticalCenter: parent.verticalCenter
                                                }

                                                Row {
                                                    width: parent.width - 90
                                                    spacing: 4
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    clip: true

                                                    Text {
                                                        id: toolSummaryTxt
                                                        width: Math.min(implicitWidth, parent.width - (streamingCursor.visible ? 14 : 0))
                                                        text: (seg && seg.status === "building")
                                                              ? (seg.argsText || "streaming arguments…")
                                                              : (seg && seg.summary && seg.summary !== seg.name ? seg.summary : "")
                                                        color: (seg && seg.status === "building") ? pAccent : Theme.textFaint
                                                        elide: Text.ElideRight
                                                        maximumLineCount: 1
                                                        font { family: Theme.fontMono; pixelSize: 9 }
                                                        anchors.verticalCenter: parent.verticalCenter
                                                    }

                                                    Text {
                                                        id: streamingCursor
                                                        visible: !!(seg && seg.status === "building")
                                                        text: "▋"
                                                        color: pAccentText
                                                        font { family: Theme.fontMono; pixelSize: 8 }
                                                        anchors.verticalCenter: parent.verticalCenter
                                                        SequentialAnimation on opacity {
                                                            running: streamingCursor.visible; loops: Animation.Infinite
                                                            NumberAnimation { from: 1; to: 0.15; duration: 380; easing.type: Easing.InOutQuad }
                                                            NumberAnimation { from: 0.15; to: 1; duration: 380; easing.type: Easing.InOutQuad }
                                                        }
                                                    }
                                                }
                                            }

                                            Loader {
                                                width: parent.width
                                                active: cardRoot.hasDetail
                                                sourceComponent: TerminalCard {
                                                    width: toolCol.width
                                                    text: (seg && seg.detail) ? (seg.detail.text || "") : ""
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // Typing / thinking status & live SSE generation telemetry
                        footer: Item {
                            width: feed.width
                            height: typing.visible ? 28 : 0
                            Behavior on height { NumberAnimation { duration: Theme.durMed } }
                            Row {
                                id: typing
                                visible: AgentState.status === "working"
                                spacing: 8
                                anchors.verticalCenter: parent.verticalCenter

                                Row {
                                    spacing: 5
                                    anchors.verticalCenter: parent.verticalCenter

                                    Text {
                                        text: "Kinetix executing"
                                        color: pAccentText
                                        font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1 }
                                        anchors.verticalCenter: parent.verticalCenter
                                    }

                                    Repeater {
                                        model: 3
                                        Rectangle {
                                            required property int index
                                            width: 5; height: 5; radius: 2.5
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: pAccent
                                            SequentialAnimation on opacity {
                                                running: typing.visible; loops: Animation.Infinite
                                                PauseAnimation { duration: index * 180 }
                                                NumberAnimation { from: 0.2; to: 1; duration: 450; easing.type: Easing.InOutSine }
                                                NumberAnimation { from: 1; to: 0.2; duration: 450; easing.type: Easing.InOutSine }
                                                PauseAnimation { duration: 360 }
                                            }
                                        }
                                    }
                                }

                                // Live streaming telemetry pill
                                Rectangle {
                                    visible: AgentState.streamTps > 0 || AgentState.streamTokens > 0
                                    height: 18
                                    implicitWidth: streamTelemRow.implicitWidth + 12
                                    radius: 9
                                    color: Theme.alpha(pAccent, 0.12)
                                    border.width: 1
                                    border.color: Theme.alpha(pAccent, 0.35)
                                    anchors.verticalCenter: parent.verticalCenter

                                    Row {
                                        id: streamTelemRow
                                        anchors.centerIn: parent
                                        spacing: 5

                                        Text {
                                            text: "⚡"
                                            color: pAccentText
                                            font.pixelSize: 8
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                        Text {
                                            text: (AgentState.streamTps > 0 ? (AgentState.streamTps.toFixed(1) + " tok/s") : "")
                                                  + (AgentState.streamTokens > 0 ? ((AgentState.streamTps > 0 ? " · " : "") + AgentState.streamTokens + " tok") : "")
                                                  + (AgentState.streamTtft > 0 ? (" · " + AgentState.streamTtft + "ms TTFT") : "")
                                            color: pAccentText
                                            font { family: Theme.fontMono; pixelSize: 8; weight: Font.DemiBold }
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Ultra-Sleek Glass Scroll Indicator
                    Rectangle {
                        id: feedScrollTrack
                        anchors { right: feed.right; rightMargin: 1; top: feed.top; bottom: feed.bottom }
                        width: 3
                        radius: 1.5
                        color: Qt.rgba(1, 1, 1, 0.04)
                        visible: feed.contentHeight > feed.height

                        Rectangle {
                            width: parent.width
                            radius: parent.radius
                            height: Math.max(20, (feed.height / Math.max(feed.contentHeight, 1)) * feed.height)
                            y: (feed.contentY / Math.max(feed.contentHeight - feed.height, 1)) * (feed.height - height)
                            color: Theme.alpha(pAccent, 0.5)
                            opacity: (feed.moving || feed.flicking) ? 1.0 : 0.35
                            Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                        }
                    }

                    // Floating "Jump to Latest" pill button
                    Repeater {
                        model: Theme.shadowFor(1)
                        delegate: Rectangle {
                            required property var modelData
                            anchors.fill: jumpBottomBtn
                            anchors.margins: -modelData.grow
                            anchors.topMargin: -modelData.grow + modelData.dy
                            radius: jumpBottomBtn.radius + modelData.grow
                            color: Qt.rgba(0, 0, 0, modelData.a)
                            opacity: jumpBottomBtn.opacity
                        }
                    }
                    Rectangle {
                        id: jumpBottomBtn
                        anchors {
                            horizontalCenter: parent.horizontalCenter
                            bottom: compactionStrip.visible ? compactionStrip.top
                                  : approvalBanner.visible ? approvalBanner.top : composer.top
                            bottomMargin: 10
                        }
                        height: 24
                        implicitWidth: jumpRow.implicitWidth + 20
                        radius: Theme.rPill
                        color: jumpMa.containsMouse ? Theme.surfaceHigh : pWell
                        border.width: 1
                        border.color: jumpMa.containsMouse ? pAccent : Theme.alpha(pAccent, 0.45)
                        visible: opacity > 0
                        opacity: (feed.contentY < feed.contentHeight - feed.height - 80 && feed.count > 0) ? 1.0 : 0.0
                        Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }

                        Row {
                            id: jumpRow
                            anchors.centerIn: parent
                            spacing: 5
                            Text {
                                text: "↓"
                                color: pAccentText
                                font { family: Theme.fontMono; pixelSize: 10; weight: Font.Bold }
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: "Jump to Latest"
                                color: Theme.text
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }

                        MouseArea {
                            id: jumpMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                feed.autoFollow = true;
                                feed.positionViewAtEnd();
                            }
                        }
                    }

                    // Compaction status strip
                    Rectangle {
                        id: compactionStrip
                        width: parent.width
                        height: AgentState.compacting ? 28 : 0
                        anchors.bottom: approvalBanner.visible ? approvalBanner.top : composer.top
                        anchors.bottomMargin: AgentState.compacting ? Theme.s2 : 0
                        radius: Theme.rS
                        clip: true
                        color: Theme.alpha(pAccent, 0.12)
                        border.width: 1
                        border.color: Theme.alpha(pAccent, 0.32)
                        Behavior on height { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

                        Text {
                            anchors { left: parent.left; leftMargin: Theme.s3; verticalCenter: parent.verticalCenter }
                            text: "⌘  " + AgentState.compactionLabel
                            color: Theme.textDim
                            font { family: Theme.fontMono; pixelSize: Theme.tCaption }
                        }
                        Rectangle {
                            anchors { right: parent.right; rightMargin: Theme.s3; verticalCenter: parent.verticalCenter }
                            width: 74; height: 3; radius: 2; color: Theme.stroke
                            Rectangle { width: parent.width * AgentState.compactionProgress; height: parent.height; radius: 2; color: pAccent2 }
                        }
                    }

                    // Commit-tier approval banner
                    Repeater {
                        model: Theme.shadowFor(2)
                        delegate: Rectangle {
                            required property var modelData
                            visible: approvalBanner.visible
                            anchors.fill: approvalBanner
                            anchors.margins: -modelData.grow
                            anchors.topMargin: -modelData.grow + modelData.dy
                            radius: approvalBanner.radius + modelData.grow
                            color: Qt.rgba(0, 0, 0, modelData.a)
                        }
                    }
                    Rectangle {
                        id: approvalBanner
                        width: parent.width
                        height: ArgusBridge.pendingApproval !== null ? approvalCol.implicitHeight + Theme.s3 * 2 : 0
                        radius: Theme.rM
                        color: Theme.alpha(pWarn, 0.14)
                        border.width: 1
                        border.color: Theme.alpha(pWarn, 0.45)
                        clip: true
                        visible: height > 1
                        anchors { bottom: composer.top; bottomMargin: Theme.s2 }
                        Behavior on height { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

                        Column {
                            id: approvalCol
                            anchors { fill: parent; margins: Theme.s3 }
                            spacing: 4
                            Row {
                                spacing: 6
                                Text { text: "⚠"; color: pWarn; font.pixelSize: 12 }
                                Text {
                                    text: "COMMIT ACTION — HUMAN APPROVAL REQUIRED"
                                    color: pWarn
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.Bold }
                                }
                            }
                            Text {
                                width: parent.width
                                text: ArgusBridge.pendingApproval ? ArgusBridge.pendingApproval.summary : ""
                                color: Theme.text
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                                elide: Text.ElideRight
                            }
                            Row {
                                spacing: Theme.s2
                                PillButton {
                                    text: "Approve"
                                    tint: pAccent2
                                    highlighted: true
                                    implicitHeight: 24
                                    onClicked: ArgusBridge.resolveApproval(true, false)
                                }
                                PillButton {
                                    text: "Always Allow"
                                    tint: pAccent2
                                    implicitHeight: 24
                                    onClicked: ArgusBridge.resolveApproval(true, true)
                                }
                                PillButton {
                                    text: "Deny"
                                    tint: pDanger
                                    implicitHeight: 24
                                    onClicked: ArgusBridge.resolveApproval(false, false)
                                }
                            }
                        }
                    }

                    // Outer focus glow & busy breathing aura for composer
                    Rectangle {
                        anchors.fill: composer
                        anchors.margins: -2
                        radius: composer.radius + 2
                        color: "transparent"
                        border.width: 2
                        border.color: ArgusBridge.busy
                                      ? Qt.rgba(pAccent.r, pAccent.g, pAccent.b, busyPulse.opacityVal)
                                      : (input.activeFocus ? Theme.alpha(pAccent, 0.35) : "transparent")
                        Behavior on border.color {
                            enabled: !ArgusBridge.busy
                            ColorAnimation { duration: Theme.durMed }
                        }

                        QtObject {
                            id: busyPulse
                            property real opacityVal: 0.25
                            SequentialAnimation on opacityVal {
                                running: ArgusBridge.busy
                                loops: Animation.Infinite
                                NumberAnimation { from: 0.18; to: 0.60; duration: 900; easing.type: Easing.InOutSine }
                                NumberAnimation { from: 0.60; to: 0.18; duration: 900; easing.type: Easing.InOutSine }
                            }
                        }
                    }

                    // Luxury Glass Composer (Prompt input well with multi-line auto-expand)
                    Repeater {
                        model: Theme.shadowFor(1)
                        delegate: Rectangle {
                            required property var modelData
                            anchors.fill: composer
                            anchors.margins: -modelData.grow
                            anchors.topMargin: -modelData.grow + modelData.dy
                            radius: composer.radius + modelData.grow
                            color: Qt.rgba(0, 0, 0, modelData.a)
                        }
                    }
                    Rectangle {
                        id: composer
                        width: parent.width
                        height: Math.max(46, Math.min(input.contentHeight + 22, 110))
                        radius: 23
                        color: Theme.surfaceLow
                        border.width: 1
                        border.color: input.activeFocus ? Theme.alpha(pAccent, 0.65) : Theme.strokeStrong
                        Behavior on border.color { ColorAnimation { duration: Theme.durMed } }
                        Behavior on height { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutQuint } }
                        anchors { bottom: footerChip.top; bottomMargin: Theme.s2 }

                        // Top inner rim highlight
                        Rectangle {
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
                            height: 1
                            radius: parent.radius
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: "transparent" }
                                GradientStop { position: 0.25; color: input.activeFocus ? Theme.alpha(pAccent, 0.4) : Qt.rgba(1, 1, 1, 0.08) }
                                GradientStop { position: 1.0; color: "transparent" }
                            }
                        }

                        Item {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.s3
                            anchors.rightMargin: 6

                            Text {
                                id: sparkGlyph
                                text: "✦"
                                color: input.activeFocus ? pAccent : Theme.textFaint
                                font.pixelSize: 12
                                anchors { left: parent.left; top: parent.top; topMargin: 15 }
                                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            }

                            Flickable {
                                id: inputFlick
                                anchors {
                                    left: sparkGlyph.right
                                    leftMargin: 8
                                    right: composerActions.left
                                    rightMargin: 6
                                    top: parent.top
                                    bottom: parent.bottom
                                    topMargin: 12
                                    bottomMargin: 10
                                }
                                contentHeight: input.contentHeight
                                contentWidth: width
                                clip: true

                                TextEdit {
                                    id: input
                                    width: inputFlick.width
                                    color: Theme.text
                                    selectionColor: Theme.alpha(pAccent, 0.4)
                                    font { family: Theme.fontUi; pixelSize: Theme.tBody }
                                    wrapMode: TextEdit.Wrap
                                    selectByMouse: true

                                    Text {
                                        anchors.fill: parent
                                        visible: !input.text && !input.activeFocus
                                        text: "Give Kinetix a task… (Shift+↵ newline)"
                                        color: Theme.textFaint; font: input.font
                                    }

                                    Keys.onReturnPressed: function(event) {
                                        if (event.modifiers & Qt.ShiftModifier) {
                                            input.insert(input.cursorPosition, "\n");
                                        } else {
                                            event.accepted = true;
                                            sendBtn.clicked();
                                        }
                                    }
                                    Keys.onEnterPressed: function(event) {
                                        if (event.modifiers & Qt.ShiftModifier) {
                                            input.insert(input.cursorPosition, "\n");
                                        } else {
                                            event.accepted = true;
                                            sendBtn.clicked();
                                        }
                                    }
                                    Keys.onEscapePressed: AgentState.panelOpen = false
                                }
                            }

                            // Composer Action Buttons (Clear draft + Send/Stop)
                            Row {
                                id: composerActions
                                anchors { right: parent.right; bottom: parent.bottom; bottomMargin: 7 }
                                spacing: 4

                                // Clear input draft button
                                Rectangle {
                                    id: clearDraftBtn
                                    visible: input.text.length > 0 && !ArgusBridge.busy
                                    width: 24; height: 24; radius: 12
                                    color: clearDraftMa.containsMouse ? Theme.surfaceHigh : "transparent"
                                    anchors.verticalCenter: parent.verticalCenter

                                    Text {
                                        anchors.centerIn: parent
                                        text: "✕"
                                        color: clearDraftMa.containsMouse ? Theme.text : Theme.textFaint
                                        font { family: Theme.fontMono; pixelSize: 9 }
                                    }

                                    MouseArea {
                                        id: clearDraftMa
                                        anchors.fill: parent
                                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            input.text = "";
                                            input.forceActiveFocus();
                                        }
                                    }
                                }

                                PillButton {
                                    id: sendBtn
                                    implicitWidth: 32; implicitHeight: 32
                                    glyph: ArgusBridge.busy ? "■" : "↵"
                                    tint: ArgusBridge.busy ? pDanger : pAccent
                                    highlighted: ArgusBridge.busy || input.text.trim() !== ""
                                    onClicked: {
                                        if (ArgusBridge.busy) { ArgusBridge.cancel(); return; }
                                        var t = input.text.trim();
                                        if (t === "") return;
                                        ArgusBridge.send(t);
                                        input.text = "";
                                        input.forceActiveFocus();
                                    }
                                }
                            }
                        }
                    }

                    // Interactive Model / Status Footer Chip
                    Rectangle {
                        id: footerChip
                        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
                        implicitWidth: Math.min(footerRow.implicitWidth + 24, parent.width)
                        height: 22
                        radius: Theme.rPill
                        color: footerMa.containsMouse ? Theme.surfaceHigh : Theme.surfaceLow
                        border.width: 1
                        border.color: footerMa.containsMouse ? Theme.strokeStrong : "transparent"
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }

                        Row {
                            id: footerRow
                            anchors.centerIn: parent
                            spacing: 6

                            StatusOrb {
                                anchors.verticalCenter: parent.verticalCenter
                                color: ProviderConfig.hasKey(secretVar) ? pAccent2 : pWarn
                                live: ArgusBridge.busy
                            }

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: ProviderConfig.provider.toUpperCase() + " · " + ProviderConfig.model
                                      + (ProviderConfig.hasKey(secretVar)
                                         ? (ProviderConfig.isSub(ProviderConfig.provider) ? " · LINKED ✓" : " · KEY ✓")
                                         : " · NO KEY")
                                      + (ArgusBridge.busy
                                         ? (AgentState.streamTps > 0
                                            ? (" · " + AgentState.streamTps.toFixed(0) + " TOK/S")
                                            : " · WORKING…")
                                         : "")
                                color: footerMa.containsMouse ? Theme.text : Theme.textFaint
                                font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.0 }
                                elide: Text.ElideRight
                            }

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "▾"
                                color: Theme.textFaint
                                font.pixelSize: 8
                            }
                        }

                        MouseArea {
                            id: footerMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: AgentState.toggleSettings()
                        }
                    }
                }

                // ─────────────────────────────────────────────────────
                // 2. ACTIONS TAB (CONNECTED VERTICAL TIMELINE)
                // ─────────────────────────────────────────────────────
                Item {
                    id: actionsTab
                    anchors.fill: parent
                    visible: !AgentState.settingsOpen && AgentState.activeTab === "actions"

                    // Actions Header Micro-Bar
                    Row {
                        id: actHeaderRow
                        anchors { top: parent.top; left: parent.left; right: parent.right }
                        height: 24

                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6

                            Rectangle {
                                width: 6; height: 6; radius: 3
                                anchors.verticalCenter: parent.verticalCenter
                                color: ArgusBridge.busy ? pAccent : pAccent2
                                SequentialAnimation on opacity {
                                    running: ArgusBridge.busy
                                    loops: Animation.Infinite
                                    NumberAnimation { from: 0.3; to: 1.0; duration: 600 }
                                    NumberAnimation { from: 1.0; to: 0.3; duration: 600 }
                                }
                            }

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "JOURNAL TIMELINE: " + ArgusBridge.actions.length + " EVENTS"
                                color: Theme.textFaint
                                font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.Bold }
                            }
                        }

                        Item { width: Math.max(0, parent.width - x - clearActBtn.width); height: 1 }

                        Rectangle {
                            id: clearActBtn
                            visible: ArgusBridge.actions.length > 0
                            anchors.verticalCenter: parent.verticalCenter
                            implicitWidth: clearActT.implicitWidth + 14
                            height: 20
                            radius: Theme.rPill
                            color: clearActMa.containsMouse ? Theme.alpha(pDanger, 0.16) : "transparent"
                            border.width: 1
                            border.color: clearActMa.containsMouse ? Theme.alpha(pDanger, 0.35) : "transparent"

                            Text {
                                id: clearActT
                                anchors.centerIn: parent
                                text: "✕ Clear Journal"
                                color: clearActMa.containsMouse ? pDanger : Theme.textFaint
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                            }

                            MouseArea {
                                id: clearActMa
                                anchors.fill: parent
                                hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: ArgusBridge.clearActions()
                            }
                        }
                    }

                    // Connected Vertical Timeline
                    Item {
                        anchors {
                            top: actHeaderRow.bottom
                            topMargin: Theme.s2
                            left: parent.left; right: parent.right
                            bottom: parent.bottom
                        }

                        // Continuous Vertical Spine Line
                        Rectangle {
                            anchors { left: parent.left; leftMargin: 17; top: parent.top; bottom: parent.bottom }
                            width: 2
                            color: Theme.stroke
                            visible: ArgusBridge.actions.length > 0
                        }

                        ListView {
                            id: actionList
                            anchors.fill: parent
                            clip: true
                            spacing: Theme.s2
                            model: ArgusBridge.actions

                            // Same stick-to-bottom intent as the chat feed —
                            // don't yank the view back down if the user
                            // scrolled up to read earlier actions.
                            property bool autoFollow: true
                            onMovementStarted: autoFollow = false
                            onAtYEndChanged: if (atYEnd) autoFollow = true
                            onCountChanged: {
                                if (autoFollow) Qt.callLater(positionViewAtEnd);
                            }

                            add: Transition {
                                ParallelAnimation {
                                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.durMed }
                                    NumberAnimation { property: "x"; from: 18; to: 0; duration: Theme.durMed; easing.type: Easing.OutQuint }
                                }
                            }

                            delegate: Item {
                                id: actItem
                                required property var modelData
                                required property int index
                                width: actionList.width
                                height: actCard.height + 4

                                readonly property color actColor: {
                                    var k = modelData.kind;
                                    if (k === "perceive") return pAccent2;
                                    if (k === "plan") return pAccent;
                                    if (k === "act") return pAct;
                                    if (k === "verify") return pVerify;
                                    if (k === "commit") return pWarn;
                                    return pAccent;
                                }

                                readonly property string actIcon: {
                                    var k = modelData.kind;
                                    var m = { "perceive": "◉", "plan": "✦", "act": "▸", "verify": "✓", "commit": "⚠" };
                                    return m[k] || "·";
                                }

                                // Timeline Node Circle
                                Rectangle {
                                    id: nodeCircle
                                    x: 8; y: 8
                                    width: 20; height: 20; radius: 10
                                    color: Theme.alpha(actItem.actColor, 0.18)
                                    border.width: 1.5
                                    border.color: actItem.actColor
                                    z: 2

                                    Text {
                                        anchors.centerIn: parent
                                        text: actItem.actIcon
                                        color: actItem.actColor
                                        font.pixelSize: 10
                                    }
                                }

                                // Timeline Event Card
                                Rectangle {
                                    id: actCard
                                    anchors { left: parent.left; leftMargin: 36; right: parent.right }
                                    height: actCol.implicitHeight + Theme.s3 * 2
                                    radius: Theme.rM
                                    color: Theme.surfaceLow
                                    border.width: 1
                                    border.color: Theme.stroke

                                    Column {
                                        id: actCol
                                        anchors { fill: parent; margins: Theme.s3 }
                                        spacing: 4

                                        Row {
                                            width: parent.width
                                            spacing: 6

                                            // Step Index Pill
                                            Rectangle {
                                                height: 16
                                                implicitWidth: stepT.implicitWidth + 8
                                                radius: 4
                                                color: Theme.alpha(actItem.actColor, 0.15)
                                                anchors.verticalCenter: parent.verticalCenter
                                                Text {
                                                    id: stepT
                                                    anchors.centerIn: parent
                                                    text: "#" + (actItem.index + 1 < 10 ? "0" : "") + (actItem.index + 1)
                                                    color: actItem.actColor
                                                    font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                                                }
                                            }

                                            Text {
                                                text: modelData.kind.toUpperCase()
                                                color: actItem.actColor
                                                font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.Bold }
                                                anchors.verticalCenter: parent.verticalCenter
                                            }

                                            Item { width: Math.max(0, parent.width - x - tsText.width); height: 1 }

                                            Text {
                                                id: tsText
                                                text: modelData.ts
                                                color: Theme.textFaint
                                                font { family: Theme.fontMono; pixelSize: 9 }
                                                anchors.verticalCenter: parent.verticalCenter
                                            }
                                        }

                                        Text {
                                            width: parent.width
                                            text: modelData.summary
                                            color: Theme.text
                                            font { family: Theme.fontUi; pixelSize: Theme.tBody }
                                            wrapMode: Text.WordWrap
                                            lineHeight: 1.3
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Empty state for Actions
                    Column {
                        anchors.centerIn: parent
                        visible: ArgusBridge.actions.length === 0
                        spacing: Theme.s3
                        width: parent.width - Theme.s5 * 2

                        Rectangle {
                            width: 48; height: 48; radius: 24
                            anchors.horizontalCenter: parent.horizontalCenter
                            color: Theme.alpha(pAccent, 0.12)
                            border.width: 1
                            border.color: Theme.alpha(pAccent, 0.32)
                            Text {
                                anchors.centerIn: parent
                                text: "⚡"
                                color: pAccentText
                                font.pixelSize: 20
                            }
                        }

                        Column {
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 4
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: "No Agent Actions Recorded"
                                color: Theme.text
                                font { family: Theme.fontUi; pixelSize: Theme.tTitle; weight: Font.DemiBold }
                            }

                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: "Give Kinetix a task on the Chat tab to watch the autonomous perception → plan → execute → verify journal loop in real time."
                                color: Theme.textFaint
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.WordWrap
                                width: parent.width
                                lineHeight: 1.35
                            }
                        }
                    }
                }

                // ─────────────────────────────────────────────────────
                // 3. MCP TAB (SERVER MANAGEMENT)
                // ─────────────────────────────────────────────────────
                Item {
                    id: mcpTab
                    anchors.fill: parent
                    visible: !AgentState.settingsOpen && AgentState.activeTab === "mcp"

                    property bool addOpen: false
                    property string nameDraft: ""
                    property string commandDraft: ""
                    property string argsDraft: ""

                    function resetDraft() {
                        nameDraft = ""; commandDraft = ""; argsDraft = "";
                    }

                    Flickable {
                        id: mcpFlick
                        anchors.fill: parent
                        contentWidth: width
                        contentHeight: mcpCol.implicitHeight + Theme.s4
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds

                        Column {
                            id: mcpCol
                            width: parent.width
                            spacing: Theme.s4

                            Row {
                                width: parent.width
                                spacing: Theme.s2
                                Text {
                                    text: "MCP SERVERS"
                                    color: pAccentText
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.4; weight: Font.Bold }
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Item { width: Math.max(0, parent.width - x - addBtn.width); height: 1 }
                                PillButton {
                                    id: addBtn
                                    text: mcpTab.addOpen ? "Cancel" : "＋ Add Server"
                                    highlighted: mcpTab.addOpen
                                    onClicked: {
                                        mcpTab.addOpen = !mcpTab.addOpen;
                                        if (!mcpTab.addOpen) mcpTab.resetDraft();
                                    }
                                }
                            }

                            // ── Add-server inline form ──
                            Column {
                                width: parent.width
                                spacing: Theme.s2
                                visible: mcpTab.addOpen

                                Text {
                                    text: "NAME"
                                    color: Theme.textFaint
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                                }
                                Rectangle {
                                    width: parent.width; height: 34; radius: Theme.rS
                                    color: Theme.surface; border.width: 1
                                    border.color: nameField.activeFocus ? Theme.alpha(pAccent, 0.55) : Theme.stroke
                                    Behavior on border.color { ColorAnimation { duration: Theme.durMed } }
                                    TextInput {
                                        id: nameField
                                        anchors { fill: parent; leftMargin: Theme.s3; rightMargin: Theme.s3 }
                                        verticalAlignment: TextInput.AlignVCenter
                                        color: Theme.text
                                        font { family: Theme.fontMono; pixelSize: Theme.tBody }
                                        onTextChanged: mcpTab.nameDraft = text
                                        Text {
                                            anchors.fill: parent
                                            verticalAlignment: Text.AlignVCenter
                                            visible: !nameField.text
                                            text: "e.g. filesystem"
                                            color: Theme.textFaint
                                            font: nameField.font
                                        }
                                    }
                                }

                                Text {
                                    text: "COMMAND"
                                    color: Theme.textFaint
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                                }
                                Rectangle {
                                    width: parent.width; height: 34; radius: Theme.rS
                                    color: Theme.surface; border.width: 1
                                    border.color: cmdField.activeFocus ? Theme.alpha(pAccent, 0.55) : Theme.stroke
                                    Behavior on border.color { ColorAnimation { duration: Theme.durMed } }
                                    TextInput {
                                        id: cmdField
                                        anchors { fill: parent; leftMargin: Theme.s3; rightMargin: Theme.s3 }
                                        verticalAlignment: TextInput.AlignVCenter
                                        color: Theme.text
                                        font { family: Theme.fontMono; pixelSize: Theme.tBody }
                                        onTextChanged: mcpTab.commandDraft = text
                                        Text {
                                            anchors.fill: parent
                                            verticalAlignment: Text.AlignVCenter
                                            visible: !cmdField.text
                                            text: "e.g. npx"
                                            color: Theme.textFaint
                                            font: cmdField.font
                                        }
                                    }
                                }

                                Text {
                                    text: "ARGS (space-separated)"
                                    color: Theme.textFaint
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                                }
                                Rectangle {
                                    width: parent.width; height: 34; radius: Theme.rS
                                    color: Theme.surface; border.width: 1
                                    border.color: argsField.activeFocus ? Theme.alpha(pAccent, 0.55) : Theme.stroke
                                    Behavior on border.color { ColorAnimation { duration: Theme.durMed } }
                                    TextInput {
                                        id: argsField
                                        anchors { fill: parent; leftMargin: Theme.s3; rightMargin: Theme.s3 }
                                        verticalAlignment: TextInput.AlignVCenter
                                        color: Theme.text
                                        font { family: Theme.fontMono; pixelSize: Theme.tBody }
                                        onTextChanged: mcpTab.argsDraft = text
                                        Text {
                                            anchors.fill: parent
                                            verticalAlignment: Text.AlignVCenter
                                            visible: !argsField.text
                                            text: "-y @modelcontextprotocol/server-filesystem /path"
                                            color: Theme.textFaint
                                            font: argsField.font
                                        }
                                    }
                                }

                                Row {
                                    width: parent.width
                                    layoutDirection: Qt.RightToLeft
                                    PillButton {
                                        text: "Save"
                                        highlighted: mcpTab.nameDraft.trim() !== "" && mcpTab.commandDraft.trim() !== ""
                                        onClicked: {
                                            if (mcpTab.nameDraft.trim() === "" || mcpTab.commandDraft.trim() === "") return;
                                            var argsArr = mcpTab.argsDraft.trim() === "" ? [] : mcpTab.argsDraft.trim().split(/\s+/);
                                            McpConfig.addServer(mcpTab.nameDraft.trim(), mcpTab.commandDraft.trim(), argsArr, {});
                                            nameField.text = ""; cmdField.text = ""; argsField.text = "";
                                            mcpTab.resetDraft();
                                            mcpTab.addOpen = false;
                                        }
                                    }
                                }
                            }

                            // ── Empty state ──
                            Text {
                                width: parent.width
                                visible: McpConfig.loaded && McpConfig.servers.length === 0
                                text: "No MCP servers configured yet. Add one to give the agent new tools — "
                                      + "for example: command \"npx\", args \"-y @modelcontextprotocol/server-filesystem /path\"."
                                color: Theme.textFaint
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                                wrapMode: Text.WordWrap
                                horizontalAlignment: Text.AlignHCenter
                                lineHeight: 1.35
                            }

                            // ── Server cards ──
                            Repeater {
                                model: McpConfig.servers
                                delegate: Rectangle {
                                    id: card
                                    required property var modelData
                                    width: mcpCol.width
                                    implicitHeight: cardCol.implicitHeight + Theme.s3 * 2
                                    radius: Theme.rS
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.stroke

                                    Column {
                                        id: cardCol
                                        anchors { fill: parent; margins: Theme.s3 }
                                        spacing: Theme.s2

                                        Row {
                                            width: parent.width
                                            spacing: Theme.s2

                                            StatusOrb {
                                                anchors.verticalCenter: parent.verticalCenter
                                                live: McpConfig.probingServer === card.modelData.name
                                                color: !card.modelData.enabled ? Theme.textFaint
                                                     : (card.modelData.lastProbe && card.modelData.lastProbe.ok) ? pAccent2
                                                     : (card.modelData.lastProbe && !card.modelData.lastProbe.ok) ? pDanger
                                                     : pWarn
                                            }
                                            Text {
                                                text: card.modelData.name
                                                color: Theme.text
                                                font { family: Theme.fontUi; pixelSize: Theme.tBody; weight: Font.DemiBold }
                                                anchors.verticalCenter: parent.verticalCenter
                                                elide: Text.ElideRight
                                            }
                                            Item { width: Math.max(0, parent.width - x - cardRight.width); height: 1 }
                                            Row {
                                                id: cardRight
                                                spacing: Theme.s2
                                                anchors.verticalCenter: parent.verticalCenter
                                                Toggle {
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    checked: card.modelData.enabled
                                                    tint: pAccent
                                                    onToggled: McpConfig.setEnabled(card.modelData.name, checked)
                                                }
                                                CloseButton {
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    box: 24
                                                    tip: "Remove server"
                                                    onClicked: McpConfig.removeServer(card.modelData.name)
                                                }
                                            }
                                        }

                                        Text {
                                            width: parent.width
                                            text: card.modelData.command
                                                  + (card.modelData.args && card.modelData.args.length
                                                     ? " " + card.modelData.args.join(" ") : "")
                                            color: Theme.textFaint
                                            font { family: Theme.fontMono; pixelSize: 9 }
                                            elide: Text.ElideRight
                                        }

                                        Row {
                                            width: parent.width
                                            spacing: Theme.s2

                                            Text {
                                                width: parent.width - testBtn.width - parent.spacing
                                                elide: Text.ElideRight
                                                text: McpConfig.probingServer === card.modelData.name ? "Testing…"
                                                    : !card.modelData.lastProbe ? "Never tested"
                                                    : card.modelData.lastProbe.ok
                                                        ? card.modelData.tools.length + " tool"
                                                          + (card.modelData.tools.length === 1 ? "" : "s")
                                                        : "Error: " + (card.modelData.lastProbe.error || "unknown")
                                                color: (card.modelData.lastProbe && !card.modelData.lastProbe.ok)
                                                       ? pDanger : Theme.textDim
                                                font { family: Theme.fontMono; pixelSize: 9 }
                                            }
                                            PillButton {
                                                id: testBtn
                                                text: "Test"
                                                implicitHeight: 24
                                                onClicked: McpConfig.probeServer(card.modelData.name)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // ─────────────────────────────────────────────────────
                // 4. HISTORY TAB (PAST SESSIONS + REMEMBERED FACTS)
                // ─────────────────────────────────────────────────────
                Item {
                    id: historyTab
                    anchors.fill: parent
                    visible: !AgentState.settingsOpen && AgentState.activeTab === "history"

                    function relativeTime(ms) {
                        var diff = Date.now() - ms;
                        var mins = Math.floor(diff / 60000);
                        if (mins < 1) return "just now";
                        if (mins < 60) return mins + "m ago";
                        var hours = Math.floor(mins / 60);
                        if (hours < 24) return hours + "h ago";
                        return Math.floor(hours / 24) + "d ago";
                    }

                    Flickable {
                        id: historyFlick
                        anchors.fill: parent
                        contentWidth: width
                        contentHeight: historyCol.implicitHeight + Theme.s4
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds

                        Column {
                            id: historyCol
                            width: parent.width
                            spacing: Theme.s4

                            // ── Past Sessions ──
                            Text {
                                text: "PAST SESSIONS"
                                color: pAccentText
                                font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.4; weight: Font.Bold }
                            }

                            Text {
                                width: parent.width
                                visible: SessionHistory.sessions.length === 0
                                text: SessionHistory.loading ? "Loading…" : "No past sessions yet."
                                color: Theme.textFaint
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                            }

                            Repeater {
                                model: SessionHistory.sessions
                                delegate: Rectangle {
                                    id: sessionCard
                                    required property var modelData
                                    width: historyCol.width
                                    implicitHeight: sCol.implicitHeight + Theme.s3 * 2
                                    radius: Theme.rS
                                    color: sessionMa.containsMouse ? Theme.surfaceHigh : Theme.surface
                                    border.width: 1
                                    border.color: sessionMa.containsMouse ? Theme.alpha(pAccent, 0.35) : Theme.stroke
                                    scale: sessionMa.containsMouse ? 1.012 : 1.0
                                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                    Behavior on scale { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

                                    Column {
                                        id: sCol
                                        anchors { fill: parent; margins: Theme.s3 }
                                        spacing: 4
                                        Text {
                                            width: parent.width
                                            text: sessionCard.modelData.title
                                            color: Theme.text
                                            font { family: Theme.fontUi; pixelSize: Theme.tBody; weight: Font.DemiBold }
                                            elide: Text.ElideRight
                                            maximumLineCount: 1
                                        }
                                        Text {
                                            text: historyTab.relativeTime(sessionCard.modelData.last)
                                                  + " · " + sessionCard.modelData.events + " events"
                                            color: Theme.textDim
                                            font { family: Theme.fontMono; pixelSize: 9 }
                                        }
                                    }
                                    MouseArea {
                                        id: sessionMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: SessionHistory.openSession(sessionCard.modelData.session)
                                    }
                                }
                            }

                            // ── Remembered Facts ──
                            Text {
                                text: "REMEMBERED FACTS"
                                color: pAccentText
                                font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.4; weight: Font.Bold }
                            }

                            Text {
                                width: parent.width
                                visible: SessionHistory.memories.length === 0
                                text: "Nothing remembered yet — the agent saves durable facts here "
                                      + "via remember_fact, or automatically when a conversation ends."
                                color: Theme.textFaint
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                                wrapMode: Text.WordWrap
                            }

                            Repeater {
                                model: SessionHistory.memories
                                delegate: Rectangle {
                                    id: memCard
                                    required property var modelData
                                    width: historyCol.width
                                    implicitHeight: Math.max(40, memRow.implicitHeight + Theme.s2 * 2)
                                    radius: Theme.rS
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.stroke

                                    Row {
                                        id: memRow
                                        anchors { left: parent.left; right: parent.right
                                                  verticalCenter: parent.verticalCenter; margins: Theme.s3 }
                                        spacing: Theme.s2

                                        Rectangle {
                                            width: 44; height: 16; radius: 8
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: memCard.modelData.source === "auto"
                                                   ? Theme.alpha(pAccent2, 0.18) : Theme.alpha(pAccent, 0.18)
                                            Text {
                                                anchors.centerIn: parent
                                                text: memCard.modelData.source === "auto" ? "AUTO" : "AGENT"
                                                color: memCard.modelData.source === "auto" ? pAccent2 : pAccent
                                                font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                                            }
                                        }
                                        Text {
                                            width: parent.width - 44 - closeBtn.width - parent.spacing * 2
                                            text: memCard.modelData.text
                                            color: Theme.text
                                            font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                                            wrapMode: Text.WordWrap
                                        }
                                        CloseButton {
                                            id: closeBtn
                                            anchors.verticalCenter: parent.verticalCenter
                                            box: 22
                                            tip: "Forget"
                                            onClicked: SessionHistory.deleteMemory(memCard.modelData.id)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // ─────────────────────────────────────────────────────
                // 5. SETTINGS TAB (FULL-HEIGHT VIEW)
                // ─────────────────────────────────────────────────────
                Item {
                    id: settingsTab
                    anchors.fill: parent
                    visible: AgentState.settingsOpen

                    Flickable {
                        id: sheetFlick
                        anchors.fill: parent
                        contentWidth: width
                        contentHeight: settingsCol.implicitHeight + Theme.s4
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds

                        Column {
                            id: settingsCol
                            width: parent.width
                            spacing: Theme.s4

                            // Top Info Bar
                            Row {
                                width: parent.width
                                spacing: Theme.s2
                                Text {
                                    text: "PROVIDER & MODEL PREFERENCES"
                                    color: pAccentText
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.4; weight: Font.Bold }
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Item { width: Math.max(0, parent.width - x - readyBadge.width); height: 1 }
                                Rectangle {
                                    id: readyBadge
                                    height: 18
                                    implicitWidth: readyBadgeT.implicitWidth + 12
                                    radius: Theme.rPill
                                    color: ProviderConfig.hasKey(secretVar) ? Theme.alpha(pAccent2, 0.16) : Theme.alpha(pWarn, 0.16)
                                    border.width: 1
                                    border.color: ProviderConfig.hasKey(secretVar) ? Theme.alpha(pAccent2, 0.4) : Theme.alpha(pWarn, 0.4)
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text {
                                        id: readyBadgeT
                                        anchors.centerIn: parent
                                        text: ProviderConfig.hasKey(secretVar) ? "CONFIGURED ✓" : "NEEDS CREDENTIALS"
                                        color: ProviderConfig.hasKey(secretVar) ? pAccent2 : pWarn
                                        font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold; letterSpacing: 0.8 }
                                    }
                                }
                            }

                            // Provider Selection
                            Column {
                                width: parent.width
                                spacing: Theme.s2
                                Text {
                                    text: "AI MODEL PROVIDER"
                                    color: Theme.textFaint
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                                }
                                Flow {
                                    width: parent.width
                                    spacing: Theme.s2
                                    Repeater {
                                        model: ProviderConfig.providers
                                        delegate: Rectangle {
                                            required property var modelData
                                            property var prov: modelData
                                            property bool on: ProviderConfig.provider === prov.key
                                            implicitWidth: (settingsCol.width - Theme.s2) / 2
                                            implicitHeight: 48
                                            radius: Theme.rS
                                            color: on ? Theme.alpha(pAccent, 0.18)
                                                 : (provMa.containsMouse ? Theme.surfaceHigh : Theme.surface)
                                            border.width: 1
                                            border.color: on ? Theme.alpha(pAccent, 0.55) : Theme.stroke
                                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                                            Column {
                                                anchors.centerIn: parent
                                                spacing: 3
                                                Text {
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    text: prov.label
                                                    color: on ? Theme.text : Theme.textDim
                                                    font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                                                }
                                                Row {
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    spacing: 4
                                                    Rectangle {
                                                        width: 6; height: 6; radius: 3
                                                        anchors.verticalCenter: parent.verticalCenter
                                                        color: ProviderConfig.hasKey(ProviderConfig.isSub(prov.key) ? prov.subTokenVar : prov.envKey) ? pAccent2 : pDanger
                                                    }
                                                    Text {
                                                        anchors.verticalCenter: parent.verticalCenter
                                                        text: ProviderConfig.hasKey(ProviderConfig.isSub(prov.key) ? prov.subTokenVar : prov.envKey)
                                                              ? (ProviderConfig.isSub(prov.key) ? "LINKED" : "KEY SAVED") : "NO KEY"
                                                        color: Theme.textFaint
                                                        font { family: Theme.fontMono; pixelSize: 9 }
                                                    }
                                                }
                                            }

                                            MouseArea {
                                                id: provMa
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    ProviderConfig.setProvider(prov.key);
                                                    keyDraft = ""; keyField.text = ""; keyVisible = false;
                                                    modelQuery = ""; modelSearch.text = "";
                                                    kickModels(prov.key);
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            // API Key / Subscription Vault
                            Column {
                                width: parent.width
                                spacing: Theme.s2
                                Text {
                                    text: (ProviderConfig.isSub(ProviderConfig.provider) ? "SUBSCRIPTION — " : "API KEY — ") + ProviderConfig.current().label.toUpperCase()
                                    color: Theme.textFaint
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                                }

                                Row {
                                    visible: (ProviderConfig.current().authModes || []).length > 1
                                    spacing: Theme.s1
                                    Repeater {
                                        model: [{ "k": "key", "l": "API key" }, { "k": "sub", "l": "Subscription" }]
                                        delegate: Rectangle {
                                            required property var modelData
                                            property bool on: (ProviderConfig.authMode[ProviderConfig.provider] || "key") === modelData.k
                                            implicitWidth: amT.implicitWidth + 20
                                            implicitHeight: 24
                                            radius: Theme.rPill
                                            color: on ? Theme.alpha(pAccent, 0.20)
                                                     : (amMa.containsMouse ? Theme.surfaceHigh : Theme.surface)
                                            border.width: 1
                                            border.color: on ? Theme.alpha(pAccent, 0.45) : Theme.stroke
                                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                            Text {
                                                id: amT
                                                anchors.centerIn: parent
                                                text: parent.modelData.l
                                                color: parent.on ? Theme.text : Theme.textDim
                                                font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                                            }
                                            MouseArea {
                                                id: amMa
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    ProviderConfig.setAuthMode(ProviderConfig.provider, parent.modelData.k);
                                                    keyDraft = ""; keyField.text = ""; keyVisible = false;
                                                    modelQuery = ""; modelSearch.text = "";
                                                    kickModels(ProviderConfig.provider);
                                                }
                                            }
                                        }
                                    }
                                }

                                Rectangle {
                                    width: parent.width
                                    height: 38
                                    radius: Theme.rS
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: keyField.activeFocus ? Theme.alpha(pAccent, 0.55) : Theme.stroke
                                    Behavior on border.color { ColorAnimation { duration: Theme.durMed } }

                                    Row {
                                        anchors { fill: parent; leftMargin: Theme.s3; rightMargin: Theme.s2 }
                                        spacing: Theme.s2

                                        TextInput {
                                            id: keyField
                                            width: parent.width - showBtn.width - saveBtn.width - parent.spacing * 2
                                            anchors.verticalCenter: parent.verticalCenter
                                            echoMode: keyVisible ? TextInput.Normal : TextInput.Password
                                            passwordCharacter: "•"
                                            color: Theme.text
                                            selectionColor: Theme.alpha(pAccent, 0.4)
                                            font { family: Theme.fontMono; pixelSize: Theme.tBody }
                                            clip: true
                                            onTextChanged: keyDraft = text
                                            Text {
                                                anchors.fill: parent
                                                visible: !keyField.text
                                                text: ProviderConfig.hasKey(secretVar)
                                                      ? "Saved " + ProviderConfig.masked(secretVar) + " — type to replace"
                                                      : (ProviderConfig.isSub(ProviderConfig.provider) ? "Paste subscription token…" : "Paste key…")
                                                color: Theme.textFaint
                                                font: keyField.font
                                                verticalAlignment: Text.AlignVCenter
                                                elide: Text.ElideRight
                                            }
                                            Keys.onReturnPressed: saveBtn.clicked()
                                        }

                                        Text {
                                            id: showBtn
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: keyVisible ? "◉" : "◌"
                                            color: showMa.containsMouse ? Theme.text : Theme.textFaint
                                            font.pixelSize: 14
                                            MouseArea {
                                                id: showMa
                                                anchors.fill: parent; anchors.margins: -6
                                                hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                                onClicked: keyVisible = !keyVisible
                                            }
                                        }

                                        PillButton {
                                            id: saveBtn
                                            anchors.verticalCenter: parent.verticalCenter
                                            implicitWidth: 62; implicitHeight: 28
                                            text: "Save"
                                            highlighted: keyDraft.trim() !== ""
                                            onClicked: {
                                                if (keyDraft.trim() === "") return;
                                                ProviderConfig.setKey(secretVar, keyDraft);
                                                keyDraft = ""; keyField.text = "";
                                                kickModels(ProviderConfig.provider);
                                            }
                                        }
                                    }
                                }

                                Row {
                                    width: parent.width
                                    spacing: Theme.s2

                                    StatusOrb {
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: ProviderConfig.hasKey(secretVar) ? pAccent2 : pWarn
                                        live: false
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: ProviderConfig.hasKey(secretVar)
                                              ? "Saved " + ProviderConfig.masked(secretVar)
                                              : (ProviderConfig.isSub(ProviderConfig.provider)
                                                 ? "Not linked — paste a token below"
                                                 : "No saved key — uses $" + secretVar)
                                        color: Theme.textDim
                                        font { family: Theme.fontMono; pixelSize: Theme.tCaption }
                                    }
                                    Item { width: Math.max(0, parent.width - x - (clearT.visible ? clearT.width : 0) - testBtn.width - parent.spacing * 2); height: 1 }

                                    Text {
                                        id: clearT
                                        visible: ProviderConfig.hasKey(secretVar)
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: "Clear"
                                        color: clearMa.containsMouse ? pDanger : Theme.textFaint
                                        font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                                        MouseArea {
                                            id: clearMa
                                            anchors.fill: parent; anchors.margins: -4
                                            hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                            onClicked: { ProviderConfig.setKey(secretVar, ""); keyDraft = ""; keyField.text = ""; }
                                        }
                                    }

                                    PillButton {
                                        id: testBtn
                                        anchors.verticalCenter: parent.verticalCenter
                                        implicitWidth: 64; implicitHeight: 28
                                        text: ArgusBridge.testing ? "…" : "Test"
                                        tint: pAccent2
                                        onClicked: ArgusBridge.testConnection(ProviderConfig.provider)
                                    }
                                }
                            }

                            // Model Browser
                            Column {
                                width: parent.width
                                spacing: Theme.s2
                                Row {
                                    width: parent.width
                                    spacing: Theme.s2
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: "CATALOG / ACTIVE MODEL"
                                        color: Theme.textFaint
                                        font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                                    }
                                    Item { width: Math.max(0, parent.width - x - countT.width - refBtn.width - parent.spacing * 2); height: 1 }
                                    Text {
                                        id: countT
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: (ProviderConfig.live[ProviderConfig.provider] || []).length > 0
                                              ? ProviderConfig.live[ProviderConfig.provider].length + " LIVE"
                                              : "CURATED"
                                        color: (ProviderConfig.live[ProviderConfig.provider] || []).length > 0 ? pAccent2 : Theme.textFaint
                                        font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1 }
                                    }
                                    Text {
                                        id: refBtn
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: ArgusBridge.modelsLoading ? "…" : "↻"
                                        color: refMa.containsMouse ? Theme.text : Theme.textFaint
                                        font.pixelSize: 13
                                        MouseArea {
                                            id: refMa
                                            anchors.fill: parent; anchors.margins: -5
                                            hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                            onClicked: ArgusBridge.refreshModels(ProviderConfig.provider)
                                        }
                                    }
                                }

                                Rectangle {
                                    width: parent.width
                                    height: 34
                                    radius: Theme.rS
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: modelSearch.activeFocus ? Theme.alpha(pAccent, 0.5) : Theme.stroke
                                    Behavior on border.color { ColorAnimation { duration: Theme.durMed } }

                                    TextInput {
                                        id: modelSearch
                                        anchors { fill: parent; leftMargin: Theme.s3; rightMargin: Theme.s2 }
                                        verticalAlignment: TextInput.AlignVCenter
                                        color: Theme.text
                                        selectionColor: Theme.alpha(pAccent, 0.4)
                                        font { family: Theme.fontMono; pixelSize: Theme.tBody }
                                        clip: true
                                        onTextChanged: modelQuery = text
                                        Text {
                                            anchors.fill: parent
                                            visible: !modelSearch.text
                                            text: "Filter models…"
                                            color: Theme.textFaint
                                            font: modelSearch.font
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                }

                                Rectangle {
                                    width: parent.width
                                    height: Math.min(Math.max(browserModels.length, 1) * 32 + Theme.s2 * 2, 220)
                                    radius: Theme.rS
                                    color: Theme.surfaceLow
                                    border.width: 1
                                    border.color: Theme.stroke
                                    clip: true

                                    ListView {
                                        id: modelList
                                        anchors { fill: parent; margins: Theme.s2 }
                                        clip: true
                                        spacing: 2
                                        boundsBehavior: Flickable.StopAtBounds
                                        model: browserModels
                                        delegate: Rectangle {
                                            required property string modelData
                                            required property int index
                                            property bool on: ProviderConfig.model === modelData
                                            width: modelList.width
                                            height: 30
                                            radius: Theme.rS
                                            color: on ? Theme.alpha(pAccent2, 0.16)
                                                 : (mMa.containsMouse ? Theme.surfaceHigh : "transparent")
                                            Behavior on color { ColorAnimation { duration: Theme.durFast } }

                                            Row {
                                                anchors { left: parent.left; leftMargin: Theme.s2; right: parent.right; rightMargin: Theme.s2; verticalCenter: parent.verticalCenter }
                                                spacing: Theme.s2
                                                Text {
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    width: 14
                                                    text: parent.parent.on ? "✓" : ""
                                                    color: pAccent2
                                                    font.pixelSize: 12
                                                }
                                                Text {
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    width: parent.width - 14 - parent.spacing
                                                    text: parent.parent.modelData
                                                    color: parent.parent.on ? Theme.text : Theme.textDim
                                                    font { family: Theme.fontMono; pixelSize: Theme.tCaption }
                                                    elide: Text.ElideRight
                                                }
                                            }

                                            MouseArea {
                                                id: mMa
                                                anchors.fill: parent
                                                hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                                onClicked: ProviderConfig.setModel(parent.modelData)
                                            }
                                        }
                                    }
                                    Text {
                                        anchors.centerIn: parent
                                        visible: browserModels.length === 0
                                        text: "No models match"
                                        color: Theme.textFaint
                                        font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                                    }
                                }
                            }

                            // Reasoning Effort — extended thinking / reasoning_effort for
                            // models that support it. Global rather than per-provider: argusd.py
                            // maps it to whatever shape the active provider expects, and leaves
                            // the request untouched at "Off", so picking a level here is inert
                            // for a model that doesn't support reasoning rather than breaking it.
                            Column {
                                width: parent.width
                                spacing: Theme.s2
                                Text {
                                    text: "REASONING EFFORT"
                                    color: Theme.textFaint
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                                }
                                Row {
                                    spacing: Theme.s1
                                    Repeater {
                                        model: [
                                            { "k": "off", "l": "Off" },
                                            { "k": "low", "l": "Low" },
                                            { "k": "medium", "l": "Medium" },
                                            { "k": "high", "l": "High" }
                                        ]
                                        delegate: Rectangle {
                                            required property var modelData
                                            property bool on: ProviderConfig.reasoningEffort === modelData.k
                                            implicitWidth: reT.implicitWidth + 20
                                            implicitHeight: 24
                                            radius: Theme.rPill
                                            color: on ? Theme.alpha(pAccent, 0.20)
                                                     : (reMa.containsMouse ? Theme.surfaceHigh : Theme.surface)
                                            border.width: 1
                                            border.color: on ? Theme.alpha(pAccent, 0.45) : Theme.stroke
                                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                            Text {
                                                id: reT
                                                anchors.centerIn: parent
                                                text: parent.modelData.l
                                                color: parent.on ? Theme.text : Theme.textDim
                                                font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                                            }
                                            MouseArea {
                                                id: reMa
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: ProviderConfig.setReasoning(parent.modelData.k)
                                            }
                                        }
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: "Only takes effect on models that support extended thinking / reasoning effort — ignored otherwise."
                                    color: Theme.textFaint
                                    font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                                    wrapMode: Text.Wrap
                                }
                            }

                            // Capability Grants
                            Column {
                                width: parent.width
                                spacing: Theme.s2
                                Text {
                                    text: "CAPABILITY PERMISSION GRANTS"
                                    color: Theme.textFaint
                                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.2; weight: Font.DemiBold }
                                }
                                Repeater {
                                    model: [
                                        { "p": "grantScreen", "l": "Screen capture & OCR reading" },
                                        { "p": "grantInput", "l": "Desktop input injection (keys/mouse)" },
                                        { "p": "grantClipboard", "l": "Clipboard buffer access" },
                                        { "p": "grantShell", "l": "Sandboxed shell execution" },
                                        { "p": "grantNet", "l": "Sandboxed outbound network" }
                                    ]
                                    delegate: Row {
                                        width: parent.width
                                        spacing: Theme.s2
                                        Text {
                                            width: parent.width - 44
                                            text: modelData.l
                                            color: Theme.textDim
                                            font { family: Theme.fontUi; pixelSize: Theme.tBody }
                                        }
                                        Toggle {
                                            checked: ProviderConfig[modelData.p]
                                            tint: pAccent
                                            onToggled: function(c) { ProviderConfig[modelData.p] = c }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Glass Scroll Indicator for Settings
                    Rectangle {
                        anchors { right: parent.right; rightMargin: 1; top: parent.top; bottom: parent.bottom }
                        width: 3
                        radius: 1.5
                        color: Qt.rgba(1, 1, 1, 0.04)
                        visible: sheetFlick.contentHeight > sheetFlick.height

                        Rectangle {
                            width: parent.width
                            radius: parent.radius
                            height: Math.max(20, (sheetFlick.height / Math.max(sheetFlick.contentHeight, 1)) * sheetFlick.height)
                            y: (sheetFlick.contentY / Math.max(sheetFlick.contentHeight - sheetFlick.height, 1)) * (sheetFlick.height - height)
                            color: Theme.alpha(pAccent, 0.5)
                            opacity: (sheetFlick.moving || sheetFlick.flicking) ? 1.0 : 0.35
                        }
                    }
                }
            }
        }

        Connections {
            target: AgentState
            function onPanelOpenChanged() {
                if (AgentState.panelOpen) Qt.callLater(input.forceActiveFocus);
            }
        }
        Connections {
            target: ArgusBridge
            function onTestFinished(ok) {
                if (ok) kickModels(ArgusBridge.testTarget);
            }
        }
        Connections {
            target: ProviderConfig
            function onCodexImported(ok) {
                if (ok) {
                    keyDraft = ""; keyField.text = "";
                    kickModels("openai");
                }
            }
        }
    }
}
