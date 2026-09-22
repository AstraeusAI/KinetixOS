import QtQuick
import Quickshell
import Quickshell.Services.SystemTray
import "../common"

Row {
    id: root
    spacing: Theme.s1
    property var window          // bar window, for menu anchoring
    property Item menuItem: null
    readonly property int count: trayRep.count

    Repeater {
        id: trayRep
        model: SystemTray.items
        delegate: Item {
            id: trayDelegate
            required property var modelData
            width: 24
            height: 24

            Rectangle {
                anchors.fill: parent
                radius: Theme.rS
                color: ma.containsMouse ? Theme.surfaceHigh : "transparent"
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
            Image {
                anchors.centerIn: parent
                width: 15
                height: 15
                source: trayDelegate.modelData.icon
                sourceSize.width: 15
                sourceSize.height: 15
            }
            MouseArea {
                id: ma
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: function(mouse) {
                    if (mouse.button === Qt.LeftButton)
                        trayDelegate.modelData.activate();
                    else if (trayDelegate.modelData.hasMenu) {
                        root.menuItem = trayDelegate;
                        menu.menu = trayDelegate.modelData.menu;
                        menu.open();
                    }
                }
            }
        }
    }

    QsMenuAnchor {
        id: menu
        anchor.window: root.window
        anchor.item: root.menuItem
        anchor.edges: Edges.Bottom
        anchor.gravity: Edges.Bottom
    }
}
