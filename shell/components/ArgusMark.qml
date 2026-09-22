import QtQuick
import "../common"

// Kinetix mark: a kinetic core with orbiting signal nodes.
Item {
    id: root
    property color color: Theme.accent
    property bool live: true
    property real orbitSpin: 0

    implicitWidth: 18
    implicitHeight: 18

    Rectangle {
        anchors.centerIn: parent
        width: 17
        height: 17
        radius: width / 2
        color: Theme.alpha(root.color, root.live ? 0.07 : 0.035)
        border.width: 1
        border.color: Theme.alpha(root.color, root.live ? 0.68 : 0.48)
        Behavior on color { ColorAnimation { duration: Theme.durMed } }
        Behavior on border.color { ColorAnimation { duration: Theme.durMed } }
    }

    Item {
        id: orbitLayer
        anchors.fill: parent
        rotation: root.live ? root.orbitSpin : 0

        Canvas {
            id: arcs
            anchors.fill: parent
            antialiasing: true

            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                var cx = width / 2;
                var cy = height / 2;
                var radius = 7.2;

                ctx.lineCap = "round";
                ctx.lineWidth = 1.15;
                ctx.strokeStyle = Theme.alpha(root.live ? Theme.accent2 : root.color,
                                               root.live ? 0.78 : 0.46);
                ctx.beginPath();
                ctx.arc(cx, cy, radius, -Math.PI * 0.88, -Math.PI * 0.12);
                ctx.stroke();

                ctx.lineWidth = 0.8;
                ctx.strokeStyle = Theme.alpha(root.color, root.live ? 0.55 : 0.30);
                ctx.beginPath();
                ctx.arc(cx, cy, radius, Math.PI * 0.16, Math.PI * 0.68);
                ctx.stroke();
            }

            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onVisibleChanged: requestPaint()
        }

        Rectangle {
            width: 2.5
            height: 2.5
            radius: 1.25
            x: 7.75
            y: 0.4
            color: Theme.accent2
            opacity: root.live ? 0.95 : 0.42
            Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
        }

        Rectangle {
            width: 2
            height: 2
            radius: 1
            x: 13.9
            y: 12.4
            color: root.color
            opacity: root.live ? 0.78 : 0.32
            Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
        }
    }

    // The angled core gives the mark a directional, mechanical silhouette.
    Rectangle {
        id: core
        anchors.centerIn: parent
        width: 6.5
        height: 6.5
        radius: 1.8
        rotation: 45
        color: root.live ? Theme.accent2 : root.color
        opacity: root.live ? 1.0 : 0.86
        Behavior on color { ColorAnimation { duration: Theme.durMed } }
        Behavior on opacity { NumberAnimation { duration: Theme.durMed } }

        scale: root.live ? (1.0 + 0.18 * Theme.heartbeatSin) : 1.0
    }

    Rectangle {
        anchors.centerIn: core
        width: 2.2
        height: 2.2
        radius: 0.8
        rotation: 45
        color: Theme.alpha(Theme.text, root.live ? 0.82 : 0.58)
        scale: core.scale
        Behavior on color { ColorAnimation { duration: Theme.durMed } }
    }

    NumberAnimation on orbitSpin {
        from: 0
        to: 360
        duration: 4200
        loops: Animation.Infinite
        running: root.live
        easing.type: Easing.Linear
    }
}
