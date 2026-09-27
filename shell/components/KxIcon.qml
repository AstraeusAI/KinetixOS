import QtQuick
import QtQuick.Shapes

// KxIcon — the Kinetix vector icon set for the bar. One 18×18 design grid,
// one stroke weight, round caps and joins, so every glyph in the bar reads as
// the same family (it replaces Unicode glyphs like ⌘ ❖ ▾ ⏮ ⏭ ♫ ↑ ↓, whose
// look depended on whichever fallback font had them, and two hand-painted
// Canvas icons).
//
//   KxIcon { name: "bell"; color: Theme.text; size: 16 }
//
// Names: command, apps, chevron-down, prev, next, play, pause, music,
// arrow-down, arrow-up, bell, bell-off, download.
Item {
    id: root

    property string name: ""
    property color color: "white"
    property real size: 16
    property real stroke: 1.6
    property color accent: "#FFB454"   // the do-not-disturb slash

    implicitWidth: size
    implicitHeight: size
    width: size
    height: size

    component Glyph: Shape {
        property string glyph
        anchors.fill: parent
        visible: root.name === glyph
        preferredRendererType: Shape.CurveRenderer
        transform: Scale { xScale: root.size / 18; yScale: root.size / 18 }
    }
    component Line: ShapePath {
        strokeColor: root.color
        strokeWidth: root.stroke
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        joinStyle: ShapePath.RoundJoin
    }
    component Solid: ShapePath {
        strokeColor: root.color
        strokeWidth: root.stroke * 0.6
        fillColor: root.color
        joinStyle: ShapePath.RoundJoin
    }

    // ⌘ — the command palette
    Glyph {
        glyph: "command"
        Line {
            startX: 6.6; startY: 6.6
            PathLine { x: 11.4; y: 6.6 }
            PathLine { x: 11.4; y: 11.4 }
            PathLine { x: 6.6; y: 11.4 }
            PathLine { x: 6.6; y: 6.6 }
        }
        Line { PathAngleArc { centerX: 4.6; centerY: 4.6; radiusX: 2.1; radiusY: 2.1; startAngle: 0; sweepAngle: 270 } }
        Line { PathAngleArc { centerX: 13.4; centerY: 4.6; radiusX: 2.1; radiusY: 2.1; startAngle: 90; sweepAngle: 270 } }
        Line { PathAngleArc { centerX: 13.4; centerY: 13.4; radiusX: 2.1; radiusY: 2.1; startAngle: 180; sweepAngle: 270 } }
        Line { PathAngleArc { centerX: 4.6; centerY: 13.4; radiusX: 2.1; radiusY: 2.1; startAngle: 270; sweepAngle: 270 } }
    }

    // apps — three tiles and a turned one (the App Center)
    Glyph {
        glyph: "apps"
        Line {
            startX: 3; startY: 4.4
            PathArc { x: 4.4; y: 3; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 6.6; y: 3 }
            PathArc { x: 8; y: 4.4; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 8; y: 6.6 }
            PathArc { x: 6.6; y: 8; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 4.4; y: 8 }
            PathArc { x: 3; y: 6.6; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 3; y: 4.4 }
        }
        Line {
            startX: 3; startY: 11.4
            PathArc { x: 4.4; y: 10; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 6.6; y: 10 }
            PathArc { x: 8; y: 11.4; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 8; y: 13.6 }
            PathArc { x: 6.6; y: 15; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 4.4; y: 15 }
            PathArc { x: 3; y: 13.6; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 3; y: 11.4 }
        }
        Line {
            startX: 10; startY: 11.4
            PathArc { x: 11.4; y: 10; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 13.6; y: 10 }
            PathArc { x: 15; y: 11.4; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 15; y: 13.6 }
            PathArc { x: 13.6; y: 15; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 11.4; y: 15 }
            PathArc { x: 10; y: 13.6; radiusX: 1.4; radiusY: 1.4 }
            PathLine { x: 10; y: 11.4 }
        }
        Line {   // the turned tile
            startX: 12.5; startY: 1.8
            PathLine { x: 15.7; y: 5 }
            PathLine { x: 12.5; y: 8.2 }
            PathLine { x: 9.3; y: 5 }
            PathLine { x: 12.5; y: 1.8 }
        }
    }

    Glyph {
        glyph: "chevron-down"
        Line {
            startX: 5; startY: 7
            PathLine { x: 9; y: 11 }
            PathLine { x: 13; y: 7 }
        }
    }

    Glyph {
        glyph: "prev"
        Line { startX: 4.2; startY: 4.2; PathLine { x: 4.2; y: 13.8 } }
        Solid {
            startX: 14; startY: 4.4
            PathLine { x: 6.8; y: 9 }
            PathLine { x: 14; y: 13.6 }
            PathLine { x: 14; y: 4.4 }
        }
    }
    Glyph {
        glyph: "next"
        Line { startX: 13.8; startY: 4.2; PathLine { x: 13.8; y: 13.8 } }
        Solid {
            startX: 4; startY: 4.4
            PathLine { x: 11.2; y: 9 }
            PathLine { x: 4; y: 13.6 }
            PathLine { x: 4; y: 4.4 }
        }
    }

    Glyph {
        glyph: "play"
        Solid {
            startX: 5.6; startY: 3.6
            PathLine { x: 14.4; y: 9 }
            PathLine { x: 5.6; y: 14.4 }
            PathLine { x: 5.6; y: 3.6 }
        }
    }
    Glyph {
        glyph: "pause"
        Line { startX: 6.4; startY: 4; PathLine { x: 6.4; y: 14 } }
        Line { startX: 11.6; startY: 4; PathLine { x: 11.6; y: 14 } }
    }

    Glyph {
        glyph: "music"
        Line {
            startX: 7.2; startY: 13.2
            PathLine { x: 7.2; y: 3.6 }
            PathLine { x: 14.4; y: 2.4 }
            PathLine { x: 14.4; y: 11.8 }
        }
        Solid { PathAngleArc { centerX: 5.4; centerY: 13.4; radiusX: 2.1; radiusY: 1.7; startAngle: 0; sweepAngle: 360 } }
        Solid { PathAngleArc { centerX: 12.6; centerY: 12; radiusX: 2.1; radiusY: 1.7; startAngle: 0; sweepAngle: 360 } }
    }

    Glyph {
        glyph: "arrow-down"
        Line { startX: 9; startY: 3.5; PathLine { x: 9; y: 14 } }
        Line { startX: 4.8; startY: 10; PathLine { x: 9; y: 14.2 }
            PathLine { x: 13.2; y: 10 } }
    }
    Glyph {
        glyph: "arrow-up"
        Line { startX: 9; startY: 14.5; PathLine { x: 9; y: 4 } }
        Line { startX: 4.8; startY: 8; PathLine { x: 9; y: 3.8 }
            PathLine { x: 13.2; y: 8 } }
    }

    // bell (and bell-off: the same bell with an amber slash)
    Glyph {
        glyph: root.name === "bell-off" ? "bell-off" : "bell"
        Line {
            startX: 4.4; startY: 12.2
            PathLine { x: 4.4; y: 8.4 }
            PathArc { x: 13.6; y: 8.4; radiusX: 4.6; radiusY: 4.6 }
            PathLine { x: 13.6; y: 12.2 }
            PathLine { x: 15; y: 13.6 }
            PathLine { x: 3; y: 13.6 }
            PathLine { x: 4.4; y: 12.2 }
        }
        Line { startX: 9; startY: 2.4; PathLine { x: 9; y: 3.8 } }
        Line { PathAngleArc { centerX: 9; centerY: 14.8; radiusX: 1.6; radiusY: 1.6; startAngle: 0; sweepAngle: 180 } }
        ShapePath {
            strokeColor: root.name === "bell-off" ? root.accent : "transparent"
            strokeWidth: root.stroke + 0.2
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            startX: 2.6; startY: 2.6
            PathLine { x: 15.4; y: 15.4 }
        }
    }

    Glyph {
        glyph: "download"
        Line { startX: 9; startY: 2.6; PathLine { x: 9; y: 11 } }
        Line { startX: 5.2; startY: 7.6; PathLine { x: 9; y: 11.2 }
            PathLine { x: 12.8; y: 7.6 } }
        Line { startX: 3.4; startY: 14.2; PathLine { x: 14.6; y: 14.2 } }
    }
}
