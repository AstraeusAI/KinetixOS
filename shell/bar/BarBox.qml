import QtQuick
import "../common"
import "../components"

// Shared premium capsule used by the existing bar groups. It deliberately
// keeps content as the default property so every current Bar.qml box remains
// structurally unchanged.
GlassPanel {
    id: box

    // Defaults are the bar's own deep-red identity (docs/02, "Main bar
    // palette"), not the OS-wide iris accent — every pill on the bar reads
    // as cut from the same ominous-red glass unless it deliberately opts
    // out (none currently do).
    property bool active: false
    property color activeColor: Theme.crimson
    property color hoverBorderColor: Theme.barStrokeStrong
    readonly property bool hovered: hit.containsMouse

    implicitHeight: 38
    radius: Theme.rPill
    level: active || hovered ? 2 : 1
    baseColor: active
                ? Theme.alpha(activeColor, 0.13)
                : hovered && interactive ? Theme.barHoverGlow : Theme.barBaseHigh
    tinted: active || (hovered && interactive)
    tint: active ? activeColor : Theme.crimson

    scale: interactive && hit.pressed ? 0.965 : (interactive && hovered ? 1.025 : 1.0)
    Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
    Behavior on baseColor { ColorAnimation { duration: Theme.durFast } }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: Theme.rPill
        color: "transparent"
        border.width: 1
        border.color: active ? Theme.alpha(activeColor, 0.42)
                     : hovered && interactive ? hoverBorderColor : Theme.alpha(Theme.crimson, 0.12)
        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
        z: 1
    }

    // Top micro-chamfer specular highlight — stays white/bright on purpose:
    // a real glossy surface's specular reflection keeps the light source's
    // color, not the substrate's, so tinting this red would read as flat
    // colored plastic instead of glass over a red base.
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        height: 1
        radius: box.radius
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 0.20; color: Qt.rgba(1, 1, 1, 0.16) }
            GradientStop { position: 0.50; color: Qt.rgba(1, 1, 1, 0.22) }
            GradientStop { position: 0.80; color: Qt.rgba(1, 1, 1, 0.16) }
            GradientStop { position: 1.0; color: "transparent" }
        }
        z: 2
    }

    // Controlled hit target behind child controls.
    //
    // The press MUST be accepted (the default). Qt's MouseArea docs: "If
    // accepted is set to false, no further events will be sent to this
    // MouseArea until the button is next pressed" — so rejecting the press
    // means the release never arrives and `clicked` can never fire, which
    // silently killed every pill that relied on this handler.
    //
    // Nested controls still win: children sit above this area in the stacking
    // order, so they receive the press first and accept it. Only clicks on
    // empty pill space reach here. propagateComposedEvents then lets the
    // composed click continue downward if something below wants it.
    MouseArea {
        id: hit
        anchors.fill: parent
        enabled: box.interactive
        hoverEnabled: true
        cursorShape: box.interactive ? Qt.PointingHandCursor : Qt.ArrowCursor
        acceptedButtons: Qt.LeftButton
        propagateComposedEvents: true
        onClicked: function (mouse) { mouse.accepted = false; box.clicked(); }
    }

    signal clicked()
}
