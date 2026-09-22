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
        var parts = out.split("===");
        var re = /(\d+)\s+"([^"]+)"\s+"([^"]*)"/g;
        var m, arr = [];
        while ((m = re.exec(parts[0] || "")) !== null)
            arr.push({ "pos": parseInt(m[1]), "id": m[2], "name": m[3] });
        if (arr.length === 0)
            arr = [{ "pos": 0, "id": "", "name": "" }];
        desks = arr;
        current = (parts[1] || "").replace(/["\n]/g, "").replace(/^s\s+/, "").trim();
    }

    function switchTo(id) {
        setter.command = ["busctl", "--user", "set-property", "org.kde.KWin",
            "/VirtualDesktopManager", "org.kde.KWin.VirtualDesktopManager",
            "current", "s", id];
        setter.running = true;
        poll.running = true;
    }

    Timer {
        interval: 1500
        running: true
        repeat: true
        triggeredOnStart: true
        // Setting running=true mid-flight is a no-op until the next cycle,
        // so skip instead of stacking re-polls.
        onTriggered: if (!poll.running) poll.running = true
    }

    Process {
        id: poll
        command: ["sh", "-c",
            "busctl --user get-property org.kde.KWin /VirtualDesktopManager " +
            "org.kde.KWin.VirtualDesktopManager desktops 2>/dev/null; echo ===; " +
            "busctl --user get-property org.kde.KWin /VirtualDesktopManager " +
            "org.kde.KWin.VirtualDesktopManager current 2>/dev/null"]
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

            Rectangle {
                anchors.fill: parent
                radius: 4
                color: ma.containsMouse && !parent.isCurrent ? Theme.strokeStrong : Theme.surfaceHigh
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
            }
            Rectangle {
                anchors.fill: parent
                radius: 4
                opacity: parent.isCurrent ? 1.0 : 0.0
                Behavior on opacity { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutCubic } }
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.accent }
                    GradientStop { position: 1; color: Theme.accent2 }
                }

                // Micro specular rim highlight
                Rectangle {
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 0.5 }
                    height: 1
                    radius: 3
                    color: Qt.rgba(1, 1, 1, 0.45)
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

    Text {
        visible: root.currentName !== ""
        text: root.currentName
        color: Theme.textDim
        font { family: Theme.fontMono; pixelSize: Theme.tMicro; weight: Font.Medium; letterSpacing: 0.6 }
        anchors.verticalCenter: parent.verticalCenter
    }
}
