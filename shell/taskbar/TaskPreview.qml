import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import "../common"
import "../components"

// Hover preview for one app group: glass card with a live thumbnail per
// window. Thumbnails are captured on demand by kinetix-tasks.py via
// spectacle, cached until the window geometry changes, and restored to the
// previous focus after capture so hovering the taskbar does not steal the
// active window.
Item {
    id: root

    property var group: null
    // This preview is itself rendered inside a PopupWindow. Anchor nested
    // tooltips to that Quickshell window, not Window.window's proxied QWindow.
    property var popupWindow: null
    property bool open: false
    property bool hovered: previewHover.hovered || listHover.hovered

    signal focusWindow(var toplevel)
    signal minimizeWindow(var toplevel)
    signal closeWindow(var toplevel)
    signal dismiss()

    implicitWidth: 304
    implicitHeight: card.height

    opacity: open ? 1 : 0
    scale: open ? 1 : 0.94
    transform: Translate { x: open ? 0 : -10 }
    visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
    Behavior on scale { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

    // Thumbnail source cache keyed by uuid + geometry + minimized state.
    // Populated asynchronously by TaskRunner.capture requests.
    property var thumbSources: ({})

    function captureKey(tl) {
        if (!tl) return "";
        return tl.uuid + "|" + (tl.x || 0) + "," + (tl.y || 0) + "," + (tl.w || 0) + "," + (tl.h || 0) + "|" + (tl.minimized ? 1 : 0);
    }

    function refreshThumbnails() {
        if (!root.group || !root.group.items) return;
        for (var i = 0; i < root.group.items.length; i++) {
            var tl = root.group.items[i];
            var key = captureKey(tl);
            if (!key) continue;
            if (!root.thumbSources[key]) {
                // TaskRunner keeps its own cache for the life of the session
                // (see its comment) — reuse it here so a window already
                // thumbnailed earlier never gets captured, and re-focused,
                // again just because it's being hovered again.
                var cached = TaskRunner.cachedThumbnail(tl.uuid, tl.x, tl.y, tl.w, tl.h);
                if (cached) root.thumbSources[key] = cached;
                else TaskRunner.captureThumbnail(tl.uuid, tl.x, tl.y, tl.w, tl.h);
            }
        }
    }

    // Not reset to {} here: this used to wipe every cached thumbnail on
    // every hovered-group change, so simply moving the mouse across the
    // taskbar forced a fresh capture (two real focus switches — activate
    // the target, then restore) for every window, every time. Entries are
    // still keyed by geometry+minimized, so a moved/resized/minimized
    // window naturally gets a fresh capture on its own.
    onGroupChanged: refreshThumbnails()
    onOpenChanged: if (open) refreshThumbnails()

    Connections {
        target: TaskRunner
        function onThumbnailReady(uuid, path) {
            if (!root.group || !root.group.items) return;
            for (var i = 0; i < root.group.items.length; i++) {
                var tl = root.group.items[i];
                if (tl.uuid === uuid) {
                    var key = captureKey(tl);
                    if (key) root.thumbSources[key] = "file://" + path;
                    return;
                }
            }
        }
    }

    GlassPanel {
        id: card
        width: 304
        // height driven by content column
        height: contentCol.implicitHeight + Theme.s3 * 2
        radius: Theme.rL
        level: 3
        baseColor: Theme.glassBaseHigh
        tinted: true
        tint: Theme.crimson

        // crimson top crest
        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right; topMargin: 1; leftMargin: 18; rightMargin: 18 }
            height: 1
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.5; color: Theme.alpha(Theme.crimsonText, 0.55) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        Column {
            id: contentCol
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: Theme.s3 }
            spacing: Theme.s2

            // ── header: app icon + name + count + dismiss ──
            Row {
                width: parent.width
                spacing: Theme.s2

                IconImage {
                    implicitSize: 22
                    source: root.group ? root.group.icon : ""
                    visible: (root.group ? root.group.icon : "") !== ""
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    visible: (root.group ? root.group.icon : "") === ""
                    text: root.group ? root.group.name.charAt(0).toUpperCase() : "?"
                    color: Theme.textDim
                    font { family: Theme.fontUi; pixelSize: 14; weight: Font.Bold }
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    width: Math.max(0, parent.width - x - dismissBtn.width - Theme.s2)
                    text: (root.group ? root.group.name.toUpperCase() : "") + ((root.group && root.group.items.length > 1) ? "  ·  " + root.group.items.length + " WINDOWS" : "")
                    color: Theme.text
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.1; weight: Font.DemiBold }
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                }
                CloseButton {
                    id: dismissBtn
                    box: 22
                    tip: "Hide preview"
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: root.dismiss()
                }
            }

            // ── window cards ──
            Repeater {
                id: winRep
                model: root.group ? root.group.items : []
                delegate: Item {
                    id: winCard
                    required property var modelData
                    required property int index
                    width: contentCol.width
                    height: 196

                    readonly property var tl: modelData
                    readonly property bool focused: tl && tl.active
                    readonly property bool mini: tl && tl.minimized
                    readonly property bool maxed: tl && tl.maximized && !mini
                    readonly property string thumbKey: root.captureKey(tl)
                    readonly property string thumbSource: thumbKey && root.thumbSources[thumbKey] ? root.thumbSources[thumbKey] : ""

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.rM
                        color: cardMa.containsMouse ? Theme.alpha(Theme.crimson, 0.14) : Theme.surfaceLow
                        border.width: 1
                        border.color: winCard.focused ? Theme.alpha(Theme.crimsonText, 0.55)
                                      : cardMa.containsMouse ? Theme.alpha(Theme.crimson, 0.40)
                                      : Theme.stroke
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                        Column {
                            anchors { fill: parent; margins: 8 }
                            spacing: 6

                            // title row + state + close
                            Row {
                                width: parent.width
                                spacing: 6
                                Text {
                                    width: parent.width - statePill.width - winClose.width - 12
                                    text: winCard.tl ? winCard.tl.title : ""
                                    color: cardMa.containsMouse ? Theme.text : Theme.textDim
                                    font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.Medium }
                                    elide: Text.ElideRight
                                    maximumLineCount: 1
                                    anchors.verticalCenter: parent.verticalCenter
                                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                }
                                Rectangle {
                                    id: statePill
                                    implicitWidth: stateText.implicitWidth + 10
                                    implicitHeight: 16
                                    radius: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: winCard.mini ? Theme.alpha(Theme.warn, 0.16)
                                           : winCard.maxed ? Theme.alpha(Theme.gilded, 0.20)
                                           : winCard.focused ? Theme.alpha(Theme.crimson, 0.30)
                                           : Theme.surfaceHigh
                                    border.width: 1
                                    border.color: winCard.maxed ? Theme.alpha(Theme.gilded, 0.55)
                                                  : winCard.focused ? Theme.alpha(Theme.crimsonText, 0.5)
                                                  : Theme.stroke
                                    Text {
                                        id: stateText
                                        anchors.centerIn: parent
                                        text: winCard.mini ? "MINIMIZED"
                                              : winCard.maxed ? "MAXIMIZED"
                                              : winCard.focused ? "FOCUSED" : "OPEN"
                                        color: winCard.maxed ? Theme.gilded
                                               : winCard.focused ? Theme.crimsonText : Theme.textDim
                                        font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 0.8; weight: Font.Bold }
                                    }
                                }
                                // per-window close — the requested control
                                Rectangle {
                                    id: winClose
                                    width: 20
                                    height: 20
                                    radius: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: closeMa.containsMouse ? Theme.alpha(Theme.danger, 0.30) : Theme.surfaceHigh
                                    border.width: 1
                                    border.color: closeMa.containsMouse ? Theme.alpha(Theme.danger, 0.6) : Theme.stroke
                                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: "✕"
                                        color: closeMa.containsMouse ? Theme.danger : Theme.textDim
                                        font.pixelSize: 10
                                        font.weight: Font.Bold
                                    }
                                    // Real Quickshell PopupWindow, not the
                                    // built-in ToolTip — same layer-shell/
                                    // popup-surface click-eating issue as
                                    // everywhere else this pattern has
                                    // been fixed (see TaskButton.qml).
                                    Timer {
                                        id: winCloseTipDelay
                                        interval: 400
                                        onTriggered: winCloseTip.shown = true
                                    }
                                    Connections {
                                        target: closeMa
                                        function onContainsMouseChanged() {
                                            if (closeMa.containsMouse) {
                                                winCloseTipDelay.restart();
                                            } else {
                                                winCloseTipDelay.stop();
                                                winCloseTip.shown = false;
                                            }
                                        }
                                    }
                                    PopupWindow {
                                        id: winCloseTip
                                        property bool shown: false
                                        anchor.window: root.popupWindow
                                        anchor.item: winClose
                                        anchor.edges: Edges.Top
                                        anchor.gravity: Edges.Top
                                        anchor.adjustment: PopupAdjustment.Slide
                                        anchor.margins.bottom: 6
                                        visible: shown && root.popupWindow !== null
                                        color: "transparent"
                                        implicitWidth: winCloseTipText.implicitWidth + 16
                                        implicitHeight: winCloseTipText.implicitHeight + 10

                                        Rectangle {
                                            anchors.fill: parent
                                            radius: Theme.rS
                                            color: Theme.glassBaseHigh
                                            border.width: 1
                                            border.color: Theme.alpha(Theme.crimsonText, 0.35)

                                            Text {
                                                id: winCloseTipText
                                                anchors.centerIn: parent
                                                text: "Close window"
                                                color: Theme.text
                                                font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                                            }
                                        }
                                    }
                                    MouseArea {
                                        id: closeMa
                                        anchors.fill: parent
                                        anchors.margins: -3
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: function(mouse) { mouse.accepted = true; root.closeWindow(winCard.tl); }
                                    }
                                }
                            }

                            // Live thumbnail. Spectacle can only capture the
                            // active window, so kinetix-tasks.py briefly
                            // activates the target, captures it, then restores
                            // the previous focus. The result is cached per
                            // uuid+geometry and refreshed on open/geometry
                            // change. Minimized windows show a desaturated
                            // placeholder.
                            Rectangle {
                                width: parent.width
                                height: 128
                                radius: Theme.rS
                                color: "#04050A"
                                clip: true
                                border.width: 1
                                border.color: Theme.alpha(Theme.crimson, 0.22)

                                Image {
                                    id: thumbImage
                                    anchors.fill: parent
                                    anchors.margins: 1
                                    source: winCard.thumbSource
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    mipmap: true
                                    opacity: status === Image.Ready ? (winCard.mini ? 0.55 : 0.95) : 0
                                    visible: winCard.thumbSource !== "" && status !== Image.Error
                                    Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
                                }

                                // Soft glow behind the icon / placeholder.
                                Rectangle {
                                    width: parent.width * 0.7
                                    height: parent.height * 0.9
                                    anchors.centerIn: parent
                                    radius: width / 2
                                    gradient: Gradient {
                                        GradientStop { position: 0.0; color: Theme.alpha(Theme.crimson, winCard.focused ? 0.20 : 0.10) }
                                        GradientStop { position: 1.0; color: "transparent" }
                                    }
                                    visible: winCard.thumbSource === "" || thumbImage.status !== Image.Ready
                                }

                                Column {
                                    anchors.centerIn: parent
                                    spacing: 8
                                    visible: winCard.thumbSource === "" || thumbImage.status !== Image.Ready
                                    IconImage {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        implicitSize: 52
                                        source: root.group ? root.group.icon : ""
                                        visible: (root.group ? root.group.icon : "") !== ""
                                        opacity: winCard.mini ? 0.55 : 0.95
                                        Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
                                    }
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        visible: (root.group ? root.group.icon : "") === ""
                                        text: root.group ? root.group.name.charAt(0).toUpperCase() : "?"
                                        color: Theme.textFaint
                                        font { family: Theme.fontUi; pixelSize: 34; weight: Font.Bold }
                                    }
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: root.group ? root.group.appId.toUpperCase() : ""
                                        visible: text !== ""
                                        color: Theme.alpha(Theme.textFaint, 0.75)
                                        font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 1.6 }
                                    }
                                }

                                // faint scanlines: a deliberate "screen"
                                // texture cue, not an attempt at realism.
                                Column {
                                    anchors.fill: parent
                                    spacing: 3
                                    Repeater {
                                        model: Math.ceil(128 / 4)
                                        delegate: Rectangle {
                                            width: parent.width
                                            height: 1
                                            color: Qt.rgba(1, 1, 1, 0.02)
                                        }
                                    }
                                }

                                // top glass sheen, matching the rest of the shell's cards
                                Rectangle {
                                    anchors.fill: parent
                                    radius: parent.radius
                                    gradient: Gradient {
                                        orientation: Gradient.Vertical
                                        GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.06) }
                                        GradientStop { position: 0.35; color: "transparent" }
                                    }
                                }
                            }

                            // quick actions
                            Row {
                                width: parent.width
                                spacing: 6
                                Rectangle {
                                    implicitWidth: (parent.width - 12) / 3
                                    implicitHeight: 24
                                    radius: 8
                                    color: focusMa.containsMouse ? Theme.alpha(Theme.crimson, 0.28) : Theme.surfaceHigh
                                    border.width: 1
                                    border.color: focusMa.containsMouse ? Theme.alpha(Theme.crimsonText, 0.5) : Theme.stroke
                                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: winCard.mini ? "RESTORE" : (winCard.focused ? "MINIMIZE" : "FOCUS")
                                        color: focusMa.containsMouse ? Theme.text : Theme.textDim
                                        font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 0.8; weight: Font.Bold }
                                    }
                                    MouseArea {
                                        id: focusMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            if (winCard.mini || !winCard.focused) root.focusWindow(winCard.tl);
                                            else root.minimizeWindow(winCard.tl);
                                        }
                                    }
                                }
                                Rectangle {
                                    implicitWidth: (parent.width - 12) / 3
                                    implicitHeight: 24
                                    radius: 8
                                    color: maxMa.containsMouse ? Theme.alpha(Theme.crimson, 0.20) : (winCard.tl && winCard.tl.maximized ? Theme.alpha(Theme.crimson, 0.14) : "transparent")
                                    border.width: 1
                                    border.color: maxMa.containsMouse ? Theme.alpha(Theme.crimsonText, 0.5) : Theme.stroke
                                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: winCard.tl && winCard.tl.maximized ? "RESTORE" : "ZOOM"
                                        color: maxMa.containsMouse ? Theme.text : Theme.textDim
                                        font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 0.8; weight: Font.Bold }
                                    }
                                    MouseArea {
                                        id: maxMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        // toggleMaximize's own KWin script already
                                        // activates the window as part of the
                                        // toggle — no separate focusWindow needed.
                                        onClicked: TaskStore.toggleMaximize(winCard.tl)
                                    }
                                }
                                Rectangle {
                                    implicitWidth: (parent.width - 12) / 3
                                    implicitHeight: 24
                                    radius: 8
                                    color: killMa.containsMouse ? Theme.alpha(Theme.danger, 0.22) : "transparent"
                                    border.width: 1
                                    border.color: killMa.containsMouse ? Theme.alpha(Theme.danger, 0.5) : Theme.stroke
                                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: "CLOSE"
                                        color: killMa.containsMouse ? Theme.danger : Theme.textDim
                                        font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 0.8; weight: Font.Bold }
                                    }
                                    MouseArea {
                                        id: killMa
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: root.closeWindow(winCard.tl)
                                    }
                                }
                            }
                        }

                        MouseArea {
                            id: cardMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            acceptedButtons: Qt.LeftButton
                            // clicks on child buttons are accepted there first;
                            // a plain card click focuses.
                            onClicked: root.focusWindow(winCard.tl)
                        }
                    }
                }
            }

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: "CLICK FOCUS   ·   MIDDLE-CLICK TASK CLOSES   ·   RIGHT-CLICK MORE"
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: 8; letterSpacing: 0.9 }
            }
        }
    }

    HoverHandler { id: previewHover }
    // Covers the list area so moving from a task button into the preview
    // does not count as "leave" (Taskbar adds its own grace timer too).
    HoverHandler { id: listHover; target: card }
}
