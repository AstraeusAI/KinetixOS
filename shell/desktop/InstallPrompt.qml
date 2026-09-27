import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "../common"

// Live-ISO-only "Install KinetixOS" card. Shown when /run/archiso exists
// (the archiso live environment) or KINETIX_FORCE_LIVE=1 is set; on an
// installed system it never appears.
PanelWindow {
    id: root
    required property ShellScreen modelData
    screen: modelData

    property bool isLive: Quickshell.env("KINETIX_FORCE_LIVE") === "1"
    property bool dismissed: false
    visible: isLive && !dismissed

    anchors { right: true; bottom: true }
    margins { right: 20; bottom: 56 + 20 }
    implicitWidth: 300
    implicitHeight: 96
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "kinetix:install-prompt"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Process {
        command: ["test", "-d", "/run/archiso"]
        running: true
        onExited: function (code) { if (code === 0) root.isLive = true; }
    }

    Rectangle {
        anchors.fill: parent
        radius: 10
        color: Qt.rgba(0.06, 0.03, 0.045, 0.92)
        border.width: 1
        border.color: Theme.crimson

        Column {
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 16 }
            spacing: 8

            Text {
                text: "You are running KinetixOS live"
                color: Theme.text
                font { family: Theme.fontUi; pixelSize: 13 }
            }
            Rectangle {
                width: parent.width
                height: 34
                radius: 6
                color: installArea.containsMouse ? Theme.crimson : Qt.rgba(0.8, 0.1, 0.2, 0.55)
                Text {
                    anchors.centerIn: parent
                    text: "INSTALL KINETIXOS"
                    color: "white"
                    font { family: Theme.fontMono; pixelSize: 12; letterSpacing: 1.6; weight: Font.DemiBold }
                }
                MouseArea {
                    id: installArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: InstallerState.show()
                }
            }
        }

        Text {
            anchors { top: parent.top; right: parent.right; topMargin: 5; rightMargin: 9 }
            text: "×"
            color: Theme.textFaint
            font.pixelSize: 16
            MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: root.dismissed = true }
        }
    }
}
