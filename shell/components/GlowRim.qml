import QtQuick
import QtQuick.Shapes
import QtQuick.Effects

// GlowRim — the launcher logo's ring language for rounded tiles (dock tiles,
// taskbar tabs). A crisp rim that follows the tile's rounded shape, plus a
// glow behind it fed by a thicker hidden copy of the rim (blurring the thin
// rim alone spreads its light too thin to read as a glow).
//
//   rgb      red → green → blue, turning slowly (the focused state)
//   color    solid rim colour when not rgb (e.g. the app's own colour)
//   rimOpacity / glowOpacity   how present each layer is
//
// Fill the tile with it (anchors.fill: tile); the glow extends 4px beyond.
Item {
    id: root

    property real radius: 12
    property real thickness: 1.6
    property real glowThickness: 6
    property real rimOpacity: 1
    property real glowOpacity: 0
    property bool rgb: false
    property color color: "white"
    // split the layers so a tile can put the glow behind its glass and the
    // crisp rim on top: two instances, one with drawRim false, one with
    // drawGlow false
    property bool drawGlow: true
    property bool drawRim: true
    // blur reach of the glow (keep it inside any clipping parent)
    property real glowBlurMax: 22

    Behavior on rimOpacity { NumberAnimation { duration: 220 } }
    Behavior on glowOpacity { NumberAnimation { duration: 260 } }

    // only the RGB rim turns, and only while it is shown
    property real angle: 0
    NumberAnimation on angle {
        running: root.rgb && root.visible && ((root.drawGlow && root.glowOpacity > 0.01) || (root.drawRim && root.rimOpacity > 0.01))
        from: 0; to: 360
        loops: Animation.Infinite
        duration: 6000
    }
    readonly property color stopA: rgb ? "#EA4335" : color
    readonly property color stopB: rgb ? "#34A853" : color
    readonly property color stopC: rgb ? "#4285F4" : color

    component RimPath: ShapePath {
        id: rp
        property real inset: 0
        property real thick: 2
        property real rad: 10
        property real w: 10
        property real h: 10
        strokeColor: "transparent"
        fillRule: ShapePath.OddEvenFill
        fillGradient: ConicalGradient {
            centerX: rp.w / 2; centerY: rp.h / 2; angle: root.angle
            GradientStop { position: 0.000; color: root.stopA }
            GradientStop { position: 0.333; color: root.stopB }
            GradientStop { position: 0.667; color: root.stopC }
            GradientStop { position: 1.000; color: root.stopA }
        }
        startX: rp.inset; startY: rp.inset
        PathRectangle {
            x: rp.inset; y: rp.inset
            width: rp.w - 2 * rp.inset; height: rp.h - 2 * rp.inset
            radius: rp.rad
        }
        PathMove { x: rp.inset + rp.thick; y: rp.inset + rp.thick }
        PathRectangle {
            x: rp.inset + rp.thick; y: rp.inset + rp.thick
            width: rp.w - 2 * (rp.inset + rp.thick); height: rp.h - 2 * (rp.inset + rp.thick)
            radius: Math.max(0, rp.rad - rp.thick)
        }
    }

    // ── glow ──
    Shape {
        id: glowShape
        x: -4; y: -4
        width: root.width + 8; height: root.height + 8
        visible: false
        preferredRendererType: Shape.CurveRenderer
        RimPath {
            inset: 2; thick: root.glowThickness
            w: glowShape.width; h: glowShape.height
            rad: root.radius + 2
        }
    }
    ShaderEffectSource {
        id: glowTex
        anchors.fill: glowShape
        sourceItem: glowShape
        hideSource: true
        visible: false
    }
    MultiEffect {
        anchors.fill: glowShape
        source: glowTex
        blurEnabled: true
        blur: 0.8
        blurMax: root.glowBlurMax
        brightness: 0.45
        saturation: 0.35
        opacity: root.glowOpacity
        visible: root.drawGlow && opacity > 0.01
    }

    // ── crisp rim ──
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        opacity: root.rimOpacity
        visible: root.drawRim && opacity > 0.01
        RimPath {
            inset: 0; thick: root.thickness
            w: root.width; h: root.height
            rad: root.radius
        }
    }
}
