import QtQuick
import "../common"
import "../components"

// Active window capsule with app chip, title truncation, and unified BarBox obsidian glass.
// Sourced from TaskRunner (kinetix-tasks.py), not Quickshell.Wayland.ToplevelManager —
// see shell/common/TaskRunner.qml for why.
BarBox {
    id: root

    property string title: (typeof TaskRunner !== "undefined" && TaskRunner.activeWindow && TaskRunner.activeWindow.title)
                           ? TaskRunner.activeWindow.title
                           : (typeof AgentState !== "undefined" && AgentState ? AgentState.activeWindowTitle : "")
    property string app: (typeof TaskRunner !== "undefined" && TaskRunner.activeWindow && TaskRunner.activeWindow.appId)
                         ? TaskRunner.activeWindow.appId
                         : (typeof AgentState !== "undefined" && AgentState ? AgentState.activeWindowApp : "")

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
            color: Theme.alpha(Theme.crimsonText, 0.12)
            border.width: 1
            border.color: Theme.alpha(Theme.crimsonText, 0.28)
            anchors.verticalCenter: parent.verticalCenter

            // Top micro-sheen on app chip
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
                height: 1
                radius: Theme.rXS
                color: Qt.rgba(1, 1, 1, 0.24)
            }

            Text {
                id: appText
                anchors.centerIn: parent
                text: root.app.toUpperCase()
                color: Theme.crimsonText
                font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.DemiBold; letterSpacing: 0.6 }
            }
        }

        // Window Title
        Item {
            implicitWidth: Math.min(titleText.implicitWidth, 220)
            implicitHeight: titleText.implicitHeight
            anchors.verticalCenter: parent.verticalCenter

            Text {
                text: titleText.text
                color: Qt.rgba(0, 0, 0, 0.65)
                font: titleText.font
                elide: Text.ElideRight
                width: parent.implicitWidth
                anchors.centerIn: parent
                anchors.verticalCenterOffset: 1
            }

            Text {
                id: titleText
                text: root.title
                color: hov.hovered ? Theme.text : Theme.textDim
                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                elide: Text.ElideRight
                width: parent.implicitWidth
                anchors.centerIn: parent
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
        }
    }
}
