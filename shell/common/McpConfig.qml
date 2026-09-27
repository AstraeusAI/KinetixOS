pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// MCP (Model Context Protocol) server registry for the Agent Panel's MCP
// tab. Mirrors ProviderConfig.qml's established pattern exactly: an
// in-process FileView reader (inotify + refresh Timer), a Process writer for plain
// config edits (add/remove/enable), and — the one thing that genuinely
// needs Python, since it has to spawn the server and speak MCP — a Process
// that runs `argusd.py mcp-probe` for the "Test" action.
//
// Storage: ~/.config/argus/mcp.json, stdio servers only (v1):
//   {"servers": {"<name>": {"command":"npx","args":[...],"env":{},
//                            "enabled":true,"tools":[...],"lastProbe":{...}}}}
// Secrets can live in a server's `env` block, so it's written 0600 the same
// way keys.env/prefs.json are (see runtime/lib/mcp.py's save_config).
QtObject {
    readonly property string confDir: "$HOME/.config/argus"
    readonly property string configPath: confDir + "/mcp.json"

    // [{name, command, args, env, enabled, tools, lastProbe}], sorted by name
    property var servers: []
    property bool loaded: false
    // Name of the server currently being probed, "" if none — one probe at
    // a time keeps the UI unambiguous about which card's spinner is live.
    property string probingServer: ""

    readonly property int enabledCount: {
        var n = 0;
        for (var i = 0; i < servers.length; i++) if (servers[i].enabled) n++;
        return n;
    }

    // In-process read (was sh+cat every 4s): inotify catches writes at once;
    // the timer keeps the old re-read cadence for files created or replaced
    // from outside. Unchanged text is not re-parsed.
    property string _lastText: "\u0000"
    function _ingest(t) {
        if (t === _lastText) return;
        _lastText = t;
        loadFromText(t);
    }
    property FileView reader: FileView {
        path: Quickshell.env("HOME") + "/.config/argus/mcp.json"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: McpConfig._ingest(text())
        onLoadFailed: McpConfig._ingest("")
    }

    // The file can change from outside this shell instance (a probe writes
    // it, a hot-reloaded panel writes it) — re-read it like ProviderConfig
    // re-reads keys.env, rather than trusting only this session's own writes.
    property Timer refreshTimer: Timer {
        interval: 4000
        repeat: true
        running: true
        onTriggered: McpConfig.reader.reload()
    }

    property Process writer: Process {}
    property Timer persistRetry: Timer { interval: 120; onTriggered: McpConfig._persist() }
    property Process prober: Process {
        stdout: StdioCollector {
            onStreamFinished: McpConfig._onProbeFinished()
        }
    }

    function loadFromText(text) {
        loaded = true;
        if (!text || text.trim() === "") { servers = []; return; }
        try {
            var doc = JSON.parse(text);
            var raw = doc.servers || {};
            var out = [];
            for (var name in raw) {
                var e = raw[name] || {};
                out.push({
                    "name": name, "command": e.command || "",
                    "args": e.args || [], "env": e.env || {},
                    "enabled": e.enabled !== false,
                    "tools": e.tools || [], "lastProbe": e.lastProbe || null,
                });
            }
            out.sort(function (a, b) { return a.name < b.name ? -1 : (a.name > b.name ? 1 : 0); });
            servers = out;
        } catch (err) { /* corrupt on disk — keep the last known-good list */ }
    }

    function _docFromServers() {
        var doc = { "servers": {} };
        for (var i = 0; i < servers.length; i++) {
            var s = servers[i];
            doc.servers[s.name] = { "command": s.command, "args": s.args, "env": s.env,
                                     "enabled": s.enabled, "tools": s.tools, "lastProbe": s.lastProbe };
        }
        return doc;
    }

    function _persist() {
        // Never re-command a Process mid-run; retry shortly instead.
        if (writer.running) { persistRetry.restart(); return; }
        var json = JSON.stringify(_docFromServers());
        var esc = json.replace(/'/g, "'\\''");
        writer.command = ["sh", "-c",
            "(umask 077; mkdir -p " + confDir + " && printf '%s' '" + esc + "' > " +
            configPath + " && chmod 600 " + configPath + ")"];
        writer.running = true;
    }

    // name/command required; args is an array of strings, env an object of
    // string->string. Adding a name that already exists replaces it, so the
    // panel's "edit" and "add" flows are the same call.
    function addServer(name, command, args, env) {
        name = String(name || "").trim();
        command = String(command || "").trim();
        if (name === "" || command === "") return;
        var list = servers.slice();
        var idx = -1;
        for (var i = 0; i < list.length; i++) if (list[i].name === name) idx = i;
        var entry = { "name": name, "command": command, "args": args || [],
                      "env": env || {}, "enabled": true, "tools": [], "lastProbe": null };
        if (idx >= 0) list[idx] = entry; else list.push(entry);
        servers = list;
        _persist();
    }

    function removeServer(name) {
        servers = servers.filter(function (s) { return s.name !== name; });
        _persist();
    }

    function setEnabled(name, on) {
        var list = servers.slice();
        for (var i = 0; i < list.length; i++) {
            if (list[i].name === name) {
                var copy = Object.assign({}, list[i]);
                copy.enabled = on;
                list[i] = copy;
            }
        }
        servers = list;
        _persist();
    }

    function probeServer(name) {
        if (probingServer !== "") return;  // one at a time
        probingServer = name;
        var esc = String(name).replace(/'/g, "'\\''");
        prober.command = ["sh", "-c", "python3 '" + Quickshell.shellDir +
            "/../runtime/argusd.py' mcp-probe --name '" + esc + "' 2>/dev/null"];
        prober.running = true;
    }

    function _onProbeFinished() {
        probingServer = "";
        // mcp-probe wrote tools/lastProbe straight to disk — reload from
        // there rather than trying to parse its stdout here, so this
        // singleton has exactly one source of truth for server state.
        reader.reload();
    }
}
