import QtQuick
import "../common"

// Compact icon button used across the bar and panels.
Rectangle {
    id: root
    property string glyph: ""
    property string tip: ""
    property bool active: false
    property color tint: Theme.accent
    signal clicked()

    implicitWidth: 28
    implicitHeight: 26
    radius: Theme.rS
    clip: true
    color: active ? Theme.alpha(tint, 0.18)
         : ma.containsMouse ? Theme.surfaceHigh : "transparent"
    border.width: 1
    border.color: active ? Theme.alpha(tint, 0.40)
                 : ma.containsMouse ? Theme.alpha(tint, 0.25) : "transparent"
    // Google-style spring: hover lifts, press squashes with overshoot
    scale: ma.pressed ? 0.90 : (ma.containsMouse ? 1.08 : 1)

    Behavior on color { ColorAnimation { duration: Theme.durFast } }
    Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }

    // ── material ripple on press ──
    Rectangle {
        id: ripple
        anchors.centerIn: parent
        width: 6; height: 6; radius: 3
        color: Theme.alpha(root.tint, 0.40)
        opacity: 0
        scale: 1
    }
    SequentialAnimation {
        id: rippleAnim
        NumberAnimation { target: ripple; property: "opacity"; to: 1; duration: 60 }
        ParallelAnimation {
            NumberAnimation { target: ripple; property: "scale"; to: 5.2; duration: 320; easing.type: Easing.OutQuint }
            NumberAnimation { target: ripple; property: "opacity"; to: 0; duration: 320; easing.type: Easing.OutQuint }
        }
    }

    Text {
        anchors.centerIn: parent
        text: root.glyph
        color: root.active ? root.tint
             : ma.containsMouse ? Theme.text : Theme.textDim
        font.pixelSize: 13
        scale: ma.pressed ? 0.92 : 1
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
        Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutBack } }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: { ripple.opacity = 1; ripple.scale = 1; rippleAnim.restart(); root.clicked(); }
    }
}
