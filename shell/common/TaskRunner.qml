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
    property string _lastPreviewCaptureUuid: ""
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

    // kinetix-tasks.py can only screenshot the *active* window (spectacle
    // -a), so every capture briefly activates the target and restores the
    // previous focus afterward — a real, visible focus switch for as long
    // as the capture takes. TaskPreview used to keep its own thumbnail
    // cache and wipe it every time the hovered taskbar group changed, so
    // simply moving the mouse across the taskbar re-triggered a capture
    // (and the two real focus switches it costs) for every window, every
    // time — the cause of windows appearing to switch on their own while
    // just hovering. Caching here instead, keyed by geometry and kept for
    // the life of the shell session, means a window is only ever captured
    // once (until it actually moves/resizes), so re-hovering it is free.
    property var thumbCache: ({})
    property var pendingThumbKeys: ({})
    property var pendingKeyForUuid: ({})

    function _thumbKey(uuid, x, y, w, h) {
        return uuid + "|" + (x || 0) + "," + (y || 0) + "," + (w || 0) + "," + (h || 0);
    }

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
                        var pendingKey = root.pendingKeyForUuid[state.uuid];
                        if (pendingKey) {
                            delete root.pendingKeyForUuid[state.uuid];
                            delete root.pendingThumbKeys[pendingKey];
                            if (state.ok && state.path) root.thumbCache[pendingKey] = state.path;
                        }
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
    function cachedThumbnail(uuid, x, y, w, h) {
        var path = root.thumbCache[root._thumbKey(uuid, x, y, w, h)];
        return path ? "file://" + path : "";
    }

    function captureThumbnail(uuid, x, y, w, h) {
        if (!uuid) return;
        var key = root._thumbKey(uuid, x, y, w, h);
        // Already cached, or a capture for this exact window+geometry is
        // already in flight — never fire a second real focus-switch for it.
        if (root.thumbCache[key] || root.pendingThumbKeys[key]) return;
        // Serialise captures so a previous capture's focus restoration is
        // fully complete before we start the next one. Interleaving them
        // made the daemon restore focus to the wrong window and caused
        // taskbar hover to feel like it was randomly switching windows.
        if (root._lastPreviewCaptureUuid !== "" && root._lastPreviewCaptureUuid !== uuid &&
            root.pendingKeyForUuid[root._lastPreviewCaptureUuid]) {
            return;
        }
        root.pendingThumbKeys[key] = true;
        root.pendingKeyForUuid[uuid] = key;
        root._lastPreviewCaptureUuid = uuid;
        proc.write("CAPTURE " + uuid + " " + (x || 0) + " " + (y || 0) + " " + (w || 0) + " " + (h || 0) + "\n");
    }
}
