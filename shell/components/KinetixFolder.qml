import QtQuick
import QtQuick.Shapes
import "../common"

// KinetixFolder — the KinetixOS folder icon, drawn in vector (crisp at any
// size). A deep crimson back panel with a tab, a sheet of paper peeking out,
// and a glossy crimson glass front whose top edge carries the system's
// red → green → blue light. Hovered or open, the front flap tips forward to
// reveal the paper. Nothing animates at rest.
Item {
    id: root

    property real size: 52
    property bool hovered: false
    property bool open: false        // e.g. selected

    implicitWidth: size
    implicitHeight: size
    width: size
    height: size

    // 0 → closed, 1 → flap tipped open
    property real flap: open ? 1.0 : (hovered ? 0.7 : 0.0)
    Behavior on flap { NumberAnimation { duration: 280; easing.type: Easing.OutBack; easing.overshoot: 1.4 } }

    Item {
        id: art
        width: 100
        height: 100
        scale: root.size / 100
        transformOrigin: Item.TopLeft

        // soft contact shadow
        Rectangle {
            x: 12; y: 82
            width: 76; height: 10
            radius: 5
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.45) }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: 0.9 - 0.25 * root.flap
        }

        // ── back panel with tab ──
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: Qt.rgba(1, 1, 1, 0.10)
                strokeWidth: 0.8
                fillGradient: LinearGradient {
                    x1: 0; y1: 18; x2: 0; y2: 84
                    GradientStop { position: 0.0; color: "#8E1A2E" }
                    GradientStop { position: 1.0; color: "#3E0A15" }
                }
                startX: 16; startY: 18
                PathLine { x: 38; y: 18 }
                PathQuad { x: 43; y: 21; controlX: 41; controlY: 18 }
                PathLine { x: 47; y: 26 }
                PathLine { x: 84; y: 26 }
                PathQuad { x: 90; y: 32; controlX: 90; controlY: 26 }
                PathLine { x: 90; y: 78 }
                PathQuad { x: 84; y: 84; controlX: 90; controlY: 84 }
                PathLine { x: 16; y: 84 }
                PathQuad { x: 10; y: 78; controlX: 10; controlY: 84 }
                PathLine { x: 10; y: 24 }
                PathQuad { x: 16; y: 18; controlX: 10; controlY: 18 }
            }
        }
        // tab highlight
        Rectangle {
            x: 17; y: 19.2
            width: 21; height: 1.2
            radius: 0.6
            color: Qt.rgba(1, 0.8, 0.84, 0.45)
        }

        // ── paper peeking out (rises a little as the flap opens) ──
        Rectangle {
            x: 17
            y: 31 - 4 * root.flap
            width: 66; height: 40
            radius: 4
            rotation: -2
            antialiasing: true
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#FFF6F7" }
                GradientStop { position: 1.0; color: "#D9CDD0" }
            }
            // ruled lines
            Column {
                x: 9; y: 9
                spacing: 5
                Repeater {
                    model: 3
                    Rectangle {
                        required property int index
                        width: [34, 44, 26][index]; height: 1.6; radius: 0.8
                        color: Qt.rgba(0.55, 0.12, 0.2, 0.28)
                    }
                }
            }
        }

        // ── glossy glass front, tipping forward on hover/open ──
        Item {
            id: front
            anchors.fill: parent
            transform: [
                // foreshortening around the bottom edge reads as the flap
                // opening toward the viewer
                Scale { origin.y: 84; yScale: 1 - 0.16 * root.flap },
                Translate { y: 1.5 * root.flap }
            ]

            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "transparent"
                    fillGradient: LinearGradient {
                        x1: 0; y1: 36; x2: 0; y2: 84
                        GradientStop { position: 0.0; color: "#F2415C" }
                        GradientStop { position: 0.45; color: "#D0203F" }
                        GradientStop { position: 1.0; color: "#8A1026" }
                    }
                    startX: 12; startY: 36
                    PathLine { x: 88; y: 36 }
                    PathQuad { x: 93; y: 41; controlX: 93; controlY: 36 }
                    PathLine { x: 91; y: 78 }
                    PathQuad { x: 85; y: 84; controlX: 91; controlY: 84 }
                    PathLine { x: 15; y: 84 }
                    PathQuad { x: 9; y: 78; controlX: 9; controlY: 84 }
                    PathLine { x: 7; y: 41 }
                    PathQuad { x: 12; y: 36; controlX: 7; controlY: 36 }
                }
            }
            // glass gloss: a soft sheen across the upper half
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "transparent"
                    fillGradient: LinearGradient {
                        x1: 0; y1: 36; x2: 0; y2: 62
                        GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.32) }
                        GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0.0) }
                    }
                    startX: 12; startY: 37
                    PathLine { x: 88; y: 37 }
                    PathQuad { x: 92; y: 41; controlX: 92; controlY: 37 }
                    PathLine { x: 91.3; y: 58 }
                    PathQuad { x: 50; y: 62; controlX: 70; controlY: 54 }
                    PathQuad { x: 8.7; y: 58; controlX: 30; controlY: 66 }
                    PathLine { x: 8; y: 41 }
                    PathQuad { x: 12; y: 37; controlX: 8; controlY: 37 }
                }
            }
            // the system's light along the front's top edge
            Rectangle {
                x: 13; y: 36.2
                width: 74; height: 1.8
                radius: 0.9
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.00; color: Qt.rgba(1, 0.42, 0.36, 0.0) }
                    GradientStop { position: 0.15; color: "#FF6A5C" }
                    GradientStop { position: 0.50; color: "#5BE08A" }
                    GradientStop { position: 0.85; color: "#6FA8FF" }
                    GradientStop { position: 1.00; color: Qt.rgba(0.43, 0.66, 1, 0.0) }
                }
                opacity: 0.85 + 0.15 * root.flap
            }
            // lower lip: gives the glass thickness
            Rectangle {
                x: 16; y: 82.4
                width: 68; height: 1
                color: Qt.rgba(0, 0, 0, 0.35)
            }
        }
    }
}
