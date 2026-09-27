import QtQuick
import Quickshell
import Quickshell.Io
import "../common"
import "../components"

// Update capsule — shows a badge when `kinetix check` reports updates waiting,
// and launches `kinetix update` on click.
//
// The check is the same command a human runs, so the badge and the terminal
// can never disagree about whether updates exist. It runs as the ordinary
// user (checkupdates syncs into a throwaway database precisely so it can),
// on a slow timer rather than constantly — an update checker that polls the
// network every few seconds is a worse neighbour than one that does not.
BarBox {
    id: updateCap

    implicitWidth: 44
    interactive: true
    active: updateCap.count > 0
    activeColor: Theme.warn

    property int count: 0
    property bool kinetixUpdate: false
    property bool checking: false

    readonly property string tip: {
        if (updateCap.checking) return "Checking for updates\u2026";
        if (updateCap.count === 0) return "KinetixOS is up to date";
        if (updateCap.kinetixUpdate) return "KinetixOS update available \u2014 click to install";
        return updateCap.count + " system update(s) available \u2014 click to install";
    }

    function refresh() {
        if (!checkProc.running)
            checkProc.running = true;
    }

    function runUpdate() {
        // Updates need a TTY: pacman and sudo both want to prompt. Opening the
        // system terminal keeps the same flow a person would use by hand,
        // rather than trying to carry an interactive transaction with no pty.
        Quickshell.execDetached(["ghostty", "-e", "kinetix", "update"]);
    }

    onClicked: updateCap.runUpdate()
    Component.onCompleted: refresh()

    // Six hours: often enough to catch a security update in the same day,
    // rare enough that the sync is not a standing network cost.
    Timer {
        interval: 6 * 60 * 60 * 1000
        running: true
        repeat: true
        onTriggered: updateCap.refresh()
    }

    Process {
        id: checkProc
        command: ["kinetix", "check", "--json"]
        running: false
        onRunningChanged: updateCap.checking = running
        // Exit 10 means "updates available", not failure, so the exit code is
        // deliberately ignored — the JSON on stdout is the result.
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var d = JSON.parse(this.text);
                    updateCap.count = d.count | 0;
                    updateCap.kinetixUpdate = !!d.kinetix;
                } catch (e) {
                    updateCap.count = 0;
                    updateCap.kinetixUpdate = false;
                }
            }
        }
    }

    // Art: a download arrow into a tray, the conventional "install updates"
    // glyph. Drawn on a Canvas like the notification bell so it stays crisp
    // and themeable without an icon theme dependency.
    Item {
        id: updateArt
        anchors.centerIn: parent
        width: 18; height: 18

        KxIcon {
            id: updateCanvas
            anchors.centerIn: parent
            name: "download"
            size: 18
            color: updateCap.active ? Theme.warn
                   : (updateCap.hovered ? Theme.text : Theme.textDim)
        }

        // A slow rotate while checking, so a long sync reads as work rather
        // than a frozen badge. Pivots the whole glyph; harmless when idle.
        RotationAnimation on rotation {
            running: updateCap.checking
            from: 0; to: 360; duration: 1400
            loops: Animation.Infinite
        }
    }

    // Count badge, mirroring the notification bell's so the two read as one
    // family. Amber, to separate "action available" from "message waiting".
    Rectangle {
        visible: updateCap.count > 0
        anchors { top: parent.top; right: parent.right; topMargin: 4; rightMargin: 5 }
        width: Math.max(16, badgeLabel.implicitWidth + 8); height: 16; radius: 8
        color: Theme.warn
        border.width: 1.5
        border.color: Qt.rgba(0.06, 0.02, 0.03, 0.9)
        scale: updateCap.count > 0 ? 1 : 0
        Behavior on scale { NumberAnimation { duration: 260; easing.type: Easing.OutBack } }
        Text {
            id: badgeLabel
            anchors.centerIn: parent
            text: updateCap.count > 9 ? "9+" : String(updateCap.count)
            color: "#1a1206"
            font { family: Theme.fontMono; pixelSize: 9; weight: Font.Bold }
        }
    }

    HoverTip { target: updateCap; hovered: updateCap.hovered; text: updateCap.tip }
}
