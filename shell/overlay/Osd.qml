import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"
import "../components"

// Floating OSD — pops below the bar on volume/brightness changes.
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; left: true; right: true }
    implicitHeight: 130
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "argus:osd"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    mask: Region {}   // click-through

    visible: osd.pop > 0.01

    GlassPanel {
        id: osd
        anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 66 }
        width: 300
        height: 56
        radius: Theme.rPill
        level: 3

        property real pop: OsdState.visible ? 1 : 0
        opacity: pop
        scale: 0.92 + 0.08 * pop
        transform: Translate { y: -8 * (1 - osd.pop) }
        Behavior on pop { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

        Row {
            anchors { fill: parent; leftMargin: Theme.s4; rightMargin: Theme.s4 }
            spacing: Theme.s4

            StatusOrb {
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.accent2
                live: OsdState.visible
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: 52
                text: OsdState.label !== "" ? OsdState.label : OsdState.kind.toUpperCase()
                color: Theme.textDim
                font { family: Theme.fontMono; pixelSize: Theme.tCaption; letterSpacing: 1.2; weight: Font.DemiBold }
            }

            // level track
            Item {
                anchors.verticalCenter: parent.verticalCenter
                width: 120
                height: 6

                Rectangle {
                    anchors.fill: parent
                    radius: 3
                    color: Theme.surfaceHigh
                }
                Rectangle {
                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                    width: Math.max(0, parent.width * Math.min(1, OsdState.value))
                    radius: 3
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: Theme.accent }
                        GradientStop { position: 1; color: Theme.accent2 }
                    }
                    Behavior on width { NumberAnimation { duration: Theme.durFast } }
                }
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: 34
                horizontalAlignment: Text.AlignRight
                text: Math.round(OsdState.value * 100)
                color: Theme.text
                font { family: Theme.fontMono; pixelSize: Theme.tBody; weight: Font.Medium }
            }
        }
    }
}
