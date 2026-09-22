import QtQuick
import "../common"

// Shared exit control for every Argus surface: launcher, palette, agent
// panel, widget catalog, widget settings, sys popup, notification toasts.
// Google-style: soft circle, hover lifts + tints danger, press springs in.
Rectangle {
    id: root
    property string glyph: "✕"
    property string tip: "Close"
    property real box: 26
    signal clicked()

    implicitWidth: box
    implicitHeight: box
    radius: box / 2
    color: ma.containsMouse ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.16)
                            : Theme.surfaceLow
    border.width: 1
    border.color: ma.containsMouse ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.45)
                                   : Theme.stroke
    scale: ma.pressed ? 0.88 : (ma.containsMouse ? 1.06 : 1)

    Behavior on color { ColorAnimation { duration: Theme.durFast } }
    Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
    Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutBack } }

    Text {
        anchors.centerIn: parent
        text: root.glyph
        color: ma.containsMouse ? Theme.danger : Theme.textDim
        font.pixelSize: 12
        font.weight: Font.DemiBold
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        anchors.margins: -4
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
