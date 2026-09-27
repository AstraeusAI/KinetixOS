pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Installed-application index, shared by the app launcher and command palette.
// Scans .desktop files once at startup via scripts/argus-appscan.sh, which
// also resolves freedesktop icon names to absolute paths.
QtObject {
    id: root

    property var apps: []
    property bool ready: false
    property bool scanning: false
    property var favorites: []

    readonly property string scanScript: Quickshell.shellDir + "/../scripts/argus-appscan.py"

    property Process scanner: Process {
        command: ["python3", root.scanScript]
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                root.parse(this.text);
                root.scanning = false;
            }
        }
    }

    function reloadFavs() {
        if (favReader.running) favReader.running = false;
        favReader.command = ["sh", "-c", "cat " + AppIndex.favPath + " 2>/dev/null"];
        favReader.running = true;
    }

    function rescan() {
        if (scanner.running) {
            scanner.running = false;
        }
        scanning = true;
        scanner.command = ["python3", scanScript];
        scanner.running = true;
        reloadFavs();
    }

    // Auto-rescan periodically to detect background pacman/flatpak/AUR installs.
    // 120s: a full appscan costs ~44ms CPU + 20MB transient allocs, so 30s
    // polling burned ~1s of CPU per 10min for an event that happens a few
    // times a day; installs are still picked up on next open via refresh.
    property Timer autoRescanTimer: Timer {
        interval: 120000
        running: true
        repeat: true
        onTriggered: root.rescan()
    }

    property Process launcher: Process {}

    // ── favorites persistence (~/.config/argus/favorites.json) ──
    // Pins are matched by .desktop file path, so they survive rescans.
    readonly property string favPath: "$HOME/.config/argus/favorites.json"

    property Process favReader: Process {
        command: ["sh", "-c", "cat " + AppIndex.favPath + " 2>/dev/null"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: AppIndex.loadFavs(this.text)
        }
    }
    property Process favWriter: Process {}
    property Timer favSaveTimer: Timer {
        interval: 600
        onTriggered: AppIndex.saveFavsNow()
    }

    function loadFavs(text) {
        if (!text || text.trim() === "") return;
        try {
            var j = JSON.parse(text);
            if (j && j.favorites instanceof Array) favorites = j.favorites;
        } catch (e) { /* corrupt file → start with no pins */ }
    }
    function saveFavs() { favSaveTimer.restart(); }
    function saveFavsNow() {
        // Same guard as WidgetStore: a running writer must not be re-commanded.
        if (favWriter.running) { favSaveTimer.restart(); return; }
        var json = JSON.stringify({ "favorites": favorites });
        var esc = json.replace(/'/g, "'\\''");
        favWriter.command = ["sh", "-c",
            "mkdir -p $HOME/.config/argus && printf '%s' '" + esc + "' > " + favPath];
        favWriter.running = true;
    }

    function parse(text) {
        var lines = text.split("\n");
        var out = [];
        for (var i = 0; i < lines.length; i++) {
            if (lines[i] === "") continue;
            var p = lines[i].split("\t");
            if (p.length < 6 || p[0] === "") continue;
            out.push({ "name": p[0], "exec": p[1], "icon": p[2],
                       "comment": p[3], "categories": p[4], "file": p[5] });
        }
        out.sort(function(a, b) {
            return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1;
        });
        apps = out;
        ready = true;
    }

    function category(app) {
        var c = app.categories || "";
        var map = [
            ["Development", "Development"], ["Graphics", "Graphics"],
            ["WebBrowser", "Internet"], ["Network", "Internet"],
            ["AudioVideo", "Multimedia"], ["Audio", "Multimedia"], ["Video", "Multimedia"],
            ["Office", "Office"], ["Game", "Games"], ["Education", "Education"],
            ["Settings", "System"], ["System", "System"],
            ["TerminalEmulator", "Utilities"], ["Utility", "Utilities"]
        ];
        for (var i = 0; i < map.length; i++)
            if (c.indexOf(map[i][0]) >= 0) return map[i][1];
        return "Other";
    }

    readonly property var categoryOrder: ["All", "Favorites", "Development", "Graphics",
        "Internet", "Multimedia", "Office", "Games", "System", "Utilities", "Education", "Other"]

    function filter(query, cat) {
        var q = (query || "").toLowerCase();
        var out = [];
        for (var i = 0; i < apps.length; i++) {
            var a = apps[i];
            if (cat === "Favorites" && !isFav(a)) continue;
            if (cat && cat !== "All" && cat !== "Favorites" && category(a) !== cat) continue;
            if (q !== "" &&
                a.name.toLowerCase().indexOf(q) < 0 &&
                (a.comment || "").toLowerCase().indexOf(q) < 0) continue;
            out.push(a);
        }
        return out;
    }

    function quote(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'"; }

    function launch(app) {
        if (!app) return;
        var cmd = "setsid -f gio launch " + quote(app.file) + " </dev/null >/dev/null 2>&1";
        if (app.exec)
            cmd += " || setsid -f sh -c " + quote(app.exec) + " </dev/null >/dev/null 2>&1";
        launcher.command = ["sh", "-c", cmd];
        launcher.running = true;
    }

    function isFav(app) { return favorites.indexOf(app.file) >= 0; }
    function toggleFav(app) {
        var f = favorites.slice();
        var i = f.indexOf(app.file);
        if (i >= 0) f.splice(i, 1); else f.push(app.file);
        favorites = f;
        saveFavs();
    }
}
