import QtQuick
import Quickshell.Io
import "../../common"

// High-fidelity terminal output gadget: shell command runner with status beacon,
// live refresh trigger, console well, and formatted monospace output.
Item {
    id: root
    property var widget
    property var cfg: ({})
    property string output: ""
    property bool running: false
    property string lastRunTime: ""

    readonly property string cmd: cfg.cmd || ""
    readonly property int interval: (cfg.interval === undefined || cfg.interval === "") ? 10 : Math.max(0, parseInt(cfg.interval) || 0)

    function run() {
        if (cmd === "") return;
        root.running = true;
        proc.command = ["sh", "-c", cmd];
        proc.running = true;
    }

    Component.onCompleted: run()
    onCmdChanged: run()

    Timer {
        id: refreshTimer
        interval: root.interval * 1000
        running: root.cmd !== "" && root.interval > 0
        repeat: true
        onTriggered: root.run()
    }

    Process {
        id: proc
        stdout: StdioCollector {
            onStreamFinished: {
                root.output = this.text;
                root.running = false;
                root.lastRunTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (this.text.trim() !== "") {
                    root.output = this.text;
                }
            }
        }
    }

    Component.onDestruction: {
        proc.running = false;
        refreshTimer.running = false;
    }

    Column {
        anchors { fill: parent; margins: Theme.s3 }
        spacing: Theme.s2

        // Terminal Top Bar
        Item {
            width: parent.width
            height: 20

            Row {
                anchors { left: parent.left; right: rightControls.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                spacing: 5
                clip: true

                Text {
                    text: "❯"
                    color: Theme.accent2
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.Bold }
                    anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                    width: Math.max(0, parent.width - 20)
                    text: root.cmd === "" ? "NO COMMAND CONFIGURED" : root.cmd
                    color: root.cmd === "" ? Theme.textFaint : Theme.textDim
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.Medium }
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            Row {
                id: rightControls
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                spacing: 6

                // Status indicator & interval badge
                Rectangle {
                    height: 18
                    implicitWidth: refreshRow.implicitWidth + 12
                    radius: Theme.rXS
                    color: refMa.containsMouse ? Theme.surfaceHigh : Theme.surfaceLow
                    border.width: 1
                    border.color: Theme.stroke
                    anchors.verticalCenter: parent.verticalCenter
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }

                    Row {
                        id: refreshRow
                        anchors.centerIn: parent
                        spacing: 4

                        Rectangle {
                            width: 5; height: 5; radius: 3
                            color: root.running ? Theme.warn : Theme.accent2
                            anchors.verticalCenter: parent.verticalCenter
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        }

                        Text {
                            text: root.running ? "running…" : (root.interval + "s")
                            color: Theme.textFaint
                            font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    MouseArea {
                        id: refMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.run()
                    }
                }
            }
        }

        // Terminal Console Body
        Rectangle {
            width: parent.width
            height: parent.height - y
            radius: Theme.rS
            color: Theme.surfaceLow
            border.width: 1
            border.color: Theme.stroke

            Flickable {
                id: flick
                anchors { fill: parent; margins: Theme.s3 }
                contentWidth: width
                contentHeight: outText.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                clip: true

                Text {
                    id: outText
                    width: parent.width
                    text: root.cmd === "" ? "Click the ⚙ gear icon in the header to set a shell command (e.g. 'uptime', 'df -h', 'git status')."
                        : root.output.trim() === "" ? (root.running ? "Executing…" : "(Empty output)") : root.output
                    color: root.cmd === "" ? Theme.textFaint : Theme.text
                    font { family: Theme.fontMono; pixelSize: Theme.tCaption }
                    wrapMode: Text.WrapAnywhere
                }
            }
        }
    }
}
