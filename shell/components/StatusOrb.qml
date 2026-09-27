import QtQuick
import "../common"

Item {
    id: root
    property color color: Theme.accent2
    property bool live: true   // ring pulses while a state is live

    implicitWidth: 12
    implicitHeight: 12

    // Outer atmospheric aura
    Rectangle {
        anchors.centerIn: parent
        width: 10
        height: 10
        radius: 5
        color: Theme.alpha(root.color, root.live ? 0.32 : 0.12)
        scale: root.live ? (0.86 + 0.28 * Theme.heartbeatSin) : 1.0
        Behavior on color { ColorAnimation { duration: Theme.durMed } }
    }

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
                NumberAnimation { target: ring; property: "scale"; from: 1; to: 2.8; duration: 1500; easing.type: Easing.OutCubic }
                NumberAnimation { target: ring; property: "opacity"; from: 0.75; to: 0; duration: 1500; easing.type: Easing.OutCubic }
            }
            PauseAnimation { duration: 350 }
        }
    }

    // 3D Glass Jewel Orb
    Rectangle {
        id: orbBody
        anchors.centerIn: parent
        width: 6.5
        height: 6.5
        radius: 3.25
        color: root.color
        border.width: 0.5
        border.color: Qt.rgba(0, 0, 0, 0.40)
        Behavior on color { ColorAnimation { duration: Theme.durMed } }

        // Upper-left specular glint: spherical lens reflex
        Rectangle {
            x: 1
            y: 1
            width: 2
            height: 2
            radius: 1
            color: Qt.rgba(1, 1, 1, 0.85)
        }
    }
}
