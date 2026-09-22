import QtQuick
import "../common"
import "content"

// Resolves a widget instance's type to its content component.
Item {
    id: host
    property var widget
    property var cfg: widget ? (widget.config || {}) : {}

    Loader {
        anchors.fill: parent
        sourceComponent: {
            if (!host.widget) return null;
            switch (host.widget.type) {
            case "clock":   return clockC;
            case "sysmon":  return sysmonC;
            case "notes":   return notesC;
            case "command": return commandC;
            case "agent":   return agentC;
            case "image":   return imageC;
            case "weather": return weatherC;
            }
            return null;
        }
        onLoaded: {
            // Live bindings, not one-shot copies: WidgetStore replaces the
            // widget object on every move/resize/config edit, so a plain
            // assignment would freeze content on stale state (e.g. gear-icon
            // edits to command/image/weather/notes would never apply).
            item.widget = Qt.binding(function() { return host.widget; });
            item.cfg = Qt.binding(function() { return host.cfg; });
        }
    }

    Component { id: clockC;   ClockWidget {} }
    Component { id: sysmonC;  SysMonWidget {} }
    Component { id: notesC;   NotesWidget {} }
    Component { id: commandC; CommandWidget {} }
    Component { id: agentC;   AgentWidget {} }
    Component { id: imageC;   ImageWidget {} }
    Component { id: weatherC; WeatherWidget {} }
}
