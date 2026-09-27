import QtQuick
import QtQuick.Controls
import "../common"
import "../components"

// Narrow-bar summary; the existing click still opens the full telemetry popup.
BarBox {
    id: root

    readonly property color cpuTone: SysInfo.cpu > 85 ? Theme.alarm
                                      : SysInfo.cpu > 55 ? Theme.gilded : Theme.ember
    readonly property color memTone: SysInfo.memPct > 85 ? Theme.alarm
                                      : SysInfo.memPct > 65 ? Theme.gilded : Theme.crimsonText
    readonly property real cpuPct: Math.max(0, Math.min(100, SysInfo.cpu))
    readonly property real memPct: Math.max(0, Math.min(100, SysInfo.memPct))

    implicitWidth: summaryRow.implicitWidth + Theme.s3 * 2
    interactive: true
    active: AgentState.sysOpen
    onClicked: AgentState.toggleSys()
    HoverTip { target: root; hovered: root.hovered; text: "System telemetry details" }

    Row {
        id: summaryRow
        anchors.centerIn: parent
        spacing: 7

        Item {
            width: 48
            height: 22

            Text {
                anchors { left: parent.left; verticalCenter: value.verticalCenter }
                text: "CPU"
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 0.7; weight: Font.Medium }
            }
            Text {
                id: value
                anchors { right: parent.right; top: parent.top }
                text: SysInfo.ready ? Math.round(SysInfo.cpu) + "%" : "—"
                color: root.cpuTone
                font { family: Theme.fontMono; pixelSize: 10; weight: Font.DemiBold }
            }
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 2
                radius: 1
                color: Theme.alpha(Theme.text, 0.10)
                Rectangle {
                    width: parent.width * root.cpuPct / 100
                    height: parent.height
                    radius: 1
                    color: root.cpuTone
                    Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
                    Behavior on color { ColorAnimation { duration: Theme.durMed } }
                }
            }
        }

        Rectangle {
            width: 1
            height: 14
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.alpha(Theme.text, 0.12)
        }

        Item {
            width: 48
            height: 22

            Text {
                anchors { left: parent.left; verticalCenter: valueMem.verticalCenter }
                text: "RAM"
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 0.7; weight: Font.Medium }
            }
            Text {
                id: valueMem
                anchors { right: parent.right; top: parent.top }
                text: SysInfo.ready ? Math.round(SysInfo.memPct) + "%" : "—"
                color: root.memTone
                font { family: Theme.fontMono; pixelSize: 10; weight: Font.DemiBold }
            }
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 2
                radius: 1
                color: Theme.alpha(Theme.text, 0.10)
                Rectangle {
                    width: parent.width * root.memPct / 100
                    height: parent.height
                    radius: 1
                    color: root.memTone
                    Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
                    Behavior on color { ColorAnimation { duration: Theme.durMed } }
                }
            }
        }
    }
}
