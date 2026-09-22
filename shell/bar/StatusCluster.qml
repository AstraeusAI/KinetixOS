import QtQuick
import Quickshell.Services.Pipewire
import Quickshell.Services.UPower
import "../common"

// Audio level + battery. Drawn, not font-dependent.
Row {
    id: root
    spacing: Theme.s3

    PwObjectTracker { objects: [Pipewire.defaultAudioSink] }

    // ── volume: three bars, filled by level ──
    Item {
        id: volItem
        width: 16
        height: 14
        scale: maVol.pressed ? 0.88 : (maVol.containsMouse ? 1.15 : 1.0)
        Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }

        property var sink: Pipewire.defaultAudioSink
        property real vol: (sink && sink.audio) ? sink.audio.volume : 0
        property bool muted: (sink && sink.audio) ? sink.audio.muted : true

        Row {
            anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
            spacing: 2
            Repeater {
                model: 3
                Rectangle {
                    required property int index
                    width: 3
                    height: 5 + index * 3
                    radius: 1
                    color: parent.parent.muted ? Theme.danger : (maVol.containsMouse ? Theme.accent2 : Theme.text)
                    opacity: parent.parent.muted ? 0.45
                           : (parent.parent.vol * 3 > index ? 0.95 : 0.22)
                    Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                }
            }
        }

        MouseArea {
            id: maVol
            anchors.fill: parent
            anchors.margins: -4
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                var s = parent.sink;
                if (s && s.audio) {
                    s.audio.muted = !s.audio.muted;
                    OsdState.show("volume", s.audio.muted ? 0 : s.audio.volume,
                                  s.audio.muted ? "MUTED" : "");
                }
            }
            onWheel: function(w) {
                var s = parent.sink;
                if (s && s.audio) {
                    s.audio.muted = false;
                    s.audio.volume = Math.max(0, Math.min(1, s.audio.volume + (w.angleDelta.y > 0 ? 0.05 : -0.05)));
                    OsdState.show("volume", s.audio.volume, "");
                }
            }
        }
    }

    // ── battery: drawn cell, laptop-only ──
    Row {
        spacing: Theme.s1 + 2
        visible: dev !== null && dev.ready && dev.isLaptopBattery

        property var dev: UPower.displayDevice
        property real pct: dev ? (dev.percentage > 1 ? dev.percentage / 100 : dev.percentage) : 0
        property bool charging: dev && dev.state === UPowerDeviceState.Charging

        Item {
            width: 20
            height: 12
            anchors.verticalCenter: parent.verticalCenter

            Rectangle {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                width: 16; height: 9; radius: 2
                color: Qt.rgba(1, 1, 1, 0.04)
                border.width: 1
                border.color: parent.parent.charging ? Theme.alpha(Theme.accent2, 0.5) : Theme.strokeStrong
                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
            }
            Rectangle {
                x: 2
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, 12 * parent.parent.pct)
                height: 5
                radius: 1
                color: parent.parent.charging ? Theme.accent2
                     : parent.parent.pct < 0.2 ? Theme.danger : Theme.text
                Behavior on width { NumberAnimation { duration: Theme.durMed } }
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
            Rectangle {
                anchors { left: parent.left; leftMargin: 17; verticalCenter: parent.verticalCenter }
                width: 2; height: 4; radius: 1
                color: Theme.strokeStrong
            }
        }
        Text {
            text: Math.round(parent.pct * 100) + "%"
            color: parent.charging ? Theme.accent2 : (parent.pct < 0.2 ? Theme.danger : Theme.textDim)
            font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.Medium }
            anchors.verticalCenter: parent.verticalCenter
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }
    }
}
