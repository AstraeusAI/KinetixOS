pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Live window inventory, sourced from scripts/kinetix-tasks.py rather than
// Quickshell.Wayland.ToplevelManager. KWin implements its own
// org_kde_plasma_window_management protocol, not the zwlr-foreign-toplevel
// (or ext-foreign-toplevel-list) family ToplevelManager speaks — confirmed
// by grepping both binaries' symbols, neither side references the other's
// protocol at all — so ToplevelManager.toplevels is permanently empty under
// KWin, taskbar or no taskbar, VM or bare metal. kinetix-tasks.py instead
// talks to KWin directly via its scripting/KRunner D-Bus interfaces and
// streams newline-delimited JSON over stdout.
QtObject {
    id: root

    property var windows: []
    property string activeUuid: ""
    readonly property var activeWindow: {
        for (var i = 0; i < windows.length; i++)
            if (windows[i].uuid === activeUuid) return windows[i];
        return null;
    }

    readonly property string scriptPath: Quickshell.shellDir + "/../scripts/kinetix-tasks.py"

    // Thumbnail capture happens inline in the stream process. Each request
    // writes a CAPTURE command; the daemon replies with a thumbnail record
    // before the next state push. UI layers listen to thumbnailReady.
    signal thumbnailReady(uuid: string, path: string)

    property Process proc: Process {
        command: ["python3", root.scriptPath, "--stream"]
        running: true
        stdinEnabled: true
        onExited: function (code) {
            if (code !== 0)
                Notif.reportInternal("Kinetix Shell", "Task manager stopped",
                    "scripts/kinetix-tasks.py exited with code " + code + ". Open windows will no longer update in the taskbar until the shell is restarted.");
        }
        stdout: SplitParser {
            onRead: function (line) {
                var str = String(line).trim();
                if (str === "" || str.charAt(0) !== "{") return;
                try {
                    var state = JSON.parse(str);
                    if (state.type === "thumbnail") {
                        root.thumbnailReady(state.uuid, state.path);
                        return;
                    }
                    root.windows = state.windows || [];
                    root.activeUuid = state.activeUuid || "";
                } catch (e) { /* malformed line — keep last-known state */ }
            }
        }
    }

    function activate(uuid) { if (uuid) proc.write("ACTIVATE " + uuid + "\n"); }
    function toggle(uuid) { if (uuid) proc.write("TOGGLE " + uuid + "\n"); }
    function close(uuid) { if (uuid) proc.write("CLOSE " + uuid + "\n"); }
    function setMinimized(uuid, mini) {
        if (uuid) proc.write("MINIMIZE " + uuid + " " + (mini ? "1" : "0") + "\n");
    }
    function toggleMaximize(uuid) { if (uuid) proc.write("MAXIMIZE " + uuid + "\n"); }
    function captureThumbnail(uuid, x, y, w, h) {
        if (!uuid) return;
        proc.write("CAPTURE " + uuid + " " + (x || 0) + " " + (y || 0) + " " + (w || 0) + " " + (h || 0) + "\n");
    }
}
