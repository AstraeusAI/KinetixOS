import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import QtQuick.Effects
import "../common"
import "../components"

// One app-group tab in the taskbar's task row. Glass tab tinted with the
// app's own colour (sampled from its icon); the focused app's tab widens to
// show its name; per-window dots show open/focused/minimized windows;
// minimized apps desaturate; hover lifts, press sinks.
// Hover is reported upward so Taskbar can open the preview; all clicks are
// handled here (left toggle/cycle, middle close, right menu).
//
// Sized to match Taskbar.qml's `chipSize` (44) exactly — it used to be 52,
// left over from the old taller floating rail; the task row here is only
// 44 tall, so the mismatch silently clipped every icon top and bottom.
Item {
    id: root

    property var group: null          // { key, appId, name, icon, items:[TaskRunner window data] }
    property var anchorWindow: null   // owning Quickshell PanelWindow
    readonly property bool currentHovered: ma.containsMouse
    signal hovered(var group)
    signal unhovered()
    signal requestMenu(var group)
    signal leftClicked(var group)
    signal middleClicked(var group)

    // Collapsed: a 44px square. Focused: widens to fit the app name.
    readonly property bool expanded: isActive && title.length > 0
    implicitWidth: expanded ? Math.min(44 + Math.max(nameText.implicitWidth, subText.implicitWidth) + 14, 212) : 44
    implicitHeight: 44
    Behavior on implicitWidth { NumberAnimation { duration: 320; easing.type: Easing.OutQuint } }

    // Live state from TaskRunner's window data (re-evaluated whenever
    // Taskbar rebuilds `groups`, which happens on every TaskRunner push).
    readonly property bool isActive: {
        if (!group || !group.items) return false;
        for (var i = 0; i < group.items.length; i++) {
            if (group.items[i].active) return true;
        }
        return false;
    }
    readonly property bool isMinimized: {
        if (!group || !group.items || group.items.length === 0) return false;
        for (var j = 0; j < group.items.length; j++) {
            if (!group.items[j].minimized) return false;
        }
        return !isActive;
    }
    readonly property int winCount: group && group.items ? group.items.length : 0
    readonly property string title: group ? group.name : ""
    // caption of the focused window in this group (shown under the name)
    readonly property string activeCaption: {
        if (!group || !group.items) return "";
        for (var i = 0; i < group.items.length; i++) {
            var w = group.items[i];
            if (!w.active) continue;
            // drop a trailing " — App" / " - App" suffix: the name is already shown above
            var t = (w.title || "").replace(new RegExp("\\s+[\u2014\u2013-]\\s+" + title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "$", "i"), "");
            return t === title ? "" : t;
        }
        return "";
    }

    Accessible.role: Accessible.Button
    Accessible.name: title + (winCount > 1 ? " (" + winCount + " windows)" : "")
    activeFocusOnTab: true
    Keys.onReturnPressed: function(event) { root.leftClicked(root.group); event.accepted = true; }
    Keys.onSpacePressed: function(event) { root.leftClicked(root.group); event.accepted = true; }

    // A real Quickshell PopupWindow, not the built-in QtQuick.Controls
    // ToolTip — this tile lives inside Taskbar.qml's PanelWindow
    // (wlr-layer-shell), where that control renders on top of the tile
    // instead of above it and eats the click meant for it (this is the
    // app-name-tooltip-blocks-the-taskbar-icon report; same root cause
    // already fixed for IconButton/CloseButton and the launcher/desktop
    // buttons — see those components' own comments for the full story).
    Timer {
        id: tipDelay
        interval: 300
        onTriggered: tipPopup.shown = true
    }
    Connections {
        target: ma
        function onContainsMouseChanged() {
            if (ma.containsMouse && root.title.length > 0) {
                tipDelay.restart();
            } else {
                tipDelay.stop();
                tipPopup.shown = false;
            }
        }
    }
    PopupWindow {
        id: tipPopup
        property bool shown: false
        anchor.window: root.anchorWindow
        anchor.item: root
        anchor.edges: Edges.Top
        anchor.gravity: Edges.Top
        anchor.adjustment: PopupAdjustment.Slide
        anchor.margins.bottom: 6
        visible: shown && root.anchorWindow !== null
        color: "transparent"
        implicitWidth: tipText.implicitWidth + 16
        implicitHeight: tipText.implicitHeight + 10

        Rectangle {
            anchors.fill: parent
            radius: Theme.rS
            color: Theme.glassBaseHigh
            border.width: 1
            border.color: Theme.alpha(Theme.crimsonText, 0.35)

            Text {
                id: tipText
                anchors.centerIn: parent
                text: root.title
                color: Theme.text
                font { family: Theme.fontMono; pixelSize: Theme.tMicro }
            }
        }
    }

    // ── app accent colour ──────────────────────────────────────
    // The most vivid mid-lightness colour in the icon; falls back to the
    // Kinetix crimson for monochrome or unresolved icons.
    ColorQuantizer {
        id: quant
        source: root.group && root.group.icon ? root.group.icon : ""
        depth: 3
        rescaleSize: 48
    }
    readonly property color accentTarget: {
        var best = Theme.crimsonText, bestScore = 0.16;
        var cs = quant.colors || [];
        for (var i = 0; i < cs.length; i++) {
            var c = cs[i];
            var mx = Math.max(c.r, c.g, c.b), mn = Math.min(c.r, c.g, c.b);
            var l = (mx + mn) / 2;
            var sat = mx === mn ? 0 : (mx - mn) / (1 - Math.abs(2 * l - 1));
            var score = sat * (1 - Math.abs(l - 0.56) * 1.6);
            if (score > bestScore) { bestScore = score; best = c; }
        }
        // lift very dark accents so they still read as light on dark glass
        return Qt.hsla(best.hslHue, Math.min(1, best.hslSaturation * 1.05),
                       Math.max(0.52, Math.min(0.68, best.hslLightness)), 1);
    }
    property color accent: accentTarget
    Behavior on accent { ColorAnimation { duration: 400 } }

    readonly property bool hot: ma.containsMouse
    onHotChanged: if (hot) sheenAnim.restart()
    readonly property bool sunk: ma.pressed && (ma.pressedButtons & Qt.LeftButton)

    // everything visual rides on this so hover can lift it without the
    // MouseArea (and the preview anchor) moving under the pointer
    Item {
        id: face
        width: root.width
        height: root.height
        y: root.sunk ? 1 : (root.hot ? -2 : 0)
        scale: root.sunk ? 0.95 : 1.0
        Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutQuint } }
        Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutBack } }

        // depth: a soft contact shadow under every tab
        RectangularShadow {
            anchors.fill: tab
            radius: tab.radius
            offset.y: root.hot ? 3 : 2
            blur: root.hot ? 7 : 5
            spread: -1
            color: Qt.rgba(0, 0, 0, root.hot ? 0.30 : 0.20)
            Behavior on offset.y { NumberAnimation { duration: 220; easing.type: Easing.OutQuint } }
        }
        // ── glow, in the launcher logo's language (components/GlowRim) ──
        // focused: a turning red → green → blue glow; hover: the app's own
        // colour. Sits behind the glass; the crisp rim is drawn on top below.
        // A tight blur keeps it inside the task row's clip.
        GlowRim {
            anchors.fill: tab
            radius: tab.radius
            drawRim: false
            glowThickness: 5
            glowBlurMax: 12
            rgb: root.isActive
            color: root.accent
            glowOpacity: root.isActive ? 1.0 : (root.hot ? 0.75 : 0)
        }

        // ── glass tab ──
        Rectangle {
            id: tab
            anchors.fill: parent
            radius: 13
            antialiasing: true
            clip: true
            color: Theme.alpha(Theme.bg, 0.30)
            border.width: 0   // the rim is drawn by GlowRim

            // base glass body: lighter at the top, deeper at the foot
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, root.hot ? 0.10 : 0.060) }
                    GradientStop { position: 0.55; color: Qt.rgba(1, 1, 1, root.hot ? 0.035 : 0.018) }
                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.16) }
                }
            }
            // accent fill: rises from the foot of the tab, strongest when focused
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                opacity: root.isActive ? 1 : (root.hot ? 0.55 : 0)
                Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Theme.alpha(root.accent, 0.06) }
                    GradientStop { position: 0.65; color: Theme.alpha(root.accent, 0.13) }
                    GradientStop { position: 1.0; color: Theme.alpha(root.accent, 0.30) }
                }
            }
            // light pooling under the focused indicator
            Rectangle {
                anchors { bottom: parent.bottom; horizontalCenter: parent.left; horizontalCenterOffset: 22 }
                width: 40; height: 16
                radius: 8
                opacity: root.isActive ? 0.9 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 1.0; color: Theme.alpha(root.accent, 0.40) }
                }
            }
            // top specular hairline
            Rectangle {
                anchors { top: parent.top; topMargin: 1; left: parent.left; right: parent.right; leftMargin: 7; rightMargin: 7 }
                height: 1
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, root.isActive || root.hot ? 0.34 : 0.16) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }
            // inner foot shadow: gives the glass a thickness at its lower lip
            Rectangle {
                anchors { bottom: parent.bottom; bottomMargin: 1; left: parent.left; right: parent.right; leftMargin: 6; rightMargin: 6 }
                height: 1
                color: Qt.rgba(0, 0, 0, 0.28)
            }
            // hover sheen: one diagonal band of light sweeps across on entry
            Rectangle {
                id: sheen
                width: 26
                height: parent.height * 2
                y: -parent.height / 2
                x: -width * 2
                rotation: 22
                opacity: 0
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.16) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
                ParallelAnimation {
                    id: sheenAnim
                    NumberAnimation { target: sheen; property: "x"; from: -sheen.width * 2; to: tab.width + sheen.width; duration: 620; easing.type: Easing.InOutSine }
                    SequentialAnimation {
                        NumberAnimation { target: sheen; property: "opacity"; from: 0; to: 1; duration: 140 }
                        PauseAnimation { duration: 320 }
                        NumberAnimation { target: sheen; property: "opacity"; to: 0; duration: 160 }
                    }
                }
            }
        }

        // ── crisp rim + inner glass edge ──
        GlowRim {
            anchors.fill: tab
            radius: tab.radius
            drawGlow: false
            thickness: root.isActive ? 2.0 : 1.4
            rgb: root.isActive
            color: root.hot ? root.accent : Theme.alpha(root.accent, 0.9)
            rimOpacity: root.isActive ? 1.0 : (root.hot ? 0.85 : 0.40)
        }
        Rectangle {
            anchors.fill: tab
            anchors.margins: 2
            radius: tab.radius - 2
            color: "transparent"
            border.width: 0.8
            border.color: Qt.rgba(1, 1, 1, root.isActive || root.hot ? 0.24 : 0.10)
            Behavior on border.color { ColorAnimation { duration: 200 } }
        }

        // ── icon ──
        Item {
            id: iconSlot
            anchors { left: parent.left; verticalCenter: parent.verticalCenter; verticalCenterOffset: -2 }
            width: 44; height: 30

            // accent glow behind a focused icon
            Rectangle {
                anchors.centerIn: parent
                width: 30; height: 30; radius: 15
                color: Theme.alpha(root.accent, 0.16)
                opacity: root.isActive ? 1 : 0
                scale: root.isActive ? 1 : 0.6
                Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                Behavior on scale { NumberAnimation { duration: 320; easing.type: Easing.OutBack } }
            }
            IconImage {
                id: appIcon
                anchors.centerIn: parent
                implicitSize: 24
                source: root.group ? root.group.icon : ""
                asynchronous: true
                mipmap: true
                visible: false          // drawn through the effect below
            }
            MultiEffect {
                anchors.fill: appIcon
                source: appIcon
                visible: appIcon.source != ""
                saturation: root.isMinimized ? -0.85 : 0
                brightness: root.hot && !root.isMinimized ? 0.06 : 0
                opacity: root.isMinimized ? 0.55 : 1
                scale: root.hot ? 1.10 : 1.0
                shadowEnabled: true
                shadowColor: Qt.rgba(0, 0, 0, 0.55)
                shadowBlur: 0.45
                shadowVerticalOffset: 1.5
                Behavior on saturation { NumberAnimation { duration: Theme.durMed } }
                Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                Behavior on scale { NumberAnimation { duration: 240; easing.type: Easing.OutBack } }
            }
            // glyph fallback when no icon resolves
            Rectangle {
                anchors.centerIn: parent
                visible: (root.group ? root.group.icon : "") === ""
                width: 24; height: 24; radius: 7
                color: Theme.alpha(root.accent, 0.22)
                border.width: 1
                border.color: Theme.alpha(root.accent, 0.5)
                Text {
                    anchors.centerIn: parent
                    text: root.group ? root.group.name.charAt(0).toUpperCase() : "?"
                    color: Theme.text
                    font { family: Theme.fontUi; pixelSize: 13; weight: Font.Bold }
                }
            }
        }

        // ── app name + focused window caption (focused tab only) ──
        Column {
            anchors { left: iconSlot.right; leftMargin: -4; verticalCenter: parent.verticalCenter; verticalCenterOffset: -1 }
            width: Math.max(0, root.width - 44 - 10)
            spacing: 0
            opacity: root.expanded && root.width > 70 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 220 } }
            Text {
                id: nameText
                width: parent.width
                text: root.title
                elide: Text.ElideRight
                color: Theme.text
                font { family: Theme.fontUi; pixelSize: 12; weight: Font.DemiBold; letterSpacing: 0.2 }
            }
            Text {
                id: subText
                width: parent.width
                visible: text.length > 0
                text: root.activeCaption
                elide: Text.ElideRight
                color: Theme.alpha(Theme.text, 0.55)
                font { family: Theme.fontUi; pixelSize: 10 }
            }
        }

        // ── per-window indicators ──
        // One mark per window (up to 4): the focused window is a wide accent
        // pill, open windows are dots, minimized windows are hollow rings.
        Row {
            id: dots
            anchors { bottom: parent.bottom; bottomMargin: 3; horizontalCenter: iconSlot.horizontalCenter }
            spacing: 3
            Repeater {
                model: root.group && root.group.items ? root.group.items.slice(0, 4) : []
                Rectangle {
                    required property var modelData
                    readonly property bool focusedWin: !!modelData.active
                    readonly property bool minWin: !!modelData.minimized
                    anchors.verticalCenter: parent.verticalCenter
                    width: focusedWin ? 14 : 4
                    height: focusedWin ? 3 : 4
                    radius: height / 2
                    color: minWin ? "transparent"
                         : focusedWin ? root.accent
                         : Theme.alpha(root.accent, root.isActive ? 0.75 : 0.60)
                    border.width: minWin ? 1 : 0
                    border.color: Theme.alpha(Theme.textDim, 0.9)
                    Behavior on width { NumberAnimation { duration: 280; easing.type: Easing.OutQuint } }
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                    // bloom on the focused pill
                    Rectangle {
                        visible: parent.focusedWin
                        anchors.centerIn: parent
                        width: parent.width + 8; height: 7; radius: 3.5
                        z: -1
                        color: Theme.alpha(root.accent, 0.35)
                    }
                }
            }
        }

        // overflow count for groups with more than 4 windows
        Rectangle {
            anchors { top: parent.top; topMargin: 2; left: parent.left; leftMargin: 28 }
            implicitWidth: Math.max(15, countText.implicitWidth + 7)
            implicitHeight: 15
            radius: 7.5
            visible: root.winCount > 4
            color: Theme.alpha(root.accent, 0.9)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.35)
            Text {
                id: countText
                anchors.centerIn: parent
                text: root.winCount
                color: "white"
                font { family: Theme.fontMono; pixelSize: 9; weight: Font.Bold }
            }
        }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        anchors.margins: -2
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
        onEntered: root.hovered(root.group)
        onExited: root.unhovered()
        onClicked: function(mouse) {
            if (mouse.button === Qt.LeftButton) root.leftClicked(root.group);
            else if (mouse.button === Qt.MiddleButton) root.middleClicked(root.group);
            else if (mouse.button === Qt.RightButton) root.requestMenu(root.group);
        }
        onPressAndHold: root.requestMenu(root.group)
    }
}
