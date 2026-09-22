import QtQuick
import "../common"

// High-fidelity glass surface: layered shadow → tinted base → depth wash →
// specular sheen → rim light → optional accent glow. Every Argus surface
// should be built on this.
Item {
    id: root

    property real radius: Theme.rL
    property int level: 1                 // 0–3 elevation
    property bool tinted: false           // accent-tinted border + glow
    property color tint: Theme.accent
    property bool interactive: false      // hover lift
    property bool wash: true              // vertical depth gradient
    property bool sheen: true             // diagonal specular highlight
    property bool rim: true               // 1px top rim light
    property bool clipContent: false
    property color baseColor: Theme.glassBase

    default property alias content: contentItem.data

    // ── soft multi-layer shadow ──
    Repeater {
        model: Theme.shadowFor(root.level)
        delegate: Rectangle {
            required property var modelData
            anchors.fill: parent
            anchors.margins: -modelData.grow
            anchors.topMargin: -modelData.grow + modelData.dy
            radius: root.radius + modelData.grow
            color: Qt.rgba(0, 0, 0, modelData.a)
        }
    }

    // ── glass body ──
    Rectangle {
        id: base
        anchors.fill: parent
        radius: root.radius
        color: root.baseColor
        border.width: 1
        border.color: root.tinted
                      ? Theme.alpha(root.tint, 0.42)
                      : Theme.stroke
        Behavior on border.color { ColorAnimation { duration: Theme.durMed } }

        Rectangle {
            anchors.fill: parent
            visible: root.wash
            radius: parent.radius
            gradient: Gradient {
                GradientStop { position: 0.0; color: Theme.glassWashTop }
                GradientStop { position: 0.55; color: "transparent" }
                GradientStop { position: 1.0; color: Theme.glassWashBottom }
            }
        }

        Rectangle {
            anchors.fill: parent
            visible: root.sheen
            radius: parent.radius
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.sheen }
                GradientStop { position: 0.42; color: "transparent" }
            }
        }

        Rectangle {
            visible: root.rim
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 1 }
            height: 1
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.16; color: Theme.rimTop }
                GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.10) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // inner hairline — a faint machined edge that lifts the glass off
        // whatever sits behind it
        Rectangle {
            anchors { fill: parent; margins: 1 }
            radius: Math.max(1, root.radius - 1)
            color: "transparent"
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.055)
        }
    }

    // ── accent glow (active/tinted) ──
    Rectangle {
        anchors.fill: parent
        radius: root.radius
        visible: root.tinted
        color: "transparent"
        border.width: 2
        border.color: Theme.alpha(root.tint, 0.20)
    }

    Item {
        id: contentItem
        anchors.fill: parent
        clip: root.clipContent
    }

    // hover lift
    scale: (root.interactive && hover.hovered) ? 1.012 : 1.0
    Behavior on scale { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
    HoverHandler { id: hover; enabled: root.interactive }
}
