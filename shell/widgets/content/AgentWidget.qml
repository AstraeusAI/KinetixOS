import QtQuick
import "../../common"
import "../../components"

// High-fidelity AI desktop companion: interactive prompt bar, glowing status orb,
// frosted message bubble, and provider/model badge.
Item {
    id: root
    property var widget
    property var cfg: ({})

    Column {
        anchors { fill: parent; margins: Theme.s4 }
        spacing: Theme.s3

        // Header: Orb + Status + Model Chip
        Item {
            width: parent.width
            height: 28

            Row {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                spacing: Theme.s2

                StatusOrb {
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.statusColor(AgentState.status)
                    live: AgentState.status !== "idle"
                }

                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 1

                    Text {
                        text: "KINETIX AI"
                        color: Theme.text
                        font { family: Theme.fontMono; pixelSize: Theme.tLabel; letterSpacing: 1.6; weight: Font.DemiBold }
                    }

                    Text {
                        text: AgentState.status.toUpperCase()
                        color: Theme.statusColor(AgentState.status)
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.0; weight: Font.Medium }
                    }
                }
            }

            // Controls & Model Badge
            Row {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                spacing: 6

                // Stop button when running
                Rectangle {
                    visible: AgentState.status === "working"
                    height: 20
                    implicitWidth: stopRow.implicitWidth + 12
                    radius: Theme.rXS
                    color: stopMa.containsMouse ? Theme.danger : Theme.alpha(Theme.danger, 0.20)
                    border.width: 1
                    border.color: Theme.danger
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }

                    Row {
                        id: stopRow
                        anchors.centerIn: parent
                        spacing: 4
                        Text {
                            text: "■"
                            color: Theme.text
                            font.pixelSize: 8
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "STOP"
                            color: Theme.text
                            font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.DemiBold }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    MouseArea {
                        id: stopMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: ArgusBridge.panic()
                    }
                }

                // Model badge pill
                Rectangle {
                    height: 20
                    implicitWidth: modelText.implicitWidth + 14
                    radius: Theme.rXS
                    color: Theme.surfaceLow
                    border.width: 1
                    border.color: Theme.stroke

                    Text {
                        id: modelText
                        anchors.centerIn: parent
                        text: ProviderConfig.provider.toUpperCase() + " · " + ProviderConfig.model
                        color: Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                    }
                }
            }
        }

        // Message Bubble Card — click opens the full Agent Panel
        Rectangle {
            width: parent.width
            height: Math.max(50, parent.height - y - 46)
            radius: Theme.rS
            color: bubbleMa.containsMouse ? Theme.surfaceHigh : Theme.surfaceLow
            border.width: 1
            border.color: bubbleMa.containsMouse ? Theme.alpha(Theme.accent, 0.45) : Theme.stroke
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

            MouseArea {
                id: bubbleMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: AgentState.panelOpen = true
            }

            // Left accent line
            Rectangle {
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                width: 2
                radius: 1
                color: Theme.accent
                opacity: 0.8
            }

            Flickable {
                anchors { fill: parent; leftMargin: Theme.s3; rightMargin: Theme.s3; topMargin: Theme.s2; bottomMargin: Theme.s2 }
                contentWidth: width
                contentHeight: msgText.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                clip: true

                Text {
                    id: msgText
                    width: parent.width
                    property string lastText: AgentState.lastMessageTextCache
                    text: AgentState.turnLive && AgentState.liveToolText !== ""
                          ? ("⚙️ " + AgentState.liveToolText)
                          : (AgentState.status === "blocked"
                             ? "⚠️ Action awaiting approval — click to review"
                             : (lastText === "" ? "Kinetix is on standby and ready for tasks." : lastText))
                    color: (lastText === "" && !AgentState.turnLive && AgentState.status !== "blocked") ? Theme.textFaint : Theme.text
                    font { family: Theme.fontUi; pixelSize: Theme.tBody }
                    wrapMode: Text.WordWrap
                }
            }
        }

        // Prompt Input Pill
        Rectangle {
            width: parent.width
            height: 34
            radius: Theme.rPill
            color: Theme.surfaceLow
            border.width: 1
            border.color: task.activeFocus ? Theme.alpha(Theme.accent, 0.6) : Theme.stroke
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

            Row {
                anchors { fill: parent; leftMargin: Theme.s3; rightMargin: 6 }
                spacing: Theme.s2
                Text {
                    text: "✦"
                    color: task.text ? Theme.accent : Theme.textFaint
                    font.pixelSize: 12
                    anchors.verticalCenter: parent.verticalCenter
                }

                TextInput {
                    id: task
                    width: parent.width - 24 - sendBtn.width - Theme.s2 * 2
                    height: parent.height
                    verticalAlignment: TextInput.AlignVCenter
                    color: Theme.text
                    font { family: Theme.fontUi; pixelSize: Theme.tBody }
                    clip: true
                    Keys.onReturnPressed: submit()
                    Keys.onEnterPressed: submit()

                    Text {
                        anchors.fill: parent
                        visible: !task.text
                        text: "Ask Kinetix…"
                        color: Theme.textFaint
                        font: task.font
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                Rectangle {
                    id: sendBtn
                    width: 24; height: 24; radius: 12
                    color: task.text.trim() ? Theme.accent : Theme.surfaceLow
                    anchors.verticalCenter: parent.verticalCenter
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }

                    Text {
                        anchors.centerIn: parent
                        text: "➤"
                        color: task.text.trim() ? Theme.bg : Theme.textFaint
                        font.pixelSize: 11
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: task.text.trim() ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: submit()
                    }
                }
            }

            function submit() {
                var t = task.text.trim();
                if (t === "" || ArgusBridge.busy) return;
                ArgusBridge.send(t);
                task.text = "";
            }
        }
    }
}
