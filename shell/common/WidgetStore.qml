pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Desktop widget layer state: instances, catalog, persistence.
// Widgets float over applications and are persisted to
// ~/.config/argus/widgets.json. See docs/06-widget-layer.md.
//
// Data model: _data (id→object map) + order (ID array used by Variants).
// Non-structural mutations (move/resize/config) create a NEW object in
// _data so QML bindings detect the change via ===. The order array only
// changes on add/remove/bringToFront. `revision` is bumped on every
// mutation so WidgetWindow's binding re-evaluates.
QtObject {
    id: store

    // ── core state ──
    property var _data: ({})          // id → widget data object
    property var order: []            // id strings — Variants model
    property int revision: 0
    property bool catalogOpen: false
    property bool editMode: false
    property bool loaded: false

    // Backward-compat: ordered array of widget objects. Not used as a
    // model (WidgetLayer uses `order`), but WidgetCatalog references
    // widgets.length and widgets[i].id.
    readonly property var widgets: {
        var _r = revision;  // depend on revision
        var a = [];
        for (var i = 0; i < order.length; i++) {
            var w = _data[order[i]];
            if (w) a.push(w);
        }
        return a;
    }

    // shell-expandable paths (resolved by the sh -c commands below)
    readonly property string storeDir: "$HOME/.config/argus"
    readonly property string storePath: storeDir + "/widgets.json"
    readonly property string displayPath: "~/.config/argus/widgets.json"

    // available widget types — "any kind" is served by `command`
    readonly property var types: [
        { "type":"clock",   "label":"Clock",     "glyph":"◷", "desc":"Time, date, world clock",        "w":280, "h":150,
          "fields":[] },
        { "type":"sysmon",  "label":"System",    "glyph":"▤", "desc":"CPU · RAM · GPU · network",      "w":320, "h":250,
          "fields":[] },
        { "type":"notes",   "label":"Notes",     "glyph":"✎", "desc":"Editable scratchpad",            "w":300, "h":220,
          "fields":[] },
        { "type":"command", "label":"Command",   "glyph":"▸", "desc":"Live output of any shell command","w":360, "h":180,
          "fields":[{"k":"cmd","l":"Command"},{"k":"interval","l":"Refresh (s)"}] },
        { "type":"agent",   "label":"Agent",     "glyph":"◉", "desc":"Agent status + quick task",      "w":320, "h":230,
          "fields":[] },
        { "type":"image",   "label":"Image",     "glyph":"▣", "desc":"Display a local image",          "w":280, "h":220,
          "fields":[{"k":"path","l":"Image path"}] },
        { "type":"weather", "label":"Weather",   "glyph":"☁", "desc":"Live weather (wttr.in)",         "w":280, "h":190,
          "fields":[{"k":"location","l":"Location (blank = auto)"}] }
    ]

    function typeInfo(t) {
        for (var i = 0; i < types.length; i++)
            if (types[i].type === t) return types[i];
        return types[0];
    }

    function quote(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'"; }

    // ── load ──
    property Process reader: Process {
        command: ["sh", "-c", "cat " + WidgetStore.storePath + " 2>/dev/null"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: WidgetStore.load(this.text)
        }
    }

    function load(text) {
        var parsed = null;
        if (text && text.trim() !== "") {
            try { parsed = JSON.parse(text); } catch (e) { parsed = null; }
        }
        var list = (parsed && parsed.widgets && parsed.widgets.length > 0)
            ? removeLegacySeed(parsed.widgets) : [];
        if (parsed && parsed.widgets && list.length !== parsed.widgets.length) save();

        var d = {};
        var o = [];
        for (var i = 0; i < list.length; i++) {
            d[list[i].id] = list[i];
            o.push(list[i].id);
        }
        _data = d;
        order = o;
        loaded = true;
        revision++;
        if (!parsed || !parsed.widgets || parsed.widgets.length === 0) save();
    }

    function removeLegacySeed(a) {
        var out = [];
        for (var i = 0; i < a.length; i++)
            if (a[i].id !== "w-clock" && a[i].id !== "w-s") out.push(a[i]);
        return out;
    }

    // ── persist (debounced) ──
    property Process writer: Process {}
    property Timer saveTimer: Timer {
        interval: 600
        onTriggered: WidgetStore.saveNow()
    }
    property bool savePending: false
    function save() {
        if (!savePending) {
            savePending = true;
            saveTimer.restart();
        }
    }
    function saveNow() {
        savePending = false;
        var arr = [];
        for (var i = 0; i < order.length; i++) {
            var w = _data[order[i]];
            if (w) arr.push(w);
        }
        var json = JSON.stringify({ "widgets": arr });
        var esc = json.replace(/'/g, "'\\''");
        writer.command = ["sh", "-c",
            "mkdir -p " + storeDir + " && printf '%s' '" + esc + "' > " + storePath];
        writer.running = true;
    }

    // ── internal helpers ──
    function _patch(id, patchObj) {
        var old = _data[id];
        if (!old) return;
        var w = {};
        for (var k in old) w[k] = old[k];
        for (var k2 in patchObj) w[k2] = patchObj[k2];
        var d = {};
        for (var k3 in _data) d[k3] = _data[k3];
        d[id] = w;
        _data = d;
        revision++;
        save();
    }

    // ── public API ──
    function nextId() { return "w-" + Date.now().toString(36); }

    function byId(id) { return _data[id] || null; }

    function add(type) {
        var info = typeInfo(type);
        var count = order.length;
        var w = { "id": nextId(), "type": type,
                  "x": 120 + (count % 5) * 26,
                  "y": 110 + (count % 5) * 26,
                  "w": info.w, "h": info.h,
                  "config": defaultConfig(type) };
        var d = {};
        for (var k in _data) d[k] = _data[k];
        d[w.id] = w;
        _data = d;
        order = order.concat([w.id]);
        save();
        revision++;
        return w.id;
    }

    function defaultConfig(type) {
        if (type === "command") return { "cmd": "echo 'Set a command in widget settings'", "interval": 10 };
        if (type === "image") return { "path": "" };
        if (type === "notes") return { "text": "" };
        if (type === "weather") return { "location": "" };
        return {};
    }

    function remove(id) {
        var d = {};
        for (var k in _data) if (k !== id) d[k] = _data[k];
        _data = d;
        var o = [];
        for (var i = 0; i < order.length; i++)
            if (order[i] !== id) o.push(order[i]);
        order = o;
        save();
        revision++;
    }

    function setConfig(id, key, value) {
        var w = _data[id];
        if (!w) return;
        var cfg = {};
        for (var k in w.config) cfg[k] = w.config[k];
        cfg[key] = value;
        _patch(id, { "config": cfg });
    }

    function move(id, x, y) { _patch(id, { "x": Math.round(x), "y": Math.round(y) }); }
    function resize(id, w, h) { _patch(id, { "w": Math.round(w), "h": Math.round(h) }); }

    // Reorder: move widget to end of order array (front of z-stack).
    // This IS a structural change to the Variants model — call on
    // click/release, not during drag.
    function bringToFront(id) {
        var idx = -1;
        for (var i = 0; i < order.length; i++) {
            if (order[i] === id) { idx = i; break; }
        }
        if (idx < 0 || idx === order.length - 1) return;
        var o = [];
        for (var j = 0; j < order.length; j++)
            if (j !== idx) o.push(order[j]);
        o.push(id);
        order = o;
        revision++;
        save();
    }

    function resetLayout() {
        _data = {};
        order = [];
        save();
        revision++;
    }
}
