import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import "../common"
import "../components"
import "../taskbar"

// Dock — a floating glass rail on the left edge of the screen.
//
//   • pinned apps (the same favourites the launcher's ★ manages), then a
//     divider, then running apps that are not pinned
//   • macOS-style magnification: icons swell smoothly under the pointer and
//     grow away from the screen edge
//   • each tile takes its app's own colour (sampled from the icon) for its
//     glow, tint and window indicators
//   • launch bounce until the app's window appears; per-window indicators
//     on the edge side; right-click menu (new window, pin/unpin, show or
//     minimize, close)
//
// Reserves its strip of the screen like the taskbar does, so maximized
// windows never sit under it. The window is wider than that strip so icons
// can magnify outward; an input mask keeps the unused area click-through.
// The light rail animates continuously, like the bars' (so the dock
// redraws at the display rate, the same as the two bars).
PanelWindow {
    id: dock
    required property ShellScreen modelData
    screen: modelData

    readonly property int edgeGap: 8
    readonly property int railW: 60
    readonly property int tileBase: 42
    readonly property int spacing: 8
    readonly property int pad: 9
    readonly property real maxMagnify: 1.45
    readonly property real sigma: 58

    // Anchored to the left edge only: the compositor centres it vertically,
    // and the surface is just the rail (plus magnification room) rather than
    // the full screen height — the light rail redraws it every frame.
    anchors { left: true }
    // The label and the menu are drawn in this surface (xdg popups were
    // composited translucent here, so text behind showed through). The
    // surface only widens to make room for them while the pointer is on the
    // dock or the menu is open; the rest of the time it hugs the rail.
    implicitWidth: (hover.hovered || menu.open || label.shown)
                   ? 330 : edgeGap + railW + Math.ceil(tileBase * (maxMagnify - 1)) + 16
    implicitHeight: Math.max(300, baseRailH + 120)
    // An empty dock (no pinned apps, nothing running — e.g. a fresh live
    // account) hides and gives its strip back, instead of drawing a squashed
    // empty pill; it slides back in as soon as there is something to show.
    readonly property bool empty: dockModel.count === 0
    property real shown: empty ? 0 : 1
    Behavior on shown { NumberAnimation { duration: 420; easing.type: Easing.OutQuint } }
    exclusiveZone: empty ? 0 : edgeGap + railW + 6
    color: "transparent"

    WlrLayershell.namespace: "argus:dock"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    mask: Region {
        item: hitArea
        Region { item: menuBox }
    }
    BackgroundEffect.blurRegion: Region {
        item: rail
        radius: rail.radius
        Region { item: menuBox; radius: 16 }
    }

    // ── model ──────────────────────────────────────────────────────────
    // Keyed ListModel (not a reassigned array) so tiles keep their state —
    // hover, bounce, colour — across the frequent TaskRunner updates.
    ListModel { id: dockModel }

    readonly property var favApps: {
        var favs = AppIndex.favorites || [];
        var apps = AppIndex.apps || [];
        var out = [];
        for (var i = 0; i < favs.length; i++)
            for (var j = 0; j < apps.length; j++)
                if (apps[j].file === favs[i]) { out.push(apps[j]); break; }
        return out;
    }

    function appByFile(file) {
        var apps = AppIndex.apps || [];
        for (var i = 0; i < apps.length; i++) if (apps[i].file === file) return apps[i];
        return null;
    }

    function buildEntries() {
        var map = {}, order = [];
        var wins = TaskRunner.windows || [];
        for (var w = 0; w < wins.length; w++) {
            var tl = wins[w];
            var appId = tl.appId || "", title = tl.title || "";
            if (!TaskStore.isValid(appId, title)) continue;
            var key = TaskStore.groupKey(appId, title);
            if (!map[key]) { map[key] = { "key": key, "appId": appId, "items": [] }; order.push(key); }
            map[key].items.push(tl);
            if (appId !== "") map[key].appId = appId;
        }
        var groups = [];
        for (var k = 0; k < order.length; k++) {
            var g = map[order[k]];
            var first = g.items.length ? (g.items[0].title || "") : "";
            var entry = TaskStore.lookupEntry(g.appId, first);
            groups.push({ "key": g.key, "appId": g.appId, "items": g.items,
                          "file": entry ? entry.file : "",
                          "name": TaskStore.displayName(g.appId, first),
                          "icon": TaskStore.iconSource(g.appId, first) });
        }
        var out = [], used = {};
        var favs = dock.favApps;
        for (var f = 0; f < favs.length; f++) {
            var app = favs[f], items = [];
            for (var q = 0; q < groups.length; q++) {
                if (!used[q] && groups[q].file !== "" && groups[q].file === app.file) {
                    items = groups[q].items; used[q] = true; break;
                }
            }
            out.push({ "key": "pin:" + app.file, "name": app.name,
                       "icon": app.icon ? "file://" + app.icon : "",
                       "appFile": app.file, "pinned": true, "itemsJson": JSON.stringify(items) });
        }
        for (var r = 0; r < groups.length; r++) {
            if (used[r]) continue;
            var gr = groups[r];
            out.push({ "key": "run:" + gr.key, "name": gr.name, "icon": gr.icon,
                       "appFile": gr.file, "pinned": false, "itemsJson": JSON.stringify(gr.items) });
        }
        return out;
    }

    function sync() {
        var want = buildEntries();
        for (var i = 0; i < want.length; i++) {
            var found = -1;
            for (var j = i; j < dockModel.count; j++)
                if (dockModel.get(j).key === want[i].key) { found = j; break; }
            if (found < 0) dockModel.insert(i, want[i]);
            else {
                if (found !== i) dockModel.move(found, i, 1);
                var cur = dockModel.get(i);
                for (var p in want[i])
                    if (cur[p] !== want[i][p]) dockModel.setProperty(i, p, want[i][p]);
            }
        }
        while (dockModel.count > want.length) dockModel.remove(dockModel.count - 1);
        pinnedCount = 0;
        for (var c = 0; c < want.length; c++) if (want[c].pinned) pinnedCount++;
    }
    property int pinnedCount: 0
    readonly property bool showDivider: pinnedCount > 0 && dockModel.count > pinnedCount

    Connections { target: TaskRunner; function onWindowsChanged() { dock.sync(); } }
    Connections { target: AppIndex; function onAppsChanged() { dock.sync(); } function onFavoritesChanged() { dock.sync(); } }
    Component.onCompleted: sync()

    // ── launch feedback ────────────────────────────────────────────────
    property var launching: ({})
    function launchApp(file) {
        var app = appByFile(file);
        if (!app) return;
        AppIndex.launch(app);
        var l = Object.assign({}, launching); l[file] = Date.now(); launching = l;
        launchClear.restart();
    }
    Timer { id: launchClear; interval: 4000; onTriggered: dock.launching = ({}) }

    // ── actions ────────────────────────────────────────────────────────
    function mostRecent(items) {
        for (var i = items.length - 1; i >= 0; i--) if (!items[i].minimized) return items[i];
        return items.length ? items[items.length - 1] : null;
    }
    function activateEntry(appFile, items) {
        if (items.length === 0) { launchApp(appFile); return; }
        if (items.length === 1) { TaskStore.toggleMinimize(items[0]); return; }
        var cur = null;
        for (var i = 0; i < items.length; i++) if (items[i].active) cur = items[i];
        if (cur) TaskStore.activate(items[(items.indexOf(cur) + 1) % items.length]);
        else TaskStore.activate(mostRecent(items));
    }

    // ── magnification ──────────────────────────────────────────────────
    // Scales come from the *unmagnified* layout, so growing tiles can't feed
    // back into the pointer mapping and make the dock wobble.
    property real pointerY: -1e6
    property real magnet: hover.hovered && !menu.open ? 1 : 0
    Behavior on magnet { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    readonly property real pitch: tileBase + spacing
    readonly property real dividerH: showDivider ? 10 : 0
    // Column: N cells (+ divider gap) and N-1 gaps
    readonly property real baseRailH: pad * 2 + dockModel.count * tileBase + dividerH
                                      + spacing * Math.max(0, dockModel.count - 1)
    function baseCenter(index) {
        return pad + index * pitch + tileBase / 2 + (index >= pinnedCount ? dividerH : 0);
    }
    function magnifyAt(center) {
        if (dock.magnet <= 0.001) return 1;
        var d = (dock.pointerY - center) / dock.sigma;
        return 1 + (dock.maxMagnify - 1) * dock.magnet * Math.exp(-d * d);
    }

    // input region: the rail, widened while hovered so magnified tiles stay clickable
    Item {
        id: hitArea
        x: 0
        y: rail.y - 12
        width: dock.empty ? 0 : (hover.hovered ? rail.x + rail.width + 24 : dock.edgeGap + dock.railW + 4)
        height: rail.height + 24
    }

    HoverHandler {
        id: hover
        target: hitArea
        onPointChanged: {
            var baseTop = (dock.height - dock.baseRailH) / 2;
            dock.pointerY = hover.point.position.y + hitArea.y - baseTop;
        }
    }

    // ── the rail ───────────────────────────────────────────────────────
    GlassPanel {
        id: rail
        x: dock.edgeGap
        anchors.verticalCenter: parent.verticalCenter
        // widens with the magnified tiles so they stay inside the glass
        width: Math.max(dock.railW, content.width + dock.pad * 2)
        height: content.implicitHeight + dock.pad * 2
        radius: 26
        level: 3
        baseColor: Qt.rgba(0.045, 0.047, 0.066, 0.72)
        rim: true
        sheen: false

        // entrance: slides in from the edge on startup
        property real enter: 0
        Component.onCompleted: enter = 1
        Behavior on enter { NumberAnimation { duration: 700; easing.type: Easing.OutQuint } }
        opacity: enter * dock.shown
        visible: opacity > 0.01
        transform: Translate { x: -dock.railW * (1 - rail.enter * dock.shown) }

        // edge light: a hairline of crimson along the rail's inner edge, and a
        // cool glass highlight down the outer one
        Rectangle {
            anchors { left: parent.left; leftMargin: 1; top: parent.top; bottom: parent.bottom; topMargin: 22; bottomMargin: 22 }
            width: 1
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.5; color: Theme.alpha(Theme.crimsonText, 0.45) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
        Rectangle {
            anchors { right: parent.right; rightMargin: 1; top: parent.top; bottom: parent.bottom; topMargin: 22; bottomMargin: 22 }
            width: 1
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.14) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // Animated red / green / blue light filling the whole rail behind the
        // tiles (components/RgbFlow.qml — the same light as both bars).
        // Declared before the tiles so they sit on top.
        RgbFlow {
            anchors.fill: parent
            horizontal: false
            radius: rail.radius
            status: AgentState.status
            hovered: hover.hovered
        }

        Column {
            id: content
            x: dock.pad
            y: dock.pad
            spacing: dock.spacing

            Repeater {
                model: dockModel
                // A cell per app; the last pinned cell also owns the divider
                // gap below it, so the layout (and baseCenter) stay exact.
                delegate: Item {
                    id: cell
                    required property int index
                    required property string key
                    required property string name
                    required property string icon
                    required property string appFile
                    required property bool pinned
                    required property string itemsJson
                    readonly property bool lastPinned: dock.showDivider && index === dock.pinnedCount - 1
                    readonly property var wins: JSON.parse(itemsJson)

                    width: tileItem.width
                    height: tileItem.height + (lastPinned ? dock.dividerH : 0)

                    DockItem {
                        id: tileItem
                        base: dock.tileBase
                        appName: cell.name
                        iconSource: cell.icon
                        items: cell.wins
                        magnify: dock.magnifyAt(dock.baseCenter(cell.index))
                        launching: dock.launching[cell.appFile] !== undefined && cell.wins.length === 0
                        onClicked: dock.activateEntry(cell.appFile, cell.wins)
                        onMiddleClicked: if (cell.appFile !== "") dock.launchApp(cell.appFile)
                        onMenuRequested: menu.openFor(tileItem, cell.name, cell.appFile, cell.wins)
                        onHotChanged: hot ? dock.showLabel(tileItem, cell.name, cell.wins.length)
                                          : dock.hideLabel(tileItem)
                    }
                    Rectangle {
                        visible: cell.lastPinned
                        x: (dock.tileBase - width) / 2
                        y: tileItem.height + (dock.dividerH + dock.spacing) / 2 - 1
                        width: 24; height: 2; radius: 1
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "transparent" }
                            GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.22) }
                            GradientStop { position: 1.0; color: "transparent" }
                        }
                    }
                }
            }

        }
    }


    // ── name label, drawn beside the hovered tile ──────────────────────
    property Item labelFor: null
    property string labelText: ""
    property int labelWins: 0
    function showLabel(item, name, wins) {
        labelFor = item; labelText = name; labelWins = wins;
        if (!label.shown) labelDelay.restart();
    }
    function hideLabel(item) {
        if (labelFor !== item) return;
        labelDelay.stop();
        labelLinger.restart();
    }
    Timer { id: labelDelay; interval: 240; onTriggered: label.shown = true }
    Timer { id: labelLinger; interval: 120; onTriggered: { if (!dock.labelFor || !dock.labelFor.hot) label.shown = false; } }

    Item {
        id: label
        property bool shown: false
        readonly property real cy: dock.labelFor
            ? dock.labelFor.mapToItem(dock.contentItem, 0, dock.labelFor.height / 2).y : 0
        x: rail.x + rail.width + 12
        y: cy - height / 2
        width: labelRow.implicitWidth + 26
        height: 34
        visible: opacity > 0.01 && !menu.open
        opacity: shown && dock.labelFor && dock.labelFor.hot ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
        Behavior on y { enabled: label.opacity > 0.5; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        transform: Translate { x: (1 - label.opacity) * -6 }

        Rectangle {
            anchors.fill: parent
            radius: 12
            color: Qt.rgba(0.043, 0.046, 0.063, 0.94)
            border.width: 1
            border.color: dock.labelFor ? Theme.alpha(dock.labelFor.accent, 0.50) : Qt.rgba(1, 1, 1, 0.1)
            Rectangle {
                anchors { top: parent.top; topMargin: 1; left: parent.left; right: parent.right; leftMargin: 10; rightMargin: 10 }
                height: 1
                color: Qt.rgba(1, 1, 1, 0.10)
            }
        }
        // pointer notch toward the tile
        Rectangle {
            width: 8; height: 8
            rotation: 45
            x: -4
            anchors.verticalCenter: parent.verticalCenter
            color: Qt.rgba(0.043, 0.046, 0.063, 0.94)
            border.width: 1
            border.color: dock.labelFor ? Theme.alpha(dock.labelFor.accent, 0.50) : "transparent"
            z: -1
        }
        Row {
            id: labelRow
            anchors.centerIn: parent
            spacing: 8
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 6; height: 6; radius: 3
                visible: dock.labelWins > 0
                color: dock.labelFor ? dock.labelFor.accent : Theme.crimsonText
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: dock.labelText
                color: Theme.text
                font { family: Theme.fontUi; pixelSize: 12; weight: Font.DemiBold }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: dock.labelWins > 1
                text: dock.labelWins + " windows"
                color: Theme.textFaint
                font { family: Theme.fontUi; pixelSize: 11 }
            }
        }
    }

    // ── right-click menu ───────────────────────────────────────────────
    Item {
        id: menu
        property bool open: false
        property Item target: null
        property string title: ""
        property string appFile: ""
        property var items: []
        readonly property bool isPinned: appFile !== "" && (AppIndex.favorites || []).indexOf(appFile) >= 0
        function openFor(item, name, file, wins) {
            target = item; title = name; appFile = file; items = wins; open = true;
            closeTimer.stop();
        }
        function close() { open = false; }
        visible: false
    }
    Item {
        id: menuBox
        readonly property real cy: menu.target
            ? menu.target.mapToItem(dock.contentItem, 0, menu.target.height / 2).y : 0
        x: rail.x + rail.width + 12
        y: Math.max(8, Math.min(dock.height - height - 8, cy - 28))
        // zero-sized while closed so the input mask and blur region vanish
        width: menu.open ? 230 : 0
        height: menu.open ? menuCol.implicitHeight + 16 : 0
        opacity: menu.open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
        transform: Translate { x: (1 - menuBox.opacity) * -8 }
        clip: true

        Timer { id: closeTimer; interval: 650; onTriggered: menu.close() }
        HoverHandler {
            onHoveredChanged: hovered ? closeTimer.stop() : closeTimer.restart()
        }
        // swallow clicks on the menu body itself
        MouseArea { anchors.fill: parent; z: -1 }

        // Popups get no compositor blur, so the body is near-opaque: text
        // behind it must never bleed through the menu's labels.
        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Qt.rgba(0.043, 0.046, 0.063, 0.985)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.10)
            Rectangle {   // top light
                anchors { top: parent.top; topMargin: 1; left: parent.left; right: parent.right; leftMargin: 14; rightMargin: 14 }
                height: 1
                color: Qt.rgba(1, 1, 1, 0.12)
            }

            Column {
                id: menuCol
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 8 }
                spacing: 2

                Text {
                    leftPadding: 10; topPadding: 6; bottomPadding: 6
                    width: parent.width
                    text: menu.title
                    elide: Text.ElideRight
                    color: Theme.text
                    font { family: Theme.fontUi; pixelSize: 13; weight: Font.DemiBold }
                }
                Rectangle { width: parent.width; height: 1; color: Qt.rgba(1, 1, 1, 0.08) }

                component MenuRow: Rectangle {
                    id: mrow
                    property string label
                    property bool danger: false
                    signal activated()
                    width: menuCol.width
                    height: 34
                    radius: 10
                    color: rowMa.containsMouse ? (danger ? Theme.alpha(Theme.crimson, 0.24) : Qt.rgba(1, 1, 1, 0.08)) : "transparent"
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text {
                        anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                        text: mrow.label
                        color: mrow.danger ? Theme.crimsonText : Theme.text
                        font { family: Theme.fontUi; pixelSize: 12 }
                    }
                    MouseArea {
                        id: rowMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { mrow.activated(); menu.close(); }
                    }
                }

                MenuRow {
                    visible: menu.appFile !== ""
                    label: menu.items.length > 0 ? "New window" : "Open"
                    onActivated: dock.launchApp(menu.appFile)
                }
                MenuRow {
                    visible: menu.appFile !== ""
                    label: menu.isPinned ? "Unpin from dock" : "Pin to dock"
                    onActivated: { var a = dock.appByFile(menu.appFile); if (a) AppIndex.toggleFav(a); }
                }
                MenuRow {
                    visible: menu.items.length > 0
                    label: {
                        for (var i = 0; i < menu.items.length; i++) if (!menu.items[i].minimized) return "Minimize";
                        return "Show";
                    }
                    onActivated: {
                        var anyUp = false;
                        for (var i = 0; i < menu.items.length; i++) if (!menu.items[i].minimized) anyUp = true;
                        for (var j = 0; j < menu.items.length; j++) TaskStore.setMinimized(menu.items[j], anyUp);
                    }
                }
                MenuRow {
                    visible: menu.items.length > 0
                    danger: true
                    label: menu.items.length > 1 ? "Close " + menu.items.length + " windows" : "Close"
                    onActivated: { for (var i = 0; i < menu.items.length; i++) TaskStore.requestClose(menu.items[i]); }
                }
            }
        }
    }
    // the menu also closes when the pointer leaves the dock with it open
    Connections {
        target: hover
        function onHoveredChanged() { if (!hover.hovered && menu.open) closeTimer.restart(); }
    }
}
