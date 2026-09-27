import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"

// Shared exit control for every Argus surface: launcher, palette, agent
// panel, widget catalog, widget settings, sys popup, notification toasts,
// taskbar preview cards. Google-style: soft circle, hover lifts + tints
// danger, press springs in.
Rectangle {
    id: root
    property string glyph: "✕"
    property string tip: "Close"
    property real box: 26
    signal clicked()

    implicitWidth: box
    implicitHeight: box
    radius: box / 2
    color: ma.containsMouse ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.16)
                            : Theme.surfaceLow
    border.width: 1
    border.color: ma.containsMouse ? Qt.rgba(Theme.danger.r, Theme.danger.g, Theme.danger.b, 0.45)
                                   : Theme.stroke
    scale: ma.pressed ? 0.88 : (ma.containsMouse ? 1.06 : 1)

    Behavior on color { ColorAnimation { duration: Theme.durFast } }
    Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
    Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutBack } }

    Text {
        anchors.centerIn: parent
        text: root.glyph
        color: ma.containsMouse ? Theme.danger : Theme.textDim
        font.pixelSize: 12
        font.weight: Font.DemiBold
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        anchors.margins: -4
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    // ── tooltip ──────────────────────────────────────────────────
    // `tip` was declared but never actually wired to anything — no
    // CloseButton anywhere ever showed one. A real Quickshell PopupWindow,
    // not the built-in QtQuick.Controls ToolTip: this component lives
    // inside PanelWindow (wlr-layer-shell) surfaces throughout the shell,
    // where that control renders on top of its target instead of above it
    // and eats the click (see shell/components/IconButton.qml and
    // shell/taskbar/Taskbar.qml for the same fix applied first).
    // root.Window.window resolves to whichever surface actually hosts
    // this instance, so it works generically everywhere CloseButton is
    // used.
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
