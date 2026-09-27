import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "../common"
import "../components"

// Command palette: app launcher + agent commands. Open from the bar's
// search pill. Agent can also populate it (Phase 2: argusd command surface).
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; left: true; right: true }
    implicitHeight: 420
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "argus:palette"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: AgentState.paletteOpen
                                 ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    visible: AgentState.paletteOpen

    // global "close" — clicking outside the card closes. The card stops propagation.
    // (No `mask`: an empty Region would make the whole surface click-through and
    //  the result rows unclickable. The scrim MouseArea handles outside clicks.)
    MouseArea {
        anchors.fill: parent
        onClicked: AgentState.paletteOpen = false
    }

    GlassPanel {
        id: card
        anchors { top: parent.top; topMargin: 66; horizontalCenter: parent.horizontalCenter }
        width: 560
        height: 380
        radius: Theme.rXL
        level: 3
        clipContent: true

        // entrance
        scale: AgentState.paletteOpen ? 1 : 0.96
        opacity: AgentState.paletteOpen ? 1 : 0
        transform: Translate { y: -10 * (1 - card.opacity) }
        Behavior on opacity { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
        Behavior on scale { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

        MouseArea { anchors.fill: parent; onClicked: {} }   // swallow clicks

        Column {
            anchors { fill: parent; margins: Theme.s4 }
            spacing: Theme.s3

            // ── title + exit ──
            Row {
                width: parent.width
                spacing: Theme.s3
                Text {
                    text: "COMMAND"
                    color: Theme.text
                    font { family: Theme.fontMono; pixelSize: Theme.tLabel; letterSpacing: 2.5; weight: Font.DemiBold }
                    anchors.verticalCenter: parent.verticalCenter
                }
                Item { width: Math.max(0, parent.width - x - palClose.width); height: 1 }
                CloseButton {
                    id: palClose
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: AgentState.paletteOpen = false
                }
            }

            // search field
            Rectangle {
                width: parent.width
                height: 44
                radius: Theme.rM
                color: Theme.surfaceLow
                border.width: 1
                border.color: search.activeFocus
                              ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.5)
                              : Theme.stroke

                Text {
                    anchors { left: parent.left; leftMargin: Theme.s3; verticalCenter: parent.verticalCenter }
                    text: "⌘"
                    color: Theme.textFaint
                    font.pixelSize: 16
                }
                TextInput {
                    id: search
                    anchors { left: parent.left; leftMargin: 34; right: parent.right; rightMargin: Theme.s3; verticalCenter: parent.verticalCenter }
                    color: Theme.text
                    font { family: Theme.fontUi; pixelSize: Theme.tBody }
                    clip: true
                    focus: AgentState.paletteOpen
                    onActiveFocusChanged: if (AgentState.paletteOpen && !activeFocus) forceActiveFocus()
                    Text {
                        anchors.fill: parent
                        visible: !search.text
                        text: "Search apps or tell Argus what to do…"
                        color: Theme.textFaint
                        font: search.font
                    }
                    Keys.onEscapePressed: AgentState.paletteOpen = false
                    Keys.onReturnPressed: runFirst()
                    Keys.onDownPressed: list.currentIndex = Math.min(list.currentIndex + 1, list.count - 1)
                    Keys.onUpPressed: list.currentIndex = Math.max(list.currentIndex - 1, 0)
                    onTextChanged: list.currentIndex = 0
                }
            }

            // results
            ListView {
                id: list
                width: parent.width
                height: parent.height - y - 8
                clip: true
                model: filtered
                currentIndex: 0
                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    width: list.width
                    height: 38
                    radius: Theme.rS
                    color: index === list.currentIndex ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.14)
                         : (ma.containsMouse ? Theme.surfaceHigh : "transparent")
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }

                    Row {
                        anchors { left: parent.left; leftMargin: Theme.s3; verticalCenter: parent.verticalCenter }
                        spacing: Theme.s3
                        Text {
                            text: parent.parent.modelData.glyph
                            color: parent.parent.modelData.agent ? Theme.accent2 : Theme.textFaint
                            font.pixelSize: 14
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                text: parent.parent.parent.modelData.name
                                color: Theme.text
                                font { family: Theme.fontUi; pixelSize: Theme.tBody; weight: Font.Medium }
                            }
                            Text {
                                visible: parent.parent.parent.modelData.sub !== ""
                                text: parent.parent.parent.modelData.sub
                                color: Theme.textFaint
                                font { family: Theme.fontMono; pixelSize: 9 }
                            }
                        }
                    }

                    MouseArea {
                        id: ma
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { list.currentIndex = index; runFirst() }
                    }
                }
            }
        }
    }

    // ── data ──────────────────────────────────────────────
    readonly property bool widgetSystemEnabled: Quickshell.env("KINETIX_ENABLE_WIDGETS") === "1"
    property var commands: [
        { "name": "Open app launcher", "sub": "browse all applications", "glyph": "▦", "agent": false, "exec": "launcher" },
        { "name": "New agent task", "sub": "open the agent panel", "glyph": "◉", "agent": true, "exec": "agent" },
        { "name": "Toggle computer use", "sub": "grant/revoke input control", "glyph": "⌨", "agent": true, "exec": "cu" },
        { "name": "Add desktop widget", "sub": "open the widget catalog", "glyph": "◫", "agent": false, "exec": "widgets" },
        { "name": "Toggle widget edit mode", "sub": "move/resize gadgets", "glyph": "✥", "agent": false, "exec": "widgetedit" },
        { "name": "Panic — halt agents", "sub": "revoke all input, freeze", "glyph": "✕", "agent": true, "exec": "panic" }
    ]

    readonly property var filtered: {
        var q = search.text.toLowerCase();
        var out = [];
        var i;
        for (i = 0; i < commands.length; i++) {
            var c = commands[i];
            if (!win.widgetSystemEnabled && (c.exec === "widgets" || c.exec === "widgetedit")) continue;
            if (q === "" || c.name.toLowerCase().indexOf(q) >= 0)
                out.push(c);
        }
        var apps = AppIndex.filter(q, "All");
        for (i = 0; i < apps.length; i++)
            out.push({ "name": apps[i].name, "sub": AppIndex.category(apps[i]),
                       "glyph": "▢", "agent": false, "app": apps[i] });
        return out;
    }

    function runFirst() {
        var m = filtered;
        if (list.currentIndex >= 0 && list.currentIndex < m.length)
            run(m[list.currentIndex]);
    }
    function run(item) {
        if (item.app) { AppIndex.launch(item.app); }
        else if (item.exec === "launcher") { AgentState.launcherOpen = true; }
        else if (item.exec === "agent") { AgentState.panelOpen = true; }
        else if (item.exec === "cu") { AgentState.computerUse = !AgentState.computerUse; }
        else if (item.exec === "widgets" && widgetSystemEnabled) { WidgetStore.catalogOpen = true; }
        else if (item.exec === "widgetedit" && widgetSystemEnabled) { WidgetStore.editMode = !WidgetStore.editMode; }
        else if (item.exec === "panic") { ArgusBridge.panic(); }
        AgentState.paletteOpen = false;
        search.text = "";
    }

    // Fresh query on every open (mirrors AppLauncher's reset).
    Connections {
        target: AgentState
        function onPaletteOpenChanged() {
            if (AgentState.paletteOpen) {
                AppIndex.rescan();
                search.text = "";
                list.currentIndex = 0;
                Qt.callLater(search.forceActiveFocus);
            }
        }
    }
}
