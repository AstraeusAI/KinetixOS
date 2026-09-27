import QtQuick
import "../common"

// RgbFlow — the animated red / green / blue light field that fills the dock,
// the top bar and the taskbar (shaders/rgbflow.frag). Put it inside the
// surface's glass, declared before the controls so they sit on top.
//
//   horizontal  colour flows along x (bars) or along y (dock)
//   radius      corner radius of the surface (the outline glow follows it)
//   period      px per red→green→blue cycle
//   flash()     brief brightness burst (e.g. a window opened)
//
// The flow clock integrates `speed`, so hover and agent activity speed it up
// smoothly instead of making it jump.
Item {
    id: root

    property bool horizontal: true
    property real radius: 0
    property real period: horizontal ? 1100 : height * 0.9
    property real amplitude: 1.0
    property string status: "idle"
    property bool boosted: false
    property bool hovered: false

    readonly property bool isWorking: status === "working" || boosted

    property real pulse: 0
    function flash() { pulseAnim.restart(); }
    NumberAnimation { id: pulseAnim; target: root; property: "pulse"; from: 1; to: 0; duration: 1600; easing.type: Easing.OutCubic }

    property real speed: isWorking ? 2.2 : (hovered ? 1.4 : 1.0)
    Behavior on speed { NumberAnimation { duration: 900; easing.type: Easing.InOutSine } }
    property real level: isWorking ? 1.1 : (hovered ? 1.0 : 0.85)
    Behavior on level { NumberAnimation { duration: 600; easing.type: Easing.InOutSine } }

    // seconds of flow; wraps after ~28h to keep shader float precision high
    property real clock: 0
    FrameAnimation {
        running: root.visible && root.width > 0 && root.height > 0
        onTriggered: root.clock = (root.clock + frameTime * root.speed) % 100000
    }

    ShaderEffect {
        anchors.fill: parent
        property real time: root.clock
        property real gain: root.level * root.amplitude
        property real resW: width
        property real resH: height
        property real radius: root.radius
        property real horizontal: root.horizontal ? 1 : 0
        property real period: root.period
        property real pulse: root.pulse
        fragmentShader: Qt.resolvedUrl("../shaders/rgbflow.frag.qsb")
    }
}
