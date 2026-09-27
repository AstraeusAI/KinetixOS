pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import "."

// Streams app-crash / failed-service events from scripts/kinetix-errors.py
// (systemd journal watcher) into the notification system. The watcher only
// wakes on journal entries matching crash/unit-failure message ids, so it
// costs nothing while everything is healthy. Restarts itself if it dies.
QtObject {
    id: root

    property bool active: true
    readonly property string script: Quickshell.shellDir + "/../scripts/kinetix-errors.py"

    function handle(line) {
        var str = String(line).trim();
        if (str.charAt(0) !== "{") return;
        var ev;
        try { ev = JSON.parse(str); } catch (e) { return; }
        if (ev.type === "error") Notif.reportError(ev);
    }

    function simulate() { simProc.running = false; simProc.running = true; }

    property Process watcher: Process {
        command: ["python3", root.script, "watch"]
        running: root.active
        stdout: SplitParser { onRead: function (line) { root.handle(line); } }
        onExited: if (root.active) restart.start()
    }
    property Timer restart: Timer {
        interval: 5000
        onTriggered: root.watcher.running = true
    }
    property Process simProc: Process {
        command: ["python3", root.script, "simulate"]
        stdout: SplitParser { onRead: function (line) { root.handle(line); } }
    }
}
