import QtQuick
import "../common"
import "../components"

// High-fidelity live resource monitor for the QuickShell bar:
// CPU (load % + temp/freq + smooth gradient sparkline)
// RAM (load % + GB readout + sparkline)
// GPU (load % + temp + sparkline)
// Network (throughput + auto-scaling sparkline)
// Hover opens the deep telemetry popup with per-core visualizer.
BarBox {
    id: root

    implicitWidth: contentRow.implicitWidth + Theme.s3 * 2
    interactive: true
    active: AgentState.sysOpen
    activeColor: Theme.accent2
    hoverBorderColor: Theme.alpha(Theme.accent2, 0.48)
    onClicked: AgentState.toggleSys()

    // The sampler updates once per second. These eased values keep the bar
    // alive between samples instead of making the numbers and rails jump.
    property real cpuVisual: SysInfo.cpu
    property real memVisual: SysInfo.memPct
    readonly property real cpuPercent: Math.max(0, Math.min(100, cpuVisual))
    readonly property real memPercent: Math.max(0, Math.min(100, memVisual))
    readonly property color cpuTone: SysInfo.cpu > 85 ? Theme.danger
                                      : SysInfo.cpu > 55 ? Theme.warn : Theme.accent2
    readonly property color memTone: SysInfo.memPct > 85 ? Theme.danger
                                      : SysInfo.memPct > 65 ? Theme.warn : Theme.accent
    readonly property real cpuPeak: peakOf(SysInfo.cpuHist)
    readonly property real memPeak: peakOf(SysInfo.memHist)
    Behavior on cpuVisual { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
    Behavior on memVisual { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }

    function peakOf(values) {
        var peak = 0;
        for (var i = 0; i < (values || []).length; i++)
            peak = Math.max(peak, Number(values[i]) || 0);
        return Math.max(0, Math.min(100, peak));
    }

    Row {
        id: contentRow
        anchors.centerIn: parent
        spacing: Theme.s3

        // ── CPU Metric (Elevated) ─────────────────────────
        Column {
            id: cpuMetric
            width: 82
            spacing: 1
            anchors.verticalCenter: parent.verticalCenter

            Item {
                width: parent.width
                height: 12

                Row {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 3

                    // Live dynamic activity beacon with dual-layer pulse
                    Item {
                        width: 7; height: 7
                        anchors.verticalCenter: parent.verticalCenter

                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width + 4; height: parent.height + 4
                            radius: width / 2
                            color: Theme.alpha(root.cpuTone, 0.28)
                            scale: (root.hovered || root.cpuPercent > 70) ? (0.85 + 0.5 * Theme.heartbeatSin) : 1.0
                            Behavior on scale { NumberAnimation { duration: Theme.durFast } }
                        }

                        Rectangle {
                            anchors.centerIn: parent
                            width: 5; height: 5
                            radius: 2.5
                            color: root.cpuTone
                            Behavior on color { ColorAnimation { duration: Theme.durMed } }
                        }
                    }

                    Text {
                        text: "CPU"
                        color: Theme.textDim
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 0.8; weight: Font.Medium }
                    }
                }

                Row {
                    id: cpuValRow
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Text {
                        text: SysInfo.ready ? Math.round(root.cpuVisual) + "%" : "—"
                        color: root.cpuTone
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.DemiBold }
                        Behavior on color { ColorAnimation { duration: Theme.durMed } }
                    }

                    Text {
                        visible: SysInfo.ready && (SysInfo.cpuTemp > 0 || SysInfo.cpuFreq > 0)
                        text: SysInfo.cpuTemp > 0 ? (Math.round(SysInfo.cpuTemp) + "°") : (SysInfo.cpuFreq.toFixed(1) + "G")
                        color: SysInfo.cpuTemp > 80 ? Theme.danger
                             : SysInfo.cpuTemp > 65 ? Theme.warn : Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: 8 }
                    }
                }
            }

            Sparkline {
                width: parent.width
                height: 12
                values: SysInfo.cpuHist
                lineColor: root.cpuTone
                fillColor: Theme.alpha(root.cpuTone, 0.26)
                ceiling: 100
                showDot: true
                Behavior on lineColor { ColorAnimation { duration: Theme.durMed } }
            }

            // A quiet baseline makes the current level legible even when the
            // history is flat or the sparkline has not filled yet.
            Item {
                width: parent.width
                height: 2
                Rectangle {
                    anchors.fill: parent
                    radius: 1
                    color: Theme.alpha(Theme.text, 0.08)
                }
                Rectangle {
                    width: Math.max(0, parent.width * root.cpuPercent / 100)
                    height: parent.height
                    radius: 1
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Theme.alpha(root.cpuTone, 0.38) }
                        GradientStop { position: 1.0; color: root.cpuTone }
                    }
                    Behavior on width { NumberAnimation { duration: 520; easing.type: Easing.OutCubic } }
                }
                Rectangle {
                    x: parent.width * root.cpuPeak / 100
                    width: 1
                    height: parent.height
                    radius: 1
                    color: Theme.alpha(root.cpuTone, 0.42)
                    visible: SysInfo.ready && root.cpuPeak > root.cpuPercent + 2
                    Behavior on x { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
                }
                Rectangle {
                    width: 4
                    height: 4
                    x: Math.max(0, Math.min(parent.width - width,
                                             parent.width * root.cpuPercent / 100 - width / 2))
                    y: -1
                    radius: 2
                    color: root.cpuTone
                    visible: SysInfo.ready
                    opacity: (root.hovered || root.cpuPercent > 70) ? (0.48 + 0.34 * Theme.heartbeatSin) : 0.82
                    Behavior on x { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
                    Behavior on color { ColorAnimation { duration: Theme.durMed } }
                }
            }
        }

        Rectangle {
            width: 1; height: 16
            anchors.verticalCenter: parent.verticalCenter
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.25; color: Qt.rgba(1, 1, 1, 0.14) }
                GradientStop { position: 0.75; color: Qt.rgba(1, 1, 1, 0.14) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // ── RAM Metric ───────────────────────────────────
        Column {
            width: 92
            spacing: 1
            anchors.verticalCenter: parent.verticalCenter

            Item {
                width: parent.width
                height: 12

                Row {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 3

                    Item {
                        width: 5; height: 5
                        anchors.verticalCenter: parent.verticalCenter

                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width + 4; height: parent.height + 4
                            radius: width / 2
                            color: Theme.alpha(root.memTone, 0.28)
                            scale: (root.hovered || root.memPercent > 80) ? (0.85 + 0.5 * Theme.heartbeatSin) : 1.0
                            Behavior on scale { NumberAnimation { duration: Theme.durFast } }
                        }

                        Rectangle {
                            anchors.centerIn: parent
                            width: 5; height: 5
                            radius: 2.5
                            color: root.memTone
                            Behavior on color { ColorAnimation { duration: Theme.durMed } }
                        }
                    }

                    Text {
                        text: "RAM"
                        color: Theme.textDim
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 0.8; weight: Font.Medium }
                    }
                }

                Row {
                    id: ramValRow
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Text {
                        id: ramVal
                        text: SysInfo.ready ? Math.round(root.memVisual) + "%" : "—"
                        color: root.memTone
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.DemiBold }
                        Behavior on color { ColorAnimation { duration: Theme.durMed } }
                    }

                    Text {
                        visible: SysInfo.ready && SysInfo.memUsed > 0
                        text: "·" + SysInfo.fmtGB(SysInfo.memUsed) + "G"
                        color: Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: 8 }
                    }
                }
            }

            Sparkline {
                width: parent.width
                height: 12
                values: SysInfo.memHist
                lineColor: root.memTone
                fillColor: Theme.alpha(root.memTone, 0.22)
                ceiling: 100
                showDot: true
                Behavior on lineColor { ColorAnimation { duration: Theme.durMed } }
            }

            Item {
                width: parent.width
                height: 2
                Rectangle {
                    anchors.fill: parent
                    radius: 1
                    color: Theme.alpha(Theme.text, 0.08)
                }
                Rectangle {
                    width: Math.max(0, parent.width * root.memPercent / 100)
                    height: parent.height
                    radius: 1
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Theme.alpha(root.memTone, 0.38) }
                        GradientStop { position: 1.0; color: root.memTone }
                    }
                    Behavior on width { NumberAnimation { duration: 520; easing.type: Easing.OutCubic } }
                }
                Rectangle {
                    x: parent.width * root.memPeak / 100
                    width: 1
                    height: parent.height
                    radius: 1
                    color: Theme.alpha(root.memTone, 0.42)
                    visible: SysInfo.ready && root.memPeak > root.memPercent + 2
                    Behavior on x { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
                }
                Rectangle {
                    width: 4
                    height: 4
                    x: Math.max(0, Math.min(parent.width - width,
                                             parent.width * root.memPercent / 100 - width / 2))
                    y: -1
                    radius: 2
                    color: root.memTone
                    visible: SysInfo.ready
                    opacity: (root.hovered || root.memPercent > 80) ? (0.48 + 0.34 * Theme.heartbeatSin) : 0.82
                    Behavior on x { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
                    Behavior on color { ColorAnimation { duration: Theme.durMed } }
                }
            }
        }

        Rectangle {
            width: 1; height: 16
            anchors.verticalCenter: parent.verticalCenter
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.25; color: Qt.rgba(1, 1, 1, 0.14) }
                GradientStop { position: 0.75; color: Qt.rgba(1, 1, 1, 0.14) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // ── GPU Metric ───────────────────────────────────
        Column {
            width: 52
            spacing: 1
            anchors.verticalCenter: parent.verticalCenter

            Item {
                width: parent.width
                height: 12

                Text {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: "GPU"
                    color: Theme.textDim
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 0.8; weight: Font.Medium }
                }

                Text {
                    id: gpuVal
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: Math.round(SysInfo.gpu) + "%"
                    color: SysInfo.gpu > 85 ? Theme.danger
                         : SysInfo.gpu > 60 ? Theme.warn : Theme.text
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.DemiBold }
                    Behavior on color { ColorAnimation { duration: Theme.durMed } }
                }
            }

            Sparkline {
                width: parent.width
                height: 12
                values: SysInfo.gpuHist
                lineColor: Theme.accent3
                fillColor: Theme.alpha(Theme.accent3, 0.22)
                ceiling: 100
                showDot: true
            }
        }

        Rectangle {
            width: 1; height: 16
            anchors.verticalCenter: parent.verticalCenter
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.25; color: Qt.rgba(1, 1, 1, 0.14) }
                GradientStop { position: 0.75; color: Qt.rgba(1, 1, 1, 0.14) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // ── Network Metric ───────────────────────────────
        Column {
            width: 58
            spacing: 1
            anchors.verticalCenter: parent.verticalCenter

            Item {
                width: parent.width
                height: 12

                Text {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: "NET"
                    color: Theme.textDim
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 0.8; weight: Font.Medium }
                }

                Row {
                    id: netSpeeds
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Text {
                        text: "↓" + (SysInfo.rx >= 1024 ? (SysInfo.rx / 1024).toFixed(0) + "M" : SysInfo.rx.toFixed(0) + "K")
                        color: SysInfo.rx > 500 ? Theme.accent2 : Theme.textDim
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.DemiBold }
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                    }
                }
            }

            Sparkline {
                width: parent.width
                height: 12
                values: SysInfo.netHist
                lineColor: Theme.warn
                fillColor: Theme.alpha(Theme.warn, 0.22)
                ceiling: 0
                showDot: true
            }
        }

        // Dropdown Chevron Indicator Chip
        Rectangle {
            width: 16; height: 16
            radius: 8
            anchors.verticalCenter: parent.verticalCenter
            color: AgentState.sysOpen ? Theme.alpha(Theme.accent2, 0.18)
                 : (root.hovered ? Theme.alpha(Theme.text, 0.10) : Qt.rgba(1, 1, 1, 0.03))
            border.width: 1
            border.color: AgentState.sysOpen ? Theme.alpha(Theme.accent2, 0.40)
                        : (root.hovered ? Theme.alpha(Theme.text, 0.16) : Qt.rgba(1, 1, 1, 0.07))
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

            Text {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: root.hovered && !AgentState.sysOpen ? 1 : 0
                text: "▾"
                color: AgentState.sysOpen ? Theme.accent2 : (root.hovered ? Theme.text : Theme.textFaint)
                font { family: Theme.fontUi; pixelSize: 10; bold: true }
                rotation: AgentState.sysOpen ? 180 : 0
                Behavior on anchors.verticalCenterOffset { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
                Behavior on rotation { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutQuint } }
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
        }
    }
}
