import QtQuick
import Quickshell
import "../common"

// High-fidelity center clock: horizontal precision layout with accent separator.
Row {
    id: root
    property bool compact: false
    spacing: Theme.s2

    SystemClock { id: clock; precision: SystemClock.Seconds }

    Item {
        implicitWidth: timeText.implicitWidth
        implicitHeight: timeText.implicitHeight
        anchors.verticalCenter: parent.verticalCenter

        Text {
            text: timeText.text
            color: Qt.rgba(0, 0, 0, 0.65)
            font: timeText.font
            anchors.centerIn: parent
            anchors.verticalCenterOffset: 1
        }

        Text {
            id: timeText
            text: Qt.formatDateTime(clock.date, "hh:mm")
            color: Theme.text
            font { family: Theme.fontUi; pixelSize: 14; weight: Font.DemiBold; letterSpacing: -0.2 }
            anchors.centerIn: parent
        }
    }

    // High-definition illuminated ruby beacon
    Item {
        visible: !root.compact
        width: 7
        height: 7
        anchors.verticalCenter: parent.verticalCenter

        Rectangle {
            anchors.centerIn: parent
            width: parent.width
            height: parent.height
            radius: width / 2
            color: Theme.alpha(Theme.crimson, 0.38)
            opacity: 0.50 + 0.50 * Theme.heartbeatSin
            scale: 0.85 + 0.35 * Theme.heartbeatSin
        }

        Rectangle {
            anchors.centerIn: parent
            width: 3.2
            height: 3.2
            radius: 1.6
            color: Theme.crimsonText
        }

        Rectangle {
            anchors.centerIn: parent
            width: 1.2
            height: 1.2
            radius: 0.6
            color: Qt.rgba(1, 1, 1, 0.90)
        }
    }

    Text {
        visible: !root.compact
        text: Qt.formatDateTime(clock.date, "ddd · MMM d").toUpperCase()
        color: Theme.textDim
        font { family: Theme.fontMono; pixelSize: 10; letterSpacing: 1.3; weight: Font.Medium }
        anchors.verticalCenter: parent.verticalCenter
    }
}
