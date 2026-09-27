import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import Quickshell
import Quickshell.Widgets
import "../common"
import "../components"

// One app in the left dock. A pinned app, a running app, or both.
//
//   magnify   1.0 at rest, up to ~1.45 under the pointer (set by Dock)
//   pinned    shown in the favourites section
//   items     this app's live windows (TaskRunner data), [] when not running
//
// The icon is rendered once at its largest magnified size and scaled down,
// so magnification never re-rasterizes an icon while the pointer moves.
Item {
    id: root

    property string appName: ""
    property string iconSource: ""
    property bool pinned: false
    property var items: []
    property real magnify: 1.0
    property bool launching: false

    signal clicked()
    signal middleClicked()
    signal menuRequested()

    property real base: 42
    readonly property real size: base * magnify
    readonly property bool running: items.length > 0
    readonly property bool focused: {
        for (var i = 0; i < items.length; i++) if (items[i].active) return true;
        return false;
    }
    readonly property bool allMinimized: {
        if (items.length === 0) return false;
        for (var i = 0; i < items.length; i++) if (!items[i].minimized) return false;
        return true;
    }
    readonly property bool hot: ma.containsMouse
    readonly property bool lit: hot || focused

    implicitWidth: size
    implicitHeight: size

    // ── the app's own colour, sampled from its icon ──
    ColorQuantizer {
        id: quant
        source: root.iconSource
        depth: 3
        rescaleSize: 32
    }
    readonly property color accentTarget: Theme.appAccent(quant.colors)
    property color accent: accentTarget
    Behavior on accent { ColorAnimation { duration: 300 } }

    // ── launch bounce: hops away from the edge until the window shows up ──
    property real hop: 0
    SequentialAnimation {
        id: bounceAnim
        loops: 3
        NumberAnimation { target: root; property: "hop"; from: 0; to: 14; duration: 230; easing.type: Easing.OutQuad }
        NumberAnimation { target: root; property: "hop"; to: 0; duration: 300; easing.type: Easing.OutBounce }
    }
    onLaunchingChanged: if (launching) bounceAnim.restart()
    onRunningChanged: if (running) { bounceAnim.stop(); hop = 0; }

    Item {
        id: face
        width: root.size
        height: root.size
        x: root.hop
        scale: ma.pressed ? 0.9 : 1.0
        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutBack } }

        // ── rim + glow, in the launcher logo's language (components/GlowRim) ──
        // focused: a turning red → green → blue rim with a constant glow
        // running: a rim in the app's own colour
        // pinned:  a quiet neutral rim
        // hover brings the glow up in the app's own colour.
        // The glow sits behind the glass; the crisp rim is drawn on top below.
        GlowRim {
            anchors.fill: tile
            radius: tile.radius
            drawRim: false
            rgb: root.focused
            color: root.accent
            glowOpacity: root.focused ? 1.0 : (root.hot ? 0.8 : 0)
        }

        // ── glass tile ──
        Rectangle {
            id: tile
            anchors.fill: parent
            radius: root.size * 0.30
            antialiasing: true
            clip: true
            color: Qt.rgba(0.02, 0.022, 0.032, 0.55)
            border.width: 0

            // glass body: lit from above, deeper at the foot
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, root.hot ? 0.13 : 0.075) }
                    GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, root.hot ? 0.04 : 0.02) }
                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.18) }
                }
            }
            // the app's colour rising from the edge the dock is anchored to
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                opacity: root.focused ? 1 : (root.hot ? 0.7 : 0)
                Behavior on opacity { NumberAnimation { duration: 220 } }
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Theme.alpha(root.accent, 0.34) }
                    GradientStop { position: 0.6; color: Theme.alpha(root.accent, 0.08) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }
            // top specular line
            Rectangle {
                anchors { top: parent.top; topMargin: 1; left: parent.left; right: parent.right; leftMargin: tile.radius * 0.6; rightMargin: tile.radius * 0.6 }
                height: 1
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, root.lit ? 0.42 : 0.20) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }
            // lower lip: gives the glass thickness
            Rectangle {
                anchors { bottom: parent.bottom; bottomMargin: 1; left: parent.left; right: parent.right; leftMargin: tile.radius * 0.5; rightMargin: tile.radius * 0.5 }
                height: 1
                color: Qt.rgba(0, 0, 0, 0.30)
            }
            // hover sheen: one diagonal sweep of light on entry
            Rectangle {
                id: sheen
                width: 22
                height: parent.height * 2
                y: -parent.height / 2
                x: -width * 2
                rotation: 24
                opacity: 0
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.20) }
                    GradientStop { position: 1.0; color: "transparent" }
                }
                ParallelAnimation {
                    id: sheenAnim
                    NumberAnimation { target: sheen; property: "x"; from: -sheen.width * 2; to: tile.width + sheen.width; duration: 560; easing.type: Easing.InOutSine }
                    SequentialAnimation {
                        NumberAnimation { target: sheen; property: "opacity"; from: 0; to: 1; duration: 120 }
                        PauseAnimation { duration: 300 }
                        NumberAnimation { target: sheen; property: "opacity"; to: 0; duration: 140 }
                    }
                }
            }
        }

        GlowRim {
            anchors.fill: parent
            radius: tile.radius
            drawGlow: false
            thickness: root.focused ? 2.2 : 1.6
            rgb: root.focused
            color: root.running || root.hot ? root.accent : Qt.rgba(1, 1, 1, 0.6)
            rimOpacity: root.focused ? 1.0 : (root.hot ? 0.85 : (root.running ? 0.55 : 0.22))
        }
        // bright inner glass edge, like the logo ring's
        Rectangle {
            anchors.fill: parent
            anchors.margins: 2
            radius: Math.max(0, tile.radius - 2)
            color: "transparent"
            border.width: 0.8
            border.color: Qt.rgba(1, 1, 1, root.lit ? 0.26 : 0.12)
            Behavior on border.color { ColorAnimation { duration: 200 } }
        }

        // ── icon ──
        Item {
            anchors.centerIn: parent
            width: 64; height: 64
            scale: (root.size * 0.74) / 64

            IconImage {
                id: icon
                anchors.fill: parent
                implicitSize: 64
                source: root.iconSource
                asynchronous: true
                mipmap: true
                visible: false
            }
            MultiEffect {
                anchors.fill: icon
                source: icon
                visible: root.iconSource !== ""
                saturation: root.allMinimized ? -0.7 : 0
                opacity: root.allMinimized ? 0.62 : 1
                brightness: root.hot ? 0.05 : 0
                shadowEnabled: true
                shadowColor: Qt.rgba(0, 0, 0, 0.6)
                shadowBlur: 0.5
                shadowVerticalOffset: 3
                Behavior on saturation { NumberAnimation { duration: 240 } }
                Behavior on opacity { NumberAnimation { duration: 240 } }
            }
            // no icon resolved: a lettered squircle in the app's colour
            Rectangle {
                anchors.centerIn: parent
                visible: root.iconSource === ""
                width: 54; height: 54; radius: 16
                color: Theme.alpha(root.accent, 0.24)
                border.width: 1.5
                border.color: Theme.alpha(root.accent, 0.55)
                Text {
                    anchors.centerIn: parent
                    text: root.appName.charAt(0).toUpperCase()
                    color: Theme.text
                    font { family: Theme.fontUi; pixelSize: 26; weight: Font.Bold }
                }
            }
        }
    }

    // ── running indicators, on the screen edge side of the tile ──
    // focused window: tall glowing pill; other windows: dots (max 3);
    // minimized windows: hollow.
    Column {
        anchors { right: parent.left; rightMargin: 3; verticalCenter: parent.verticalCenter }
        spacing: 3
        Repeater {
            model: root.items.slice(0, 3)
            Rectangle {
                required property var modelData
                readonly property bool on: !!modelData.active
                anchors.horizontalCenter: parent.horizontalCenter
                width: 3
                height: on ? 15 : 4
                radius: 1.5
                color: modelData.minimized ? "transparent" : (on ? root.accent : Theme.alpha(root.accent, 0.75))
                border.width: modelData.minimized ? 1 : 0
                border.color: Theme.alpha(Theme.textDim, 0.9)
                Behavior on height { NumberAnimation { duration: 260; easing.type: Easing.OutQuint } }
                Rectangle {   // bloom
                    visible: parent.on
                    anchors.centerIn: parent
                    width: 10; height: parent.height + 8; radius: 5
                    z: -1
                    color: Theme.alpha(root.accent, 0.35)
                }
            }
        }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
        onContainsMouseChanged: if (containsMouse) sheenAnim.restart()
        onClicked: function(mouse) {
            if (mouse.button === Qt.LeftButton) root.clicked();
            else if (mouse.button === Qt.MiddleButton) root.middleClicked();
            else root.menuRequested();
        }
        onPressAndHold: root.menuRequested()
    }
}
