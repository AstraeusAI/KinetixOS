import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"

// Shared safe tooltip. Nearly every surface in this shell lives inside a
// PanelWindow (wlr-layer-shell) or a Quickshell PopupWindow — real Wayland
// surfaces, not the "normal top-level window" the built-in QtQuick.Controls
// ToolTip's positioning logic assumes. Under that combination it renders on
// top of its target instead of above it, eating the click meant for the
// target — confirmed repeatedly, independently, across many components
// (IconButton, CloseButton, TaskButton, TaskPreview's close, the bar's own
// App Center/agent/sys-monitor/now-playing capsules, the launcher's pin
// tiles) before this got pulled into one shared component instead of being
// fixed one incident report at a time.
//
// Use `HoverTip { target: someItem; hovered: someCondition; text: "..." }`
// — never ToolTip.visible/ToolTip.text/ToolTip.delay — anywhere in this
// shell.
Item {
    id: root
    property Item target: null
    property bool hovered: false
    property string text: ""
    property int delay: 450

    Timer {
        id: tipDelay
        interval: root.delay
        onTriggered: popup.shown = true
    }
    onHoveredChanged: {
        if (root.hovered && root.text.length > 0 && root.target !== null) {
            tipDelay.restart();
        } else {
            tipDelay.stop();
            popup.shown = false;
        }
    }

    PopupWindow {
        id: popup
        property bool shown: false
        anchor.window: root.target ? root.target.Window.window : null
        anchor.item: root.target
        anchor.edges: Edges.Top
        anchor.gravity: Edges.Top
        anchor.adjustment: PopupAdjustment.Slide
        anchor.margins.bottom: 6
        visible: shown && root.target !== null && root.target.Window.window !== null
        color: "transparent"
        implicitWidth: tipLabel.implicitWidth + 16
        implicitHeight: tipLabel.implicitHeight + 10

        Rectangle {
            anchors.fill: parent
            radius: Theme.rS
            color: Theme.glassBaseHigh
            border.width: 1
            border.color: Theme.alpha(Theme.crimsonText, 0.35)

            Text {
                id: tipLabel
                anchors.centerIn: parent
                text: root.text
                color: Theme.text
                font { family: Theme.fontMono; pixelSize: Theme.tMicro }
            }
        }
    }
}
