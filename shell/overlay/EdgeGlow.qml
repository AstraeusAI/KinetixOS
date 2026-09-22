import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"

// The signature: screen edges breathe while an agent holds input control.
// Overlay layer, click-through — awareness, never obstruction.
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "argus:glow"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    mask: Region {}   // empty input region → clicks pass through

    visible: glow.shown > 0.01

    Item {
        id: glow
        anchors.fill: parent
        opacity: shown * breath

        property real shown: AgentState.agentActive ? 1 : 0
        Behavior on shown { NumberAnimation { duration: 600; easing.type: Easing.InOutSine } }

        property real breath: 1
        SequentialAnimation on breath {
            running: AgentState.agentActive
            loops: Animation.Infinite
            NumberAnimation { to: 0.55; duration: 1400; easing.type: Easing.InOutSine }
            NumberAnimation { to: 1.0; duration: 1400; easing.type: Easing.InOutSine }
        }

        property color edge: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.55)

        // ── top: bright core line + soft falloff ──
        Item {
            anchors { top: parent.top; left: parent.left; right: parent.right }
            height: 20
            Rectangle {
                anchors { top: parent.top; left: parent.left; right: parent.right }
                height: 2
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.accent }
                    GradientStop { position: 1; color: Theme.accent2 }
                }
            }
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 2 }
                height: 18
                gradient: Gradient {
                    orientation: Gradient.Vertical
                    GradientStop { position: 0; color: glow.edge }
                    GradientStop { position: 1; color: "transparent" }
                }
            }
        }

        // ── bottom ──
        Item {
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
            height: 20
            Rectangle {
                anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
                height: 2
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.accent2 }
                    GradientStop { position: 1; color: Theme.accent }
                }
            }
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom; bottomMargin: 2 }
                height: 18
                gradient: Gradient {
                    orientation: Gradient.Vertical
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 1; color: glow.edge }
                }
            }
        }

        // ── left ──
        Item {
            anchors { top: parent.top; bottom: parent.bottom; left: parent.left }
            width: 20
            Rectangle {
                anchors { top: parent.top; bottom: parent.bottom; left: parent.left }
                width: 2
                gradient: Gradient {
                    orientation: Gradient.Vertical
                    GradientStop { position: 0; color: Theme.accent }
                    GradientStop { position: 1; color: Theme.accent2 }
                }
            }
            Rectangle {
                anchors { top: parent.top; bottom: parent.bottom; left: parent.left; leftMargin: 2 }
                width: 18
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: glow.edge }
                    GradientStop { position: 1; color: "transparent" }
                }
            }
        }

        // ── right ──
        Item {
            anchors { top: parent.top; bottom: parent.bottom; right: parent.right }
            width: 20
            Rectangle {
                anchors { top: parent.top; bottom: parent.bottom; right: parent.right }
                width: 2
                gradient: Gradient {
                    orientation: Gradient.Vertical
                    GradientStop { position: 0; color: Theme.accent2 }
                    GradientStop { position: 1; color: Theme.accent }
                }
            }
            Rectangle {
                anchors { top: parent.top; bottom: parent.bottom; right: parent.right; rightMargin: 2 }
                width: 18
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 1; color: glow.edge }
                }
            }
        }
    }
}
