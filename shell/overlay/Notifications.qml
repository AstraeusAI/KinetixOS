import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"
import "../components"

// Toast stack for tracked notifications. Lives on the right edge, below the
// bar. Each toast auto-dismisses; click to dismiss early.
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; right: true; bottom: true }
    implicitWidth: 360
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "argus:notifs"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    visible: contentCol.notifCount() > 0

    // Input region == the toast column only: clicks reach toasts/close buttons
    // and pass through everywhere else. (An empty Region made toasts dead.)
    mask: Region { item: contentCol }

    Column {
        id: contentCol
        anchors { top: parent.top; topMargin: 64; right: parent.right; rightMargin: 14 }
        spacing: Theme.s2
        width: 340

        // ObjectModel exposes count/get; plain arrays expose length/[i] —
        // support both so the header works regardless of backend shape.
        function notifCount() {
            var m = Notif.tracked;
            if (!m) return 0;
            return m.count !== undefined ? m.count : (m.length || 0);
        }
        function dismissAll() {
            var m = Notif.tracked;
            if (!m) return;
            var n = contentCol.notifCount();
            for (var i = n - 1; i >= 0; i--) {
                var item = m.get ? m.get(i) : m[i];
                if (item) item.dismiss();
            }
        }

        // ── dismiss-all header + exit ──
        Row {
            width: parent.width
            visible: contentCol.notifCount() > 0
            spacing: Theme.s2
            Text {
                text: contentCol.notifCount() + " NOTIFICATION" + (contentCol.notifCount() === 1 ? "" : "S")
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.4; weight: Font.DemiBold }
                anchors.verticalCenter: parent.verticalCenter
            }
            Item { width: Math.max(0, parent.width - x - clearAll.width - notifClose.width - parent.spacing * 2); height: 1 }
            PillButton {
                id: clearAll
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: 76; implicitHeight: 24
                text: "Clear all"
                onClicked: contentCol.dismissAll()
            }
            CloseButton {
                id: notifClose
                box: 24
                anchors.verticalCenter: parent.verticalCenter
                onClicked: contentCol.dismissAll()
            }
        }

        Repeater {
            model: Notif.tracked
            delegate: GlassPanel {
                id: notifCard
                required property var modelData
                readonly property var item: modelData
                width: 340
                height: col.implicitHeight + Theme.s4 * 2
                radius: Theme.rM
                level: 2
                interactive: true

                Column {
                    id: col
                    anchors { fill: parent; margins: Theme.s4 }
                    spacing: Theme.s1 + 1

                    Row {
                        width: parent.width
                        Text {
                            text: (notifCard.item && notifCard.item.appName) ? notifCard.item.appName : "Notification"
                            color: Theme.accent2
                            font { family: Theme.fontMono; pixelSize: Theme.tCaption; letterSpacing: 1; weight: Font.DemiBold }
                        }
                        Item { width: parent.width - x - closeW.width; height: 1 }
                        Text {
                            id: closeW
                            text: "✕"
                            color: Theme.textFaint
                            font.pixelSize: 10
                            MouseArea {
                                anchors.fill: parent; anchors.margins: -6
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (notifCard.item && notifCard.item.dismiss)
                                        notifCard.item.dismiss();
                                }
                            }
                        }
                    }
                    Text {
                        width: parent.width
                        text: (notifCard.item && notifCard.item.summary) ? notifCard.item.summary : ""
                        color: Theme.text
                        font { family: Theme.fontUi; pixelSize: Theme.tBody; weight: Font.DemiBold }
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: parent.width
                        visible: !!(notifCard.item && notifCard.item.body)
                        text: (notifCard.item && notifCard.item.body) ? notifCard.item.body : ""
                        color: Theme.textDim
                        font { family: Theme.fontUi; pixelSize: Theme.tBody }
                        wrapMode: Text.WordWrap
                        maximumLineCount: 4
                        elide: Text.ElideRight
                    }
                }

                Timer {
                    interval: 5000
                    running: true
                    onTriggered: {
                        if (notifCard.item && notifCard.item.dismiss)
                            notifCard.item.dismiss();
                    }
                }
            }
        }
    }
}
