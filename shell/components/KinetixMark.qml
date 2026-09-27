import QtQuick
import QtQuick.Shapes
import QtQuick.Effects
import "../common"

// KinetixMark — the animated Kinetix logo, in the shell's red/green/blue light.
//
//   • the "K" is filled with the same flowing light as the bars and the dock
//     (shaders/rgbflow.frag, masked to the K's faceted shape), with a white
//     glint that sweeps across it and a real gaussian glow of its own colours
//   • it sits in a slowly turning red → green → blue ring; a white comet with
//     a soft tail orbits the ring, and a quieter inner arc counter-rotates
//   • the K's arms open on hover (half) and while active (fully); a click
//     spins the orbit once and sends two shockwave rings out
//
// Pure vector (QtQuick.Shapes) — crisp at any size. Nothing animates when
// `animated` is false or the item is hidden.
Item {
    id: mark

    property real size: 32
    property bool hovered: false
    property bool active: false
    property bool pressed: false
    property bool animated: true
    property color tint: Theme.crimsonText

    implicitWidth: size
    implicitHeight: size
    width: size
    height: size

    readonly property bool live: animated && visible

    // 0 → closed, 1 → open arms; hover half-opens, active fully opens.
    property real open: (active ? 1.0 : (hovered ? 0.6 : 0.0)) + (active ? 0 : 0.10 * Theme.heartbeatSin)
    Behavior on open { NumberAnimation { duration: 340; easing.type: Easing.OutBack; easing.overshoot: 1.5 } }

    // One-shot spin of the orbit on click for a tactile "engage".
    property real kick: 0
    onPressedChanged: if (pressed) { kickAnim.restart(); engage(); }
    NumberAnimation { id: kickAnim; target: mark; property: "kick"; from: 0; to: 360; duration: 640; easing.type: Easing.OutCubic }

    // Glint: a bright band that periodically sweeps across the K.
    property real glint: -0.4
    SequentialAnimation on glint {
        running: mark.live
        loops: Animation.Infinite
        PauseAnimation { duration: mark.active || mark.hovered ? 900 : 3200 }
        NumberAnimation { from: -0.4; to: 1.4; duration: 950; easing.type: Easing.InOutSine }
    }

    // Shockwave: two staggered rings expand from the ring on open / click.
    property real wave: 0
    property real wave2: 0
    function engage() { waveAnim.restart(); wave2Anim.restart(); }
    onActiveChanged: if (active) engage()
    NumberAnimation { id: waveAnim; target: mark; property: "wave"; from: 0; to: 1; duration: 820; easing.type: Easing.OutCubic }
    SequentialAnimation {
        id: wave2Anim
        PauseAnimation { duration: 140 }
        NumberAnimation { target: mark; property: "wave2"; from: 0; to: 1; duration: 820; easing.type: Easing.OutCubic }
    }

    // Flow clock for the K's light (integrates speed: no jumps on hover).
    property real flowSpeed: active ? 2.0 : (hovered ? 1.5 : 1.0)
    Behavior on flowSpeed { NumberAnimation { duration: 600; easing.type: Easing.InOutSine } }
    property real clock: 0
    FrameAnimation {
        running: mark.live
        onTriggered: mark.clock = (mark.clock + frameTime * mark.flowSpeed) % 100000
    }

    // ── the K's geometry, shared by the mask and the glint ──
    component KPath: ShapePath {
        strokeColor: "transparent"
        // stem
        startX: 31; startY: 26
        PathLine { x: 42; y: 26 }
        PathLine { x: 42; y: 74 }
        PathLine { x: 31; y: 74 }
        PathLine { x: 31; y: 26 }
        // upper arm
        PathMove { x: 42; y: 50 }
        PathLine { x: 57 + 5 * mark.open; y: 26 - 6 * mark.open }
        PathLine { x: 70 + 5 * mark.open; y: 26 - 6 * mark.open }
        PathLine { x: 50; y: 57 }
        PathLine { x: 42; y: 50 }
        // lower leg
        PathMove { x: 47; y: 47 }
        PathLine { x: 60; y: 40 }
        PathLine { x: 72 + 5 * mark.open; y: 74 + 6 * mark.open }
        PathLine { x: 59 + 5 * mark.open; y: 74 + 6 * mark.open }
        PathLine { x: 47; y: 47 }
    }

    Item {
        id: art
        width: 100
        height: 100
        scale: mark.size / 100
        transformOrigin: Item.TopLeft

        // shockwave rings (outside the ring, fade as they expand)
        Rectangle {
            anchors.centerIn: parent
            width: 88 + 46 * mark.wave; height: width; radius: width / 2
            color: "transparent"
            border.width: 2.2 * (1 - mark.wave) + 0.4
            border.color: Qt.rgba(0.92, 0.26, 0.21, 0.85 * (1 - mark.wave))   // red
            visible: mark.wave > 0 && mark.wave < 1
        }
        Rectangle {
            anchors.centerIn: parent
            width: 88 + 46 * mark.wave2; height: width; radius: width / 2
            color: "transparent"
            border.width: 1.6 * (1 - mark.wave2) + 0.3
            border.color: Qt.rgba(0.26, 0.52, 0.96, 0.75 * (1 - mark.wave2))  // blue
            visible: mark.wave2 > 0 && mark.wave2 < 1
        }

        // dark glass disc: gives the light something to glow against
        Rectangle {
            anchors.centerIn: parent
            width: 86; height: 86; radius: 43
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, mark.active ? 0.10 : (mark.hovered ? 0.08 : 0.05)) }
                GradientStop { position: 0.5; color: Qt.rgba(0.02, 0.02, 0.03, 0.35) }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.45) }
            }
        }

        // ── ring: red → green → blue, turning, with a constant glow ──
        // The colours flow round the ring; a blurred copy of the same ring
        // sits behind it (a tight glow plus a wide bloom), so the halo is
        // always lit and carries the same colours as they rotate.
        Item {
            id: ringSpinner
            anchors.fill: parent
            rotation: -ringSpin.value
            QtObject { id: ringSpin; property real value: 0 }
            NumberAnimation {
                target: ringSpin; property: "value"
                running: mark.live
                from: 0; to: 360
                loops: Animation.Infinite
                duration: mark.active ? 3600 : (mark.hovered ? 6000 : 9000)
            }

            // wide soft bloom
            MultiEffect {
                anchors.fill: parent
                source: ringTex
                blurEnabled: true
                blur: 1.0
                blurMax: 48
                brightness: 0.35
                saturation: 0.30
                opacity: mark.active ? 1.0 : (mark.hovered ? 0.95 : 0.85)
                Behavior on opacity { NumberAnimation { duration: 260 } }
            }
            // tight glow hugging the ring
            MultiEffect {
                anchors.fill: parent
                source: ringTex
                blurEnabled: true
                blur: 0.5
                blurMax: 16
                brightness: 0.40
                saturation: 0.25
                opacity: mark.active ? 1.0 : (mark.hovered ? 1.0 : 0.92)
                Behavior on opacity { NumberAnimation { duration: 260 } }
            }
            // the crisp ring itself
            Shape {
                id: ringShape
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "transparent"
                    fillRule: ShapePath.OddEvenFill
                    fillGradient: ConicalGradient {
                        centerX: 50; centerY: 50; angle: 90
                        GradientStop { position: 0.000; color: "#EA4335" }
                        GradientStop { position: 0.333; color: "#34A853" }
                        GradientStop { position: 0.667; color: "#4285F4" }
                        GradientStop { position: 1.000; color: "#EA4335" }
                    }
                    PathAngleArc { centerX: 50; centerY: 50; radiusX: 46; radiusY: 46; startAngle: 0; sweepAngle: 360 }
                    PathMove { x: 50 + 42.6; y: 50 }
                    PathAngleArc { centerX: 50; centerY: 50; radiusX: 42.6; radiusY: 42.6; startAngle: 0; sweepAngle: 360 }
                }
            }
            // thicker copy of the ring feeding the halos (blurring the thin
            // ring alone spreads its light too thin to read as a glow)
            Shape {
                id: glowRing
                anchors.fill: parent
                visible: false
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "transparent"
                    fillRule: ShapePath.OddEvenFill
                    fillGradient: ConicalGradient {
                        centerX: 50; centerY: 50; angle: 90
                        GradientStop { position: 0.000; color: "#FF5A4A" }
                        GradientStop { position: 0.333; color: "#3DDC76" }
                        GradientStop { position: 0.667; color: "#5A9BFF" }
                        GradientStop { position: 1.000; color: "#FF5A4A" }
                    }
                    PathAngleArc { centerX: 50; centerY: 50; radiusX: 48; radiusY: 48; startAngle: 0; sweepAngle: 360 }
                    PathMove { x: 50 + 40.5; y: 50 }
                    PathAngleArc { centerX: 50; centerY: 50; radiusX: 40.5; radiusY: 40.5; startAngle: 0; sweepAngle: 360 }
                }
            }
            ShaderEffectSource {
                id: ringTex
                anchors.fill: parent
                sourceItem: glowRing
                hideSource: true
                visible: false
            }
            // bright inner edge so the ring reads as lit glass, not flat paint
            Rectangle {
                anchors.centerIn: parent
                width: 85.6; height: 85.6; radius: 42.8
                color: "transparent"
                border.width: 0.8
                border.color: Qt.rgba(1, 1, 1, 0.35)
            }
        }
        // inner bevel hairline
        Rectangle {
            anchors.centerIn: parent
            width: 81; height: 81; radius: 40.5
            color: "transparent"
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.12)
        }

        // ── the K, filled with the shell's flowing light ──
        Item {
            id: kItem
            anchors.fill: parent
            scale: 1.16
            transformOrigin: Item.Center
            rotation: mark.hovered ? -4 : 0
            Behavior on rotation { NumberAnimation { duration: 380; easing.type: Easing.OutBack } }

            // the light itself (same shader as the bars/dock, tuned brighter)
            ShaderEffect {
                id: kLight
                anchors.fill: parent
                visible: false
                layer.enabled: true
                property real time: mark.clock
                property real gain: 1.9
                property real resW: 100
                property real resH: 100
                property real radius: 0
                property real horizontal: 0
                property real period: 70
                property real pulse: mark.wave > 0 && mark.wave < 1 ? (1 - mark.wave) : 0
                fragmentShader: Qt.resolvedUrl("../shaders/rgbflow.frag.qsb")
            }


            // glow of the K's own colours
            MultiEffect {
                anchors.fill: parent
                source: kColourTex
                blurEnabled: true
                blur: 1.0
                blurMax: 24
                brightness: 0.1
                opacity: 0.45 + 0.35 * mark.open + 0.10 * Theme.heartbeatSin
            }
            // the K's own path filled with the live light texture — exact
            // alignment by construction (no mask pass)
            Shape {
                id: kColour
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                KPath { fillItem: kLight }
            }
            ShaderEffectSource {
                id: kColourTex
                anchors.fill: parent
                sourceItem: kColour
                visible: false
            }
            // bright core so the K reads as lit from within, not flat colour
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                opacity: 0.30
                KPath {
                    fillGradient: LinearGradient {
                        x1: 30; y1: 24; x2: 72; y2: 78
                        GradientStop { position: 0.0; color: "#FFFFFF" }
                        GradientStop { position: 0.55; color: Qt.rgba(1, 1, 1, 0.15) }
                        GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0.0) }
                    }
                }
            }
            // travelling glint
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                visible: mark.glint > -0.3 && mark.glint < 1.3
                KPath {
                    fillGradient: LinearGradient {
                        x1: 30; y1: 24; x2: 72; y2: 78
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: Math.min(0.97, Math.max(0.01, mark.glint - 0.14)); color: "transparent" }
                        GradientStop { position: Math.min(0.98, Math.max(0.02, mark.glint)); color: Qt.rgba(1, 1, 1, 0.85) }
                        GradientStop { position: Math.min(0.99, Math.max(0.03, mark.glint + 0.14)); color: "transparent" }
                        GradientStop { position: 1.0; color: "transparent" }
                    }
                }
            }
        }

        // ── comet: a white head with a soft tail, riding the ring ──
        Item {
            id: orbit
            anchors.fill: parent
            rotation: spin + mark.kick
            property real spin: 0
            NumberAnimation on spin {
                running: mark.live
                from: 0; to: 360
                loops: Animation.Infinite
                duration: mark.active ? 2000 : (mark.hovered ? 2800 : 6500)
            }
            Item {
                anchors.fill: parent
                layer.enabled: true
                layer.samples: 4
                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: "transparent"
                        fillRule: ShapePath.OddEvenFill
                        fillGradient: ConicalGradient {
                            centerX: 50; centerY: 50; angle: 0
                            GradientStop { position: 0.00; color: "#FFFFFF" }
                            GradientStop { position: 0.03; color: Qt.rgba(1, 1, 1, 0.85) }
                            GradientStop { position: 0.12; color: Qt.rgba(1, 1, 1, 0.35) }
                            GradientStop { position: 0.30; color: Qt.rgba(1, 1, 1, 0.0) }
                            GradientStop { position: 1.00; color: Qt.rgba(1, 1, 1, 0.0) }
                        }
                        PathAngleArc { centerX: 50; centerY: 50; radiusX: 46.5; radiusY: 46.5; startAngle: 0; sweepAngle: 360 }
                        PathMove { x: 50 + 41.8; y: 50 }
                        PathAngleArc { centerX: 50; centerY: 50; radiusX: 41.8; radiusY: 41.8; startAngle: 0; sweepAngle: 360 }
                    }
                }
            }
            // comet head glow
            Rectangle {
                x: 50 + 44.2 - width / 2; y: 50 - height / 2
                width: 7; height: 7; radius: 3.5
                color: "white"
                Rectangle {
                    anchors.centerIn: parent
                    width: 18; height: 18; radius: 9; z: -1
                    color: Qt.rgba(1, 1, 1, 0.22)
                }
            }
        }

        // quieter inner arc, counter-rotating: depth + a second rhythm
        Item {
            id: innerOrbit
            anchors.fill: parent
            rotation: -innerSpin
            property real innerSpin: 0
            NumberAnimation on innerSpin {
                running: mark.live
                from: 0; to: 360
                loops: Animation.Infinite
                duration: mark.active ? 3200 : 11000
            }
            Shape {
                anchors.fill: parent
                layer.enabled: true
                layer.samples: 4
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: Qt.rgba(1, 1, 1, mark.active || mark.hovered ? 0.40 : 0.18)
                    strokeWidth: 1.4
                    fillColor: "transparent"
                    capStyle: ShapePath.RoundCap
                    PathAngleArc { centerX: 50; centerY: 50; radiusX: 36; radiusY: 36; startAngle: 200; sweepAngle: 60 }
                }
            }
        }

        // spark at the arm junction, breathing with the shell heartbeat
        Rectangle {
            x: 47 - width / 2; y: 47 - height / 2
            width: 3.5 + 1.5 * Theme.heartbeatSin + 2.5 * mark.open
            height: width
            radius: width / 2
            color: Qt.rgba(1, 1, 1, 0.75 + 0.25 * Theme.heartbeatSin)
            visible: mark.animated
        }
    }
}
