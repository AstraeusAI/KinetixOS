import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import "../common"
import "../components"

// Full application launcher: dimmed scrim, centered glass window, category
// filters, icon grid, keyboard navigation. Open with the grid button in the
// bar or from the command palette.
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "argus:launcher"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: AgentState.launcherOpen
                                 ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    visible: AgentState.launcherOpen

    property string query: ""
    property string cat: "All"

    // scrim
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, AgentState.launcherOpen ? 0.45 : 0)
        Behavior on color { ColorAnimation { duration: Theme.durSlow } }
        MouseArea { anchors.fill: parent; onClicked: AgentState.launcherOpen = false }
    }

    GlassPanel {
        id: card
        anchors.centerIn: parent
        width: Math.min(820, parent.width - 80)
        height: Math.min(560, parent.height - 100)
        radius: Theme.rXL
        level: 3
        clipContent: true

        scale: AgentState.launcherOpen ? 1 : 0.96
        opacity: AgentState.launcherOpen ? 1 : 0
        transform: Translate { y: 14 * (1 - card.opacity) }
        Behavior on opacity { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
        Behavior on scale { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

        MouseArea { anchors.fill: parent; onClicked: {} }

        Column {
            anchors { fill: parent; margins: Theme.s5 }
            spacing: Theme.s4

            // ── title + exit ──
            Row {
                width: parent.width
                spacing: Theme.s3
                Text {
                    text: "APPLICATIONS"
                    color: Theme.text
                    font { family: Theme.fontMono; pixelSize: Theme.tLabel; letterSpacing: 2.5; weight: Font.DemiBold }
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: "ESC TO CLOSE"
                    color: Theme.textFaint
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.2 }
                    anchors.verticalCenter: parent.verticalCenter
                }
                Item { width: Math.max(0, parent.width - x - closeBtn.width); height: 1 }
                CloseButton {
                    id: closeBtn
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: AgentState.launcherOpen = false
                }
            }

            // ── search ──
            Rectangle {
                width: parent.width
                height: 52
                radius: Theme.rM
                color: Theme.surfaceLow
                border.width: 1
                border.color: search.activeFocus
                              ? Theme.alpha(Theme.accent, 0.55) : Theme.stroke
                Behavior on border.color { ColorAnimation { duration: Theme.durMed } }

                Text {
                    anchors { left: parent.left; leftMargin: Theme.s4; verticalCenter: parent.verticalCenter }
                    text: "⌕"
                    color: Theme.textFaint
                    font.pixelSize: 20
                }
                TextInput {
                    id: search
                    anchors { left: parent.left; leftMargin: 44; right: rightControls.left; rightMargin: Theme.s3; verticalCenter: parent.verticalCenter }
                    color: Theme.text
                    font { family: Theme.fontUi; pixelSize: Theme.tHeading }
                    clip: true
                    focus: AgentState.launcherOpen
                    onActiveFocusChanged: if (AgentState.launcherOpen && !activeFocus) forceActiveFocus()
                    onTextChanged: { win.query = text; grid.currentIndex = 0; }
                    Keys.onEscapePressed: AgentState.launcherOpen = false
                    Keys.onReturnPressed: {
                        var app = grid.currentItem ? grid.currentItem.appData : null;
                        if (app) { AppIndex.launch(app); AgentState.launcherOpen = false; }
                    }
                    Keys.onDownPressed: grid.moveCurrentIndexDown()
                    Keys.onUpPressed: grid.moveCurrentIndexUp()
                    Keys.onLeftPressed: grid.moveCurrentIndexLeft()
                    Keys.onRightPressed: grid.moveCurrentIndexRight()
                    Text {
                        anchors.fill: parent
                        visible: !search.text
                        text: "Search applications…"
                        color: Theme.textFaint
                        font: search.font
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                Row {
                    id: rightControls
                    anchors { right: parent.right; rightMargin: Theme.s4; verticalCenter: parent.verticalCenter }
                    spacing: Theme.s2

                    Text {
                        id: count
                        text: grid.count + " apps"
                        color: Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: Theme.tCaption }
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Rectangle {
                        width: 26
                        height: 26
                        radius: 6
                        color: rescanMa.containsMouse ? Theme.surfaceHigh : "transparent"
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                            id: spinIcon
                            anchors.centerIn: parent
                            text: "↻"
                            color: rescanMa.containsMouse ? Theme.accent : Theme.textDim
                            font.pixelSize: 15
                            rotation: 0
                            NumberAnimation on rotation {
                                running: AppIndex.scanning
                                loops: Animation.Infinite
                                from: 0; to: 360; duration: 800
                            }
                        }

                        MouseArea {
                            id: rescanMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: AppIndex.rescan()
                        }
                    }
                }
            }

            // ── categories ──
            Flickable {
                width: parent.width
                height: 30
                contentWidth: catRow.width
                clip: true
                flickableDirection: Flickable.HorizontalFlick
                boundsBehavior: Flickable.StopAtBounds

                Row {
                    id: catRow
                    spacing: Theme.s1 + 2
                    Repeater {
                        model: AppIndex.categoryOrder
                        delegate: Rectangle {
                            required property string modelData
                            property bool on: win.cat === modelData
                            implicitWidth: catT.implicitWidth + Theme.s3 * 2
                            implicitHeight: 28
                            radius: Theme.rPill
                            color: on ? Theme.alpha(Theme.accent, 0.18)
                                 : (catMa.containsMouse ? Theme.surfaceHigh : Theme.surfaceLow)
                            border.width: 1
                            border.color: on ? Theme.alpha(Theme.accent, 0.42) : Theme.stroke
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Text {
                                id: catT
                                anchors.centerIn: parent
                                text: parent.modelData
                                color: parent.on ? Theme.text : Theme.textDim
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                            }
                            MouseArea {
                                id: catMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: { win.cat = modelData; grid.currentIndex = 0; }
                            }
                        }
                    }
                }
            }

            // ── app grid ──
            GridView {
                id: grid
                width: parent.width
                height: parent.height - y - hint.height - Theme.s3
                clip: true
                cellWidth: Math.floor(width / 6)
                cellHeight: 104
                model: AppIndex.filter(win.query, win.cat)
                currentIndex: 0
                keyNavigationWraps: true

                delegate: Item {
                    id: cell
                    required property var modelData
                    required property int index
                    width: grid.cellWidth
                    height: grid.cellHeight
                    property var appData: modelData
                    property bool cur: GridView.isCurrentItem

                    Rectangle {
                        anchors { fill: parent; margins: 5 }
                        radius: Theme.rM
                        color: cur ? Theme.alpha(Theme.accent, 0.16)
                             : cellMa.containsMouse ? Theme.surfaceHigh : "transparent"
                        border.width: 1
                        border.color: cur ? Theme.alpha(Theme.accent, 0.38) : "transparent"
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }

                        Column {
                            anchors.centerIn: parent
                            width: parent.width - Theme.s3
                            spacing: Theme.s2

                            Item {
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: 46; height: 46
                                Rectangle {
                                    anchors.fill: parent
                                    radius: Theme.rM
                                    color: Theme.surfaceLow
                                }
                                IconImage {
                                    anchors.centerIn: parent
                                    implicitSize: 34
                                    source: cell.modelData.icon !== "" ? "file://" + cell.modelData.icon : ""
                                    visible: cell.modelData.icon !== ""
                                }
                                Text {
                                    anchors.centerIn: parent
                                    visible: cell.modelData.icon === ""
                                    text: "▢"
                                    color: Theme.textFaint
                                    font.pixelSize: 20
                                }
                            }
                            Text {
                                width: parent.width
                                text: cell.modelData.name
                                color: Theme.text
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.Medium }
                                horizontalAlignment: Text.AlignHCenter
                                elide: Text.ElideRight
                                maximumLineCount: 2
                                wrapMode: Text.WordWrap
                            }
                        }

                        // favorite star
                        Text {
                            anchors { top: parent.top; right: parent.right; margins: 6 }
                            text: AppIndex.isFav(cell.modelData) ? "★" : "☆"
                            color: AppIndex.isFav(cell.modelData) ? Theme.warn
                                 : (cellMa.containsMouse ? Theme.textFaint : "transparent")
                            font.pixelSize: 12
                        }
                    }

                    MouseArea {
                        id: cellMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: function(mouse) {
                            grid.currentIndex = cell.index;
                            if (mouse.button === Qt.RightButton) AppIndex.toggleFav(cell.modelData);
                            else { AppIndex.launch(cell.modelData); AgentState.launcherOpen = false; }
                        }
                    }
                }

                // empty state
                Text {
                    anchors.centerIn: parent
                    visible: grid.count === 0
                    text: AppIndex.ready ? "No applications match" : "Scanning applications…"
                    color: Theme.textFaint
                    font { family: Theme.fontUi; pixelSize: Theme.tBody }
                }
            }

            Text {
                id: hint
                anchors.horizontalCenter: parent.horizontalCenter
                text: "↵ LAUNCH   ·   ⇥ NAVIGATE   ·   RIGHT-CLICK PIN   ·   ESC CLOSE"
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.2 }
            }
        }
    }

    Connections {
        target: AgentState
        function onLauncherOpenChanged() {
            if (AgentState.launcherOpen) {
                AppIndex.rescan();
                win.query = "";
                search.text = "";
                win.cat = "All";
                grid.currentIndex = 0;
                Qt.callLater(search.forceActiveFocus);
            }
        }
    }
}
