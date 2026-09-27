import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"
import "../components"

// Popup toasts: a stack of glass cards sliding in from the right edge, below
// the bar. Toasts time out on their own (hover pauses) WITHOUT dismissing —
// they remain in the Notification Center until cleared. Do-not-disturb
// suppresses them (critical ones still pop). Input is limited to the stack.
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; right: true; bottom: true }
    implicitWidth: 392
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "argus:notifs"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    // linger briefly so the last toast can play its exit animation
    property bool linger: false
    Timer { id: lingerTimer; interval: 420; onTriggered: win.linger = false }
    readonly property int toastCount: (typeof Notif !== "undefined" && Notif && Notif.toasts) ? Notif.toasts.count : 0
    onToastCountChanged: {
        if (toastCount === 0) { win.linger = true; lingerTimer.restart(); }
    }
    // Opening the Notification Center clears the popups — the same entries
    // are already listed there.
    readonly property bool centerOpen: (typeof AgentState !== "undefined" && AgentState) ? AgentState.notifOpen : false
    onCenterOpenChanged: {
        if (centerOpen && typeof Notif !== "undefined" && Notif && Notif.toasts) Notif.toasts.clear();
    }
    visible: !centerOpen && (toastCount > 0 || linger)

    mask: Region { item: stack }

    // A Column (not a ListView): positioners re-flow the moment any card's
    // height changes, so cards that settle after creation can never overlap.
    // Exit animations run in the delegate, which then finalizes the removal.
    Column {
        id: stack
        anchors { top: parent.top; topMargin: 66; right: parent.right; rightMargin: 16 }
        width: 360
        spacing: 0

        add: Transition {
            ParallelAnimation {
                NumberAnimation { property: "x"; from: 420; duration: 420; easing.type: Easing.OutBack; easing.overshoot: 0.9 }
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 260 }
            }
        }
        move: Transition {
            NumberAnimation { properties: "y"; duration: 320; easing.type: Easing.OutCubic }
        }

        Repeater {
            model: Notif.toasts
            delegate: Item {
                id: tw
                required property var model
                width: stack.width
                height: (leaving ? shrink : 1) * (tc.height + 12)
                clip: false
                property real shrink: 1
                readonly property bool leaving: model.leaving

                onLeavingChanged: if (leaving) exitAnim.start()
                ParallelAnimation {
                    id: exitAnim
                    NumberAnimation { target: tc; property: "x"; to: 420; duration: 300; easing.type: Easing.InCubic }
                    NumberAnimation { target: tc; property: "opacity"; to: 0; duration: 260 }
                    SequentialAnimation {
                        PauseAnimation { duration: 140 }
                        NumberAnimation { target: tw; property: "shrink"; to: 0; duration: 200; easing.type: Easing.InOutQuad }
                    }
                    onFinished: Notif.finalizeToast(tw.model.nid)
                }

                NotifCard {
                    id: tc
                    width: parent.width
                    nid: tw.model.nid
                    appName: tw.model.appName
                    summary: tw.model.summary
                    body: tw.model.body
                    icon: tw.model.icon
                    image: tw.model.image
                    urgency: tw.model.urgency
                    ts: tw.model.ts
                    actionsJson: tw.model.actionsJson
                    timeout: tw.model.timeout
                    kind: tw.model.kind
                    repeat: tw.model.repeat
                    saved: tw.model.saved
                    toast: true
                }
            }
        }
    }
}
