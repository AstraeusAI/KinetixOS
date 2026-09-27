import QtQuick
import Quickshell.Io
import "../common"

// KWin virtual desktops over D-Bus (no standard Wayland protocol yet).
// Path verified on Plasma 6.7: /VirtualDesktopManager, iface
// org.kde.KWin.VirtualDesktopManager, desktops: a(uss) → pos, id, name.
Row {
    id: root
    spacing: Theme.s2

    property var desks: []
    property string current: ""
    property string currentName: {
        for (var i = 0; i < desks.length; i++)
            if (desks[i].id === current)
                return desks[i].name;
        return "";
    }

    function parse(out) {
        // Single busctl call prints one line per property:
        //   a(uss) N pos id name ...
        //   s "currentId"
        var lines = String(out).split("\n");
        var deskPart = "", curPart = "";
        for (var li = 0; li < lines.length; li++) {
            var l = lines[li];
            if (l.indexOf("a(uss)") === 0) deskPart = l;
            else if (l.indexOf("s ") === 0) curPart = l;
        }
        var re = /(\d+)\s+"([^"]+)"\s+"([^"]*)"/g;
        var m, arr = [];
        while ((m = re.exec(deskPart)) !== null)
            arr.push({ "pos": parseInt(m[1]), "id": m[2], "name": m[3] });
        if (arr.length === 0)
            arr = [{ "pos": 0, "id": "", "name": "" }];
        desks = arr;
        current = curPart.replace(/s\s+"([^"]*)"/, "$1").replace(/"/g, "").trim();
    }

    function switchTo(id) {
        setter.command = ["busctl", "--user", "set-property", "org.kde.KWin",
            "/VirtualDesktopManager", "org.kde.KWin.VirtualDesktopManager",
            "current", "s", id];
        setter.running = true;
        poll.running = true;
    }

    // Event-driven: KWin announces every desktop switch / add / remove /
    // rename on D-Bus, so one long-lived dbus-monitor replaces the old 2.5s
    // busctl poll (which forked a process from the shell every 2.5s). Each
    // signal just triggers one re-read. `poll.running` guards against
    // stacking reads when several signals arrive together.
    Process {
        id: kwinWatch
        running: true
        command: ["dbus-monitor", "--session",
            "type='signal',sender='org.kde.KWin',path='/VirtualDesktopManager'"]
        stdout: SplitParser {
            onRead: function(line) {
                if (line.indexOf("signal ") === 0 && !poll.running) poll.running = true;
            }
        }
        // restart if the monitor ever exits (session bus restart etc.)
        onExited: watchRestart.restart()
    }
    Timer { id: watchRestart; interval: 3000; onTriggered: kwinWatch.running = true }

    // Initial read, plus a slow safety net in case a signal is ever missed.
    Timer {
        interval: 30000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: if (!poll.running) poll.running = true
    }

    Process {
        id: poll
        // One busctl invocation for both properties — no sh wrapper, no
        // second spawn (busctl accepts multiple property names).
        command: ["busctl", "--user", "get-property", "org.kde.KWin",
            "/VirtualDesktopManager", "org.kde.KWin.VirtualDesktopManager",
            "desktops", "current"]
        stdout: StdioCollector {
            onStreamFinished: root.parse(this.text)
        }
    }

    Process { id: setter }

    Repeater {
        model: root.desks
        delegate: Item {
            required property var modelData
            property bool isCurrent: modelData.id === root.current
            width: isCurrent ? 22 : (ma.containsMouse ? 10 : 8)
            height: 8
            anchors.verticalCenter: parent.verticalCenter
            scale: ma.pressed ? 0.90 : 1.0

            Behavior on width { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutQuint } }
            Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }

            // Active workspace ambient drop-glow
            Rectangle {
                anchors.fill: parent
                anchors.margins: -2
                radius: 6
                color: "transparent"
                border.width: 1
                border.color: Theme.alpha(Theme.crimsonText, 0.40)
                opacity: parent.isCurrent ? 0.75 : 0.0
                Behavior on opacity { NumberAnimation { duration: Theme.durMed } }
            }

            Rectangle {
                anchors.fill: parent
                radius: 4
                color: ma.containsMouse && !parent.isCurrent ? Theme.alpha(Theme.crimson, 0.42) : Theme.alpha(Theme.crimson, 0.18)
                border.width: 1
                border.color: ma.containsMouse && !parent.isCurrent ? Theme.alpha(Theme.alarm, 0.65) : Theme.alpha(Theme.crimson, 0.28)
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
            }
            Rectangle {
                anchors.fill: parent
                radius: 4
                opacity: parent.isCurrent ? 1.0 : 0.0
                Behavior on opacity { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutCubic } }
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.crimson }
                    GradientStop { position: 1; color: Theme.crimsonText }
                }

                // Micro specular rim highlight
                Rectangle {
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 0.5 }
                    height: 1
                    radius: 3
                    color: Qt.rgba(1, 1, 1, 0.55)
                }
            }

            MouseArea {
                id: ma
                anchors.fill: parent
                anchors.margins: -4
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (parent.modelData.id !== "") root.switchTo(parent.modelData.id)
            }
        }
    }

    Item {
        visible: root.currentName !== ""
        implicitWidth: nameText.implicitWidth
        implicitHeight: nameText.implicitHeight
        anchors.verticalCenter: parent.verticalCenter

        Text {
            text: nameText.text
            color: Qt.rgba(0, 0, 0, 0.65)
            font: nameText.font
            anchors.centerIn: parent
            anchors.verticalCenterOffset: 1
        }

        Text {
            id: nameText
            text: root.currentName
            color: Theme.textDim
            font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.Medium; letterSpacing: 0.8 }
            anchors.centerIn: parent
        }
    }
}
