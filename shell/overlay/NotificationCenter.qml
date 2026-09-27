import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland
import "../common"
import "../components"

// Notification Center — slides in from the right edge under the bar. Full
// history of live notifications (newest first) as swipeable glass cards, a
// do-not-disturb switch, clear-all, and an empty state. Opened from the bar's
// bell (AgentState.notifOpen); Esc or the ✕ closes it.
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    readonly property bool open: AgentState.notifOpen
    property real slide: open ? 0 : 1
    Behavior on slide { NumberAnimation { duration: 380; easing.type: Easing.OutQuint } }

    anchors { top: true; right: true; bottom: true }
    margins { top: 62; bottom: 62; right: 14 }
    implicitWidth: 428
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    visible: open || slide < 0.999

    WlrLayershell.namespace: "argus:notifcenter"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: open ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    Item {
        id: root
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: AgentState.notifOpen = false

        Item {
            id: panel
            width: 410
            height: parent.height
            x: win.slide * (width + 30)
            opacity: 1 - win.slide * 0.6
            anchors.verticalCenter: parent.verticalCenter

            // shadow + glass
            Repeater {
                model: [ { "g": 22, "a": 0.08, "dy": 10 }, { "g": 10, "a": 0.12, "dy": 5 }, { "g": 3, "a": 0.20, "dy": 1 } ]
                Rectangle {
                    required property var modelData
                    anchors.fill: glass
                    anchors.margins: -modelData.g
                    anchors.topMargin: -modelData.g + modelData.dy
                    radius: glass.radius + modelData.g
                    color: Qt.rgba(0, 0, 0, modelData.a)
                }
            }
            Rectangle {
                id: glass
                anchors.fill: parent
                radius: 22
                clip: true
                color: Qt.rgba(0.045, 0.025, 0.036, 0.90)
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.12)

                Rectangle {   // depth wash + crimson bloom from the top
                    anchors.fill: parent
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: Qt.rgba(0.36, 0.05, 0.10, 0.34) }
                        GradientStop { position: 0.22; color: Qt.rgba(0.14, 0.04, 0.07, 0.10) }
                        GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.22) }
                    }
                }
                Rectangle {   // top specular hairline
                    anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 22; rightMargin: 22 }
                    height: 1
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.0) }
                        GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.34) }
                        GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0.0) }
                    }
                }

                // ── header ──
                Item {
                    id: head
                    anchors { left: parent.left; right: parent.right; top: parent.top }
                    height: 112
                    Text {
                        anchors { left: parent.left; leftMargin: 22; top: parent.top; topMargin: 18 }
                        text: "Notifications"
                        color: Theme.text
                        font { family: Theme.fontUi; pixelSize: 22; weight: Font.Light }
                    }
                    Text {
                        anchors { left: parent.left; leftMargin: 22; bottom: parent.bottom; bottomMargin: 20 }
                        text: Notif.count === 0 ? "You're all caught up"
                            : Notif.count + (Notif.count === 1 ? " notification" : " notifications")
                        color: Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: 11; letterSpacing: 0.8 }
                    }
                    // close
                    Item {
                        anchors { right: parent.right; rightMargin: 14; top: parent.top; topMargin: 16 }
                        width: 30; height: 30
                        Text { anchors.centerIn: parent; text: "✕"; color: closeMa2.containsMouse ? Theme.text : Theme.textFaint; font.pixelSize: 13 }
                        MouseArea { id: closeMa2; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: AgentState.notifOpen = false }
                    }
                    Row {
                        anchors { right: parent.right; rightMargin: 16; bottom: parent.bottom; bottomMargin: 14 }
                        spacing: 8
                        // DND
                        Rectangle {
                            id: dndBtn
                            height: 30; radius: 15
                            width: dndRow.implicitWidth + 24
                            color: Notif.dnd ? Theme.alpha(Theme.crimson, 0.30) : (dndMa.containsMouse ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(1, 1, 1, 0.055))
                            border.width: 1
                            border.color: Notif.dnd ? Theme.alpha(Theme.crimsonText, 0.6) : Qt.rgba(1, 1, 1, 0.12)
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Row {
                                id: dndRow
                                anchors.centerIn: parent
                                spacing: 7
                                Canvas {   // crescent moon
                                    width: 13; height: 13
                                    anchors.verticalCenter: parent.verticalCenter
                                    property bool on: Notif.dnd
                                    onOnChanged: requestPaint()
                                    onPaint: {
                                        var c = getContext("2d"); c.reset();
                                        c.fillStyle = on ? "#FFD3DA" : "#9A9AA6";
                                        c.beginPath(); c.arc(6.5, 6.5, 5.6, 0.5 * Math.PI, 1.5 * Math.PI, false);
                                        c.arc(8.6, 6.5, 4.6, 1.5 * Math.PI, 0.5 * Math.PI, true); c.fill();
                                    }
                                }
                                Text {
                                    text: "Do not disturb"
                                    color: Notif.dnd ? Theme.text : Theme.textDim
                                    font { family: Theme.fontUi; pixelSize: 12; weight: Font.DemiBold }
                                }
                            }
                            MouseArea { id: dndMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Notif.toggleDnd() }
                        }
                        // Clear all
                        Rectangle {
                            height: 30; radius: 15
                            width: clearLbl.implicitWidth + 24
                            visible: Notif.count > 0
                            color: clearMa.containsMouse ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(1, 1, 1, 0.055)
                            border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.12)
                            Text { id: clearLbl; anchors.centerIn: parent; text: "Clear all"; color: Theme.textDim
                                font { family: Theme.fontUi; pixelSize: 12; weight: Font.DemiBold } }
                            MouseArea { id: clearMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Notif.clearAll() }
                        }
                    }
                    Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: 22; rightMargin: 22 } height: 1; color: Qt.rgba(1, 1, 1, 0.08) }
                }

                // ── history (grouped by app, collapsible) ──
                ListView {
                    id: list
                    anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: foot.top; leftMargin: 14; rightMargin: 14; topMargin: 8 }
                    spacing: 0
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    cacheBuffer: 400
                    model: Notif.items
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 5 }

                    section.property: "appName"
                    section.criteria: ViewSection.FullString
                    section.delegate: Item {
                        id: sec
                        required property string section
                        readonly property bool folded: (Notif.collapsed, Notif.isCollapsed(section))
                        readonly property int n: (Notif.count, Notif.groupCount(section))
                        width: ListView.view.width - 8
                        height: 40
                        Row {
                            anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter }
                            spacing: 9
                            Text {
                                text: "▾"
                                color: Theme.textFaint
                                font.pixelSize: 11
                                rotation: sec.folded ? -90 : 0
                                anchors.verticalCenter: parent.verticalCenter
                                Behavior on rotation { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                            }
                            Text {
                                text: sec.section.toUpperCase()
                                color: Theme.textDim
                                font { family: Theme.fontMono; pixelSize: 11; letterSpacing: 1.6; weight: Font.DemiBold }
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Rectangle {
                                height: 15; radius: 7.5; width: cntTxt.implicitWidth + 12
                                color: Qt.rgba(1, 1, 1, 0.09)
                                anchors.verticalCenter: parent.verticalCenter
                                Text { id: cntTxt; anchors.centerIn: parent; text: sec.n; color: Theme.textDim
                                    font { family: Theme.fontMono; pixelSize: 9; weight: Font.Bold } }
                            }
                        }
                        Text {
                            anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                            text: "Clear"
                            color: clrMa.containsMouse ? Theme.text : Theme.textFaint
                            font { family: Theme.fontMono; pixelSize: 10; letterSpacing: 0.6 }
                            MouseArea { id: clrMa; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor; onClicked: Notif.clearGroup(sec.section) }
                        }
                        MouseArea {
                            anchors { left: parent.left; right: parent.right; top: parent.top; bottom: parent.bottom; rightMargin: 50 }
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Notif.toggleGroup(sec.section)
                        }
                    }

                    delegate: Item {
                        id: row
                        required property var model
                        readonly property bool folded: (Notif.collapsed, Notif.isCollapsed(model.appName))
                        width: ListView.view.width - 8
                        height: folded ? 0 : cardItem.height + 12
                        opacity: folded ? 0 : 1
                        clip: true
                        Behavior on height { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                        Behavior on opacity { NumberAnimation { duration: 180 } }
                        NotifCard {
                            id: cardItem
                            width: parent.width
                            nid: row.model.nid
                            appName: row.model.appName
                            summary: row.model.summary
                            body: row.model.body
                            icon: row.model.icon
                            image: row.model.image
                            urgency: row.model.urgency
                            ts: row.model.ts
                            actionsJson: row.model.actionsJson
                            kind: row.model.kind
                            repeat: row.model.repeat
                            saved: row.model.saved
                            toast: false
                        }
                    }
                    add: Transition {
                        ParallelAnimation {
                            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 260 }
                            NumberAnimation { property: "scale"; from: 0.94; to: 1; duration: 320; easing.type: Easing.OutBack }
                        }
                    }
                    displaced: Transition { NumberAnimation { properties: "x,y"; duration: 300; easing.type: Easing.OutCubic } }
                    remove: Transition {
                        ParallelAnimation {
                            NumberAnimation { property: "x"; to: 440; duration: 300; easing.type: Easing.InCubic }
                            NumberAnimation { property: "opacity"; to: 0; duration: 260 }
                        }
                    }
                }

                // ── footer: error logs ──
                Item {
                    id: foot
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                    height: 48
                    Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 22; rightMargin: 22 } height: 1; color: Qt.rgba(1, 1, 1, 0.08) }
                    Rectangle {
                        anchors { left: parent.left; leftMargin: 18; verticalCenter: parent.verticalCenter; verticalCenterOffset: 1 }
                        height: 28; radius: 14; width: logRow.implicitWidth + 24
                        color: logMa.containsMouse ? Qt.rgba(1, 1, 1, 0.10) : "transparent"
                        border.width: 1; border.color: Qt.rgba(1, 1, 1, logMa.containsMouse ? 0.14 : 0.07)
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        Row {
                            id: logRow
                            anchors.centerIn: parent
                            spacing: 7
                            Text { text: "⚠"; color: "#FF7A5C"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: "Error logs"; color: Theme.textDim; font { family: Theme.fontUi; pixelSize: 12; weight: Font.DemiBold }
                                anchors.verticalCenter: parent.verticalCenter }
                        }
                        MouseArea { id: logMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Notif.openErrorDir() }
                    }
                    Text {
                        anchors { right: parent.right; rightMargin: 22; verticalCenter: parent.verticalCenter; verticalCenterOffset: 1 }
                        text: "Crashes are captured automatically"
                        color: Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: 10; letterSpacing: 0.4 }
                    }
                }

                // ── empty state ──
                Column {
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: 20
                    spacing: 14
                    visible: Notif.count === 0
                    opacity: visible ? 1 : 0
                    Item {
                        width: 84; height: 84
                        anchors.horizontalCenter: parent.horizontalCenter
                        Rectangle {
                            anchors.centerIn: parent
                            width: 84; height: 84; radius: 42
                            color: "transparent"
                            border.width: 1.5
                            border.color: Theme.alpha(Theme.crimson, 0.35 + 0.2 * Theme.heartbeatSin)
                        }
                        Rectangle {
                            anchors.centerIn: parent
                            width: 60; height: 60; radius: 30
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: Theme.alpha(Theme.crimsonText, 0.22) }
                                GradientStop { position: 1.0; color: Theme.alpha(Theme.crimson, 0.06) }
                            }
                        }
                        Canvas {   // check-in-ring
                            anchors.centerIn: parent
                            width: 30; height: 30
                            onPaint: {
                                var c = getContext("2d"); c.reset();
                                c.strokeStyle = "#FFB3C0"; c.lineWidth = 2.6; c.lineCap = "round"; c.lineJoin = "round";
                                c.beginPath(); c.moveTo(7, 16); c.lineTo(13, 22); c.lineTo(24, 9); c.stroke();
                            }
                        }
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "All caught up"
                        color: Theme.text
                        font { family: Theme.fontUi; pixelSize: 18; weight: Font.Light }
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 260; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                        text: Notif.dnd ? "Do not disturb is on. New notifications arrive silently."
                                        : "New notifications from your apps and the agent will appear here."
                        color: Theme.textFaint
                        font { family: Theme.fontUi; pixelSize: 13 }
                    }
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        height: 28; radius: 14; width: prevLbl.implicitWidth + 24
                        color: prevMa.containsMouse ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(1, 1, 1, 0.05)
                        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.10)
                        Text { id: prevLbl; anchors.centerIn: parent; text: "Preview notifications"; color: Theme.textDim
                            font { family: Theme.fontUi; pixelSize: 12 } }
                        MouseArea { id: prevMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Notif.demo() }
                    }
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        height: 28; radius: 14; width: prevErrLbl.implicitWidth + 24
                        color: prevErrMa.containsMouse ? Qt.rgba(1, 0.4, 0.35, 0.16) : Qt.rgba(1, 0.4, 0.35, 0.07)
                        border.width: 1; border.color: Qt.rgba(1, 0.4, 0.35, 0.3)
                        Text { id: prevErrLbl; anchors.centerIn: parent; text: "Preview app error"; color: "#FF9A88"
                            font { family: Theme.fontUi; pixelSize: 12 } }
                        MouseArea { id: prevErrMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: ErrorWatch.simulate() }
                    }
                }

                // shared panel finish: rim, inner glass edge, the system's top light
                PopupChrome { anchors.fill: parent; radius: glass.radius }
            }
        }
    }
}
