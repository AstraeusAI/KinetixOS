import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland
import "../common"

// Compact icon button used across the bar and panels.
Rectangle {
    id: root
    property string glyph: ""
    property string iconName: ""
    property string tip: ""
    property bool active: false
    property color tint: Theme.accent
    signal clicked()

    implicitWidth: 28
    implicitHeight: 26
    radius: Theme.rS
    clip: true
    color: active ? Theme.alpha(tint, 0.18)
         : ma.containsMouse ? Theme.surfaceHigh : "transparent"
    border.width: 1
    border.color: active ? Theme.alpha(tint, 0.40)
                 : ma.containsMouse ? Theme.alpha(tint, 0.25) : "transparent"
    // Google-style spring: hover lifts, press squashes with overshoot
    scale: ma.pressed ? 0.90 : (ma.containsMouse ? 1.08 : 1)

    Behavior on color { ColorAnimation { duration: Theme.durFast } }
    Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }

    // ── material ripple on press ──
    Rectangle {
        id: ripple
        anchors.centerIn: parent
        width: 6; height: 6; radius: 3
        color: Theme.alpha(root.tint, 0.40)
        opacity: 0
        scale: 1
    }
    SequentialAnimation {
        id: rippleAnim
        NumberAnimation { target: ripple; property: "opacity"; to: 1; duration: 60 }
        ParallelAnimation {
            NumberAnimation { target: ripple; property: "scale"; to: 5.2; duration: 320; easing.type: Easing.OutQuint }
            NumberAnimation { target: ripple; property: "opacity"; to: 0; duration: 320; easing.type: Easing.OutQuint }
        }
    }

    Canvas {
        id: vectorIcon
        anchors.centerIn: parent
        width: 14
        height: 14
        visible: root.iconName !== ""

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            ctx.strokeStyle = root.active ? root.tint
                            : ma.containsMouse ? Theme.text : Theme.textDim;
            ctx.lineWidth = 1.45;
            ctx.lineCap = "round";
            ctx.lineJoin = "round";

            if (root.iconName === "grid") {
                for (var row = 0; row < 2; row++) {
                    for (var col = 0; col < 2; col++) {
                        ctx.strokeRect(2.2 + col * 6.0, 2.2 + row * 6.0, 3.6, 3.6);
                    }
                }
            } else if (root.iconName === "terminal") {
                ctx.beginPath();
                ctx.moveTo(2.5, 3.5);
                ctx.lineTo(6.5, 6.8);
                ctx.lineTo(2.5, 10.1);
                ctx.moveTo(7.6, 10.1);
                ctx.lineTo(12, 10.1);
                ctx.stroke();
            }
        }

        onVisibleChanged: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()

        Connections {
            target: root
            function onActiveChanged() { vectorIcon.requestPaint(); }
            function onTintChanged() { vectorIcon.requestPaint(); }
        }
        Connections {
            target: ma
            function onContainsMouseChanged() { vectorIcon.requestPaint(); }
        }
    }

    Text {
        visible: root.iconName === ""
        anchors.centerIn: parent
        text: root.glyph
        color: root.active ? root.tint
             : ma.containsMouse ? Theme.text : Theme.textDim
        font.pixelSize: 13
        scale: ma.pressed ? 0.92 : 1
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
        Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutBack } }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: { ripple.opacity = 1; ripple.scale = 1; rippleAnim.restart(); root.clicked(); }
    }

    // ── tooltip ──────────────────────────────────────────────────
    // A real Quickshell PopupWindow anchored above this button, not the
    // built-in QtQuick.Controls ToolTip attached property that used to be
    // here. This component is used inside PanelWindow (wlr-layer-shell)
    // surfaces — the bar's own launcher/terminal buttons, App Center's
    // header buttons — and the built-in ToolTip positions itself assuming
    // a normal top-level window; anchored inside a layer-shell surface
    // instead, it rendered on top of the button rather than above it and
    // ate the click meant for the button (confirmed live in the taskbar's
    // launcher button, fixed there with this same pattern first).
    // root.Window.window resolves to whichever PanelWindow actually hosts
    // this instance, so the fix works generically everywhere IconButton
    // is used, not just one call site.
    Timer {
        id: tipDelay
        interval: 500
        onTriggered: tipPopup.shown = true
    }
    Connections {
        target: ma
        function onContainsMouseChanged() {
            if (ma.containsMouse && root.tip.length > 0) {
                tipDelay.restart();
            } else {
                tipDelay.stop();
                tipPopup.shown = false;
            }
        }
    }
    PopupWindow {
        id: tipPopup
        property bool shown: false
        anchor.window: root.Window.window
        anchor.item: root
        anchor.edges: Edges.Top
        anchor.gravity: Edges.Top
        anchor.adjustment: PopupAdjustment.Slide
        anchor.margins.bottom: 6
        visible: shown && root.Window.window !== null
        color: "transparent"
        implicitWidth: tipText.implicitWidth + 16
        implicitHeight: tipText.implicitHeight + 10

        Rectangle {
            anchors.fill: parent
            radius: Theme.rS
            color: Theme.glassBaseHigh
            border.width: 1
            border.color: Theme.alpha(Theme.crimsonText, 0.35)

            Text {
                id: tipText
                anchors.centerIn: parent
                text: root.tip
                color: Theme.text
                font { family: Theme.fontMono; pixelSize: Theme.tMicro }
            }
        }
    }
}
