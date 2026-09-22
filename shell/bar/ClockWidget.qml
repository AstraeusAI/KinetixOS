import QtQuick
import Quickshell
import "../common"

// High-fidelity center clock: horizontal precision layout with accent separator.
Row {
    id: root
    spacing: Theme.s2

    SystemClock { id: clock; precision: SystemClock.Seconds }

    Text {
        text: Qt.formatDateTime(clock.date, "hh:mm")
        color: Theme.text
        font { family: Theme.fontUi; pixelSize: 14; weight: Font.DemiBold; letterSpacing: -0.2 }
        anchors.verticalCenter: parent.verticalCenter
    }

    Rectangle {
        width: 3; height: 3; radius: 1.5
        color: Theme.accent2
        opacity: 0.55 + 0.45 * Theme.heartbeatSin
        scale: 0.88 + 0.24 * Theme.heartbeatSin
        anchors.verticalCenter: parent.verticalCenter
    }

    Text {
        text: Qt.formatDateTime(clock.date, "ddd · MMM d").toUpperCase()
        color: Theme.textDim
        font { family: Theme.fontMono; pixelSize: 10; letterSpacing: 1.2; weight: Font.Medium }
        anchors.verticalCenter: parent.verticalCenter
    }
}
