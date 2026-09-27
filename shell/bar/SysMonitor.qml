import QtQuick
import QtQuick.Controls
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
    onClicked: AgentState.toggleSys()
    HoverTip {
        target: root
        hovered: root.hovered && !AgentState.sysOpen
        text: "CPU: " + Math.round(SysInfo.cpu) + "%" + (SysInfo.cpuTemp > 0 ? " (" + Math.round(SysInfo.cpuTemp) + "°C, " : " (") + SysInfo.cpuFreq.toFixed(1) + " GHz)\n" +
              "RAM: " + Math.round(SysInfo.memPct) + "% (" + SysInfo.fmtGB(SysInfo.memUsed) + " / " + SysInfo.fmtGB(SysInfo.memTotal) + " GB)\n" +
              (root.gpuAvailable ? ("GPU: " + Math.round(SysInfo.gpu) + "%" + (SysInfo.gpuTemp > 0 ? " (" + Math.round(SysInfo.gpuTemp) + "°C)" : "") + "\n") : "") +
              "NET: ↓" + root.fmtRate(SysInfo.rx) + " ↑" + root.fmtRate(SysInfo.tx) + "\n" +
              "Click for hardware details"
    }
    // Full-detail telemetry stays in this popup surface; narrow bars use the
    // separate CompactTelemetry summary and preserve this click target.

    // The sampler updates once per second. These eased values keep the bar
    // alive between samples instead of making the numbers and rails jump.
    property real cpuVisual: SysInfo.cpu
    property real memVisual: SysInfo.memPct
    readonly property real cpuPercent: Math.max(0, Math.min(100, cpuVisual))
    readonly property real memPercent: Math.max(0, Math.min(100, memVisual))
    // Same three-tier crimson-family escalation as the popup (ember=calm,
    // gilded=elevated, alarm=critical) — CPU and memory keep distinct calm
    // hues (ember vs crimsonText) so the two adjacent readouts stay
    // tellable apart at a glance, matching the popup's Overview tab.
    readonly property color cpuTone: SysInfo.cpu > 85 ? Theme.alarm
                                      : SysInfo.cpu > 55 ? Theme.gilded : Theme.ember
    readonly property color memTone: SysInfo.memPct > 85 ? Theme.alarm
                                      : SysInfo.memPct > 65 ? Theme.gilded : Theme.crimsonText
    readonly property color gpuTone: SysInfo.gpu > 85 ? Theme.alarm
                                      : SysInfo.gpu > 60 ? Theme.gilded : Theme.text
    readonly property bool gpuAvailable: SysInfo.gpus && SysInfo.gpus.length > 0
    readonly property real cpuPeak: peakOf(SysInfo.cpuHist)
    readonly property real memPeak: peakOf(SysInfo.memHist)
    Behavior on cpuVisual { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
    Behavior on memVisual { NumberAnimation { duration: 650; easing.type: Easing.OutCubic } }
    // Rails/dots bound to cpuPercent/memPercent ride this ease directly. They
    // must not carry their own Behavior: a second animation chasing an
    // already-animating value restarts every frame and (650 + 520ms > the 1s
    // sample period) never settles, which kept the bar redrawing forever.

    function peakOf(values) {
        var peak = 0;
        for (var i = 0; i < (values || []).length; i++)
            peak = Math.max(peak, Number(values[i]) || 0);
        return Math.max(0, Math.min(100, peak));
    }

    function fmtRate(kbps) {
        if (!SysInfo.ready) return "—";
        if (kbps >= 1048576) return (kbps / 1048576).toFixed(1) + "G";
        if (kbps >= 1024) return (kbps / 1024).toFixed(1) + "M";
        if (kbps >= 10) return Math.round(kbps) + "K";
        if (kbps > 0) return (Math.round(kbps * 10) / 10).toFixed(1) + "K";
        return "0K";
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

                            Rectangle {
                                anchors.centerIn: parent
                                width: 1.4; height: 1.4
                                radius: 0.7
                                color: Qt.rgba(1, 1, 1, 0.85)
                            }
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
                        text: SysInfo.ready ? Math.round(SysInfo.cpu) + "%" : "—"
                        color: root.cpuTone
                        font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                        Behavior on color { ColorAnimation { duration: Theme.durMed } }
                    }

                    Text {
                        visible: SysInfo.ready && (SysInfo.cpuTemp > 0 || SysInfo.cpuFreq > 0)
                        text: SysInfo.cpuTemp > 0 ? (Math.round(SysInfo.cpuTemp) + "°") : (SysInfo.cpuFreq.toFixed(1) + "G")
                        color: SysInfo.cpuTemp > 80 ? Theme.alarm
                             : SysInfo.cpuTemp > 65 ? Theme.gilded : Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: 8 }
                    }
                }
            }

            Sparkline {
                width: parent.width
                height: 12
                values: SysInfo.cpuHist
                lineColor: root.cpuTone
                fillColor: Theme.alpha(root.cpuTone, 0.16)
                ceiling: 100
                lineWidth: 1.15
                showDot: false
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
                    color: Theme.alpha(Theme.crimson, 0.16)
                    border.width: 0.5
                    border.color: Theme.alpha(Theme.crimson, 0.28)
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
                    Behavior on color { ColorAnimation { duration: Theme.durMed } }
                }
            }
        }

        Rectangle {
            width: 1; height: 16
            anchors.verticalCenter: parent.verticalCenter
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.20; color: Theme.alpha(Theme.crimson, 0.30) }
                GradientStop { position: 0.50; color: Qt.rgba(1, 1, 1, 0.22) }
                GradientStop { position: 0.80; color: Theme.alpha(Theme.crimson, 0.30) }
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

                            Rectangle {
                                anchors.centerIn: parent
                                width: 1.4; height: 1.4
                                radius: 0.7
                                color: Qt.rgba(1, 1, 1, 0.85)
                            }
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
                        text: SysInfo.ready ? Math.round(SysInfo.memPct) + "%" : "—"
                        color: root.memTone
                        font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.DemiBold }
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
                fillColor: Theme.alpha(root.memTone, 0.15)
                ceiling: 100
                lineWidth: 1.15
                showDot: false
                Behavior on lineColor { ColorAnimation { duration: Theme.durMed } }
            }

            Item {
                width: parent.width
                height: 2
                Rectangle {
                    anchors.fill: parent
                    radius: 1
                    color: Theme.alpha(Theme.crimson, 0.16)
                    border.width: 0.5
                    border.color: Theme.alpha(Theme.crimson, 0.28)
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
                    Behavior on color { ColorAnimation { duration: Theme.durMed } }
                }
            }
        }

        Rectangle {
            width: 1; height: 16
            anchors.verticalCenter: parent.verticalCenter
            visible: root.gpuAvailable
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.20; color: Theme.alpha(Theme.crimson, 0.30) }
                GradientStop { position: 0.50; color: Qt.rgba(1, 1, 1, 0.22) }
                GradientStop { position: 0.80; color: Theme.alpha(Theme.crimson, 0.30) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // ── GPU Metric ───────────────────────────────────
        Column {
            width: 70
            spacing: 1
            anchors.verticalCenter: parent.verticalCenter
            visible: root.gpuAvailable

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
                            width: parent.width + 3; height: parent.height + 3
                            radius: width / 2
                            color: Theme.alpha(root.gpuTone, 0.25)
                            scale: (root.hovered || SysInfo.gpu > 60) ? (0.85 + 0.5 * Theme.heartbeatSin) : 1.0
                            Behavior on scale { NumberAnimation { duration: Theme.durFast } }
                        }

                        Rectangle {
                            anchors.centerIn: parent
                            width: 5; height: 5
                            radius: 2.5
                            color: root.gpuTone
                            Behavior on color { ColorAnimation { duration: Theme.durMed } }

                            Rectangle {
                                anchors.centerIn: parent
                                width: 1.4; height: 1.4
                                radius: 0.7
                                color: Qt.rgba(1, 1, 1, 0.85)
                            }
                        }
                    }

                    Text {
                        text: "GPU"
                        color: Theme.textDim
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 0.8; weight: Font.Medium }
                    }
                }

                Row {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Text {
                        id: gpuVal
                        text: SysInfo.ready ? Math.round(SysInfo.gpu) + "%" : "—"
                        color: root.gpuTone
                        font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                        Behavior on color { ColorAnimation { duration: Theme.durMed } }
                    }

                    Text {
                        visible: SysInfo.ready && SysInfo.gpuTemp > 0
                        text: Math.round(SysInfo.gpuTemp) + "°"
                        color: SysInfo.gpuTemp > 80 ? Theme.alarm
                             : SysInfo.gpuTemp > 65 ? Theme.gilded : Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: 8 }
                    }
                }
            }

            Sparkline {
                width: parent.width
                height: 12
                values: SysInfo.gpuHist
                lineColor: root.gpuTone
                fillColor: Theme.alpha(root.gpuTone, 0.15)
                ceiling: 100
                lineWidth: 1.15
                showDot: false
                Behavior on lineColor { ColorAnimation { duration: Theme.durMed } }
            }

            Item {
                width: parent.width
                height: 2
                Rectangle {
                    anchors.fill: parent
                    radius: 1
                    color: Theme.alpha(Theme.crimson, 0.16)
                    border.width: 0.5
                    border.color: Theme.alpha(Theme.crimson, 0.28)
                }
                Rectangle {
                    width: Math.max(0, parent.width * Math.min(100, Math.max(0, SysInfo.gpu)) / 100)
                    height: parent.height
                    radius: 1
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Theme.alpha(root.gpuTone, 0.38) }
                        GradientStop { position: 1.0; color: root.gpuTone }
                    }
                    Behavior on width { NumberAnimation { duration: 520; easing.type: Easing.OutCubic } }
                }
            }
        }

        Rectangle {
            width: 1; height: 16
            anchors.verticalCenter: parent.verticalCenter
            visible: root.gpuAvailable
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.20; color: Theme.alpha(Theme.crimson, 0.30) }
                GradientStop { position: 0.50; color: Qt.rgba(1, 1, 1, 0.22) }
                GradientStop { position: 0.80; color: Theme.alpha(Theme.crimson, 0.30) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // ── Network Metric ───────────────────────────────
        Column {
            width: 82
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
                    spacing: 3

                    Text {
                        text: "↓" + root.fmtRate(SysInfo.rx)
                        color: SysInfo.rx > 500 ? Theme.crimsonText : (SysInfo.rx > 1 ? Theme.text : Theme.textDim)
                        font { family: Theme.fontMono; pixelSize: 8; weight: SysInfo.rx > 50 ? Font.DemiBold : Font.Normal }
                    }

                    Text {
                        text: "↑" + root.fmtRate(SysInfo.tx)
                        color: SysInfo.tx > 500 ? Theme.gilded : (SysInfo.tx > 1 ? Theme.text : Theme.textDim)
                        font { family: Theme.fontMono; pixelSize: 8; weight: SysInfo.tx > 50 ? Font.DemiBold : Font.Normal }
                    }
                }
            }

            Sparkline {
                width: parent.width
                height: 12
                values: SysInfo.netHist
                lineColor: Theme.ember
                fillColor: Theme.alpha(Theme.ember, 0.14)
                ceiling: 0
                lineWidth: 1.15
                showDot: false
            }

            Item {
                width: parent.width
                height: 2
                Rectangle {
                    anchors.fill: parent
                    radius: 1
                    color: Theme.alpha(Theme.crimson, 0.16)
                    border.width: 0.5
                    border.color: Theme.alpha(Theme.crimson, 0.28)
                }
                Rectangle {
                    readonly property real totalRate: SysInfo.rx + SysInfo.tx
                    width: Math.max(0, parent.width * Math.min(100, totalRate > 0 ? Math.min(100, Math.log10(Math.max(1, totalRate)) * 25) : 0) / 100)
                    height: parent.height
                    radius: 1
                    color: Theme.ember
                    Behavior on width { NumberAnimation { duration: 520; easing.type: Easing.OutCubic } }
                }
            }
        }

        // Dropdown Chevron Indicator Chip
        Rectangle {
            width: 16; height: 16
            radius: 8
            anchors.verticalCenter: parent.verticalCenter
            color: AgentState.sysOpen ? Theme.alpha(Theme.crimson, 0.22)
                 : (root.hovered ? Theme.alpha(Theme.crimson, 0.24) : Theme.alpha(Theme.crimson, 0.08))
            border.width: 1
            border.color: AgentState.sysOpen ? Theme.alpha(Theme.crimson, 0.50)
                        : (root.hovered ? Theme.alpha(Theme.crimson, 0.55) : Theme.alpha(Theme.crimson, 0.22))
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

            // Upper micro-sheen
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
                height: 1
                radius: 8
                color: Qt.rgba(1, 1, 1, root.hovered ? 0.25 : 0.12)
            }

            Text {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: root.hovered && !AgentState.sysOpen ? 1 : 0
                text: "▾"
                color: AgentState.sysOpen ? Theme.crimsonText : (root.hovered ? Theme.text : Theme.textFaint)
                font { family: Theme.fontUi; pixelSize: 10; bold: true }
                rotation: AgentState.sysOpen ? 180 : 0
                Behavior on anchors.verticalCenterOffset { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
                Behavior on rotation { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutQuint } }
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
        }
    }
}
