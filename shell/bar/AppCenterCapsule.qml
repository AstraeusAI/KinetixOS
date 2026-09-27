import QtQuick
import QtQuick.Controls
import "../common"
import "../components"

// High-fidelity App Center Capsule for the main QuickShell bar.
// Displays the software hub status, live pending update count badge,
// and opens the master App Center dropdown on click.
// Built on the unified BarBox obsidian glass system.
BarBox {
    id: root

    property bool compact: false

    implicitWidth: contentRow.implicitWidth + Theme.s4 * 2
    interactive: true
    active: AgentState.appCenterOpen
    activeColor: Theme.crimson
    onClicked: AgentState.toggleAppCenter()
    HoverTip { target: root; hovered: root.compact && root.hovered; text: "App Center" }

    Row {
        id: contentRow
        anchors.centerIn: parent
        spacing: Theme.s2

        // App Center Icon with dynamic aura glow
        Item {
            width: 18
            height: 18
            anchors.verticalCenter: parent.verticalCenter

            Rectangle {
                anchors.centerIn: parent
                width: parent.width + 2
                height: parent.height + 2
                radius: 5
                color: root.active || root.hovered
                       ? Theme.alpha(Theme.crimson, 0.22)
                       : Theme.alpha(Theme.crimson, 0.08)
                border.width: 1
                border.color: root.active || root.hovered
                       ? Theme.alpha(Theme.crimson, 0.45)
                       : Theme.alpha(Theme.crimson, 0.20)
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                // Upper micro-sheen on icon chip
                Rectangle {
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
                    height: 1
                    radius: 4
                    color: Qt.rgba(1, 1, 1, root.hovered ? 0.28 : 0.12)
                }
            }

            Text {
                anchors.centerIn: parent
                text: "❖"
                color: root.active ? Theme.crimson : (root.hovered ? Theme.text : Theme.textDim)
                font.pixelSize: 13
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
        }

        // Label
        Text {
            visible: !root.compact
            text: "AppCenter"
            color: root.active ? Theme.text : (root.hovered ? Theme.text : Theme.textDim)
            font {
                family: Theme.fontMono
                pixelSize: Theme.tCaption
                letterSpacing: 0.6
                weight: Font.DemiBold
            }
            anchors.verticalCenter: parent.verticalCenter
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }

        // Live Pending Updates Badge / Status Pill
        Rectangle {
            id: badge
            anchors.verticalCenter: parent.verticalCenter
            height: 17
            radius: 8.5
            clip: true

            readonly property bool hasUpdates: AppCenterState.updatesCount > 0

            implicitWidth: hasUpdates ? (badgeText.implicitWidth + 10) : 10
            color: hasUpdates
                   ? Theme.alpha(Theme.warn, 0.18 + 0.08 * Theme.heartbeatSin)
                   : Theme.alpha(Theme.crimsonText, 0.16)
            border.width: 1
            border.color: hasUpdates
                         ? Theme.alpha(Theme.warn, 0.45 + 0.35 * Theme.heartbeatSin)
                         : Theme.alpha(Theme.crimsonText, 0.40)

            Behavior on implicitWidth { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

            // Activity / Status Dot (Jewel Micro-Beacon)
            Item {
                visible: !badge.hasUpdates
                anchors.centerIn: parent
                width: 6; height: 6

                Rectangle {
                    anchors.centerIn: parent
                    width: 5
                    height: 5
                    radius: 2.5
                    color: Theme.crimsonText
                }

                Rectangle {
                    anchors.centerIn: parent
                    width: 1.4
                    height: 1.4
                    radius: 0.7
                    color: Qt.rgba(1, 1, 1, 0.90)
                }
            }

            // Updates Count
            Text {
                id: badgeText
                visible: badge.hasUpdates
                anchors.centerIn: parent
                text: AppCenterState.updatesCount > 99 ? "99+" : AppCenterState.updatesCount.toString()
                color: Theme.warn
                font {
                    family: Theme.fontMono
                    pixelSize: 9
                    weight: Font.Bold
                }
            }
        }

        // Dropdown Chevron Indicator Chip (matching SysMonitor styling)
        Rectangle {
            width: 16; height: 16
            radius: 8
            anchors.verticalCenter: parent.verticalCenter
            color: root.active ? Theme.alpha(Theme.crimson, 0.18)
                 : (root.hovered ? Theme.alpha(Theme.text, 0.10) : Qt.rgba(1, 1, 1, 0.03))
            border.width: 1
            border.color: root.active ? Theme.alpha(Theme.crimson, 0.40)
                        : (root.hovered ? Theme.alpha(Theme.text, 0.16) : Qt.rgba(1, 1, 1, 0.07))
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

            Text {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: root.hovered && !root.active ? 1 : 0
                text: "▾"
                color: root.active ? Theme.crimson : (root.hovered ? Theme.text : Theme.textFaint)
                font { family: Theme.fontUi; pixelSize: 10; bold: true }
                rotation: root.active ? 180 : 0
                Behavior on anchors.verticalCenterOffset { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
                Behavior on rotation { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutQuint } }
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
        }
    }
}
