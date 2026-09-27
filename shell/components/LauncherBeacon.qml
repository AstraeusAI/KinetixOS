import QtQuick
import "../common"

// Ultra-premium cybernetic Start Button & Application Launcher for KinetixOS.
// Encased in a sculpted glass capsule with directionally-lit micro-chamfer,
// the iconic Kinetix Start Medallion with faceted chrome bezel,
// radiant crimson laser ring, dynamic caustic sweep, and tactile press dynamics.
Item {
    id: beacon

    property color tint: Theme.crimsonText
    property bool active: AgentState.launcherOpen
    readonly property bool hovered: hit.containsMouse
    readonly property bool pressed: hit.pressed
    signal clicked()

    implicitWidth: 60
    implicitHeight: 70
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: "Open applications"

    scale: pressed ? 0.93 : ((hovered || active) ? 1.04 : 1.0)
    Behavior on scale {
        NumberAnimation { duration: 170; easing.type: Easing.OutBack }
    }

    onHoveredChanged: if (hovered) sweepAnim.restart()
    onActiveChanged: if (active) sweepAnim.restart()

    Keys.onReturnPressed: function(event) {
        clicked();
        event.accepted = true;
    }
    Keys.onSpacePressed: function(event) {
        clicked();
        event.accepted = true;
    }

    // ── Sculpted Optical Glass Capsule Base ──
    Rectangle {
        id: capsule
        anchors.fill: parent
        radius: Theme.rM
        color: beacon.active ? Qt.rgba(0.24, 0.032, 0.060, 0.78)
             : (beacon.hovered ? Qt.rgba(0.18, 0.024, 0.042, 0.62)
             : Qt.rgba(0.08, 0.010, 0.018, 0.38))
        border.width: 1
        border.color: beacon.active ? Theme.alpha(Theme.crimsonText, 0.72)
                    : (beacon.hovered ? Theme.alpha(Theme.crimson, 0.58)
                    : Theme.alpha(Theme.crimson, 0.22))
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
        z: 0

        // Overhead micro-chamfer specular highlight
        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 1 }
            height: 1
            radius: capsule.radius - 1
            color: Qt.rgba(1, 1, 1, beacon.active ? 0.45 : (beacon.hovered ? 0.38 : 0.16))
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }

        // Bottom laser reflex line on active/hover
        Rectangle {
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right; margins: 1 }
            anchors.leftMargin: 4; anchors.rightMargin: 4
            height: 1
            radius: 1
            color: beacon.active ? Theme.alpha(Theme.crimsonText, 0.60)
                 : (beacon.hovered ? Theme.alpha(Theme.crimson, 0.40) : "transparent")
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: 3
        z: 1

        // ── 1. The Circular Medallion Core ──
        Item {
            id: medallionBox
            width: 48
            height: 48
            anchors.horizontalCenter: parent.horizontalCenter

            // Multi-tier state-driven crimson bloom behind the medallion
            Image {
                anchors.centerIn: parent
                width: beacon.active ? 76 : (beacon.hovered ? 72 : 58)
                height: width
                source: Qt.resolvedUrl("../assets/startbutton_glow.png")
                smooth: true
                opacity: beacon.active ? 0.95 : (beacon.hovered ? 0.88 : 0.45)
                scale: beacon.pressed ? 0.90 : 1.0
                Behavior on width { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
                Behavior on scale { NumberAnimation { duration: Theme.durFast } }
                z: 0
            }

            // High-resolution master medallion image
            Image {
                id: medallionImg
                anchors.centerIn: parent
                width: 48
                height: 48
                source: Qt.resolvedUrl("../assets/button_medallion_256.png")
                mipmap: true
                smooth: true
                fillMode: Image.PreserveAspectFit
                scale: beacon.hovered ? 1.04 : 1.0
                Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutBack } }
                z: 2
            }

            // 3D Convex glass lens highlight aligned over inner optical dome
            Rectangle {
                anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 5 }
                width: 32
                height: 16
                radius: 16
                gradient: Gradient {
                    orientation: Gradient.Vertical
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, beacon.hovered ? 0.38 : 0.20) }
                    GradientStop { position: 0.75; color: Qt.rgba(1, 1, 1, 0.04) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
                Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
                z: 3
            }

            // Caustic light sweep across the medallion face
            Item {
                anchors.fill: parent
                clip: true
                z: 4

                Rectangle {
                    id: sheen
                    x: -width - 12
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 14
                    rotation: 20
                    opacity: 0
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.55) }
                        GradientStop { position: 1.0; color: "transparent" }
                    }
                }
            }

            // Tactile press shockwave ring
            Rectangle {
                id: ripple
                anchors.centerIn: parent
                width: 48
                height: 48
                radius: 24
                color: "transparent"
                border.width: 1.5
                border.color: Theme.crimsonText
                opacity: 0
                scale: 1.0
                z: 5
            }
        }

        // ── 2. Laser-Engraved "APPS" Microcopy ──
        Item {
            width: parent.width
            height: 12
            anchors.horizontalCenter: parent.horizontalCenter

            // Engraved drop shadow
            Text {
                text: "APPS"
                color: Qt.rgba(0, 0, 0, 0.80)
                font {
                    family: Theme.fontMono
                    pixelSize: 9
                    weight: Font.DemiBold
                    letterSpacing: 1.6
                }
                anchors.centerIn: parent
                anchors.verticalCenterOffset: 1
            }

            // Radiant foreground text
            Text {
                text: "APPS"
                color: beacon.active ? Theme.crimsonText
                      : beacon.hovered ? Theme.text : Theme.textDim
                font {
                    family: Theme.fontMono
                    pixelSize: 9
                    weight: Font.DemiBold
                    letterSpacing: 1.6
                }
                anchors.centerIn: parent
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
        }
    }

    // Keyboard focus ring
    Rectangle {
        anchors.fill: parent
        radius: capsule.radius
        color: "transparent"
        border.width: 1
        border.color: Theme.crimsonText
        opacity: beacon.activeFocus ? 0.95 : 0.0
        Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
        z: 8
    }

    // Light pass sweep animation
    SequentialAnimation {
        id: sweepAnim
        running: false
        ParallelAnimation {
            NumberAnimation {
                target: sheen
                property: "x"
                from: -medallionBox.width
                to: medallionBox.width + 12
                duration: 440
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                target: sheen
                property: "opacity"
                from: 0.0
                to: 0.65
                duration: 120
            }
        }
        NumberAnimation { target: sheen; property: "opacity"; to: 0.0; duration: 130 }
        PropertyAction { target: sheen; property: "x"; value: -medallionBox.width - 12 }
    }

    // Tactile shockwave animation on press
    SequentialAnimation {
        id: pressRipple
        running: false
        ParallelAnimation {
            NumberAnimation { target: ripple; property: "scale"; from: 0.9; to: 1.8; duration: 280; easing.type: Easing.OutCubic }
            NumberAnimation { target: ripple; property: "opacity"; from: 0.75; to: 0.0; duration: 280; easing.type: Easing.OutCubic }
        }
        PropertyAction { target: ripple; property: "scale"; value: 1.0 }
    }

    MouseArea {
        id: hit
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        cursorShape: Qt.PointingHandCursor
        onPressed: {
            beacon.forceActiveFocus();
            pressRipple.restart();
        }
        onClicked: beacon.clicked()
        z: 10
    }
}