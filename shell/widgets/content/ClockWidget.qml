import QtQuick
import Quickshell
import "../../common"

// High-fidelity desktop timepiece: hero digital typography, animated seconds bar,
// aerospace dial background accents, and formatted calendar chip.
Item {
    id: root
    property var widget
    property var cfg: ({})

    SystemClock { id: clock; precision: SystemClock.Seconds }

    readonly property int currentSec: clock.date.getSeconds()
    readonly property real secFraction: currentSec / 60.0

    // Ambient aerospace dial markings in the background
    Canvas {
        id: dialCanvas
        anchors.fill: parent
        opacity: 0.28

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var cx = width / 2;
            var cy = height / 2;
            var r = Math.min(width, height) * 0.44;
            if (r < 20) return;

            // Faint outer ring
            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, 2 * Math.PI);
            ctx.strokeStyle = Theme.stroke;
            ctx.lineWidth = 1;
            ctx.stroke();

            // Inner dotted ring
            ctx.beginPath();
            ctx.arc(cx, cy, r * 0.82, 0, 2 * Math.PI);
            ctx.strokeStyle = Theme.alpha(Theme.stroke, 0.4);
            ctx.lineWidth = 1;
            ctx.setLineDash([2, 6]);
            ctx.stroke();
            ctx.setLineDash([]);
        }

        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Column {
        anchors.centerIn: parent
        spacing: Theme.s2
        width: Math.min(parent.width - 24, 260)

        // Day of week chip
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            height: 20
            implicitWidth: dayText.implicitWidth + 16
            radius: Theme.rXS
            color: Theme.surfaceLow
            border.width: 1
            border.color: Theme.stroke

            Text {
                id: dayText
                anchors.centerIn: parent
                text: Qt.formatDateTime(clock.date, "dddd").toUpperCase()
                color: Theme.accent2
                font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 2.0; weight: Font.DemiBold }
            }
        }

        // Hero time readout: hh:mm
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 2

            Text {
                text: Qt.formatDateTime(clock.date, "hh")
                color: Theme.text
                font { family: Theme.fontUi; pixelSize: 46; weight: Font.ExtraLight; letterSpacing: -1.5 }
            }

            Text {
                text: ":"
                color: Theme.accent2
                font { family: Theme.fontUi; pixelSize: 42; weight: Font.Light }
                opacity: 0.4 + 0.6 * (root.currentSec % 2 === 0 ? 1.0 : 0.4)
                Behavior on opacity { NumberAnimation { duration: 180 } }
            }

            Text {
                text: Qt.formatDateTime(clock.date, "mm")
                color: Theme.text
                font { family: Theme.fontUi; pixelSize: 46; weight: Font.ExtraLight; letterSpacing: -1.5 }
            }

            // Seconds badge
            Column {
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 8
                spacing: 1

                Text {
                    text: Qt.formatDateTime(clock.date, "ss")
                    color: Theme.textDim
                    font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.Medium }
                }
            }
        }

        // Smooth seconds progress bar
        Rectangle {
            width: parent.width
            height: 3
            radius: 1.5
            color: Theme.surfaceLow

            Rectangle {
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                width: Math.max(2, Math.round(parent.width * root.secFraction))
                radius: 1.5
                color: Theme.accent2
                Behavior on width { NumberAnimation { duration: Theme.durMed } }
            }
        }

        // Full Date
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatDateTime(clock.date, "d MMMM yyyy")
            color: Theme.textFaint
            font { family: Theme.fontUi; pixelSize: Theme.tCaption; letterSpacing: 0.5 }
        }
    }
}
