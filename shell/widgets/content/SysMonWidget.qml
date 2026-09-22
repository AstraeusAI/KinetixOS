import QtQuick
import "../../common"
import "../../components"

// High-fidelity desktop telemetry dashboard: CPU, Memory, GPU, Network, Disk.
Item {
    id: root
    property var widget
    property var cfg: ({})
    clip: true

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: mainCol.implicitHeight + Theme.s4 * 2
        boundsBehavior: Flickable.StopAtBounds
        clip: true

        Column {
            id: mainCol
            anchors {
                left: parent.left
                right: parent.right
                top: parent.top
                margins: Theme.s4
            }
            spacing: Theme.s3

            // ── CPU Card ──────────────────────────────────────────
            Column {
                width: parent.width
                spacing: 4

                Item {
                    width: parent.width
                    height: 20

                    Row {
                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                        spacing: 6

                        Rectangle {
                            width: 6; height: 6; radius: 3
                            color: SysInfo.cpu > 85 ? Theme.danger
                                 : SysInfo.cpu > 55 ? Theme.warn : Theme.accent2
                            anchors.verticalCenter: parent.verticalCenter
                            Behavior on color { ColorAnimation { duration: Theme.durMed } }
                        }

                        Text {
                            text: "CPU"
                            color: Theme.textDim
                            font { family: Theme.fontMono; pixelSize: Theme.tCaption; letterSpacing: 1.2; weight: Font.DemiBold }
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Text {
                            visible: SysInfo.cpuFreq > 0
                            text: SysInfo.fmtFreq(SysInfo.cpuFreq)
                            color: Theme.textFaint
                            font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    Row {
                        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                        spacing: 6

                        Text {
                            visible: SysInfo.cpuTemp > 0
                            text: SysInfo.fmtTemp(SysInfo.cpuTemp)
                            color: SysInfo.cpuTemp > 80 ? Theme.danger
                                 : SysInfo.cpuTemp > 65 ? Theme.warn : Theme.textDim
                            font { family: Theme.fontMono; pixelSize: Theme.tCaption }
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Text {
                            text: Math.round(SysInfo.cpu) + "%"
                            color: SysInfo.cpu > 85 ? Theme.danger
                                 : SysInfo.cpu > 55 ? Theme.warn : Theme.text
                            font { family: Theme.fontMono; pixelSize: Theme.tBody; weight: Font.DemiBold }
                            anchors.verticalCenter: parent.verticalCenter
                            Behavior on color { ColorAnimation { duration: Theme.durMed } }
                        }
                    }
                }

                // Mini per-core activity equalizer
                Item {
                    width: parent.width
                    height: 12
                    visible: SysInfo.coreLoads && SysInfo.coreLoads.length > 0

                    Row {
                        anchors.fill: parent
                        spacing: Math.max(1, Math.floor((parent.width - (SysInfo.coreLoads.length * 5)) / Math.max(1, SysInfo.coreLoads.length - 1)))

                        Repeater {
                            model: SysInfo.coreLoads || []
                            delegate: Rectangle {
                                required property real modelData
                                width: Math.max(2, Math.floor((mainCol.width - (SysInfo.coreLoads.length - 1) * 2) / SysInfo.coreLoads.length))
                                height: parent.height
                                radius: 1
                                color: Theme.surfaceLow

                                Rectangle {
                                    anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
                                    height: Math.max(1, Math.round(parent.height * (Math.min(100, Math.max(0, modelData)) / 100)))
                                    radius: 1
                                    color: modelData > 85 ? Theme.danger
                                         : modelData > 55 ? Theme.warn : Theme.accent2
                                    Behavior on height { NumberAnimation { duration: Theme.durMed } }
                                    Behavior on color { ColorAnimation { duration: Theme.durMed } }
                                }
                            }
                        }
                    }
                }

                Sparkline {
                    width: parent.width
                    height: 24
                    values: SysInfo.cpuHist
                    lineColor: SysInfo.cpu > 85 ? Theme.danger
                             : SysInfo.cpu > 55 ? Theme.warn : Theme.accent2
                    fillColor: Theme.alpha(lineColor, 0.26)
                    ceiling: 100
                    showDot: true
                }
            }

            // ── Memory Card ───────────────────────────────────────
            Column {
                width: parent.width
                spacing: 4

                Item {
                    width: parent.width
                    height: 20

                    Row {
                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                        spacing: 6
                        Text {
                            text: "RAM"
                            color: Theme.textDim
                            font { family: Theme.fontMono; pixelSize: Theme.tCaption; letterSpacing: 1.2; weight: Font.DemiBold }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: SysInfo.fmtGB(SysInfo.memUsed) + " / " + SysInfo.fmtGB(SysInfo.memTotal) + " GB"
                            color: Theme.textFaint
                            font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    Text {
                        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                        text: Math.round(SysInfo.memPct) + "%"
                        color: SysInfo.memPct > 85 ? Theme.danger
                             : SysInfo.memPct > 65 ? Theme.warn : Theme.text
                        font { family: Theme.fontMono; pixelSize: Theme.tBody; weight: Font.DemiBold }
                    }
                }

                // Progress Bar
                Rectangle {
                    width: parent.width
                    height: 4
                    radius: 2
                    color: Theme.surfaceLow

                    Rectangle {
                        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                        width: Math.max(4, Math.round(parent.width * (Math.min(100, Math.max(0, SysInfo.memPct)) / 100)))
                        radius: 2
                        color: Theme.accent
                        Behavior on width { NumberAnimation { duration: Theme.durMed } }
                    }
                }

                Sparkline {
                    width: parent.width
                    height: 22
                    values: SysInfo.memHist
                    lineColor: Theme.accent
                    fillColor: Theme.alpha(Theme.accent, 0.22)
                    ceiling: 100
                    showDot: true
                }
            }

            // ── GPU Card ──────────────────────────────────────────
            Column {
                width: parent.width
                spacing: 4

                Item {
                    width: parent.width
                    height: 20

                    Row {
                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                        spacing: 6
                        Text {
                            text: "GPU"
                            color: Theme.textDim
                            font { family: Theme.fontMono; pixelSize: Theme.tCaption; letterSpacing: 1.2; weight: Font.DemiBold }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            visible: SysInfo.gpuTemp > 0
                            text: Math.round(SysInfo.gpuTemp) + "°C"
                            color: Theme.textFaint
                            font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    Text {
                        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                        text: Math.round(SysInfo.gpu) + "%"
                        color: SysInfo.gpu > 85 ? Theme.danger
                             : SysInfo.gpu > 60 ? Theme.warn : Theme.text
                        font { family: Theme.fontMono; pixelSize: Theme.tBody; weight: Font.DemiBold }
                    }
                }

                Sparkline {
                    width: parent.width
                    height: 22
                    values: SysInfo.gpuHist
                    lineColor: Theme.accent3
                    fillColor: Theme.alpha(Theme.accent3, 0.22)
                    ceiling: 100
                    showDot: true
                }
            }

            // ── Network & Storage Wells ───────────────────────────
            Row {
                width: parent.width
                spacing: Theme.s2

                // Network Pill
                Rectangle {
                    width: Math.floor((parent.width - Theme.s2) / 2)
                    height: 34
                    radius: Theme.rS
                    color: Theme.surfaceLow
                    border.width: 1
                    border.color: Theme.stroke

                    Row {
                        anchors.centerIn: parent
                        spacing: 6
                        Text {
                            text: "↓" + SysInfo.fmtNet(SysInfo.rx)
                            color: Theme.textDim
                            font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                        }
                        Text {
                            text: "↑" + SysInfo.fmtNet(SysInfo.tx)
                            color: Theme.textFaint
                            font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                        }
                    }
                }

                // Disk Pill
                Rectangle {
                    width: Math.floor((parent.width - Theme.s2) / 2)
                    height: 34
                    radius: Theme.rS
                    color: Theme.surfaceLow
                    border.width: 1
                    border.color: Theme.stroke

                    Row {
                        anchors.centerIn: parent
                        spacing: 6
                        Text {
                            text: "DISK"
                            color: Theme.textFaint
                            font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 0.8 }
                        }
                        Text {
                            text: Math.round(SysInfo.disk) + "%"
                            color: SysInfo.disk > 90 ? Theme.danger : Theme.textDim
                            font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.Medium }
                        }
                    }
                }
            }
        }
    }
}
