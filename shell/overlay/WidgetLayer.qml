import QtQuick
import Quickshell
import "../common"
import "../widgets"

// The desktop widget layer: one layer-shell window per widget instance,
// floating over applications. Add/remove via the widget catalog.
Variants {
    model: WidgetStore.order
    WidgetWindow {}
}
