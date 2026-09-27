import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"
import "../components"

// Master-class App Center & Package Hub for Kinetix OS.
// Elegant dropdown from the quickshell bar featuring unified search across
// AUR (90,000+ packages), official Arch repositories, and Flathub (Flatpak),
// 1-click install/uninstall of apps, 1-click system Update All, and
// 1-click installation and management of modular package engines (Flatpak, Snapd, Paru, Yay, AppImage).
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore

    // Keys.onEscapePressed cannot attach to a PanelWindow (not an Item — the
    // runtime logs "Could not attach Keys property"). A window-scoped Shortcut
    // resolves through the QsWindow parent chain instead.
    Shortcut {
        sequence: "Escape"
        context: Qt.WindowShortcut
        enabled: AgentState.appCenterOpen
        onActivated: AgentState.appCenterOpen = false
    }

    Shortcut {
        sequence: "Ctrl+F"
        context: Qt.WindowShortcut
        enabled: AgentState.appCenterOpen
        onActivated: {
            searchInput.forceActiveFocus();
            searchInput.selectAll();
        }
    }

    WlrLayershell.namespace: "argus:appcenter"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: AgentState.appCenterOpen
                                 ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    visible: AgentState.appCenterOpen || pop.popProgress > 0.01

    // Dismiss when clicking outside the popup
    MouseArea {
        id: dismissArea
        anchors.fill: parent
        onClicked: function(mouse) {
            var p = mapToItem(pop, mouse.x, mouse.y);
            if (p.x >= 0 && p.x <= pop.width && p.y >= 0 && p.y <= pop.height) return;
            AgentState.appCenterOpen = false;
        }
    }

    GlassPanel {
        id: pop
        anchors {
            top: parent.top
            topMargin: 62
            right: parent.right
            rightMargin: Math.max(16, Math.min(parent.width - pop.width - 16, AgentState.appCenterRightMargin))
        }
        width: 680
        height: 660
        radius: Theme.rXL
        level: 3
        clipContent: true
        baseColor: "#0F0709"   // deep ominous maroon base — matches the agent panel

        readonly property color cardBg: Qt.rgba(0.09, 0.043, 0.05, 0.75)
        readonly property color cardBorder: Qt.rgba(1, 1, 1, 0.08)

        property real popProgress: AgentState.appCenterOpen ? 1.0 : 0.0
        opacity: popProgress
        scale: 0.96 + 0.04 * popProgress
        transform: Translate { y: -10 * (1.0 - pop.popProgress) }
        Behavior on popProgress { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }

        Keys.onEscapePressed: AgentState.appCenterOpen = false

        // Volumetric atmospheric crimson depth wash
        Rectangle {
            anchors.fill: parent
            radius: pop.radius
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0.92, 0.12, 0.20, 0.06) }
                GradientStop { position: 0.35; color: "transparent" }
                GradientStop { position: 0.75; color: "transparent" }
                GradientStop { position: 1.0; color: Qt.rgba(0.40, 0.04, 0.08, 0.08) }
            }
        }

        // Specular grazing highlight along top edge
        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right }
            height: 1.5
            radius: pop.radius
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.20; color: Qt.rgba(1, 1, 1, 0.22) }
                GradientStop { position: 0.50; color: Theme.alpha(Theme.crimson, 0.65) }
                GradientStop { position: 0.80; color: Qt.rgba(1, 1, 1, 0.18) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // Absorb clicks inside
        MouseArea {
            anchors.fill: parent
            onClicked: {}
        }

        Column {
            id: mainCol
            anchors.fill: parent
            anchors.margins: Theme.s4
            spacing: Theme.s3

            // ── 1. Header Bar ─────────────────────────────────────────
            Item {
                id: headerRow
                width: parent.width
                height: 40

                Row {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.s3

                    // Glowing Icon Monogram with synchronized heartbeat beacon
                    Rectangle {
                        width: 38
                        height: 38
                        radius: 11
                        color: Theme.alpha(Theme.crimson, 0.16 + 0.08 * Theme.heartbeatSin)
                        border.width: 1
                        border.color: Theme.alpha(Theme.crimson, 0.42 + 0.25 * Theme.heartbeatSin)
                        anchors.verticalCenter: parent.verticalCenter

                        // Subtle pulsing halo
                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -2
                            radius: 13
                            color: "transparent"
                            border.width: 1
                            border.color: Theme.alpha(Theme.crimson, 0.18 * (Theme.heartbeatSin + 1.0) * 0.5)
                        }

                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width - 4
                            height: parent.height - 4
                            radius: 9
                            color: Qt.rgba(1, 1, 1, 0.03)
                        }

                        Text {
                            anchors.centerIn: parent
                            text: "❖"
                            color: Theme.crimsonText
                            font.pixelSize: 18
                        }
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2

                        Row {
                            spacing: Theme.s2

                            Text {
                                text: "KINETIX APP CENTER"
                                color: Theme.text
                                font {
                                    family: Theme.fontMono
                                    pixelSize: Theme.tBody
                                    weight: Font.Bold
                                    letterSpacing: 1.4
                                }
                            }

                            // Active Engine count pill badge
                            Rectangle {
                                implicitHeight: 18
                                implicitWidth: engPillTxt.implicitWidth + 10
                                radius: Theme.rPill
                                color: Theme.alpha(Theme.crimson, 0.16)
                                border.width: 1
                                border.color: Theme.alpha(Theme.crimson, 0.40)
                                anchors.verticalCenter: parent.verticalCenter

                                Text {
                                    id: engPillTxt
                                    anchors.centerIn: parent
                                    text: AppCenterState.installedEnginesCount + "/" + AppCenterState.totalEnginesCount + " ENGINES"
                                    color: Theme.crimsonText
                                    font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                                }
                            }
                        }

                        Text {
                            text: "Arch Linux · AUR Community · Flathub Universal"
                            color: Theme.textDim
                            font {
                                family: Theme.fontUi
                                pixelSize: Theme.tCaption
                            }
                        }
                    }
                }

                // Crimson identity keyline — the panel's signature edge,
                // mirrored from the agent panel's laser keyline (static, no
                // animation: the bar's laser rail stays the only animated one)
                Rectangle {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                    height: 1
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: 0.18; color: Theme.alpha(Theme.crimson, 0.55) }
                        GradientStop { position: 0.5;  color: Theme.crimson }
                        GradientStop { position: 0.82; color: Theme.alpha(Theme.crimson, 0.55) }
                        GradientStop { position: 1.0; color: "transparent" }
                    }
                }

                Row {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.s2

                    // "Update All" Master Button
                    Rectangle {
                        id: updateAllBtn
                        implicitHeight: 32
                        implicitWidth: updateRow.implicitWidth + Theme.s3 * 2
                        radius: Theme.rPill
                        anchors.verticalCenter: parent.verticalCenter

                        readonly property bool hasUpdates: AppCenterState.updatesCount > 0
                        readonly property bool isUpdating: AppCenterState.updatingAll
                        readonly property bool hovered: updateHit.containsMouse

                        color: isUpdating
                               ? Theme.alpha(Theme.gilded, 0.25)
                               : hasUpdates
                               ? (hovered ? Theme.alpha(Theme.gilded, 0.32) : Theme.alpha(Theme.gilded, 0.18))
                               : (hovered ? Theme.alpha(Theme.ember, 0.25) : Theme.alpha(Theme.ember, 0.12))
                        border.width: 1
                        border.color: isUpdating
                                     ? Theme.gilded
                                     : hasUpdates
                                     ? (hovered ? Theme.gilded : Theme.alpha(Theme.gilded, 0.50 + 0.30 * Theme.heartbeatSin))
                                     : (hovered ? Theme.ember : Theme.alpha(Theme.ember, 0.35))
                        scale: updateHit.pressed ? 0.95 : (hovered ? 1.03 : 1.0)

                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                        Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutBack } }

                        MouseArea {
                            id: updateHit
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                AppCenterState.updateAll();
                            }
                        }

                        Row {
                            id: updateRow
                            anchors.centerIn: parent
                            spacing: 6

                            Text {
                                text: updateAllBtn.isUpdating ? "◐" : (updateAllBtn.hasUpdates ? "⇧" : "✓")
                                color: updateAllBtn.hasUpdates || updateAllBtn.isUpdating ? Theme.gilded : Theme.ember
                                font { family: Theme.fontMono; pixelSize: 11; weight: Font.Bold }
                                rotation: updateAllBtn.isUpdating ? (Theme.heartbeatPhase * 360) : 0
                            }

                            Text {
                                text: updateAllBtn.isUpdating
                                      ? "Updating System..."
                                      : (updateAllBtn.hasUpdates
                                         ? ("Update All (" + AppCenterState.updatesCount + ")")
                                         : "Up to Date")
                                color: updateAllBtn.hasUpdates || updateAllBtn.isUpdating ? Theme.gilded : Theme.ember
                                font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.DemiBold }
                            }
                        }
                    }

                    // Refresh Button with smooth spin micro-interaction
                    IconButton {
                        id: refreshBtn
                        glyph: "↻"
                        tip: "Refresh Catalogs & Updates"
                        anchors.verticalCenter: parent.verticalCenter
                        property real spinAngle: 0
                        transform: Rotation {
                            origin.x: refreshBtn.width / 2
                            origin.y: refreshBtn.height / 2
                            angle: refreshBtn.spinAngle
                        }
                        NumberAnimation {
                            id: spinAnim
                            target: refreshBtn
                            property: "spinAngle"
                            from: 0
                            to: 360
                            duration: 480
                            easing.type: Easing.OutCubic
                        }
                        onClicked: {
                            spinAnim.restart();
                            AppCenterState.refreshStatus();
                            AppCenterState.refreshFeatured();
                        }
                    }

                    // Close Button
                    IconButton {
                        glyph: "✕"
                        tip: "Close (Esc)"
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: AgentState.appCenterOpen = false
                    }
                }
            }

            // ── 2. Search Box ─────────────────────────────────────────
            Rectangle {
                id: searchBar
                width: parent.width
                height: 42
                radius: Theme.rM
                // Warm well that deepens toward crimson on focus
                color: searchInput.activeFocus ? Theme.alpha(Theme.crimson, 0.10) : Theme.surfaceLow
                border.width: 1
                border.color: searchInput.activeFocus ? Theme.crimson : Theme.stroke
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                Row {
                    anchors {
                        left: parent.left; leftMargin: Theme.s3
                        right: parent.right; rightMargin: Theme.s3
                        verticalCenter: parent.verticalCenter
                    }
                    spacing: Theme.s2

                    Text {
                        text: "🔍"
                        color: searchInput.activeFocus ? Theme.crimsonText : Theme.textDim
                        font.pixelSize: 13
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    TextInput {
                        id: searchInput
                        width: parent.width - 85
                        anchors.verticalCenter: parent.verticalCenter
                        text: AppCenterState.searchQuery
                        color: Theme.text
                        font { family: Theme.fontUi; pixelSize: Theme.tBody }
                        clip: true
                        selectByMouse: true
                        focus: AgentState.appCenterOpen

                        onActiveFocusChanged: {
                            if (AgentState.appCenterOpen && !activeFocus) {
                                forceActiveFocus();
                            }
                        }

                        Text {
                            visible: searchInput.text === "" && !searchInput.activeFocus
                            text: "Search 100,000+ Arch, AUR, and Flathub applications..."
                            color: Theme.textFaint
                            font: searchInput.font
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Keys.onEscapePressed: AgentState.appCenterOpen = false
                        Keys.onReturnPressed: AppCenterState.executeSearch()
                        onTextChanged: AppCenterState.setSearch(text)
                    }

                    // Shortcut Hint Badge when focused and empty
                    Rectangle {
                        visible: searchInput.activeFocus && searchInput.text === ""
                        implicitHeight: 20
                        implicitWidth: hintTxt.implicitWidth + 8
                        radius: 4
                        color: Theme.surfaceHigh
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            id: hintTxt
                            anchors.centerIn: parent
                            text: "↵ Enter"
                            color: Theme.textDim
                            font { family: Theme.fontMono; pixelSize: 9 }
                        }
                    }

                    // Clear button
                    Item {
                        visible: searchInput.text !== ""
                        width: 22
                        height: 22
                        anchors.verticalCenter: parent.verticalCenter

                        Rectangle {
                            anchors.centerIn: parent
                            width: 20; height: 20; radius: 10
                            color: clearMa.containsMouse ? Theme.surfaceHigh : Theme.surface
                            Text {
                                anchors.centerIn: parent
                                text: "×"
                                color: Theme.textDim
                                font.pixelSize: 14
                            }
                        }
                        MouseArea {
                            id: clearMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                searchInput.text = "";
                                searchInput.forceActiveFocus();
                            }
                        }
                    }
                }
            }

            // ── 3. Navigation Tabs & Source Filters ───────────────────
            Item {
                id: tabsBar
                width: parent.width
                height: 32

                Row {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.s2

                    Repeater {
                        model: [
                            { id: "discover", label: "Discover", icon: "✦" },
                            { id: "updates", label: "Updates (" + AppCenterState.updatesCount + ")", icon: "⇧" },
                            { id: "engines", label: "Package Engines (" + AppCenterState.installedEnginesCount + "/" + AppCenterState.totalEnginesCount + ")", icon: "⚙" }
                        ]

                        delegate: Rectangle {
                            id: tabBtn
                            readonly property bool isSelected: AppCenterState.activeTab === modelData.id
                            readonly property bool hovered: tabHit.containsMouse

                            implicitHeight: 28
                            implicitWidth: tabRow.implicitWidth + Theme.s3 * 2
                            radius: Theme.rPill

                            color: isSelected
                                   ? Theme.alpha(Theme.crimson, 0.22)
                                   : (hovered ? Theme.surfaceHigh : "transparent")
                            border.width: 1
                            border.color: isSelected
                                         ? Theme.crimson
                                         : (hovered ? Theme.strokeStrong : "transparent")
                            scale: tabHit.pressed ? 0.95 : 1.0

                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                            MouseArea {
                                id: tabHit
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    AppCenterState.activeTab = modelData.id;
                                    if (modelData.id === "discover") {
                                        searchInput.text = "";
                                    }
                                }
                            }

                            Row {
                                id: tabRow
                                anchors.centerIn: parent
                                spacing: 6

                                Text {
                                    text: modelData.icon
                                    color: tabBtn.isSelected ? Theme.crimsonText : Theme.textDim
                                    font.pixelSize: 11
                                }

                                Text {
                                    text: modelData.label
                                    color: tabBtn.isSelected ? Theme.text : Theme.textDim
                                    font {
                                        family: Theme.fontUi
                                        pixelSize: Theme.tCaption
                                        weight: tabBtn.isSelected ? Font.DemiBold : Font.Normal
                                    }
                                }
                            }
                        }
                    }
                }

                // Source filter when searching
                Row {
                    visible: AppCenterState.activeTab === "search" || searchInput.text !== ""
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4

                    Text {
                        text: "Source:"
                        color: Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Repeater {
                        model: [
                            { id: "all", label: "All", color: Theme.crimsonText },
                            { id: "aur", label: "AUR", color: Theme.alarm },
                            { id: "arch", label: "Arch", color: Theme.ember },
                            { id: "flatpak", label: "Flathub", color: Theme.gilded }
                        ]

                        delegate: Rectangle {
                            id: filterBtn
                            readonly property bool isFilter: AppCenterState.sourceFilter === modelData.id
                            implicitHeight: 22
                            implicitWidth: fText.implicitWidth + 14
                            radius: 11
                            color: isFilter ? Theme.alpha(modelData.color, 0.22) : Theme.surfaceLow
                            border.width: 1
                            border.color: isFilter ? modelData.color : Theme.stroke

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: AppCenterState.setFilter(modelData.id)
                            }

                            Text {
                                id: fText
                                anchors.centerIn: parent
                                text: modelData.label
                                color: filterBtn.isFilter ? modelData.color : Theme.textDim
                                font { family: Theme.fontMono; pixelSize: 9; weight: Font.Medium }
                            }
                        }
                    }
                }

                // Discover view badge
                Text {
                    visible: AppCenterState.activeTab === "discover" && searchInput.text === ""
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Curated Directory"
                    color: Theme.textFaint
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                }

                // Engines view active count pill
                Text {
                    visible: AppCenterState.activeTab === "engines"
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Unified Package Runtimes"
                    color: Theme.textFaint
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                }
            }

            // ── 4. Main Scrollable Body ───────────────────────────────
            Item {
                width: parent.width
                height: mainCol.height - headerRow.height - searchBar.height - tabsBar.height - mainCol.spacing * 3
                clip: true

                // ── View A: Discover View ───────────────────────────────
                Item {
                    id: discoverView
                    visible: AppCenterState.activeTab === "discover"
                    anchors.fill: parent

                    Column {
                        anchors.fill: parent
                        spacing: Theme.s2

                        // Category Filter Chips Bar with Live Counts
                        Item {
                            width: parent.width
                            height: 30

                            Flickable {
                                id: catFlick
                                anchors.fill: parent
                                contentWidth: catRow.implicitWidth
                                boundsBehavior: Flickable.StopAtBounds
                                clip: true

                                Row {
                                    id: catRow
                                    spacing: 6

                                    Repeater {
                                        model: [
                                            { id: "all", label: "All Apps", icon: "✦" },
                                            { id: "Development", label: "Development", icon: "⚡" },
                                            { id: "Communication", label: "Communication", icon: "💬" },
                                            { id: "Media", label: "Media & Audio", icon: "🎬" },
                                            { id: "Browsers", label: "Browsers", icon: "🌐" },
                                            { id: "Productivity", label: "Productivity", icon: "📝" },
                                            { id: "Gaming", label: "Gaming", icon: "🎮" },
                                            { id: "System", label: "System", icon: "⚙" }
                                        ]

                                        delegate: Rectangle {
                                            id: chipBtn
                                            readonly property bool isSelected: AppCenterState.selectedCategory.toLowerCase() === modelData.id.toLowerCase()
                                            readonly property bool hovered: chipHit.containsMouse
                                            readonly property int catCount: AppCenterState.countForCategory(modelData.id)

                                            implicitHeight: 26
                                            implicitWidth: chipContent.implicitWidth + 16
                                            radius: Theme.rPill

                                            color: isSelected
                                                   ? Theme.alpha(Theme.crimson, 0.22)
                                                   : (hovered ? Theme.surfaceHigh : Theme.surfaceLow)
                                            border.width: 1
                                            border.color: isSelected
                                                         ? Theme.crimson
                                                         : (hovered ? Theme.strokeStrong : Theme.stroke)
                                            scale: chipHit.pressed ? 0.94 : (hovered ? 1.02 : 1.0)

                                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                                            Behavior on scale { NumberAnimation { duration: Theme.durFast } }

                                            MouseArea {
                                                id: chipHit
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: AppCenterState.setCategory(modelData.id)
                                            }

                                            Row {
                                                id: chipContent
                                                anchors.centerIn: parent
                                                spacing: 5

                                                Text {
                                                    text: modelData.icon
                                                    color: chipBtn.isSelected ? Theme.crimsonText : Theme.textFaint
                                                    font.pixelSize: 10
                                                }

                                                Text {
                                                    text: modelData.label
                                                    color: chipBtn.isSelected ? Theme.text : Theme.textDim
                                                    font {
                                                        family: Theme.fontUi
                                                        pixelSize: 11
                                                        weight: chipBtn.isSelected ? Font.DemiBold : Font.Normal
                                                    }
                                                }

                                                // Micro count badge
                                                Rectangle {
                                                    visible: chipBtn.catCount > 0
                                                    implicitHeight: 14
                                                    implicitWidth: cntTxt.implicitWidth + 6
                                                    radius: 7
                                                    color: chipBtn.isSelected ? Theme.alpha(Theme.crimson, 0.35) : Theme.surfaceHigh
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    Text {
                                                        id: cntTxt
                                                        anchors.centerIn: parent
                                                        text: chipBtn.catCount.toString()
                                                        color: chipBtn.isSelected ? Theme.text : Theme.textFaint
                                                        font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            // Left overflow fade mask
                            Rectangle {
                                anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                                width: 22
                                visible: catFlick.contentX > 2
                                gradient: Gradient {
                                    orientation: Gradient.Horizontal
                                    GradientStop { position: 0.0; color: pop.cardBg }
                                    GradientStop { position: 1.0; color: "transparent" }
                                }
                                z: 2
                            }

                            // Right overflow fade mask
                            Rectangle {
                                anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
                                width: 26
                                visible: catFlick.contentX < (catFlick.contentWidth - catFlick.width - 2)
                                gradient: Gradient {
                                    orientation: Gradient.Horizontal
                                    GradientStop { position: 0.0; color: "transparent" }
                                    GradientStop { position: 1.0; color: pop.cardBg }
                                }
                                z: 2
                            }
                        }

                        // Featured Apps List
                        ListView {
                            id: discoverList
                            width: parent.width
                            height: parent.height - 38
                            spacing: Theme.s2
                            boundsBehavior: Flickable.StopAtBounds
                            clip: true
                            reuseItems: true
                            cacheBuffer: 200
                            model: AppCenterState.filteredFeaturedApps

                            delegate: AppCard {
                                width: discoverList.width - (discoverScrollBar.visible ? 8 : 0)
                                appData: modelData
                            }
                        }
                    }

                    GlassScrollBar {
                        id: discoverScrollBar
                        flickable: discoverList
                        anchors.topMargin: 38
                    }
                }

                // ── View B: Search Results View ─────────────────────────
                Item {
                    visible: AppCenterState.activeTab === "search"
                    anchors.fill: parent

                    // Searching Spinner State
                    Column {
                        visible: AppCenterState.searching
                        anchors.centerIn: parent
                        spacing: Theme.s3

                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 44; height: 44; radius: 22
                            color: Theme.alpha(Theme.crimson, 0.16)
                            border.width: 1
                            border.color: Theme.alpha(Theme.crimson, 0.35)

                            Text {
                                anchors.centerIn: parent
                                text: "◐"
                                color: Theme.crimsonText
                                font.pixelSize: 22
                                rotation: Theme.heartbeatPhase * 360
                            }
                        }

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "Searching across Arch, AUR & Flathub..."
                            color: Theme.text
                            font { family: Theme.fontUi; pixelSize: Theme.tBody; weight: Font.DemiBold }
                        }

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "Querying local ALPM database, AUR RPC v5, and Flathub v2..."
                            color: Theme.textDim
                            font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                        }
                    }

                    // Empty results State
                    Column {
                        visible: !AppCenterState.searching && AppCenterState.searchResults.length === 0 && searchInput.text !== ""
                        anchors.centerIn: parent
                        spacing: Theme.s2

                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 48; height: 48; radius: 24
                            color: Theme.surfaceLow
                            border.width: 1
                            border.color: Theme.stroke

                            Text {
                                anchors.centerIn: parent
                                text: "🔍"
                                color: Theme.textFaint
                                font.pixelSize: 20
                            }
                        }

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "No packages found for '" + searchInput.text + "'"
                            color: Theme.text
                            font { family: Theme.fontUi; pixelSize: Theme.tBody; weight: Font.DemiBold }
                        }

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "Check spelling or switch the source filter above to All."
                            color: Theme.textDim
                            font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                        }
                    }

                    // Results Container
                    Column {
                        visible: !AppCenterState.searching && AppCenterState.searchResults.length > 0
                        anchors.fill: parent
                        spacing: Theme.s2

                        // Search Results Header Bar
                        Rectangle {
                            width: parent.width
                            height: 32
                            radius: Theme.rM
                            color: Theme.surfaceLow
                            border.width: 1
                            border.color: Theme.stroke

                            Row {
                                anchors {
                                    left: parent.left; leftMargin: Theme.s3
                                    right: parent.right; rightMargin: Theme.s3
                                    verticalCenter: parent.verticalCenter
                                }
                                spacing: Theme.s2

                                Text {
                                    text: "Found " + AppCenterState.searchResults.length + " packages"
                                    color: Theme.text
                                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.DemiBold }
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Text {
                                    text: "· Source: " + AppCenterState.sourceFilter.toUpperCase()
                                    color: Theme.textDim
                                    font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Item { width: 1; height: 1 }
                            }
                        }

                        ListView {
                            id: searchList
                            width: parent.width
                            height: parent.height - 40
                            spacing: Theme.s2
                            boundsBehavior: Flickable.StopAtBounds
                            clip: true
                            reuseItems: true
                            cacheBuffer: 200
                            model: AppCenterState.searchResults

                            delegate: AppCard {
                                width: searchList.width - (searchScrollBar.visible ? 8 : 0)
                                appData: modelData
                            }
                        }
                    }

                    GlassScrollBar {
                        id: searchScrollBar
                        flickable: searchList
                        anchors.topMargin: 40
                    }
                }

                // ── View C: System Updates View ─────────────────────────
                Item {
                    visible: AppCenterState.activeTab === "updates"
                    anchors.fill: parent

                    // Up to date Empty State
                    Column {
                        visible: AppCenterState.updates.length === 0
                        anchors.centerIn: parent
                        spacing: Theme.s3

                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 64; height: 64; radius: 32
                            color: Theme.alpha(Theme.ember, 0.14)
                            border.width: 1
                            border.color: Theme.alpha(Theme.ember, 0.40)

                            Text {
                                anchors.centerIn: parent
                                text: "✓"
                                color: Theme.ember
                                font { family: Theme.fontMono; pixelSize: 28; weight: Font.Bold }
                            }
                        }

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "Your system is up to date"
                            color: Theme.text
                            font { family: Theme.fontUi; pixelSize: Theme.tTitle; weight: Font.DemiBold }
                        }

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "All official Arch, AUR, and Flatpak packages are running the latest releases."
                            color: Theme.textDim
                            font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                        }

                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter
                            implicitHeight: 30
                            implicitWidth: chkTxt.implicitWidth + 24
                            radius: Theme.rPill
                            color: chkMa.containsMouse ? Theme.surfaceHigh : Theme.surfaceLow
                            border.width: 1
                            border.color: chkMa.containsMouse ? Theme.ember : Theme.stroke

                            MouseArea {
                                id: chkMa
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: AppCenterState.checkUpdates()
                            }

                            Text {
                                id: chkTxt
                                anchors.centerIn: parent
                                text: AppCenterState.checkingUpdates ? "Checking updates..." : "Check Again ↻"
                                color: Theme.ember
                                font { family: Theme.fontMono; pixelSize: 10; weight: Font.DemiBold }
                            }
                        }
                    }

                    // Pending Updates List
                    Column {
                        visible: AppCenterState.updates.length > 0
                        anchors.fill: parent
                        spacing: Theme.s2

                        // Top summary banner with Master Upgrade button
                        Rectangle {
                            width: parent.width
                            height: 42
                            radius: Theme.rM
                            color: Theme.alpha(Theme.gilded, 0.12)
                            border.width: 1
                            border.color: Theme.alpha(Theme.gilded, 0.35)

                            Row {
                                anchors {
                                    left: parent.left; leftMargin: Theme.s3
                                    right: parent.right; rightMargin: Theme.s3
                                    verticalCenter: parent.verticalCenter
                                }
                                spacing: Theme.s3

                                Rectangle {
                                    width: 8; height: 8; radius: 4
                                    color: Theme.gilded
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 2
                                    Text {
                                        text: AppCenterState.updates.length + " pending packages ready for update"
                                        color: Theme.gilded
                                        font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.Bold }
                                    }
                                    Text {
                                        text: "Arch Linux official repos & AUR community"
                                        color: Theme.textDim
                                        font { family: Theme.fontUi; pixelSize: Theme.tMicro }
                                    }
                                }

                                Item { width: 1; height: 1 }

                                // Upgrade entire system button
                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    implicitHeight: 28
                                    implicitWidth: upAllTxt.implicitWidth + 18
                                    radius: Theme.rPill
                                    color: upAllHit.containsMouse ? Theme.alpha(Theme.gilded, 0.35) : Theme.alpha(Theme.gilded, 0.20)
                                    border.width: 1
                                    border.color: upAllHit.containsMouse ? Theme.gilded : Theme.alpha(Theme.gilded, 0.55)
                                    scale: upAllHit.pressed ? 0.94 : (upAllHit.containsMouse ? 1.02 : 1.0)

                                    MouseArea {
                                        id: upAllHit
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: AppCenterState.updateAll()
                                    }

                                    Text {
                                        id: upAllTxt
                                        anchors.centerIn: parent
                                        text: "Upgrade System ⇧"
                                        color: Theme.gilded
                                        font { family: Theme.fontMono; pixelSize: 10; weight: Font.Bold }
                                    }
                                }
                            }
                        }

                        ListView {
                            id: updateListView
                            width: parent.width
                            height: parent.height - 50
                            spacing: Theme.s2
                            boundsBehavior: Flickable.StopAtBounds
                            clip: true
                            reuseItems: true
                            cacheBuffer: 200
                            model: AppCenterState.updates

                            delegate: Rectangle {
                                width: updateListView.width - (updateScrollBar.visible ? 8 : 0)
                                height: 56
                                radius: Theme.rM
                                color: pop.cardBg
                                border.width: 1
                                border.color: pop.cardBorder

                                Row {
                                    anchors {
                                        left: parent.left; leftMargin: Theme.s3
                                        right: parent.right; rightMargin: Theme.s3
                                        verticalCenter: parent.verticalCenter
                                    }
                                    spacing: Theme.s3

                                    Rectangle {
                                        width: 8; height: 8; radius: 4
                                        color: Theme.gilded
                                        anchors.verticalCenter: parent.verticalCenter
                                    }

                                    Column {
                                        width: parent.width - 180
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 2

                                        Row {
                                            spacing: Theme.s2
                                            Text {
                                                text: modelData.name
                                                color: Theme.text
                                                font { family: Theme.fontMono; pixelSize: Theme.tBody; weight: Font.DemiBold }
                                                elide: Text.ElideRight
                                            }
                                            Rectangle {
                                                implicitHeight: 16
                                                implicitWidth: srcText.implicitWidth + 8
                                                radius: 8
                                                color: modelData.source === "aur"
                                                       ? Theme.alpha(Theme.crimson, 0.20)
                                                       : Theme.alpha(Theme.ember, 0.20)
                                                Text {
                                                    id: srcText
                                                    anchors.centerIn: parent
                                                    text: (modelData.source || "arch").toUpperCase()
                                                    color: modelData.source === "aur" ? Theme.crimsonText : Theme.ember
                                                    font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                                                }
                                            }
                                        }

                                        Row {
                                            spacing: 6
                                            Text {
                                                text: modelData.current || "current"
                                                color: Theme.textDim
                                                font { family: Theme.fontMono; pixelSize: Theme.tCaption }
                                            }
                                            Text {
                                                text: "→"
                                                color: Theme.textFaint
                                                font { family: Theme.fontMono; pixelSize: Theme.tCaption }
                                            }
                                            Text {
                                                text: modelData.new || "latest"
                                                color: Theme.gilded
                                                font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                                            }
                                        }
                                    }

                                    // 1-Click Update Button for Single Package
                                    Rectangle {
                                        id: singleUpdBtn
                                        implicitHeight: 28
                                        implicitWidth: 84
                                        radius: Theme.rPill
                                        color: singleUpdHit.containsMouse ? Theme.alpha(Theme.gilded, 0.28) : Theme.surfaceLow
                                        border.width: 1
                                        border.color: singleUpdHit.containsMouse ? Theme.gilded : Theme.stroke
                                        scale: singleUpdHit.pressed ? 0.95 : 1.0

                                        MouseArea {
                                            id: singleUpdHit
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: AppCenterState.installApp(modelData.source || "arch", modelData.name)
                                        }

                                        Text {
                                            anchors.centerIn: parent
                                            text: "Update"
                                            color: Theme.gilded
                                            font { family: Theme.fontMono; pixelSize: 10; weight: Font.DemiBold }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    GlassScrollBar {
                        id: updateScrollBar
                        flickable: updateListView
                        anchors.topMargin: 50
                    }
                }

                // ── View D: Package Engines Management View ─────────────
                Item {
                    id: enginesView
                    visible: AppCenterState.activeTab === "engines"
                    anchors.fill: parent

                    Column {
                        anchors.fill: parent
                        spacing: Theme.s2

                        // Engines Overview Banner
                        Rectangle {
                            width: parent.width
                            height: 44
                            radius: Theme.rM
                            color: Theme.surfaceLow
                            border.width: 1
                            border.color: Theme.stroke

                            Row {
                                anchors {
                                    left: parent.left; leftMargin: Theme.s3
                                    right: parent.right; rightMargin: Theme.s3
                                    verticalCenter: parent.verticalCenter
                                }
                                spacing: Theme.s3

                                Rectangle {
                                    width: 28; height: 28; radius: 8
                                    color: Theme.alpha(Theme.crimson, 0.18)
                                    border.width: 1
                                    border.color: Theme.alpha(Theme.crimson, 0.40)
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text {
                                        anchors.centerIn: parent
                                        text: "⚙"
                                        color: Theme.crimsonText
                                        font.pixelSize: 13
                                    }
                                }

                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 2
                                    Text {
                                        text: "Modular Package Engines"
                                        color: Theme.text
                                        font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.DemiBold }
                                    }
                                    Text {
                                        text: "1-click enable Arch, AUR, Flathub, Snap, and AppImage runtimes."
                                        color: Theme.textDim
                                        font { family: Theme.fontUi; pixelSize: Theme.tMicro }
                                    }
                                }
                            }
                        }

                        // Scrollable Engine Cards List
                        Flickable {
                            id: enginesFlick
                            width: parent.width
                            height: parent.height - 52
                            contentHeight: enginesCol.implicitHeight
                            boundsBehavior: Flickable.StopAtBounds
                            clip: true

                            Column {
                                id: enginesCol
                                width: parent.width - (enginesScrollBar.visible ? 8 : 0)
                                spacing: Theme.s2

                                // Pacman Engine Card (Arch Linux ALPM)
                                EngineCard {
                                    width: parent.width
                                    managerId: "pacman"
                                    monogram: "ALPM"
                                    name: "Pacman (ALPM)"
                                    desc: "Arch Linux official package manager for core, extra, and system binaries."
                                    installed: true
                                    activeText: "Arch Core Active ✓"
                                    badgeText: "PACMAN"
                                    badgeColor: Theme.ember
                                }

                                // Paru AUR Helper Card
                                EngineCard {
                                    width: parent.width
                                    managerId: "paru"
                                    monogram: "PARU"
                                    name: "Paru (AUR Helper)"
                                    desc: "Blazing fast Rust-based AUR helper with pacman ALPM integration and 90,000+ packages."
                                    installed: AppCenterState.managers.paru ? AppCenterState.managers.paru.installed : (AppCenterState.managers.aur ? AppCenterState.managers.aur.installed : false)
                                    activeText: "Paru Active ✓"
                                    enableActionText: "Install Paru"
                                    badgeText: "AUR (RUST)"
                                    badgeColor: Theme.alarm
                                    onEnableRequested: AppCenterState.enableManager("paru")
                                }

                                // Yay AUR Helper Card
                                EngineCard {
                                    width: parent.width
                                    managerId: "yay"
                                    monogram: "YAY"
                                    name: "Yay (AUR Helper)"
                                    desc: "Popular Go-based AUR helper with interactive search, minimal dependencies, and pacman syntax."
                                    installed: AppCenterState.managers.yay ? AppCenterState.managers.yay.installed : false
                                    activeText: "Yay Active ✓"
                                    enableActionText: "Install Yay"
                                    badgeText: "AUR (GO)"
                                    badgeColor: Theme.alarm
                                    onEnableRequested: AppCenterState.enableManager("yay")
                                }

                                // Flatpak & Flathub Universal Engine Card
                                EngineCard {
                                    width: parent.width
                                    managerId: "flatpak"
                                    monogram: "FLAT"
                                    name: "Flatpak & Flathub Universal"
                                    desc: "Sandboxed application runtime with access to thousands of universal desktop applications from Flathub."
                                    installed: AppCenterState.managers.flatpak ? AppCenterState.managers.flatpak.installed : false
                                    activeText: "Flathub Active ✓"
                                    enableActionText: "Enable Flatpak"
                                    badgeText: "FLATHUB"
                                    badgeColor: Theme.gilded
                                    onEnableRequested: AppCenterState.enableManager("flatpak")
                                }

                                // Snapd Universal Packages Engine Card
                                EngineCard {
                                    width: parent.width
                                    managerId: "snap"
                                    monogram: "SNAP"
                                    name: "Snapd Universal Packages"
                                    desc: "Canonical universal snap packages with strict AppArmor containment and automatic background updates."
                                    installed: AppCenterState.managers.snap ? AppCenterState.managers.snap.installed : false
                                    activeText: "Snapd Active ✓"
                                    enableActionText: "Install Snapd"
                                    badgeText: "SNAP"
                                    badgeColor: Theme.crimson
                                    onEnableRequested: AppCenterState.enableManager("snap")
                                }

                                // AppImage Support Engine Card
                                EngineCard {
                                    width: parent.width
                                    managerId: "appimage"
                                    monogram: "IMAGE"
                                    name: "AppImage Support & GearLever"
                                    desc: "Portable standalone Linux applications with FUSE2 execution and automated desktop integration."
                                    installed: AppCenterState.managers.appimage ? AppCenterState.managers.appimage.installed : false
                                    activeText: "AppImage Ready ✓"
                                    enableActionText: "Install AppImage"
                                    badgeText: "APPIMAGE"
                                    badgeColor: Theme.crimsonText
                                    onEnableRequested: AppCenterState.enableManager("appimage")
                                }
                            }
                        }
                    }

                    GlassScrollBar {
                        id: enginesScrollBar
                        flickable: enginesFlick
                        anchors.topMargin: 52
                    }
                }
            }
        }
    }

    // ── Reusable Glass ScrollBar Component ──────────────────────────────
    component GlassScrollBar: Rectangle {
        id: sbar
        required property Flickable flickable
        anchors {
            right: parent.right
            rightMargin: 1
            top: parent.top
            bottom: parent.bottom
            topMargin: 2
            bottomMargin: 2
        }
        width: 3.5
        radius: 1.75
        color: Qt.rgba(1, 1, 1, 0.04)
        visible: flickable && flickable.contentHeight > flickable.height

        Rectangle {
            id: thumb
            width: parent.width
            radius: parent.radius
            height: Math.max(22, (sbar.flickable.height / Math.max(sbar.flickable.contentHeight, 1)) * sbar.flickable.height)
            y: Math.max(0, Math.min(sbar.flickable.height - height,
                (sbar.flickable.contentY / Math.max(sbar.flickable.contentHeight - sbar.flickable.height, 1)) * (sbar.flickable.height - height)))
            color: Theme.alpha(Theme.crimson, 0.55)
            opacity: (sbar.flickable.moving || sbar.flickable.flicking || thumbHit.containsMouse) ? 1.0 : 0.28
            Behavior on opacity { NumberAnimation { duration: Theme.durFast } }

            MouseArea {
                id: thumbHit
                anchors.fill: parent
                hoverEnabled: true
            }
        }
    }

    // ── Reusable App Card Component ─────────────────────────────────────
    component AppCard: Rectangle {
        id: card
        property var appData: ({})
        readonly property color cardBg: Qt.rgba(0.09, 0.043, 0.05, 0.75)
        readonly property color cardBorder: Qt.rgba(1, 1, 1, 0.08)

        height: 68
        radius: Theme.rM
        color: cardHit.containsMouse ? Theme.surfaceHigh : card.cardBg
        border.width: 1
        border.color: cardHit.containsMouse ? Theme.alpha(card.sourceAccentColor, 0.45) : card.cardBorder
        scale: cardHit.pressed ? 0.99 : 1.0

        Behavior on color { ColorAnimation { duration: Theme.durFast } }
        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
        Behavior on scale { NumberAnimation { duration: Theme.durFast } }

        readonly property string appId: (card.appData && (card.appData.id || card.appData.name)) || ""
        readonly property string appTitle: (card.appData && (card.appData.title || card.appData.name)) || ""
        readonly property string appDesc: (card.appData && card.appData.description) || ""
        readonly property string appSource: (card.appData && card.appData.source ? card.appData.source : "aur").toUpperCase()
        readonly property bool isInstalled: !!(card.appData && card.appData.installed)
        readonly property bool isInstalling: AppCenterState.installingId === card.appId
        readonly property color sourceAccentColor: card.appSource === "AUR"
                                                   ? Theme.alarm
                                                   : (card.appSource === "FLATPAK" ? Theme.gilded : Theme.ember)

        readonly property string appIcon: (card.appData && card.appData.icon) ? String(card.appData.icon) : ""
        readonly property bool hasIconUrl: appIcon.indexOf("http://") === 0 || appIcon.indexOf("https://") === 0 || appIcon.indexOf("file://") === 0 || appIcon.indexOf("/") === 0

        MouseArea {
            id: cardHit
            anchors.fill: parent
            hoverEnabled: true
        }

        Row {
            anchors {
                left: parent.left; leftMargin: Theme.s3
                right: parent.right; rightMargin: Theme.s3
                verticalCenter: parent.verticalCenter
            }
            spacing: Theme.s3

            // App Monogram / Remote Icon Box
            Rectangle {
                width: 42
                height: 42
                radius: 11
                color: Theme.alpha(card.sourceAccentColor, 0.16)
                border.width: 1
                border.color: Theme.alpha(card.sourceAccentColor, 0.40)
                anchors.verticalCenter: parent.verticalCenter
                scale: cardHit.containsMouse ? 1.05 : 1.0
                Behavior on scale { NumberAnimation { duration: Theme.durFast } }

                // Remote Flathub icon when available
                Image {
                    id: remoteIcon
                    anchors.centerIn: parent
                    width: 28
                    height: 28
                    source: card.hasIconUrl ? card.appIcon : ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    smooth: true
                    mipmap: true
                    visible: card.hasIconUrl && status === Image.Ready
                }

                Text {
                    anchors.centerIn: parent
                    text: card.appTitle.length > 0 ? card.appTitle.charAt(0).toUpperCase() : "✦"
                    color: card.sourceAccentColor
                    font { family: Theme.fontMono; pixelSize: 18; weight: Font.Bold }
                    visible: !card.hasIconUrl || remoteIcon.status !== Image.Ready
                }

                // Tiny indicator dot in corner
                Rectangle {
                    anchors { bottom: parent.bottom; right: parent.right; margins: 3 }
                    width: 5; height: 5; radius: 2.5
                    color: card.isInstalled ? Theme.ember : card.sourceAccentColor
                }
            }

            // Info Column
            Column {
                width: parent.width - 170
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3

                Row {
                    spacing: Theme.s2
                    width: parent.width

                    Text {
                        text: card.appTitle
                        color: Theme.text
                        font { family: Theme.fontUi; pixelSize: Theme.tBody; weight: Font.DemiBold }
                        elide: Text.ElideRight
                    }

                    // Source Badge Pill
                    Rectangle {
                        implicitHeight: 16
                        implicitWidth: bTxt.implicitWidth + 8
                        radius: 8
                        color: Theme.alpha(card.sourceAccentColor, 0.18)
                        border.width: 1
                        border.color: Theme.alpha(card.sourceAccentColor, 0.40)

                        Text {
                            id: bTxt
                            anchors.centerIn: parent
                            text: card.appSource
                            color: card.sourceAccentColor
                            font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                        }
                    }

                    // Official Arch Repo Pill (e.g. extra, core)
                    Rectangle {
                        visible: !!(card.appData && card.appData.repo)
                        implicitHeight: 16
                        implicitWidth: repoTxt.implicitWidth + 8
                        radius: 8
                        color: Theme.alpha(Theme.ember, 0.14)
                        border.width: 1
                        border.color: Theme.alpha(Theme.ember, 0.35)

                        Text {
                            id: repoTxt
                            anchors.centerIn: parent
                            text: (card.appData && card.appData.repo ? card.appData.repo : "").toUpperCase()
                            color: Theme.ember
                            font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                        }
                    }

                    // Category Pill (clickable to filter)
                    Rectangle {
                        visible: !!(card.appData && card.appData.category)
                        implicitHeight: 16
                        implicitWidth: catTxt.implicitWidth + 10
                        radius: 8
                        color: Theme.surfaceLow
                        border.width: 1
                        border.color: Theme.stroke

                        Text {
                            id: catTxt
                            anchors.centerIn: parent
                            text: (card.appData && card.appData.category) ? card.appData.category : ""
                            color: Theme.textDim
                            font { family: Theme.fontUi; pixelSize: 8; weight: Font.Medium }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (card.appData && card.appData.category) {
                                    AppCenterState.setCategory(card.appData.category);
                                }
                            }
                        }
                    }

                    // Popularity Pill (stars/rating)
                    Rectangle {
                        visible: !!(card.appData && card.appData.popularity && card.appData.popularity > 0)
                        implicitHeight: 16
                        implicitWidth: popTxt.implicitWidth + 8
                        radius: 8
                        color: Theme.alpha(Theme.gilded, 0.14)
                        border.width: 1
                        border.color: Theme.alpha(Theme.gilded, 0.35)

                        Text {
                            id: popTxt
                            anchors.centerIn: parent
                            text: "★ " + (card.appData && card.appData.popularity ? card.appData.popularity : "")
                            color: Theme.gilded
                            font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                        }
                    }

                    // Votes Pill (AUR votes)
                    Rectangle {
                        visible: !!(card.appData && card.appData.votes && card.appData.votes > 0)
                        implicitHeight: 16
                        implicitWidth: voteTxt.implicitWidth + 8
                        radius: 8
                        color: Theme.alpha(Theme.crimson, 0.14)
                        border.width: 1
                        border.color: Theme.alpha(Theme.crimson, 0.35)

                        Text {
                            id: voteTxt
                            anchors.centerIn: parent
                            text: "▲ " + (card.appData && card.appData.votes ? card.appData.votes : "")
                            color: Theme.crimsonText
                            font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                        }
                    }

                    // Version
                    Text {
                        visible: !!(card.appData && card.appData.version && card.appData.version !== "latest" && card.appData.version !== "official")
                        text: "v" + (card.appData && card.appData.version ? card.appData.version : "")
                        color: Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: 9 }
                        elide: Text.ElideRight
                    }
                }

                Text {
                    width: parent.width
                    text: card.appDesc + (card.appData && card.appData.maintainer ? (" · by " + card.appData.maintainer) : "")
                    color: Theme.textDim
                    font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                    elide: Text.ElideRight
                }
            }

            // 1-Click Action Button
            Rectangle {
                id: actionBtn
                implicitHeight: 30
                implicitWidth: 94
                radius: Theme.rPill
                anchors.verticalCenter: parent.verticalCenter

                readonly property bool btnHovered: actHit.containsMouse

                color: card.isInstalling
                       ? Theme.alpha(Theme.gilded, 0.22)
                       : card.isInstalled
                       ? (btnHovered ? Theme.alpha(Theme.alarm, 0.22) : Theme.alpha(Theme.ember, 0.14))
                       : (btnHovered ? Theme.alpha(card.sourceAccentColor, 0.28) : Theme.surfaceLow)

                border.width: 1
                border.color: card.isInstalling
                             ? Theme.gilded
                             : card.isInstalled
                             ? (btnHovered ? Theme.alarm : Theme.alpha(Theme.ember, 0.40))
                             : (btnHovered ? card.sourceAccentColor : Theme.stroke)

                scale: actHit.pressed ? 0.94 : (btnHovered ? 1.03 : 1.0)
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                Behavior on scale { NumberAnimation { duration: Theme.durFast } }

                MouseArea {
                    id: actHit
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (card.isInstalled) {
                            AppCenterState.uninstallApp((card.appData && card.appData.source) || "aur", card.appId);
                        } else {
                            AppCenterState.installApp((card.appData && card.appData.source) || "aur", card.appId);
                        }
                    }
                }

                Row {
                    anchors.centerIn: parent
                    spacing: 4

                    Text {
                        visible: card.isInstalling
                        text: "◐"
                        color: Theme.gilded
                        font.pixelSize: 11
                        rotation: Theme.heartbeatPhase * 360
                    }

                    Text {
                        text: card.isInstalling ? "Installing..."
                            : card.isInstalled ? (actionBtn.btnHovered ? "Uninstall ✕" : "Installed ✓")
                            : "Install +"
                        color: card.isInstalling ? Theme.gilded
                             : card.isInstalled ? (actionBtn.btnHovered ? Theme.alarm : Theme.ember)
                             : (actionBtn.btnHovered ? card.sourceAccentColor : Theme.text)
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.DemiBold }
                    }
                }
            }
        }
    }

    // ── Reusable Engine Card Component ──────────────────────────────────
    component EngineCard: Rectangle {
        id: engCard
        property string managerId: ""
        property string name: ""
        property string desc: ""
        property string monogram: ""
        property bool installed: false
        property string activeText: "Active"
        property string inactiveText: "Not Installed"
        property string enableActionText: ""
        property string badgeText: ""
        property color badgeColor: Theme.crimson
        signal enableRequested()

        readonly property color cardBg: Qt.rgba(0.09, 0.043, 0.05, 0.75)
        readonly property color cardBorder: Qt.rgba(1, 1, 1, 0.08)
        readonly property bool isEnabling: AppCenterState.enablingManager === engCard.managerId

        height: 76
        radius: Theme.rM
        color: engHit.containsMouse ? Theme.surfaceHigh : engCard.cardBg
        border.width: 1
        border.color: engHit.containsMouse ? Theme.alpha(engCard.badgeColor, 0.45) : engCard.cardBorder
        scale: engHit.pressed ? 0.99 : 1.0
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
        Behavior on scale { NumberAnimation { duration: Theme.durFast } }

        MouseArea {
            id: engHit
            anchors.fill: parent
            hoverEnabled: true
        }

        Row {
            anchors {
                left: parent.left; leftMargin: Theme.s3
                right: parent.right; rightMargin: Theme.s3
                verticalCenter: parent.verticalCenter
            }
            spacing: Theme.s3

            // Engine Monogram Icon Box
            Rectangle {
                width: 44
                height: 44
                radius: 12
                color: Theme.alpha(engCard.badgeColor, 0.16)
                border.width: 1
                border.color: Theme.alpha(engCard.badgeColor, 0.40)
                anchors.verticalCenter: parent.verticalCenter
                scale: engHit.containsMouse ? 1.05 : 1.0
                Behavior on scale { NumberAnimation { duration: Theme.durFast } }

                Text {
                    anchors.centerIn: parent
                    text: engCard.monogram !== "" ? engCard.monogram : engCard.name.charAt(0)
                    color: engCard.badgeColor
                    font { family: Theme.fontMono; pixelSize: engCard.monogram.length > 4 ? 9 : 12; weight: Font.Bold }
                }

                // Live status beacon dot
                Rectangle {
                    anchors { bottom: parent.bottom; right: parent.right; margins: 3 }
                    width: 6; height: 6; radius: 3
                    color: engCard.installed ? Theme.ember : Theme.gilded
                }
            }

            // Details Column
            Column {
                width: parent.width - 235
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3

                Row {
                    spacing: Theme.s2
                    Text {
                        text: engCard.name
                        color: Theme.text
                        font { family: Theme.fontUi; pixelSize: Theme.tBody; weight: Font.DemiBold }
                        elide: Text.ElideRight
                    }

                    Rectangle {
                        implicitHeight: 16
                        implicitWidth: ebText.implicitWidth + 8
                        radius: 8
                        color: Theme.alpha(engCard.badgeColor, 0.18)
                        border.width: 1
                        border.color: Theme.alpha(engCard.badgeColor, 0.40)
                        Text {
                            id: ebText
                            anchors.centerIn: parent
                            text: engCard.badgeText
                            color: engCard.badgeColor
                            font { family: Theme.fontMono; pixelSize: 8; weight: Font.Bold }
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: engCard.desc
                    color: Theme.textDim
                    font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                    elide: Text.ElideRight
                }
            }

            // Status or 1-Click Enable Button
            Item {
                width: 175
                height: 32
                anchors.verticalCenter: parent.verticalCenter

                // When currently enabling / installing
                Row {
                    visible: engCard.isEnabling
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6

                    Text {
                        text: "◐"
                        color: Theme.gilded
                        font.pixelSize: 12
                        rotation: Theme.heartbeatPhase * 360
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Text {
                        text: "Installing Engine..."
                        color: Theme.gilded
                        font { family: Theme.fontMono; pixelSize: 10; weight: Font.DemiBold }
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                // When installed
                Rectangle {
                    visible: engCard.installed && !engCard.isEnabling
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    implicitHeight: 28
                    implicitWidth: instRow.implicitWidth + 16
                    radius: Theme.rPill
                    color: Theme.alpha(Theme.ember, 0.14)
                    border.width: 1
                    border.color: Theme.alpha(Theme.ember, 0.40)

                    Row {
                        id: instRow
                        anchors.centerIn: parent
                        spacing: 5

                        Rectangle {
                            width: 6; height: 6; radius: 3
                            color: Theme.ember
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Text {
                            text: engCard.activeText
                            color: Theme.ember
                            font { family: Theme.fontMono; pixelSize: 10; weight: Font.Medium }
                        }
                    }
                }

                // When NOT installed -> 1-Click Install Button!
                Rectangle {
                    visible: !engCard.installed && !engCard.isEnabling
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    implicitHeight: 30
                    implicitWidth: enbText.implicitWidth + 22
                    radius: Theme.rPill
                    color: enbHit.containsMouse ? Theme.alpha(engCard.badgeColor, 0.28) : Theme.alpha(engCard.badgeColor, 0.16)
                    border.width: 1
                    border.color: enbHit.containsMouse ? engCard.badgeColor : Theme.alpha(engCard.badgeColor, 0.45)
                    scale: enbHit.pressed ? 0.94 : (enbHit.containsMouse ? 1.03 : 1.0)
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                    Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                    Behavior on scale { NumberAnimation { duration: Theme.durFast } }

                    MouseArea {
                        id: enbHit
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: engCard.enableRequested()
                    }

                    Row {
                        anchors.centerIn: parent
                        spacing: 5

                        Text {
                            text: "+"
                            color: engCard.badgeColor
                            font { family: Theme.fontMono; pixelSize: 11; weight: Font.Bold }
                        }

                        Text {
                            id: enbText
                            text: engCard.enableActionText !== "" ? engCard.enableActionText : ("Install " + engCard.name)
                            color: engCard.badgeColor
                            font { family: Theme.fontMono; pixelSize: 10; weight: Font.DemiBold }
                        }
                    }
                }
            }
        }
    }
}
