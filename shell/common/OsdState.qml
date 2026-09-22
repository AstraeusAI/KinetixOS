pragma Singleton
import QtQuick

// Shared state for the OSD overlay (volume, brightness, …).
// Any widget calls OsdState.show(kind, value, label) — overlay/Osd.qml renders it.
QtObject {
    property bool visible: false
    property string kind: "volume"
    property real value: 0
    property string label: ""

    function show(kind, value, label) {
        this.kind = kind;
        this.value = value;
        this.label = label || "";
        visible = true;
        hideTimer.restart();
    }

    property Timer hideTimer: Timer {
        interval: 1600
        onTriggered: visible = false
    }
}
