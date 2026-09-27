import QtQuick
import QtQuick.Controls
import Quickshell.Services.Mpris
import "../common"
import "../components"

// Compact now-playing capsule: shows only when a player is active.
// Built on the unified BarBox obsidian glass system.
BarBox {
    id: root

    property bool compact: false

    property var player: {
        var ps = Mpris.players;
        for (var i = 0; i < ps.length; i++)
            if (ps[i].playbackState === MprisPlaybackState.Playing) return ps[i];
        return ps.length > 0 ? ps[0] : null;
    }

    visible: player != null
    implicitWidth: Math.min(row.implicitWidth + Theme.s3 * 2, 280)
    interactive: false
    Behavior on implicitWidth { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
    HoverTip { target: root; hovered: root.compact && hov.hovered; text: trackText.text }

    HoverHandler { id: hov }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: root.compact ? Theme.s1 : Theme.s2

        // Animated micro-equalizer when playing, music glyph when paused
        Item {
            width: 12
            height: 12
            anchors.verticalCenter: parent.verticalCenter

            Row {
                anchors.bottom: parent.bottom
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 2
                visible: root.player && root.player.playbackState === MprisPlaybackState.Playing

                Repeater {
                    model: 3
                    Rectangle {
                        required property int index
                        width: 2
                        radius: 1
                        gradient: Gradient {
                            orientation: Gradient.Vertical
                            GradientStop { position: 0.0; color: Theme.crimsonText }
                            GradientStop { position: 1.0; color: Theme.alpha(Theme.crimsonText, 0.45) }
                        }
                        height: {
                            if (!root.player || root.player.playbackState !== MprisPlaybackState.Playing) return 3;
                            var phase = (Theme.heartbeatPhase + index * 0.33) % 1.0;
                            var s = 0.5 + 0.5 * Math.sin(phase * 2 * Math.PI);
                            return 3 + Math.round(s * 8);
                        }
                    }
                }
            }

            Text {
                visible: !root.player || root.player.playbackState !== MprisPlaybackState.Playing
                text: "♫"
                color: Theme.crimsonText
                font.pixelSize: 11
                anchors.centerIn: parent
            }
        }

        // Previous
        Text {
            text: "⏮"
            color: maP.containsMouse ? Theme.text : Theme.textFaint
            font.pixelSize: 11
            scale: maP.pressed ? 0.88 : (maP.containsMouse ? 1.15 : 1.0)
            Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
                id: maP
                anchors.fill: parent
                anchors.margins: -4
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (root.player && root.player.canGoPrevious) root.player.previous()
            }
        }

        // Play/Pause
        Text {
            text: root.player && root.player.playbackState === MprisPlaybackState.Playing ? "⏸" : "▶"
            color: maPlay.containsMouse ? Theme.text : Theme.crimsonText
            font.pixelSize: 13
            scale: maPlay.pressed ? 0.88 : (maPlay.containsMouse ? 1.15 : 1.0)
            Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
                id: maPlay
                anchors.fill: parent
                anchors.margins: -4
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (root.player && root.player.canTogglePlaying) root.player.togglePlaying()
            }
        }

        // Title · artist; compact mode keeps transport controls and exposes metadata by tooltip.
        Item {
            visible: !root.compact
            implicitWidth: Math.min(trackText.implicitWidth, 140)
            implicitHeight: trackText.implicitHeight
            anchors.verticalCenter: parent.verticalCenter

            Text {
                text: trackText.text
                color: Qt.rgba(0, 0, 0, 0.65)
                font: trackText.font
                elide: Text.ElideRight
                width: parent.implicitWidth
                anchors.centerIn: parent
                anchors.verticalCenterOffset: 1
            }

            Text {
                id: trackText
                text: (root.player ? root.player.trackTitle : "") +
                      (root.player && root.player.trackArtist ? " — " + root.player.trackArtist : "")
                color: hov.hovered ? Theme.text : Theme.textDim
                font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                elide: Text.ElideRight
                width: parent.implicitWidth
                anchors.centerIn: parent
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
        }

        // Next
        Text {
            text: "⏭"
            color: maN.containsMouse ? Theme.text : Theme.textFaint
            font.pixelSize: 11
            scale: maN.pressed ? 0.88 : (maN.containsMouse ? 1.15 : 1.0)
            Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
                id: maN
                anchors.fill: parent
                anchors.margins: -4
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (root.player && root.player.canGoNext) root.player.next()
            }
        }
    }
}
