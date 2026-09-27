import QtQuick
import Quickshell
import "../common"
import "../widgets"

// Optional desktop widget layer. Keep it dormant unless the user opts in;
// no widget windows are created by the default KinetixOS desktop.
Variants {
    readonly property bool widgetSystemEnabled: Quickshell.env("KINETIX_ENABLE_WIDGETS") === "1"
    model: widgetSystemEnabled ? WidgetStore.order : []
    WidgetWindow {}
}
