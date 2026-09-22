import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"
import "../components"

// Widget catalog: browse, add, and manage desktop widgets.
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "argus:catalog"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WidgetStore.catalogOpen
                                 ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    visible: WidgetStore.catalogOpen

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, WidgetStore.catalogOpen ? 0.35 : 0)
        Behavior on color { ColorAnimation { duration: Theme.durSlow } }
        MouseArea { anchors.fill: parent; onClicked: WidgetStore.catalogOpen = false }
    }

    GlassPanel {
        id: card
        anchors.centerIn: parent
        width: Math.min(560, parent.width - 80)
        height: Math.min(520, parent.height - 120)
        radius: Theme.rXL
        level: 3
        clipContent: true

        scale: WidgetStore.catalogOpen ? 1 : 0.96
        opacity: WidgetStore.catalogOpen ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
        Behavior on scale { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

        MouseArea { anchors.fill: parent; onClicked: {} }

        Column {
            anchors { fill: parent; margins: Theme.s5 }
            spacing: Theme.s4

            Row {
                width: parent.width
                Column {
                    spacing: 1
                    Text {
                        text: "WIDGETS"
                        color: Theme.text
                        font { family: Theme.fontMono; pixelSize: Theme.tTitle; letterSpacing: 3; weight: Font.DemiBold }
                    }
                    Text {
                        text: WidgetStore.editMode
                              ? "Edit mode — drag headers and resize from the lower-right corner"
                              : "Add widgets here; enable Edit to move or resize them"
                        color: Theme.textFaint
                        font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                    }
                }
                Item { width: Math.max(1, parent.width - x - headControls.width); height: 1 }
                Row {
                    id: headControls
                    spacing: Theme.s2
                    anchors.verticalCenter: parent.verticalCenter

                    PillButton {
                        text: WidgetStore.editMode ? "Done" : "Edit"
                        highlighted: WidgetStore.editMode
                        implicitHeight: 28
                        onClicked: {
                            WidgetStore.editMode = !WidgetStore.editMode;
                            // The catalog is a full-screen input surface;
                            // dismiss it when entering edit mode so widgets
                            // immediately receive the drag/resize pointer.
                            if (WidgetStore.editMode) WidgetStore.catalogOpen = false;
                        }
                    }
                    CloseButton {
                        onClicked: WidgetStore.catalogOpen = false
                    }
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.stroke }

            Text {
                text: "ADD A WIDGET"
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.6 }
            }

            GridView {
                id: grid2
                width: parent.width
                height: parent.height - y - footer.height - Theme.s3
                clip: true
                cellWidth: Math.floor(width / 2)
                cellHeight: 76
                model: WidgetStore.types

                delegate: Item {
                    id: cell
                    required property var modelData
                    width: grid2.cellWidth
                    height: grid2.cellHeight

                    Rectangle {
                        anchors { fill: parent; margins: 4 }
                        radius: Theme.rM
                        color: addMa.containsMouse ? Theme.surfaceHigh : Theme.surfaceLow
                        border.width: 1
                        border.color: addMa.containsMouse ? Theme.alpha(Theme.accent, 0.35) : Theme.stroke
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }

                        Row {
                            anchors { fill: parent; margins: Theme.s3 }
                            spacing: Theme.s3

                            Rectangle {
                                width: 40; height: 40
                                radius: Theme.rS
                                color: Theme.alpha(Theme.accent2, 0.12)
                                anchors.verticalCenter: parent.verticalCenter
                                Text {
                                    anchors.centerIn: parent
                                    text: cell.modelData.glyph
                                    color: Theme.accent2
                                    font.pixelSize: 18
                                }
                            }
                            Column {
                                width: parent.width - 52
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 1
                                Text {
                                    text: cell.modelData.label
                                    color: Theme.text
                                    font { family: Theme.fontUi; pixelSize: Theme.tLabel; weight: Font.DemiBold }
                                }
                                Text {
                                    width: parent.width
                                    text: cell.modelData.desc
                                    color: Theme.textFaint
                                    font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        Text {
                            anchors { right: parent.right; top: parent.top; margins: 6 }
                            text: "+"
                            color: Theme.accent
                            font.pixelSize: 14
                        }
                    }

                    MouseArea {
                        id: addMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: WidgetStore.add(cell.modelData.type)
                    }
                }
            }

            Row {
                id: footer
                width: parent.width
                spacing: Theme.s3

                PillButton {
                    text: "Clear all"
                    tint: Theme.danger
                    implicitHeight: 28
                    onClicked: {
                        for (var i = WidgetStore.widgets.length - 1; i >= 0; i--)
                            WidgetStore.remove(WidgetStore.widgets[i].id);
                    }
                }
                Item { width: Math.max(1, parent.width - x - activeText.width); height: 1 }
                Text {
                    id: activeText
                    anchors.verticalCenter: parent.verticalCenter
                    text: WidgetStore.widgets.length + " ACTIVE"
                    color: Theme.textFaint
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.2 }
                }
            }
        }
    }
}
