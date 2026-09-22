import QtQuick
import Quickshell.Wayland
import "../common"
import "../components"

// Active window capsule with app chip, title truncation, and unified BarBox obsidian glass.
BarBox {
    id: root

    property string title: ToplevelManager.activeToplevel
                           ? (ToplevelManager.activeToplevel.title || "") : ""
    property string app: ToplevelManager.activeToplevel
                         ? (ToplevelManager.activeToplevel.appId || "") : ""

    visible: title !== ""
    implicitWidth: Math.min(contentRow.implicitWidth + Theme.s3 * 2, 340)
    interactive: false
    Behavior on implicitWidth { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

    HoverHandler { id: hov }

    Row {
        id: contentRow
        anchors.centerIn: parent
        spacing: 6

        // App badge
        Rectangle {
            visible: root.app !== ""
            height: 18
            implicitWidth: appText.implicitWidth + 10
            radius: Theme.rXS
            color: Theme.alpha(Theme.accent2, 0.12)
            border.width: 1
            border.color: Theme.alpha(Theme.accent2, 0.28)
            anchors.verticalCenter: parent.verticalCenter

            Text {
                id: appText
                anchors.centerIn: parent
                text: root.app.toUpperCase()
                color: Theme.accent2
                font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.DemiBold; letterSpacing: 0.6 }
            }
        }

        // Window Title
        Text {
            id: titleText
            text: root.title
            color: hov.hovered ? Theme.text : Theme.textDim
            font { family: Theme.fontUi; pixelSize: Theme.tCaption }
            elide: Text.ElideRight
            width: Math.min(implicitWidth, 220)
            anchors.verticalCenter: parent.verticalCenter
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }
    }
}
