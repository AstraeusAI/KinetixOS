import QtQuick
import "../common"

Item {
    id: root
    property color color: Theme.accent2
    property bool live: true   // ring pulses while a state is live

    implicitWidth: 12
    implicitHeight: 12

    Rectangle {
        id: ring
        anchors.centerIn: parent
        width: 6
        height: 6
        radius: 3
        color: "transparent"
        border.width: 1
        border.color: root.color
        opacity: 0

        SequentialAnimation {
            running: root.live
            loops: Animation.Infinite
            ParallelAnimation {
                NumberAnimation { target: ring; property: "scale"; from: 1; to: 2.6; duration: 1500; easing.type: Easing.OutCubic }
                NumberAnimation { target: ring; property: "opacity"; from: 0.7; to: 0; duration: 1500; easing.type: Easing.OutCubic }
            }
            PauseAnimation { duration: 350 }
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: 6
        height: 6
        radius: 3
        color: root.color
        Behavior on color { ColorAnimation { duration: Theme.durMed } }
    }
}
