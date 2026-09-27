import QtQuick
import "../common"

// GoogleGlow — a constant, flowing multi-colour light rail along a bar edge,
// in the style of Google's AI surfaces. Rendered per device pixel by
// shaders/googlebeam.frag (OKLab colour flow, noise-driven plumes, gliding
// glints, tone-mapped hot core, dithered falloff), so it has no banding and
// no layer seams at any scale factor.
//
//   edge: "bottom" — rail on the bottom edge, bloom rises (top bar)
//         "top"    — rail on the top edge, bloom falls (bottom taskbar)
//
// After editing the shader, recompile it:
//   /usr/lib/qt6/bin/qsb --glsl "100es,120,150" --hlsl 50 --msl 12 \
//       -o shaders/googlebeam.frag.qsb shaders/googlebeam.frag
Item {
    id: root

    property string edge: "bottom"
    property real amplitude: 1.0
    property bool boosted: false
    property string status: "idle"
    property bool hovered: false
    // px faded out at each end of the rail (0 = full-length, as on the bars)
    property real endFade: 0

    readonly property bool isWorking: status === "working" || boosted
    readonly property bool isWatching: status === "watching"
    readonly property bool isBlocked: status === "blocked"
    readonly property bool up: edge === "bottom"

    // extra brightness burst (e.g. window opened) — decays on its own
    property real pulse: 0
    function flash() { pulseAnim.restart(); }
    NumberAnimation { id: pulseAnim; target: root; property: "pulse"; from: 1; to: 0; duration: 1600; easing.type: Easing.OutCubic }

    property real level: (isWorking ? 1.0 : isBlocked ? 0.95 : isWatching ? 0.88 : hovered ? 0.86 : 0.74)
    Behavior on level { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.InOutSine } }
    readonly property real gain: Math.min(1.35, level * amplitude)

    // Flow speed eases between states; the clock integrates it, so a speed
    // change accelerates the flow instead of making it jump.
    property real speed: isWorking ? 2.1 : (hovered ? 1.4 : 1.0)
    Behavior on speed { NumberAnimation { duration: 900; easing.type: Easing.InOutSine } }

    property real blockedMix: isBlocked ? 1 : 0
    Behavior on blockedMix { NumberAnimation { duration: 700; easing.type: Easing.InOutSine } }

    // Flow clock in seconds. Wraps after ~28h (one imperceptible hop a day)
    // to keep shader float precision high.
    property real clock: 0
    FrameAnimation {
        running: root.visible && root.width > 0
        onTriggered: root.clock = (root.clock + frameTime * root.speed) % 100000
    }

    height: 56

    ShaderEffect {
        id: beam
        anchors.fill: parent
        property real time: root.clock
        property real gain: root.gain
        property real pulse: root.pulse
        property real blocked: root.blockedMix
        property real edgeTop: root.up ? 0 : 1
        property real resW: width
        property real resH: height
        property real fadeLen: root.endFade
        fragmentShader: Qt.resolvedUrl("../shaders/googlebeam.frag.qsb")
    }

    // Fallback if the shader can't load (missing .qsb, unsupported backend):
    // a plain flowing gradient rail so the bar never loses its edge light.
    Item {
        visible: beam.status === ShaderEffect.Error
        anchors { left: parent.left; right: parent.right; bottom: root.up ? parent.bottom : undefined; top: root.up ? undefined : parent.top }
        height: 2
        clip: true
        opacity: Math.min(1, root.gain)
        Row {
            x: -((root.clock * 0.045) % 1) * root.width
            Repeater {
                model: 2
                Rectangle {
                    width: root.width; height: 2
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.00; color: "#4285F4" }
                        GradientStop { position: 0.25; color: "#EA4335" }
                        GradientStop { position: 0.50; color: "#FBBC04" }
                        GradientStop { position: 0.75; color: "#34A853" }
                        GradientStop { position: 1.00; color: "#4285F4" }
                    }
                }
            }
        }
    }
}
