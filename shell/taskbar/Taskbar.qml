import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import "../common"
import "../components"

// Taskbar — full-width, bottom-docked window manager, the conventional
// Windows/Cinnamon/KDE shape: a flush rectangular bar that reserves real
// screen space (exclusiveZone), not a floating rounded dock overlaying
// content. One button per app group, hover opens a live-thumbnail preview
// (TaskPreview) with per-window close, left-click focuses / toggles
// minimize, grouped left-click cycles, middle-click closes, right-click
// opens the window menu. Data is live from TaskRunner; icons resolve
// via TaskStore. Live thumbnails in the hover preview are not yet wired to
// a real capture source (see TaskPreview.qml) — a known gap, not new here.
PanelWindow {
    id: taskbar
    required property ShellScreen modelData
    screen: modelData

    anchors { left: true; right: true; bottom: true }
    implicitHeight: 56
    exclusiveZone: 56
    color: "transparent"

    WlrLayershell.namespace: "argus:taskbar"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    // Real frosted glass: ask the compositor to blur whatever is behind the
    // bar (KWin honors ext-background-effect). The tint layers below are
    // deliberately translucent so this shows through.
    BackgroundEffect.blurRegion: Region { item: rail }

    // ── entrance ───────────────────────────────────────────────
    property real enter: 0
    Component.onCompleted: enter = 1
    Behavior on enter { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.OutQuint } }

    // ── live app groups ────────────────────────────────────────
    // Rebuilt from TaskRunner.windows (plain data streamed from
    // scripts/kinetix-tasks.py — see shell/common/TaskRunner.qml for why
    // this isn't Quickshell.Wayland.ToplevelManager). `tick` re-runs the
    // builder ~1.2s as a safety net on top of TaskRunner's own
    // push-on-change updates.
    property int tick: 0

    readonly property var groups: {
        tick;
        TaskRunner.windows; TaskRunner.activeUuid;
        return buildGroups();
    }
    readonly property int appWindowCount: {
        var list = groups;
        var total = 0;
        for (var i = 0; i < list.length; i++)
            total += list[i].items ? list[i].items.length : 0;
        return total;
    }
    onAppWindowCountChanged: edgeGlow.flash()
    Timer {
        interval: 1200
        running: true
        repeat: true
        onTriggered: taskbar.tick++
    }

    // taskModel backs the task row's Repeater instead of binding it
    // directly to `groups`. `groups` is a plain JS array rebuilt from
    // scratch — new array, new object literals — on every TaskRunner push
    // (every window focus/minimize/maximize change) and every 1.2s tick;
    // Repeater has no way to diff a reassigned plain array by identity, so
    // binding it directly means the ENTIRE task row — every tile, every
    // delegate, every in-flight hover/press animation — gets destroyed and
    // recreated on essentially every update. This shell already hit and
    // fixed the identical problem for the agent chat's message list (see
    // AgentState.qml's own `messages` ListModel comment); same fix here.
    // A ListModel role can't hold a plain array-of-objects value once
    // reassigned via setProperty (confirmed live: works via append(), but
    // setProperty() silently drops it back to undefined) — same limitation
    // AgentState.qml worked around with `argsJson`/`detailJson`. `items`
    // here does the same as `itemsJson`, parsed back out per delegate.
    ListModel { id: taskModel }

    function syncTaskModel(groups) {
        var i, j, idx;
        for (i = taskModel.count - 1; i >= 0; i--) {
            var stillPresent = false;
            for (j = 0; j < groups.length; j++) {
                if (groups[j].key === taskModel.get(i).key) { stillPresent = true; break; }
            }
            if (!stillPresent) taskModel.remove(i);
        }
        for (j = 0; j < groups.length; j++) {
            var g = groups[j];
            idx = -1;
            for (i = 0; i < taskModel.count; i++) {
                if (taskModel.get(i).key === g.key) { idx = i; break; }
            }
            var itemsJson = JSON.stringify(g.items || []);
            if (idx === -1) {
                taskModel.insert(j, { "key": g.key, "appId": g.appId, "name": g.name, "icon": g.icon, "itemsJson": itemsJson });
            } else {
                if (idx !== j) taskModel.move(idx, j, 1);
                taskModel.setProperty(j, "appId", g.appId);
                taskModel.setProperty(j, "name", g.name);
                taskModel.setProperty(j, "icon", g.icon);
                taskModel.setProperty(j, "itemsJson", itemsJson);
            }
        }
    }
    onGroupsChanged: syncTaskModel(groups)

    function buildGroups() {
        var map = {};
        var order = [];
        var wins = TaskRunner.windows || [];
        for (var w = 0; w < wins.length; w++) {
            var tl = wins[w];
            var appId = tl.appId || "";
            var title = tl.title || "";
            if (!TaskStore.isValid(appId, title)) continue;
            var key = TaskStore.groupKey(appId, title);
            if (!map[key]) {
                map[key] = { "key": key, "appId": appId, "items": [] };
                order.push(key);
            }
            map[key].items.push(tl);
            if (appId !== "") map[key].appId = appId;
        }
        var out = [];
        for (var k = 0; k < order.length; k++) {
            var g = map[order[k]];
            var aid = g.appId || "";
            var firstTitle = "";
            try { firstTitle = g.items.length > 0 ? (g.items[0].title || "") : ""; } catch (e3) {}
            out.push({
                "key": g.key,
                "appId": aid,
                "name": TaskStore.displayName(aid, firstTitle),
                "icon": TaskStore.iconSource(aid, firstTitle),
                "items": g.items
            });
        }
        return out;
    }

    function groupActive(group) {
        if (!group || !group.items) return false;
        for (var i = 0; i < group.items.length; i++) {
            if (group.items[i].active) return true;
        }
        return false;
    }

    function mostRecent(group) {
        if (!group || !group.items || group.items.length === 0) return null;
        for (var i = group.items.length - 1; i >= 0; i--) {
            if (!group.items[i].minimized) return group.items[i];
        }
        return group.items[group.items.length - 1];
    }

    function focusedWindow(group) {
        if (!group || !group.items) return null;
        for (var i = 0; i < group.items.length; i++)
            if (group.items[i].active) return group.items[i];
        return null;
    }

    function handleLeftClick(group) {
        if (!group || !group.items || group.items.length === 0) return;
        hidePreviewNow();
        if (group.items.length === 1) {
            TaskStore.toggleMinimize(group.items[0]);
            return;
        }
        // Grouped: an active group cycles, an inactive one focuses.
        var cur = focusedWindow(group);
        if (cur) {
            var idx = group.items.indexOf(cur);
            var next = group.items[(idx + 1) % group.items.length];
            TaskStore.activate(next);
        } else {
            TaskStore.activate(mostRecent(group));
        }
    }

    function handleMiddleClick(group) {
        if (!group) return;
        var tl = focusedWindow(group) || mostRecent(group);
        if (tl) { TaskStore.requestClose(tl); hidePreviewNow(); }
    }

    function toggleShowDesktop() {
        var list = groups;
        var anyUp = false;
        for (var i = 0; i < list.length; i++) {
            var items = list[i].items || [];
            for (var j = 0; j < items.length; j++) {
                if (!items[j].minimized) anyUp = true;
            }
        }
        for (var k = 0; k < list.length; k++) {
            var windows = list[k].items || [];
            for (var m = 0; m < windows.length; m++) {
                TaskStore.setMinimized(windows[m], anyUp);
            }
        }
    }

    // ── preview state ──────────────────────────────────────────
    property var previewGroup: null
    property Item previewAnchor: null
    property bool previewOpen: false
    property var menuGroup: null
    property Item menuAnchor: null
    property bool menuOpen: false

    Timer {
        id: previewDelay
        interval: 380
        onTriggered: {
            if (taskbar.previewGroup && !taskbar.menuOpen) taskbar.previewOpen = true;
        }
    }
    Timer {
        id: previewGrace
        interval: 220
        onTriggered: {
            if (!previewCard.hovered && !anyTaskHovered()) taskbar.previewOpen = false;
        }
    }
    function anyTaskHovered() {
        for (var i = 0; i < taskRep.count; i++) {
            var it = null;
            try { it = taskRep.itemAt(i); } catch (e) { continue; }
            if (it && it.currentHovered) return true;
        }
        return launcherBtn.hovered || deskBtn.hovered;
    }

    function onTaskHovered(group, anchorItem) {
        if (taskbar.menuOpen) return;
        if (taskbar.previewGroup !== group) {
            taskbar.previewGroup = group;
            taskbar.previewAnchor = anchorItem;
            taskbar.previewOpen = false;
            previewDelay.restart();
        } else {
            previewGrace.stop();
            if (taskbar.previewGroup && !previewDelay.running && !taskbar.menuOpen)
                taskbar.previewOpen = true;
        }
    }
    function onTaskUnhovered() {
        previewDelay.stop();
        previewGrace.restart();
    }
    function hidePreviewNow() {
        previewDelay.stop();
        previewGrace.stop();
        taskbar.previewOpen = false;
        taskbar.previewGroup = null;
        taskbar.previewAnchor = null;
    }

    function openMenu(group, anchorItem) {
        hidePreviewNow();
        taskbar.menuGroup = group;
        taskbar.menuAnchor = anchorItem;
        taskbar.menuOpen = true;
    }
    function closeMenu() {
        taskbar.menuOpen = false;
        taskbar.menuGroup = null;
        taskbar.menuAnchor = null;
    }

    // ── bar ────────────────────────────────────────────────────
    GlassPanel {
        id: rail
        anchors.fill: parent
        radius: 0
        level: 3
        baseColor: Theme.barBase
        wash: false
        sheen: false
        rim: false
        clipContent: true
        opacity: taskbar.enter
        transform: Translate { y: 20 * (1 - taskbar.enter) }

        // Frosted-glass stack (over the compositor blur): cool-to-crimson
        // depth tint, an upper specular band, a soft inner glow along the
        // top, and a darker floor so the tiles carry the contrast.
        Rectangle {
            anchors.fill: parent
            z: 0
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Qt.rgba(0.34, 0.050, 0.085, 0.30) }
                GradientStop { position: 0.20; color: Qt.rgba(0.12, 0.036, 0.056, 0.22) }
                GradientStop { position: 0.60; color: Qt.rgba(0.035, 0.024, 0.036, 0.24) }
                GradientStop { position: 1.0; color: Qt.rgba(0.010, 0.012, 0.019, 0.38) }
            }
        }
        Rectangle {   // upper specular band — the "wet glass" highlight
            anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 1 }
            height: parent.height * 0.42
            z: 0
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.06) }
                GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.018) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
        Rectangle {   // long diagonal sheen drifting across the whole bar
            id: sheenBand
            z: 0
            anchors { top: parent.top; bottom: parent.bottom }
            width: 220
            rotation: 18
            opacity: 0.5
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.045) }
                GradientStop { position: 1.0; color: "transparent" }
            }
            SequentialAnimation on x {
                loops: Animation.Infinite
                running: taskbar.visible
                PauseAnimation { duration: 3500 }
                NumberAnimation { from: -260; to: rail.width + 60; duration: 5200; easing.type: Easing.InOutSine }
            }
        }
        Rectangle {   // bottom machined edge
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 1
            z: 0
            color: Qt.rgba(0, 0, 0, 0.55)
        }

        // Animated red / green / blue light filling the whole taskbar (the
        // same light as the dock and the top bar, components/RgbFlow.qml);
        // flashes brighter when windows open/close. z 0 + declared before the
        // launcher and task buttons: the light runs beneath every control.
        RgbFlow {
            id: edgeGlow
            z: 0
            anchors.fill: parent
            horizontal: true
            radius: 0
            amplitude: 1.15
            status: AgentState.status
            hovered: launcherBtn.hovered
        }

        // A low-contrast luminous trough visually groups the live window
        // buttons without hiding their individual focus/minimized states.
        // It sits behind the Flickable, so overflow and all pointer handling
        // remain exactly as before.
        Rectangle {
            id: taskBed
            z: 0.5
            anchors {
                left: parent.left; leftMargin: 8 + 1 + 8 + rail.chipSize
                right: deskBtn.left; rightMargin: 8
                verticalCenter: parent.verticalCenter
            }
            height: 42
            radius: 16
            color: Qt.rgba(0.018, 0.012, 0.020, 0.24)
            border.width: 1
            border.color: Qt.rgba(1, 0.55, 0.62, 0.075)
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(1, 0.42, 0.53, 0.035) }
                GradientStop { position: 0.48; color: Qt.rgba(1, 1, 1, 0.018) }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.085) }
            }
            Rectangle {
                anchors { top: parent.top; left: parent.left; right: parent.right; margins: 12 }
                height: 1
                radius: 1
                color: Qt.rgba(1, 1, 1, 0.075)
            }
        }

        // Fine top-edge reflection: a quiet glass meniscus, not a pulsing
        // laser line competing with the open-window indicators.
        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right }
            height: 1
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.18; color: Qt.rgba(1, 1, 1, 0.08) }
                GradientStop { position: 0.50; color: Qt.rgba(1, 0.88, 0.91, 0.20) }
                GradientStop { position: 0.82; color: Qt.rgba(1, 1, 1, 0.08) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // Chip size shared by the launcher and the task-button row, so
        // resizing one is a one-line change instead of hunting matching
        // magic numbers across the file.
        readonly property int chipSize: 44

        // launcher — the one explicit ask: opens the same application
        // drawer every other surface opens, not a second competing one.
        Rectangle {
            id: launcherBtn
            property bool hovered: launcherMa.containsMouse
            anchors { left: parent.left; leftMargin: 8; verticalCenter: parent.verticalCenter }
            width: rail.chipSize
            height: rail.chipSize
            radius: 13
            // dark glass, like the task tabs and dock tiles, so the logo's
            // light has contrast over the bar's animated background
            color: Qt.rgba(0.02, 0.022, 0.032, AgentState.launcherOpen ? 0.72 : 0.58)
            border.width: 1
            border.color: AgentState.launcherOpen ? Theme.alpha(Theme.crimsonText, 0.62)
                         : launcherMa.containsMouse ? Qt.rgba(1, 1, 1, 0.24)
                         : Qt.rgba(1, 1, 1, 0.10)
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
            scale: launcherMa.pressed ? 0.90 : (launcherMa.containsMouse ? 1.06 : 1)
            Behavior on scale { NumberAnimation { duration: 170; easing.type: Easing.OutBack } }

            // soft glow around the chip while hovered / open (a blurred ring,
            // so the glass does not fill with colour)
            Item {
                anchors.fill: parent
                anchors.margins: -4
                z: -1
                opacity: AgentState.launcherOpen ? 1 : (launcherMa.containsMouse ? 0.7 : 0)
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: 220 } }
                layer.enabled: visible
                layer.effect: MultiEffect { blurEnabled: true; blur: 0.7; blurMax: 16 }
                Rectangle {
                    anchors.fill: parent
                    radius: launcherBtn.radius + 4
                    color: "transparent"
                    border.width: 4
                    border.color: Theme.alpha(Theme.crimsonText, 0.5)
                }
            }
            // glass body: lit from above, deeper at the foot
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, launcherMa.containsMouse ? 0.12 : 0.07) }
                    GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.02) }
                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.18) }
                }
            }
            Rectangle {   // top specular line
                anchors { top: parent.top; topMargin: 1; left: parent.left; right: parent.right; leftMargin: 8; rightMargin: 8 }
                height: 1
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, launcherMa.containsMouse || AgentState.launcherOpen ? 0.40 : 0.20) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }
            KinetixMark {
                id: launcherGlyph
                anchors.centerIn: parent
                size: 38
                hovered: launcherMa.containsMouse
                active: AgentState.launcherOpen
                pressed: launcherMa.pressed
            }
            Accessible.role: Accessible.Button
            Accessible.name: "Open applications"
            activeFocusOnTab: true
            Keys.onReturnPressed: function(event) { AgentState.toggleLauncher(); event.accepted = true; }
            Keys.onSpacePressed: function(event) { AgentState.toggleLauncher(); event.accepted = true; }
            MouseArea {
                id: launcherMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: AgentState.toggleLauncher()
            }
        }

        // separator
        Rectangle {
            anchors { left: launcherBtn.right; leftMargin: 8; verticalCenter: parent.verticalCenter }
            width: 1
            height: 30
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.5; color: Theme.alpha(Theme.crimson, 0.45) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // tasks — horizontal, scrolls if they overflow the bar. Anchored
        // directly between the separator and the show-desktop button
        // (rather than a Row sized by subtracting hardcoded sibling
        // widths) so this stays correct if either neighbor's size ever
        // changes.
        Flickable {
            id: taskScroll
            z: 1
            anchors {
                left: parent.left; leftMargin: 8 + 1 + 8 + rail.chipSize
                right: deskBtn.left; rightMargin: 8
                verticalCenter: parent.verticalCenter
            }
            // A few px taller than the chips themselves: this is a clipped
            // Flickable, and a hover-scaled chip (1.05x) plus its outer
            // active-bloom margin needs a little headroom to not be cropped.
            height: rail.chipSize + 12
            contentWidth: taskRow.implicitWidth
            contentHeight: height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.HorizontalFlick

            Row {
                id: taskRow
                height: parent.height
                spacing: 6
                // Tiles animate in/out now that the Repeater is backed by
                // a real ListModel (taskModel) instead of a reassigned
                // plain array — see the comment on taskModel above for why
                // that's what makes these transitions meaningful at all
                // (a plain-array rebuild looks the same as remove-all +
                // add-all every single time, whether or not anything
                // actually changed).
                // Row/Column positioners don't support a `remove` transition
                // at all (confirmed live: "Cannot assign to non-existent
                // property remove" — unlike ListView/GridView, a plain
                // positioner has nowhere to keep a departed item visible
                // while it animates out, since it's not a delegate-recycling
                // view). TaskButton's own removal is instant; add/move cover
                // what a positioner actually can animate.
                add: Transition {
                    NumberAnimation { properties: "opacity"; from: 0; to: 1; duration: Theme.durMed; easing.type: Easing.OutQuint }
                    NumberAnimation { properties: "scale"; from: 0.7; to: 1; duration: Theme.durMed; easing.type: Easing.OutBack }
                }
                move: Transition {
                    NumberAnimation { properties: "x"; duration: Theme.durMed; easing.type: Easing.OutQuint }
                }
                Repeater {
                    id: taskRep
                    model: taskModel
                    delegate: TaskButton {
                        id: taskDelegate
                        required property string key
                        required property string appId
                        required property string name
                        required property string icon
                        required property string itemsJson
                        required property int index
                        anchors.verticalCenter: parent.verticalCenter
                        anchorWindow: taskbar
                        group: ({ "key": key, "appId": appId, "name": name, "icon": icon, "items": JSON.parse(itemsJson) })
                        onHovered: function(g) { taskbar.onTaskHovered(g, taskDelegate); }
                        onUnhovered: taskbar.onTaskUnhovered()
                        onRequestMenu: function(g) { taskbar.openMenu(g, taskDelegate); }
                        onLeftClicked: function(g) { taskbar.handleLeftClick(g); }
                        onMiddleClicked: function(g) { taskbar.handleMiddleClick(g); }
                    }
                }
            }

            // empty state
            Text {
                visible: taskRep.count === 0
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                text: "No windows open"
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 0.6 }
            }
        }

        // show desktop — far right
        Rectangle {
            id: deskBtn
            z: 1
            property bool hovered: deskMa.containsMouse
            anchors { right: parent.right; verticalCenter: parent.verticalCenter; rightMargin: 10 }
            width: 40
            height: rail.chipSize
            radius: 8
            color: deskMa.containsMouse ? Theme.alpha(Theme.crimson, 0.16) : "transparent"
            border.width: 1
            border.color: deskMa.containsMouse ? Theme.alpha(Theme.crimson, 0.45) : Theme.alpha(Theme.crimson, 0.18)
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            Canvas {
                id: desktopGlyph
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -1
                width: 17
                height: 17
                antialiasing: true

                onPaint: {
                    var ctx = getContext("2d");
                    ctx.reset();
                    ctx.strokeStyle = deskMa.containsMouse ? Theme.text : Theme.textDim;
                    ctx.lineWidth = 1.25;
                    ctx.lineJoin = "round";
                    ctx.strokeRect(2.0, 2.0, 13.0, 9.5);
                    ctx.beginPath();
                    ctx.moveTo(6.5, 14.2);
                    ctx.lineTo(10.5, 14.2);
                    ctx.moveTo(8.5, 11.8);
                    ctx.lineTo(8.5, 14.2);
                    ctx.stroke();
                }

                Connections {
                    target: deskMa
                    function onContainsMouseChanged() { desktopGlyph.requestPaint(); }
                }
            }
            Rectangle {
                visible: taskbar.appWindowCount > 0
                anchors { top: parent.top; right: parent.right; topMargin: 4; rightMargin: 4 }
                width: 13
                height: 13
                radius: 6.5
                color: Theme.alpha(Theme.crimson, 0.90)
                border.width: 1
                border.color: Theme.alpha(Theme.crimsonText, 0.62)
                Text {
                    anchors.centerIn: parent
                    text: taskbar.appWindowCount > 99 ? "99+" : taskbar.appWindowCount
                    color: Theme.text
                    font { family: Theme.fontMono; pixelSize: 7; weight: Font.Bold }
                }
            }
            Accessible.role: Accessible.Button
            Accessible.name: "Show desktop"
            activeFocusOnTab: true
            Keys.onReturnPressed: function(event) { taskbar.toggleShowDesktop(); event.accepted = true; }
            Keys.onSpacePressed: function(event) { taskbar.toggleShowDesktop(); event.accepted = true; }
            MouseArea {
                id: deskMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: taskbar.toggleShowDesktop()
            }
        }
    }

    // ── show-desktop button tooltip ────────────────────────────
    // Same built-in-ToolTip-under-wlr-layer-shell issue and fix as the
    // launcher tooltip below.
    Timer {
        id: deskTipDelay
        interval: 500
        onTriggered: deskTip.shown = true
    }
    Connections {
        target: deskMa
        function onContainsMouseChanged() {
            if (deskMa.containsMouse) {
                deskTipDelay.restart();
            } else {
                deskTipDelay.stop();
                deskTip.shown = false;
            }
        }
    }
    PopupWindow {
        id: deskTip
        property bool shown: false
        anchor.window: taskbar
        anchor.item: deskBtn
        anchor.edges: Edges.Top
        anchor.gravity: Edges.Top
        anchor.adjustment: PopupAdjustment.Slide
        anchor.margins.bottom: 6
        visible: shown
        color: "transparent"
        implicitWidth: deskTipText.implicitWidth + 16
        implicitHeight: deskTipText.implicitHeight + 10

        Rectangle {
            anchors.fill: parent
            radius: Theme.rS
            color: Theme.glassBaseHigh
            border.width: 1
            border.color: Theme.alpha(Theme.crimsonText, 0.35)

            Text {
                id: deskTipText
                anchors.centerIn: parent
                text: "Show desktop (minimize / restore all)"
                color: Theme.text
                font { family: Theme.fontMono; pixelSize: Theme.tMicro }
            }
        }
    }

    // ── launcher button tooltip ───────────────────────────────
    // A real PopupWindow (same pattern as previewPop/menuPop below), not
    // the built-in QtQuick.Controls ToolTip attached property that used to
    // be here. That one is a Popup expecting a normal top-level window to
    // position itself against; anchored inside this PanelWindow's own
    // wlr-layer-shell surface instead, it rendered on top of the button
    // itself and ate the click meant for it (confirmed: hovering to read
    // the "Applications" label made the button unclickable). Anchoring
    // explicitly above the button via Edges.Top, like the rest of this
    // file's popups already do, keeps it clear of the clickable area.
    Timer {
        id: launcherTipDelay
        interval: 500
        onTriggered: launcherTip.shown = true
    }
    Connections {
        target: launcherMa
        function onContainsMouseChanged() {
            if (launcherMa.containsMouse) {
                launcherTipDelay.restart();
            } else {
                launcherTipDelay.stop();
                launcherTip.shown = false;
            }
        }
    }
    PopupWindow {
        id: launcherTip
        property bool shown: false
        anchor.window: taskbar
        anchor.item: launcherBtn
        anchor.edges: Edges.Top
        anchor.gravity: Edges.Top
        anchor.adjustment: PopupAdjustment.Slide
        anchor.margins.bottom: 6
        visible: shown
        color: "transparent"
        implicitWidth: launcherTipText.implicitWidth + 16
        implicitHeight: launcherTipText.implicitHeight + 10

        Rectangle {
            anchors.fill: parent
            radius: Theme.rS
            color: Theme.glassBaseHigh
            border.width: 1
            border.color: Theme.alpha(Theme.crimsonText, 0.35)

            Text {
                id: launcherTipText
                anchors.centerIn: parent
                text: "Applications"
                color: Theme.text
                font { family: Theme.fontMono; pixelSize: Theme.tMicro }
            }
        }
    }

    // ── hover preview popup (opens upward, above the bar) ───────
    PopupWindow {
        id: previewPop
        anchor.window: taskbar
        anchor.item: taskbar.previewAnchor
        anchor.edges: Edges.Top
        anchor.gravity: Edges.Top
        anchor.adjustment: PopupAdjustment.Slide
        visible: taskbar.previewOpen && taskbar.previewAnchor && taskbar.previewGroup
        color: "transparent"

        TaskPreview {
            id: previewCard
            group: taskbar.previewGroup
            popupWindow: previewPop
            open: previewPop.visible
            onFocusWindow: function(tl) { TaskStore.activate(tl); taskbar.hidePreviewNow(); }
            onMinimizeWindow: function(tl) { TaskStore.setMinimized(tl, true); }
            onCloseWindow: function(tl) {
                TaskStore.requestClose(tl);
                // If that was the last window, drop the card at once.
                if (taskbar.previewGroup && taskbar.previewGroup.items.length <= 1)
                    taskbar.hidePreviewNow();
            }
            onDismiss: taskbar.hidePreviewNow()
        }
    }

    // ── right-click window menu (opens upward, above the bar) ───
    PopupWindow {
        id: menuPop
        anchor.window: taskbar
        anchor.item: taskbar.menuAnchor
        anchor.edges: Edges.Top
        anchor.gravity: Edges.Top
        anchor.adjustment: PopupAdjustment.Slide
        visible: taskbar.menuOpen && taskbar.menuAnchor && taskbar.menuGroup
        color: "transparent"
        onVisibleChanged: if (!visible && taskbar.menuOpen) taskbar.closeMenu()

        GlassPanel {
            width: 264
            height: menuCol.implicitHeight + Theme.s3 * 2
            radius: Theme.rL
            level: 3
            baseColor: Theme.glassBaseHigh
            tinted: true
            tint: Theme.crimson

            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
            }

            Column {
                id: menuCol
                anchors { top: parent.top; left: parent.left; right: parent.right; margins: Theme.s3 }
                spacing: 4

                Text {
                    text: taskbar.menuGroup ? taskbar.menuGroup.name.toUpperCase() : ""
                    color: Theme.text
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.2; weight: Font.DemiBold }
                    elide: Text.ElideRight
                    width: parent.width
                }
                Text {
                    visible: taskbar.menuGroup && taskbar.menuGroup.items.length > 1
                    text: taskbar.menuGroup ? taskbar.menuGroup.items.length + " WINDOWS" : ""
                    color: Theme.textFaint
                    font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1 }
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: Theme.stroke
                }

                // per-window rows with individual close
                Repeater {
                    model: taskbar.menuGroup ? taskbar.menuGroup.items : []
                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        readonly property var tl: modelData
                        width: menuCol.width
                        height: 30
                        radius: 8
                        color: rowMa.containsMouse ? Theme.alpha(Theme.crimson, 0.14) : "transparent"
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        Row {
                            anchors { left: parent.left; leftMargin: 8; right: rowX.left; rightMargin: 4; verticalCenter: parent.verticalCenter }
                            spacing: 6
                            Rectangle {
                                width: 6
                                height: 6
                                radius: 3
                                anchors.verticalCenter: parent.verticalCenter
                                color: {
                                    try { return parent.parent.tl.active ? Theme.crimsonText : Theme.textFaint; }
                                    catch (e) { return Theme.textFaint; }
                                }
                            }
                            Text {
                                width: parent.width - 12
                                text: { try { return parent.parent.tl.title || "Untitled"; } catch (e2) { return "Untitled"; } }
                                color: rowMa.containsMouse ? Theme.text : Theme.textDim
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                                elide: Text.ElideRight
                            }
                        }
                        Text {
                            id: rowX
                            anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                            text: "✕"
                            color: xMa.containsMouse ? Theme.danger : Theme.textFaint
                            font.pixelSize: 11
                            font.weight: Font.Bold
                            MouseArea {
                                id: xMa
                                anchors.fill: parent
                                anchors.margins: -6
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: function(mouse) {
                                    mouse.accepted = true;
                                    TaskStore.requestClose(parent.parent.tl);
                                    if (taskbar.menuGroup && taskbar.menuGroup.items.length <= 1)
                                        taskbar.closeMenu();
                                }
                            }
                        }
                        MouseArea {
                            id: rowMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                TaskStore.activate(parent.tl);
                                taskbar.closeMenu();
                            }
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: Theme.stroke
                }

                // footer verbs
                Row {
                    width: parent.width
                    spacing: 6
                    Repeater {
                        model: ["FOCUS", "MINIMIZE", "CLOSE ALL"]
                        delegate: Rectangle {
                            required property string modelData
                            implicitWidth: (menuCol.width - 12) / 3
                            implicitHeight: 26
                            radius: 8
                            color: verbMa.containsMouse ? (modelData === "CLOSE ALL" ? Theme.alpha(Theme.danger, 0.20) : Theme.alpha(Theme.crimson, 0.22)) : Theme.surfaceLow
                            border.width: 1
                            border.color: verbMa.containsMouse ? (modelData === "CLOSE ALL" ? Theme.alpha(Theme.danger, 0.5) : Theme.alpha(Theme.crimsonText, 0.5)) : Theme.stroke
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Text {
                                anchors.centerIn: parent
                                text: parent.modelData
                                color: verbMa.containsMouse ? (parent.modelData === "CLOSE ALL" ? Theme.danger : Theme.text) : Theme.textDim
                                font { family: Theme.fontMono; pixelSize: 9; weight: Font.Bold; letterSpacing: 0.6 }
                            }
                            MouseArea {
                                id: verbMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    var g = taskbar.menuGroup;
                                    if (!g) { taskbar.closeMenu(); return; }
                                    if (parent.modelData === "FOCUS") TaskStore.activate(taskbar.mostRecent(g));
                                    else if (parent.modelData === "MINIMIZE") {
                                        for (var i = 0; i < g.items.length; i++)
                                            TaskStore.setMinimized(g.items[i], true);
                                    } else {
                                        for (var j = 0; j < g.items.length; j++)
                                            TaskStore.requestClose(g.items[j]);
                                    }
                                    taskbar.closeMenu();
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Clicking anywhere else dismisses the menu.
    MouseArea {
        anchors.fill: parent
        visible: taskbar.menuOpen
        z: -1
        onClicked: taskbar.closeMenu()
    }
}
