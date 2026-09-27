import QtQuick
import "../common"
import "../components"

// High-fidelity sculpted optical glass capsule primitive for the Kinetix Quickshell bar.
// Models authentic optical physics:
// 1. Soft multi-layer drop shadow lifting the capsule off the bar slab.
// 2. Precision outer drop-bloom on hover/active.
// 3. Prismatic directionally-lit optical glass bevel frame (1px continuous perimeter gradient).
// 4. Translucent oxblood glass substrate with internal volumetric depth well and diagonal sheen.
// 5. Dual micro-chamfers: 6-stop upper Fresnel specular hairline + bottom laser reflex.
// 6. 3D convex cylindrical lens dome highlight.
// 7. Interactive refraction dynamics: hover bloom, internal luminance scatter, and micro-press physics.
Item {
    id: box

    property bool active: false
    property color activeColor: Theme.crimson
    property color hoverBorderColor: Theme.barStrokeStrong
    property bool interactive: false

    HoverHandler { id: boxHover }
    readonly property bool hovered: hit.containsMouse || boxHover.hovered

    property real radius: Theme.rPill
    property int level: active || (hovered && interactive) ? 2 : 1
    property color baseColor: active
                ? Theme.alpha(activeColor, 0.22)
                : (hovered && interactive ? Theme.barHoverGlow : Theme.barBaseHigh)
    property bool tinted: active || (hovered && interactive)
    property color tint: active ? activeColor : Theme.crimson

    implicitHeight: 38
    default property alias content: contentItem.data

    scale: interactive && hit.pressed ? 0.980 : (interactive && hovered ? 1.012 : 1.0)
    Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
    Behavior on baseColor { ColorAnimation { duration: Theme.durFast } }

    // ── 1. Soft Multi-Layer Drop Shadow ──────────────────────────────────
    Repeater {
        model: Theme.shadowFor(box.level)
        delegate: Rectangle {
            required property var modelData
            anchors.fill: parent
            anchors.margins: -modelData.grow
            anchors.topMargin: -modelData.grow + modelData.dy
            radius: box.radius + modelData.grow
            color: Qt.rgba(0, 0, 0, modelData.a * 0.90)
            z: 0
        }
    }

    // ── 2. Outer Drop-Bloom on Hover / Active ─────────────────────────────
    Rectangle {
        anchors.fill: parent
        anchors.margins: -3
        radius: box.radius + 3
        antialiasing: true
        color: "transparent"
        border.width: 2
        border.color: box.active
                      ? Theme.alpha(box.activeColor, 0.35)
                      : (box.hovered && box.interactive ? Theme.alpha(Theme.crimson, 0.24) : "transparent")
        opacity: box.tinted ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
        Behavior on border.color { ColorAnimation { duration: Theme.durMed } }
        z: 1
    }

    // ── 3. Prismatic Directionally-Lit Optical Glass Bevel Frame ─────────
    // This 1px perimeter frame acts as the outer chamfer of the glass capsule:
    // catches bright overhead key light on top, mid-tone light along the curves,
    // and warm crimson laser reflection along the bottom.
    Rectangle {
        id: bevelFrame
        anchors.fill: parent
        radius: box.radius
        antialiasing: true
        z: 2
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop {
                position: 0.0
                color: box.active
                       ? Qt.rgba(1, 1, 1, 0.48)
                       : (box.hovered ? (box.interactive ? Qt.rgba(1, 1, 1, 0.36) : Qt.rgba(1, 1, 1, 0.30)) : Qt.rgba(1, 1, 1, 0.20))
            }
            GradientStop {
                position: 0.30
                color: box.active
                       ? Theme.alpha(box.activeColor, 0.48)
                       : (box.hovered && box.interactive ? Theme.alpha(Theme.crimsonText, 0.32) : Qt.rgba(1, 1, 1, 0.075))
            }
            GradientStop {
                position: 0.70
                color: box.active
                       ? Theme.alpha(box.activeColor, 0.38)
                       : (box.hovered && box.interactive ? Theme.alpha(Theme.crimson, 0.28) : Theme.alpha(Theme.crimson, 0.12))
            }
            GradientStop {
                position: 1.0
                color: box.active
                       ? Theme.alpha(Theme.alarm, 0.56)
                       : (box.hovered && box.interactive ? Theme.alpha(Theme.crimsonText, 0.40) : Theme.alpha(Theme.crimsonText, 0.22))
            }
        }
    }

    // ── 4. Translucent Glass Substrate & Volumetric Well ──────────────────
    // Inset by 1px so the outer 1px of bevelFrame forms the directional glass chamfer.
    Rectangle {
        id: glassBody
        anchors { fill: parent; margins: 1 }
        radius: Math.max(1, box.radius - 1)
        antialiasing: true
        color: box.baseColor
        clip: true
        z: 3

        // Volumetric depth well: dark top meniscus dropping into a rich oxblood pool
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.16) }
                GradientStop { position: 0.45; color: "transparent" }
                GradientStop { position: 1.0; color: Theme.alpha(Theme.crimson, 0.10) }
            }
        }

        // Subtle diagonal specular sheen across the substrate
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.045) }
                GradientStop { position: 0.38; color: "transparent" }
            }
        }

        // Internal scatter luminance on hover / active
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: box.active ? Theme.alpha(box.activeColor, 0.14)
                             : (box.hovered ? (box.interactive ? Qt.rgba(1, 1, 1, 0.07) : Qt.rgba(1, 1, 1, 0.035)) : "transparent")
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }

        // Inner secondary machined edge (double bevel)
        Rectangle {
            anchors { fill: parent; margins: 1 }
            radius: Math.max(1, parent.radius - 1)
            antialiasing: true
            color: "transparent"
            border.width: 1
            border.color: box.active
                          ? Theme.alpha(box.activeColor, 0.28)
                          : (box.hovered && box.interactive ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.06))
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
        }
    }

    // ── 5. Internal Content Container ────────────────────────────────────
    Item {
        id: contentItem
        anchors.fill: parent
        z: 10
    }

    // ── 6. Convex Cylindrical Lens Dome Highlight ────────────────────────
    // Front-surface reflection simulating overhead specular light catching
    // the curved upper half of a cylindrical glass capsule.
    Rectangle {
        anchors { top: parent.top; left: parent.left; right: parent.right; margins: 1 }
        height: Math.round(parent.height * 0.48)
        radius: Math.max(1, box.radius - 1)
        antialiasing: true
        z: 15
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop {
                position: 0.0
                color: Qt.rgba(1, 1, 1, box.active ? 0.16 : (box.hovered ? (box.interactive ? 0.13 : 0.10) : 0.075))
            }
            GradientStop { position: 0.60; color: Qt.rgba(1, 1, 1, 0.03) }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    // ── 7. Top Micro-Chamfer Specular Crest ──────────────────────────────
    // Grazing overhead light catch across the top inner border with Fresnel crest
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 1 }
        anchors.leftMargin: Math.min(12, box.width * 0.18)
        anchors.rightMargin: anchors.leftMargin
        height: 1
        radius: box.radius
        z: 17
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 0.15; color: Qt.rgba(1, 1, 1, 0.12) }
            GradientStop {
                position: 0.50
                color: Qt.rgba(1, 1, 1, box.active ? 0.34 : (box.hovered ? (box.interactive ? 0.28 : 0.22) : 0.15))
            }
            GradientStop { position: 0.85; color: Qt.rgba(1, 1, 1, 0.12) }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    // ── 8. Bottom Laser Reflex ───────────────────────────────────────────
    // Warm reflex catching the FlowBand laser rail below
    Rectangle {
        anchors { bottom: parent.bottom; left: parent.left; right: parent.right; bottomMargin: 1 }
        anchors.leftMargin: Math.min(14, box.width * 0.2)
        anchors.rightMargin: anchors.leftMargin
        height: 1
        radius: box.radius
        z: 17
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 0.30; color: Theme.alpha(Theme.crimson, 0.20) }
            GradientStop { position: 0.50; color: Theme.alpha(Theme.crimsonText, 0.30) }
            GradientStop { position: 0.70; color: Theme.alpha(Theme.crimson, 0.20) }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    // ── 9. Controlled Hit Target ────────────────────────────────────────
    MouseArea {
        id: hit
        anchors.fill: parent
        enabled: box.interactive
        hoverEnabled: true
        cursorShape: box.interactive ? Qt.PointingHandCursor : Qt.ArrowCursor
        acceptedButtons: Qt.LeftButton
        propagateComposedEvents: true
        onClicked: function (mouse) { mouse.accepted = false; box.clicked(); }
        z: 25
    }

    signal clicked()
}
