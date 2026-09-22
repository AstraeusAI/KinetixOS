import QtQuick
import "../common"

Rectangle {
    id: root
    property string text: ""
    property string glyph: ""
    property color tint: Theme.accent
    property bool highlighted: false
    signal clicked()

    implicitWidth: row.implicitWidth + Theme.s4 * 2
    implicitHeight: 30
    radius: Theme.rPill
    clip: true
    color: highlighted ? Qt.rgba(tint.r, tint.g, tint.b, 0.18)
         : ma.containsMouse ? Theme.surfaceHigh : Theme.surface
    border.width: 1
    border.color: highlighted ? Qt.rgba(tint.r, tint.g, tint.b, 0.45)
                 : ma.containsMouse ? Theme.alpha(tint, 0.30) : Theme.stroke
    // Google-style spring
    scale: ma.pressed ? 0.94 : (ma.containsMouse ? 1.03 : 1)

    Behavior on color { ColorAnimation { duration: Theme.durFast } }
    Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }

    // ── material ripple on press ──
    Rectangle {
        id: ripple
        anchors.centerIn: parent
        width: 8; height: 8; radius: 4
        color: Theme.alpha(root.tint, 0.35)
        opacity: 0
        scale: 1
    }
    SequentialAnimation {
        id: rippleAnim
        NumberAnimation { target: ripple; property: "opacity"; to: 1; duration: 60 }
        ParallelAnimation {
            NumberAnimation { target: ripple; property: "scale"; to: 7.5; duration: 340; easing.type: Easing.OutQuint }
            NumberAnimation { target: ripple; property: "opacity"; to: 0; duration: 340; easing.type: Easing.OutQuint }
        }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: Theme.s2

        Text {
            visible: root.glyph !== ""
            text: root.glyph
            color: root.highlighted ? root.tint : Theme.textDim
            font.pixelSize: Theme.tLabel
        }
        Text {
            visible: root.text !== ""
            text: root.text
            color: Theme.text
            font.family: Theme.fontUi
            font.pixelSize: Theme.tLabel
            font.weight: Font.DemiBold
        }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: { ripple.opacity = 1; ripple.scale = 1; rippleAnim.restart(); root.clicked(); }
    }
}
