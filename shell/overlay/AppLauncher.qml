import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import "../common"
import "../components"

// Full application launcher: vignetted scrim, a large floating glass card lit
// along its top edge by the same Google-style light rail as the bars, a
// greeting header with the animated Kinetix mark, a glowing search field,
// category pills, favourite "hero" cards, and an icon grid whose tiles take
// on each app's own colour (sampled from its icon) on hover/selection.
// Keyboard navigation, pinning and the staggered entrance are unchanged.
//
// Presentation notes (distro/tests/test_app_launcher_presentation.py
// contracts these): the card body is launcher-scoped and nearly opaque so
// the terminal windows behind it stop bleeding through; section headers
// finish in a rule that fills the unused width instead of leaving dead
// space; the category row and the app grid both carry scroll affordances;
// grid tiles are dark glass (Theme.alpha REPLACES the alpha channel, so
// the old alpha(surfaceLow, 0.34) was a 34% white slab, not a 4.5% wash);
// labels reserve two lines so icons stay aligned across a row; and the
// entrance stagger is per-cell rather than one shared opacity ramp.
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.namespace: "argus:launcher"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: AgentState.launcherOpen
                                 ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    visible: AgentState.launcherOpen

    property string query: ""
    property string cat: "All"
    readonly property int gridColumns: card.width < 700 ? 4 : card.width < 860 ? 5 : card.width < 1000 ? 6 : 7

    // Launcher-scoped body color: one source for the GlassPanel base and
    // for the category-row edge fades, so a fade can never be a visibly
    // different band. More opaque than Theme.glassBase (0.74) because this
    // surface sits directly over live terminal windows.
    function cardTint(a) { return Qt.rgba(0.043, 0.046, 0.064, a); }
    readonly property color cardBase: cardTint(0.95)

    // Greeting for the header, by local time of day.
    property date now: new Date()
    Timer { interval: 30000; running: win.visible; repeat: true; onTriggered: win.now = new Date() }
    readonly property string greeting: {
        var h = now.getHours();
        return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
    }

    // Section header rule: label cluster on the left, this hairline fills
    // the remaining width. Used by FAVORITES and the app-grid header.
    component SectionRule: Rectangle {
        height: 1
        radius: 1
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: Theme.alpha(Theme.crimson, 0.40) }
            GradientStop { position: 0.35; color: Theme.alpha(Theme.text, 0.07) }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    // Small section title: bold label, dot, faint sub-label.
    component SectionLabel: Row {
        property string title
        property string sub
        spacing: Theme.s2
        Text {
            text: parent.title
            color: Theme.alpha(Theme.text, 0.62)
            font { family: Theme.fontUi; pixelSize: 11; letterSpacing: 1.6; weight: Font.Bold }
            anchors.verticalCenter: parent.verticalCenter
        }
        Rectangle { width: 3; height: 3; radius: 2; color: Theme.alpha(Theme.crimsonText, 0.8); anchors.verticalCenter: parent.verticalCenter }
        Text {
            text: parent.sub
            color: Theme.textFaint
            font { family: Theme.fontUi; pixelSize: 10; letterSpacing: 0.4 }
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    // Keycap for the footer hints.
    component Keycap: Row {
        property string key
        property string label
        spacing: 6
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: Math.max(22, keyT.implicitWidth + 12)
            implicitHeight: 20
            radius: 6
            color: Theme.alpha(Theme.text, 0.06)
            border.width: 1
            border.color: Theme.alpha(Theme.text, 0.14)
            Rectangle {   // key lip
                anchors { bottom: parent.bottom; left: parent.left; right: parent.right; margins: 1 }
                height: 2; radius: 1
                color: Qt.rgba(0, 0, 0, 0.30)
            }
            Text {
                id: keyT
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -1
                text: parent.parent.key
                color: Theme.alpha(Theme.text, 0.80)
                font { family: Theme.fontMono; pixelSize: 10; weight: Font.DemiBold }
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: parent.label
            color: Theme.textFaint
            font { family: Theme.fontUi; pixelSize: 11 }
        }
    }

    // Accent colour for an icon: the most vivid mid-lightness quantized
    // colour, lifted so it reads on dark glass; crimson when there is none.
    function accentFrom(colors) {
        var best = Theme.crimsonText, bestScore = 0.16;
        var cs = colors || [];
        for (var i = 0; i < cs.length; i++) {
            var c = cs[i];
            var mx = Math.max(c.r, c.g, c.b), mn = Math.min(c.r, c.g, c.b);
            var l = (mx + mn) / 2;
            var sat = mx === mn ? 0 : (mx - mn) / (1 - Math.abs(2 * l - 1));
            var score = sat * (1 - Math.abs(l - 0.56) * 1.6);
            if (score > bestScore) { bestScore = score; best = c; }
        }
        return Qt.hsla(best.hslHue, Math.min(1, best.hslSaturation * 1.05),
                       Math.max(0.52, Math.min(0.68, best.hslLightness)), 1);
    }

    // Entrance window for the first screenful of grid cells. `appear` is
    // only a window flag (0 → 1 over 520ms); each cell plays its own
    // delayed animation when it opens. Delegates recreated while typing —
    // the model rebuilds on every keystroke — see appear === 1 and render
    // statically, which is what keeps search flicker-free.
    property real appear: 1
    SequentialAnimation {
        id: appearAnim
        NumberAnimation {
            target: win
            property: "appear"
            from: 0
            to: 1
            duration: 560
            easing.type: Easing.OutCubic
        }
    }

    // Favorites resolved to app objects (favorites stores .desktop paths).
    readonly property var favApps: {
        var favs = AppIndex.favorites || [];
        var apps = AppIndex.apps || [];
        var out = [];
        for (var i = 0; i < favs.length; i++) {
            for (var j = 0; j < apps.length; j++) {
                if (apps[j].file === favs[i]) { out.push(apps[j]); break; }
            }
        }
        return out;
    }
    readonly property bool showPinned: win.cat === "All" && win.query === "" && favApps.length > 0

    // One open path: the Connections hook and Component.onCompleted both
    // land here, so a reopen within the loader linger window behaves
    // exactly like a fresh open (reset query/category, replay entrance,
    // re-focus search, refresh the index).
    function initOnOpen() {
        if (!AgentState.launcherOpen) return;
        AppIndex.rescan();
        win.query = "";
        search.text = "";
        win.cat = "All";
        grid.currentIndex = 0;
        win.now = new Date();
        appear = 0;
        appearAnim.restart();
        Qt.callLater(search.forceActiveFocus);
    }
    Component.onCompleted: win.initOnOpen()

    // ── scrim: deep dim + vignette + a faint crimson ambience behind the card ──
    Item {
        anchors.fill: parent
        opacity: AgentState.launcherOpen ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.OutCubic } }
        Rectangle { anchors.fill: parent; color: Qt.rgba(0.01, 0.01, 0.02, 0.52) }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.28) }
                GradientStop { position: 0.45; color: "transparent" }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.34) }
            }
        }
        RectangularShadow {   // ambient bloom the card floats in
            anchors.centerIn: parent
            width: card.width * 0.9; height: card.height * 0.8
            radius: card.radius
            blur: 160
            spread: 10
            color: Theme.alpha(Theme.crimson, 0.10)
        }
        MouseArea { anchors.fill: parent; onClicked: AgentState.launcherOpen = false }
    }

    // floating depth under the card
    RectangularShadow {
        anchors.fill: card
        radius: card.radius
        offset.y: 22
        blur: 60
        spread: -6
        color: Qt.rgba(0, 0, 0, 0.62)
        opacity: card.opacity
        scale: card.scale
    }

    GlassPanel {
        id: card
        anchors.centerIn: parent
        width: Math.min(1060, parent.width - 120)
        height: Math.min(720, parent.height - 140)
        radius: Theme.rXL
        level: 3
        clipContent: true
        baseColor: win.cardBase

        scale: AgentState.launcherOpen ? 1 : 0.95
        opacity: AgentState.launcherOpen ? 1 : 0
        transform: Translate { y: 18 * (1 - card.opacity) }
        Behavior on opacity { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
        Behavior on scale { NumberAnimation { duration: 420; easing.type: Easing.OutQuint } }

        MouseArea { anchors.fill: parent; onClicked: {} }

        // top-down sheen: the upper glass catches a little more light
        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 220
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.045) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
        // brand light rail along the card's top edge (same shader as the bars)
        GoogleGlow {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            edge: "top"
            amplitude: 0.85
            status: AgentState.status
        }

        Column {
            anchors { fill: parent; margins: 28; topMargin: 26 }
            spacing: 16

            // ── header: animated mark + greeting + count + exit ──
            Item {
                width: parent.width
                height: 48

                KinetixMark {
                    id: headMark
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    size: 44
                    active: AgentState.launcherOpen
                    hovered: markHover.hovered
                    HoverHandler { id: markHover }
                }
                Column {
                    anchors { left: headMark.right; leftMargin: 14; verticalCenter: parent.verticalCenter }
                    spacing: 2
                    Text {
                        text: win.greeting
                        color: Theme.text
                        font { family: Theme.fontUi; pixelSize: 22; weight: Font.DemiBold; letterSpacing: -0.2 }
                    }
                    Row {
                        spacing: 8
                        Text {
                            text: Qt.formatDate(win.now, "dddd, MMMM d")
                            color: Theme.textDim
                            font { family: Theme.fontUi; pixelSize: 12 }
                        }
                        Rectangle { width: 3; height: 3; radius: 2; color: Theme.textFaint; anchors.verticalCenter: parent.verticalCenter }
                        // count chip — describes the whole index, not the search box
                        Text {
                            id: countT
                            text: (AppIndex.apps ? AppIndex.apps.length : 0) + " applications"
                            color: Theme.alpha(Theme.crimsonText, 0.9)
                            font { family: Theme.fontUi; pixelSize: 12; weight: Font.Medium }
                        }
                    }
                }
                CloseButton {
                    id: closeBtn
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    onClicked: AgentState.launcherOpen = false
                }
            }

            // ── search ──
            Item {
                width: parent.width
                height: 56

                // focus glow
                RectangularShadow {
                    anchors.fill: searchBox
                    radius: searchBox.radius
                    blur: 18
                    spread: 0
                    color: Theme.alpha(Theme.crimson, 0.30)
                    opacity: search.activeFocus ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                }
                Rectangle {
                    id: searchBox
                    anchors.fill: parent
                    radius: 16
                    color: Qt.rgba(0.02, 0.022, 0.032, 0.85)
                    border.width: 1
                    border.color: search.activeFocus ? Theme.alpha(Theme.crimsonText, 0.62) : Theme.alpha(Theme.text, 0.12)
                    Behavior on border.color { ColorAnimation { duration: Theme.durMed } }
                    // inner top light
                    Rectangle {
                        anchors { top: parent.top; topMargin: 1; left: parent.left; right: parent.right; leftMargin: 14; rightMargin: 14 }
                        height: 1
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "transparent" }
                            GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.12) }
                            GradientStop { position: 1.0; color: "transparent" }
                        }
                    }

                    // magnifier
                    Item {
                        anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter }
                        width: 18; height: 18
                        Rectangle {
                            x: 1; y: 1; width: 12; height: 12; radius: 6
                            color: "transparent"
                            border.width: 2
                            border.color: search.activeFocus ? Theme.crimsonText : Theme.textFaint
                            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                        }
                        Rectangle {
                            x: 12; y: 12; width: 7; height: 2
                            rotation: 45
                            transformOrigin: Item.Left
                            radius: 1
                            color: search.activeFocus ? Theme.crimsonText : Theme.textFaint
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        }
                    }
                    TextInput {
                        id: search
                        anchors { left: parent.left; leftMargin: 52; right: rightControls.left; rightMargin: Theme.s3; verticalCenter: parent.verticalCenter }
                        color: Theme.text
                        selectionColor: Theme.alpha(Theme.crimson, 0.45)
                        font { family: Theme.fontUi; pixelSize: 18 }
                        clip: true
                        focus: AgentState.launcherOpen
                        onActiveFocusChanged: if (AgentState.launcherOpen && !activeFocus) forceActiveFocus()
                        onTextChanged: { win.query = text; grid.currentIndex = 0; }
                        Keys.onEscapePressed: AgentState.launcherOpen = false
                        Keys.onReturnPressed: {
                            var app = grid.currentItem ? grid.currentItem.appData : null;
                            if (app) { AppIndex.launch(app); AgentState.launcherOpen = false; }
                        }
                        Keys.onDownPressed: grid.moveCurrentIndexDown()
                        Keys.onUpPressed: grid.moveCurrentIndexUp()
                        Keys.onLeftPressed: grid.moveCurrentIndexLeft()
                        Keys.onRightPressed: grid.moveCurrentIndexRight()
                        Text {
                            anchors.fill: parent
                            visible: !search.text
                            text: "Search apps, tools and games…"
                            color: Theme.textFaint
                            font: search.font
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    Row {
                        id: rightControls
                        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
                        spacing: Theme.s2

                        // clear-query affordance (only when there is something to clear)
                        Rectangle {
                            width: 28; height: 28; radius: 8
                            visible: search.text !== ""
                            color: clearMa.containsMouse ? Theme.alpha(Theme.crimson, 0.25) : Theme.surfaceHigh
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                anchors.centerIn: parent
                                text: "✕"
                                color: clearMa.containsMouse ? Theme.text : Theme.textDim
                                font.pixelSize: 11
                            }
                            MouseArea {
                                id: clearMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: { search.text = ""; search.forceActiveFocus(); }
                            }
                        }

                        Rectangle {
                            width: 28; height: 28; radius: 8
                            color: rescanMa.containsMouse ? Theme.surfaceHigh : "transparent"
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                id: spinIcon
                                anchors.centerIn: parent
                                text: "↻"
                                color: rescanMa.containsMouse ? Theme.crimsonText : Theme.textDim
                                font.pixelSize: 15
                                rotation: 0
                                NumberAnimation on rotation {
                                    running: AppIndex.scanning
                                    loops: Animation.Infinite
                                    from: 0; to: 360; duration: 800
                                }
                            }
                            MouseArea {
                                id: rescanMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: AppIndex.rescan()
                            }
                        }
                    }
                }
            }

            // ── categories (lit pill for the active one + per-category counts) ──
            // Wrapped in an Item so the row can carry edge fades: the chips
            // overflow on narrow cards and used to be clipped flat against
            // nothing, which read as a broken row rather than a scrollable one.
            Item {
                id: catWrap
                width: parent.width
                height: 34
                readonly property bool catScrollable: catFlick.contentWidth > width

                Flickable {
                    id: catFlick
                    anchors.fill: parent
                    contentWidth: catRow.width
                    clip: true
                    flickableDirection: Flickable.HorizontalFlick
                    boundsBehavior: Flickable.StopAtBounds

                    Row {
                        id: catRow
                        spacing: 6
                        anchors.verticalCenter: parent.verticalCenter
                        Repeater {
                            model: AppIndex.categoryOrder
                            delegate: Rectangle {
                                id: catChip
                                required property string modelData
                                property bool on: win.cat === modelData
                                readonly property int n: {
                                    var list = AppIndex.filter(win.query, modelData);
                                    return list ? list.length : 0;
                                }
                                implicitWidth: catRowT.implicitWidth + 28 + (catN.visible ? catN.implicitWidth + 6 : 0)
                                implicitHeight: 30
                                radius: Theme.rPill
                                color: catMa.containsMouse && !on ? Theme.alpha(Theme.text, 0.08) : Theme.alpha(Theme.text, 0.035)
                                border.width: 1
                                border.color: on ? Theme.alpha(Theme.crimsonText, 0.70)
                                            : (catMa.containsMouse ? Theme.alpha(Theme.text, 0.18) : Theme.alpha(Theme.text, 0.09))
                                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                                // lit fill for the selected category
                                Rectangle {
                                    anchors.fill: parent
                                    radius: parent.radius
                                    opacity: catChip.on ? 1 : 0
                                    Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                                    gradient: Gradient {
                                        GradientStop { position: 0.0; color: Theme.alpha(Theme.crimsonText, 0.42) }
                                        GradientStop { position: 1.0; color: Theme.alpha(Theme.crimson, 0.26) }
                                    }
                                }
                                Row {
                                    anchors.centerIn: parent
                                    spacing: 6
                                    Text {
                                        id: catRowT
                                        text: catChip.modelData
                                        color: catChip.on ? "white" : (catMa.containsMouse ? Theme.text : Theme.textDim)
                                        font { family: Theme.fontUi; pixelSize: 12; weight: catChip.on ? Font.DemiBold : Font.Medium }
                                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                    }
                                    Text {
                                        id: catN
                                        visible: catChip.n > 0 && catChip.n < 1000
                                        text: catChip.n
                                        color: catChip.on ? Qt.rgba(1, 1, 1, 0.75) : Theme.textFaint
                                        font { family: Theme.fontMono; pixelSize: 10 }
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                }
                                MouseArea {
                                    id: catMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        if (win.cat !== modelData) {
                                            win.cat = modelData;
                                            grid.currentIndex = 0;
                                            appear = 0;
                                            appearAnim.restart();
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    id: catFadeLeft
                    width: 28
                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                    visible: catWrap.catScrollable && catFlick.contentX > 2
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: win.cardTint(0.95) }
                        GradientStop { position: 1.0; color: win.cardTint(0) }
                    }
                }
                Rectangle {
                    id: catFadeRight
                    width: 28
                    anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
                    visible: catWrap.catScrollable
                             && catFlick.contentX < catFlick.contentWidth - catFlick.width - 2
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: win.cardTint(0) }
                        GradientStop { position: 1.0; color: win.cardTint(0.95) }
                    }
                }
            }

            // ── favourites: horizontal hero cards tinted with each app's colour ──
            Item {
                id: pinnedWrap
                width: parent.width
                height: win.showPinned ? 98 : 0
                visible: win.showPinned
                Behavior on height { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutCubic } }

                Item {
                    id: favHead
                    anchors { top: parent.top; left: parent.left; right: parent.right }
                    height: 16
                    SectionLabel {
                        id: favLabels
                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                        title: "FAVORITES"
                        sub: "Quick launch"
                    }
                    SectionRule {
                        anchors { left: favLabels.right; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: Theme.s3 }
                    }
                }

                Flickable {
                    id: pinnedFlick
                    anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 24; bottom: parent.bottom }
                    contentWidth: pinnedRow.width
                    clip: true
                    flickableDirection: Flickable.HorizontalFlick
                    boundsBehavior: Flickable.StopAtBounds

                    Row {
                        id: pinnedRow
                        spacing: 10
                        y: 3

                        Repeater {
                            model: win.favApps
                            delegate: Item {
                                id: pinTile
                                required property var modelData
                                width: 188
                                height: 64
                                readonly property bool hot: pinMa.containsMouse
                                ColorQuantizer {
                                    id: pinQ
                                    source: pinTile.modelData.icon ? "file://" + pinTile.modelData.icon : ""
                                    depth: 3
                                    rescaleSize: 32
                                }
                                property color accent: win.accentFrom(pinQ.colors)
                                Behavior on accent { ColorAnimation { duration: 300 } }

                                Rectangle {
                                    id: pinFace
                                    width: parent.width; height: parent.height
                                    y: pinTile.hot ? -2 : 0
                                    Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutQuint } }
                                    radius: 16
                                    clip: true
                                    color: Theme.alpha(Theme.text, 0.035)
                                    border.width: 1
                                    border.color: pinTile.hot ? Theme.alpha(pinTile.accent, 0.60) : Theme.alpha(Theme.text, 0.09)
                                    Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                                    // colour wash from the icon side
                                    Rectangle {
                                        anchors.fill: parent
                                        radius: parent.radius
                                        opacity: pinTile.hot ? 1 : 0.65
                                        Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                                        gradient: Gradient {
                                            orientation: Gradient.Horizontal
                                            GradientStop { position: 0.0; color: Theme.alpha(pinTile.accent, 0.26) }
                                            GradientStop { position: 0.7; color: Theme.alpha(pinTile.accent, 0.04) }
                                            GradientStop { position: 1.0; color: "transparent" }
                                        }
                                    }
                                    Rectangle {   // top light
                                        anchors { top: parent.top; topMargin: 1; left: parent.left; right: parent.right; leftMargin: 12; rightMargin: 12 }
                                        height: 1
                                        color: Qt.rgba(1, 1, 1, pinTile.hot ? 0.20 : 0.10)
                                    }

                                    Rectangle {
                                        id: pinPlate
                                        anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                                        width: 42; height: 42; radius: 12
                                        color: Qt.rgba(0, 0, 0, 0.22)
                                        border.width: 1
                                        border.color: Theme.alpha(pinTile.accent, 0.35)
                                        IconImage {
                                            anchors.centerIn: parent
                                            implicitSize: pinTile.hot ? 32 : 30
                                            visible: pinTile.modelData.icon !== ""
                                            source: pinTile.modelData.icon ? "file://" + pinTile.modelData.icon : ""
                                            Behavior on implicitSize { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutBack } }
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            visible: pinTile.modelData.icon === ""
                                            text: pinTile.modelData.name.charAt(0).toUpperCase()
                                            color: Theme.text
                                            font { family: Theme.fontUi; pixelSize: 16; weight: Font.Bold }
                                        }
                                    }
                                    Column {
                                        anchors { left: pinPlate.right; leftMargin: 12; right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                                        spacing: 2
                                        Text {
                                            width: parent.width
                                            text: pinTile.modelData.name
                                            color: Theme.text
                                            elide: Text.ElideRight
                                            font { family: Theme.fontUi; pixelSize: 13; weight: Font.DemiBold }
                                        }
                                        Text {
                                            width: parent.width
                                            text: pinTile.hot ? "Open  →" : "Pinned"
                                            color: pinTile.hot ? pinTile.accent : Theme.textFaint
                                            elide: Text.ElideRight
                                            font { family: Theme.fontUi; pixelSize: 11 }
                                        }
                                    }
                                    // unpin star (top-right)
                                    Text {
                                        anchors { top: parent.top; right: parent.right; margins: 7 }
                                        text: "★"
                                        color: Theme.alpha(Theme.warn, pinTile.hot ? 1 : 0.55)
                                        font.pixelSize: 11
                                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                    }
                                }

                                HoverTip {
                                    target: pinTile
                                    hovered: pinMa.containsMouse
                                    text: pinTile.modelData.name + " — right-click to unpin"
                                }

                                MouseArea {
                                    id: pinMa
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                                    onClicked: function(mouse) {
                                        if (mouse.button === Qt.RightButton)
                                            AppIndex.toggleFav(pinTile.modelData);
                                        else { AppIndex.launch(pinTile.modelData); AgentState.launcherOpen = false; }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ── app grid ──
            Item {
                id: gridWrap
                width: parent.width
                height: parent.height - y - footer.height - 16
                clip: false

                Item {
                    id: gridHead
                    width: parent.width
                    height: 18
                    SectionLabel {
                        id: gridLabels
                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                        title: win.query !== "" ? "RESULTS" : win.cat === "All" ? "ALL APPS" : win.cat.toUpperCase()
                        sub: grid.count + (grid.count === 1 ? " app" : " apps")
                    }
                    // The old right-aligned grid-column readout was
                    // developer telemetry; the rule carries the eye instead.
                    SectionRule {
                        anchors { left: gridLabels.right; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: Theme.s3 }
                    }
                }

                GridView {
                    id: grid
                    anchors { top: parent.top; topMargin: 26; left: parent.left; right: parent.right; rightMargin: 12; bottom: parent.bottom }
                    clip: true
                    cellWidth: Math.floor(width / win.gridColumns)
                    cellHeight: 116
                    model: AppIndex.filter(win.query, win.cat)
                    currentIndex: 0
                    keyNavigationWraps: true
                    // hover-lift headroom for the first row
                    topMargin: 4

                    delegate: Item {
                        id: cell
                        required property var modelData
                        required property int index
                        width: grid.cellWidth
                        height: grid.cellHeight
                        property var appData: modelData
                        property bool cur: GridView.isCurrentItem
                        readonly property bool hot: cellMa.containsMouse
                        readonly property bool lit: hot || cur

                        // Accent is sampled lazily: the quantizer only gets a
                        // source once the tile is first hovered/selected, then
                        // keeps it, so opening the launcher never quantizes
                        // dozens of icons up front.
                        property bool touched: false
                        onLitChanged: if (lit) touched = true
                        ColorQuantizer {
                            id: cellQ
                            source: cell.touched && cell.modelData.icon !== "" ? "file://" + cell.modelData.icon : ""
                            depth: 3
                            rescaleSize: 32
                        }
                        property color accent: win.accentFrom(cellQ.colors)
                        Behavior on accent { ColorAnimation { duration: 260 } }

                        // Entrance is a window, not a per-frame binding: the
                        // cell animates itself once when win.appear drops to 0
                        // (open / category change). Binding opacity directly to
                        // win.appear made every cell fade as one block.
                        readonly property bool pendingEntrance: win.appear < 1 && index <= 27
                        property real liftY: 0
                        property real popScale: 1
                        opacity: pendingEntrance ? 0 : 1
                        transform: Translate { y: cell.liftY }

                        onPendingEntranceChanged: if (cell.pendingEntrance) cellIn.restart()
                        Component.onCompleted: if (cell.pendingEntrance) cellIn.restart()

                        SequentialAnimation {
                            id: cellIn
                            // Delay runs across the row then down it; capped so
                            // the last cell still starts inside the entrance window.
                            PauseAnimation { duration: Math.min(cell.index, 27) * 13 }
                            ParallelAnimation {
                                NumberAnimation { target: cell; property: "opacity"; from: 0; to: 1; duration: 280; easing.type: Easing.OutCubic }
                                NumberAnimation { target: cell; property: "liftY"; from: 14; to: 0; duration: 380; easing.type: Easing.OutQuint }
                                NumberAnimation { target: cell; property: "popScale"; from: 0.92; to: 1; duration: 380; easing.type: Easing.OutBack }
                            }
                        }

                        Item {
                            id: tileFace
                            anchors { fill: parent; margins: 5 }
                            y: cell.hot ? -3 : 0
                            scale: cell.popScale * (cellMa.pressed ? 0.96 : 1)
                            Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutQuint } }

                            // soft accent glow around a lit tile (blurred ring, not a fill)
                            Item {
                                anchors.fill: tile
                                anchors.margins: -3
                                opacity: cell.lit ? 1 : 0
                                visible: opacity > 0
                                Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                                layer.enabled: visible
                                layer.effect: MultiEffect { blurEnabled: true; blur: 0.6; blurMax: 12 }
                                Rectangle {
                                    anchors.fill: parent
                                    radius: tile.radius + 3
                                    color: "transparent"
                                    border.width: 3
                                    border.color: Theme.alpha(cell.accent, cell.cur ? 0.55 : 0.40)
                                }
                            }

                            Rectangle {
                                id: tile
                                anchors.fill: parent
                                radius: 18
                                antialiasing: true
                                clip: true
                                // Resting tiles are dark glass: Theme.alpha()
                                // REPLACES the channel, so the old
                                // alpha(surfaceLow, 0.34) was white at 34%.
                                gradient: Gradient {
                                    GradientStop { position: 0; color: Theme.alpha(Theme.text, cell.lit ? 0.075 : 0.040) }
                                    GradientStop { position: 1; color: Theme.alpha(Theme.text, cell.lit ? 0.030 : 0.014) }
                                }
                                border.width: 1
                                border.color: cell.cur ? Theme.alpha(cell.accent, 0.62)
                                            : cell.hot ? Theme.alpha(cell.accent, 0.40)
                                            : Theme.alpha(Theme.text, 0.06)
                                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                                // accent wash pooling at the foot of a lit tile
                                Rectangle {
                                    anchors.fill: parent
                                    radius: parent.radius
                                    opacity: cell.lit ? 1 : 0
                                    Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                                    gradient: Gradient {
                                        GradientStop { position: 0.0; color: "transparent" }
                                        GradientStop { position: 1.0; color: Theme.alpha(cell.accent, 0.22) }
                                    }
                                }
                                Rectangle {   // top light
                                    anchors { top: parent.top; topMargin: 1; left: parent.left; right: parent.right; leftMargin: 14; rightMargin: 14 }
                                    height: 1
                                    color: Qt.rgba(1, 1, 1, cell.lit ? 0.18 : 0.07)
                                }
                            }

                            Column {
                                anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 14 }
                                width: parent.width - Theme.s3
                                spacing: 9
                                Item {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 52; height: 52
                                    // halo behind the icon
                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: 50; height: 50; radius: 25
                                        color: Theme.alpha(cell.accent, 0.20)
                                        opacity: cell.lit ? 1 : 0
                                        scale: cell.lit ? 1 : 0.6
                                        Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
                                        Behavior on scale { NumberAnimation { duration: 300; easing.type: Easing.OutBack } }
                                    }
                                    IconImage {
                                        anchors.centerIn: parent
                                        implicitSize: cell.hot ? 46 : 42
                                        source: cell.modelData.icon !== "" ? "file://" + cell.modelData.icon : ""
                                        visible: cell.modelData.icon !== ""
                                        mipmap: true
                                        Behavior on implicitSize { NumberAnimation { duration: 240; easing.type: Easing.OutBack } }
                                    }
                                    Rectangle {
                                        anchors.centerIn: parent
                                        visible: cell.modelData.icon === ""
                                        width: 40; height: 40; radius: 12
                                        color: Theme.alpha(cell.accent, 0.20)
                                        border.width: 1
                                        border.color: Theme.alpha(cell.accent, 0.45)
                                        Text {
                                            anchors.centerIn: parent
                                            text: cell.modelData.name.charAt(0).toUpperCase()
                                            color: Theme.text
                                            font { family: Theme.fontUi; pixelSize: 18; weight: Font.Bold }
                                        }
                                    }
                                }
                                // Two lines are reserved for every label so a
                                // one-line name doesn't push its icon a line
                                // lower than its neighbours in the same row.
                                Text {
                                    id: cellLabel
                                    width: parent.width
                                    height: 30
                                    verticalAlignment: Text.AlignTop
                                    text: cell.modelData.name
                                    color: cell.lit ? Theme.text : Theme.alpha(Theme.text, 0.74)
                                    font { family: Theme.fontUi; pixelSize: 12; weight: cell.lit ? Font.DemiBold : Font.Medium }
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                    maximumLineCount: 2
                                    wrapMode: Text.WordWrap
                                    lineHeight: 1.05
                                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                }
                            }
                            Text {
                                anchors { top: parent.top; right: parent.right; margins: 8 }
                                text: AppIndex.isFav(cell.modelData) ? "★" : "☆"
                                color: AppIndex.isFav(cell.modelData) ? Theme.warn : (cell.hot ? Theme.textFaint : "transparent")
                                font.pixelSize: 12
                            }
                        }
                        MouseArea {
                            id: cellMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onClicked: function(mouse) {
                                grid.currentIndex = cell.index
                                if (mouse.button === Qt.RightButton) AppIndex.toggleFav(cell.modelData)
                                else { AppIndex.launch(cell.modelData); AgentState.launcherOpen = false }
                            }
                        }
                    }

                    Column {
                        anchors.centerIn: parent
                        visible: grid.count === 0
                        spacing: Theme.s3
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: AppIndex.ready ? (win.query !== "" ? "No applications match \"" + win.query + "\"" : "No applications in " + win.cat) : "Scanning applications…"
                            color: Theme.textDim
                            font { family: Theme.fontUi; pixelSize: 14 }
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Rectangle {
                            visible: AppIndex.ready && win.query !== ""
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: clearHintT.implicitWidth + 24
                            height: 30
                            radius: Theme.rPill
                            color: clearHintMa.containsMouse ? Theme.alpha(Theme.crimson, 0.22) : Theme.alpha(Theme.text, 0.04)
                            border.width: 1
                            border.color: Theme.alpha(Theme.crimsonText, clearHintMa.containsMouse ? 0.6 : 0.3)
                            Text { id: clearHintT; anchors.centerIn: parent; text: "CLEAR SEARCH"; color: Theme.crimsonText; font { family: Theme.fontUi; pixelSize: 11; letterSpacing: 1.2; weight: Font.DemiBold } }
                            MouseArea { id: clearHintMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { search.text = ""; search.forceActiveFocus() } }
                        }
                    }
                }

                // Scroll affordance for the grid, living in the gutter the
                // GridView's rightMargin reserves. Without it a 66-app index
                // gave no hint that more rows existed below the fold.
                Rectangle {
                    id: gridScroll
                    visible: grid.contentHeight > grid.height && grid.contentHeight > 0
                    anchors.right: parent.right
                    width: 4
                    radius: 2
                    height: Math.max(28, Math.min(grid.height, grid.height * grid.height / grid.contentHeight))
                    y: grid.y + Math.max(0, (grid.height - height) * gridScroll.frac)
                    property real frac: grid.contentHeight > grid.height
                                        ? grid.contentY / (grid.contentHeight - grid.height)
                                        : 0
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: Theme.alpha(Theme.crimsonText, 0.55) }
                        GradientStop { position: 1.0; color: Theme.alpha(Theme.text, 0.18) }
                    }
                }
                // soft fade where the grid scrolls under the footer
                Rectangle {
                    anchors { left: grid.left; right: grid.right; bottom: grid.bottom }
                    height: 26
                    visible: grid.contentHeight > grid.height && grid.contentY < grid.contentHeight - grid.height - 2
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: win.cardTint(0) }
                        GradientStop { position: 1.0; color: win.cardTint(0.95) }
                    }
                }
            }

            // ── footer: rule + keycap hints, sized as one block so the grid
            // can subtract it without a magic extra gap ──
            Item {
                id: footer
                width: parent.width
                height: footerCol.implicitHeight

                Column {
                    id: footerCol
                    width: parent.width
                    spacing: 12

                    Rectangle {
                        id: footerRule
                        width: parent.width
                        height: 1
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "transparent" }
                            GradientStop { position: 0.5; color: Theme.alpha(Theme.text, 0.10) }
                            GradientStop { position: 1.0; color: "transparent" }
                        }
                    }
                    Row {
                        id: hint
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 22
                        Keycap { key: "↵"; label: "Launch" }
                        Keycap { key: "← →"; label: "Navigate" }
                        Keycap { key: "Right-click"; label: "Pin" }
                        Keycap { key: "Esc"; label: "Close" }
                    }
                }
            }
        }
    }

    Connections {
        target: AgentState
        function onLauncherOpenChanged() { win.initOnOpen(); }
    }
}
