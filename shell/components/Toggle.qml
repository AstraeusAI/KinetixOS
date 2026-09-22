import QtQuick
import "../common"

Item {
    id: root
    property bool checked: false
    property color tint: Theme.accent
    signal toggled(bool checked)

    implicitWidth: 40
    implicitHeight: 22

    Rectangle {
        anchors.fill: parent
        radius: 11
        color: root.checked ? Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0.85)
                            : Theme.surfaceHigh
        border.width: 1
        border.color: root.checked ? "transparent" : Theme.stroke
        Behavior on color { ColorAnimation { duration: Theme.durMed } }
    }

    Rectangle {
        width: 16
        height: 16
        radius: 8
        anchors.verticalCenter: parent.verticalCenter
        x: root.checked ? parent.width - width - 3 : 3
        color: "white"
        Behavior on x { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.checked)
    }
}
