import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"

// One fixed full-screen layer-shell surface per widget instance. Only the
// child frame is included in the input mask, so the desktop remains
// click-through while the widget can move without moving its pointer space.
PanelWindow {
    id: win
    required property string modelData
    readonly property string widgetId: modelData
    // Resolve by ID against the reactive store. Depend on `revision`
    // (bumped on every mutation including in-place move/resize) rather
    // than on `widgets` (which only changes on structural add/remove).
    // Depending on `widgets` would destroy this delegate on every drag
    // tick because update() used to replace the array.
    property var widget: {
        var _r = WidgetStore.revision;
        return WidgetStore.byId(widgetId) || {};
    }

    anchors { top: true; left: true; right: true; bottom: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    // This is a pointer-interactive surface. It does not take keyboard focus
    // from applications, but its header and resize grip must receive clicks.
    focusable: true

    WlrLayershell.namespace: "argus:widget:" + (win.widget.id || "pending")
    // Overlay is consistently pointer-interactive on KWin; Top can be
    // rendered above clients while still losing pointer dispatch in a few
    // Plasma layer-shell configurations.
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

    // The Region follows the child frame as it moves/resizes. Outside this
    // rectangle KWin sends the pointer straight to the application below.
    mask: Region { item: frame }
    // Re-apply mask when frame geometry changes (the Region tracks the item
    // automatically in theory, but KWin may need a nudge).
    onWidgetChanged: { mask.item = null; mask.item = frame; }

    WidgetFrame {
        id: frame
        x: win.widget.x
        y: win.widget.y
        width: win.widget.w
        height: win.widget.h
        widget: win.widget
    }
}