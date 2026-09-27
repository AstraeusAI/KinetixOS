import QtQuick

// PopupChrome — the shared finish for the shell's panels (system monitor, App
// Center, notification centre, command palette, agent panel), in the same
// language as the dock tiles and the launcher logo: a crisp rim that follows
// the card's rounded shape, a bright inner glass edge, and the system's
// red → green → blue light along the top edge.
//
// Add it as the LAST child of a panel's card so it draws above the content:
//   PopupChrome { anchors.fill: parent; radius: card.radius }
// It only paints the edges, never over the content, and never animates.
Item {
    id: root
    property real radius: 20
    property real lightOpacity: 0.9

    z: 1000

    // crisp outer rim
    GlowRim {
        anchors.fill: parent
        radius: root.radius
        drawGlow: false
        thickness: 1.1
        color: Qt.rgba(1, 1, 1, 0.16)
    }
    // bright inner glass edge
    Rectangle {
        anchors.fill: parent
        anchors.margins: 1.6
        radius: Math.max(0, root.radius - 1.6)
        color: "transparent"
        border.width: 0.8
        border.color: Qt.rgba(1, 1, 1, 0.07)
    }
    // the system's light along the top edge
    Rectangle {
        x: root.radius * 0.8
        y: 0.4
        width: Math.max(0, parent.width - root.radius * 1.6)
        height: 1.6
        radius: 0.8
        opacity: root.lightOpacity
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.00; color: Qt.rgba(0.92, 0.26, 0.21, 0.0) }
            GradientStop { position: 0.18; color: "#EA4335" }
            GradientStop { position: 0.50; color: "#34A853" }
            GradientStop { position: 0.82; color: "#4285F4" }
            GradientStop { position: 1.00; color: Qt.rgba(0.26, 0.52, 0.96, 0.0) }
        }
    }
    // soft bloom under the light, so it reads as light and not a painted line
    Rectangle {
        x: root.radius * 0.8
        y: 1
        width: Math.max(0, parent.width - root.radius * 1.6)
        height: 10
        opacity: 0.35 * root.lightOpacity
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.10) }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }
}
