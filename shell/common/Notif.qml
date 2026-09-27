pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Notifications
import "."

// Notification backend for the Kinetix shell.
//
//   items   ListModel — every live notification, GROUPED by app (a group's
//                       block sits together, most recently active group on
//                       top): the Notification Center's history.
//   toasts  ListModel — the subset popped up on screen; toasts time out
//                       (hideToast) WITHOUT dismissing the entry.
//   dnd     bool      — do-not-disturb: suppresses toasts (errors and
//                       critical notifications still pop).
//
// Errors: app crashes / failed services arrive from ErrorWatch, shell-internal
// failures via reportInternal(). Both become "error" rows with Save log / Copy
// actions; saving copies the report into ~/.local/share/kinetix/error-logs.
//
// UI never touches Notification objects: rows are plain data; actions route
// back to the live object by id. Efficiency: history is capped, identical
// bursts coalesce into one row ("×3"), the relative-time clock only ticks
// while something is on screen, and demo()/reportError() work without a
// notification daemon (plasmashell owns the bus on Plasma).
QtObject {
    id: root

    readonly property int maxItems: 200
    readonly property int coalesceMs: 8000
    readonly property string script: Quickshell.shellDir + "/../scripts/kinetix-errors.py"

    property bool dnd: false
    property ListModel items: ListModel {}
    property ListModel toasts: ListModel {}
    readonly property int count: items.count
    property var sources: ({})
    property var details: ({})          // nid -> plain-text report for shell-internal errors
    property var collapsed: ({})        // appName -> bool (Notification Center groups)
    property int demoSeq: 900000
    property real now: Date.now()
    property string errorDir: ""

    signal arrived(int nid, bool toasted)

    // relative-time clock: only ticks while something is visible
    property Timer clock: Timer {
        interval: 30000
        running: AgentState.notifOpen || root.toasts.count > 0
        repeat: true
        onTriggered: root.now = Date.now()
    }

    // ── helpers ────────────────────────────────────────────────
    function ago(ts) {
        var s = Math.max(0, Math.floor((root.now - ts) / 1000));
        if (s < 45) return "now";
        var m = Math.round(s / 60);
        if (m < 60) return m + "m";
        var h = Math.round(m / 60);
        if (h < 24) return h + "h";
        return Math.round(h / 24) + "d";
    }

    function resolveIcon(appName, appIcon) {
        var ic = String(appIcon || "");
        if (ic.charAt(0) === "/") return "file://" + ic;
        if (ic.indexOf("file:") === 0 || ic.indexOf("image:") === 0) return ic;
        var key = String(appName || "").toLowerCase();
        var apps = AppIndex.apps || [];
        for (var i = 0; i < apps.length; i++) {
            var f = String(apps[i].file || "").split("/").pop().toLowerCase().replace(/\.desktop$/, "");
            var nm = String(apps[i].name || "").toLowerCase();
            if ((key !== "" && (nm === key || f === key || f.indexOf(key) >= 0)) ||
                (ic !== "" && f === ic.toLowerCase()))
                return apps[i].icon ? "file://" + apps[i].icon : "";
        }
        return "";
    }

    function indexOfId(model, nid) {
        for (var i = 0; i < model.count; i++)
            if (model.get(i).nid === nid) return i;
        return -1;
    }

    function urgencyOf(n) {
        if (n.urgency === NotificationUrgency.Critical) return 2;
        if (n.urgency === NotificationUrgency.Low) return 0;
        return 1;
    }

    function actionsOf(n) {
        var out = [], list = n.actions || [];
        for (var i = 0; i < list.length; i++)
            if (list[i].identifier !== "default")
                out.push({ "id": list[i].identifier, "text": list[i].text });
        return out;
    }

    function trim(s, n) { s = String(s || ""); return s.length > n ? s.substring(0, n) + "…" : s; }

    function rowFrom(n) {
        var urg = urgencyOf(n);
        var t = n.expireTimeout > 0 ? n.expireTimeout * 1000 : (urg === 2 ? 0 : 6500);
        return {
            "nid": n.id,
            "appName": n.appName || "Notification",
            "summary": trim(n.summary, 300),
            "body": trim(n.body, 2000),
            "icon": resolveIcon(n.appName, n.appIcon),
            "image": n.image ? String(n.image) : "",
            "urgency": urg,
            "ts": Date.now(),
            "actionsJson": JSON.stringify(actionsOf(n)),
            "timeout": t,
            "kind": "app",
            "logPath": "",
            "repeat": 1,
            "saved": ""
        };
    }

    // ── model mutation ─────────────────────────────────────────
    function setRow(nid, props) {
        var models = [items, toasts];
        for (var m = 0; m < models.length; m++) {
            var i = indexOfId(models[m], nid);
            if (i < 0) continue;
            for (var k in props) models[m].setProperty(i, k, props[k]);
        }
    }

    function groupRange(appName) {
        var first = -1, n = 0;
        for (var i = 0; i < items.count; i++) {
            if (items.get(i).appName === appName) { if (first < 0) first = i; n++; }
            else if (first >= 0) break;
        }
        return { "first": first, "n": n };
    }

    // returns the nid of the row that now represents this notification
    function push(row) {
        row.leaving = false;
        var replace = indexOfId(items, row.nid);
        if (replace < 0) {
            // identical burst from the same app → one row, ×N
            for (var i = 0; i < items.count; i++) {
                var r = items.get(i);
                if (r.appName === row.appName && r.summary === row.summary && r.body === row.body
                        && r.kind === row.kind && Date.now() - r.ts < coalesceMs) {
                    setRow(r.nid, { "repeat": r.repeat + 1, "ts": row.ts });
                    var t0 = indexOfId(toasts, r.nid);
                    if (t0 < 0 && (!dnd || row.urgency === 2 || row.kind !== "app")) { toasts.insert(0, items.get(i)); trimToasts(); }
                    arrived(r.nid, true);
                    return -r.nid;      // negative → merged into an existing row
                }
            }
        } else {
            items.remove(replace);
        }

        var g = groupRange(row.appName);
        items.insert(g.first >= 0 ? g.first : 0, row);
        if (g.first > 0) items.move(g.first, 0, g.n + 1);      // most recently active group to the top
        while (items.count > maxItems) removeEntry(items.get(items.count - 1).nid);

        var t = indexOfId(toasts, row.nid);
        if (t >= 0) toasts.remove(t);
        var show = !dnd || row.urgency === 2 || row.kind !== "app";
        if (show) { toasts.insert(0, row); trimToasts(); }
        arrived(row.nid, show);
        return row.nid;
    }

    function trimToasts() { while (toasts.count > 4) toasts.remove(toasts.count - 1); }

    // Timing out / dismissing a toast animates it away first (the delegate
    // calls finalizeToast when its exit animation ends).
    function hideToast(nid) {
        var i = indexOfId(toasts, nid);
        if (i >= 0) toasts.setProperty(i, "leaving", true);
    }
    function finalizeToast(nid) {
        var i = indexOfId(toasts, nid);
        if (i >= 0) toasts.remove(i);
    }

    function removeEntry(nid) {
        hideToast(nid);
        var i = indexOfId(items, nid);
        if (i >= 0) items.remove(i);
        delete sources[nid];
        delete details[nid];
    }

    function dismiss(nid) {
        var src = sources[nid];
        removeEntry(nid);
        if (src && src.dismiss) src.dismiss();
    }

    function clearAll() {
        var ids = [];
        for (var i = 0; i < items.count; i++) ids.push(items.get(i).nid);
        for (var j = 0; j < ids.length; j++) dismiss(ids[j]);
    }

    function clearGroup(appName) {
        var ids = [];
        for (var i = 0; i < items.count; i++)
            if (items.get(i).appName === appName) ids.push(items.get(i).nid);
        for (var j = 0; j < ids.length; j++) dismiss(ids[j]);
    }

    function groupCount(appName) { return groupRange(appName).n; }
    function isCollapsed(appName) { return collapsed[appName] === true; }
    function toggleGroup(appName) {
        var c = Object.assign({}, collapsed);
        c[appName] = !c[appName];
        collapsed = c;
    }

    function invoke(nid, actionId) {
        if (String(actionId).charAt(0) === "@") { localAction(nid, actionId); return; }
        var src = sources[nid];
        if (src) {
            var list = src.actions || [];
            for (var i = 0; i < list.length; i++)
                if (list[i].identifier === actionId) { list[i].invoke(); break; }
        }
        dismiss(nid);
    }

    function activate(nid) {
        var i = indexOfId(items, nid);
        if (i >= 0 && items.get(i).kind !== "app") return;   // error cards have no default action
        var src = sources[nid];
        if (src) {
            var list = src.actions || [];
            for (var j = 0; j < list.length; j++)
                if (list[j].identifier === "default") { list[j].invoke(); break; }
        }
        dismiss(nid);
    }

    function toggleDnd() { dnd = !dnd; }

    // ── error reports ──────────────────────────────────────────
    readonly property string savedActions: JSON.stringify([
        { "id": "@open-dir", "text": "Open folder" }, { "id": "@copy-path", "text": "Copy path" } ])
    readonly property string errorActions: JSON.stringify([
        { "id": "@diagnose", "text": "Diagnose" },
        { "id": "@save-log", "text": "Save log" }, { "id": "@copy-log", "text": "Copy report" } ])

    function reportError(ev) {
        demoSeq++;
        push({
            "nid": demoSeq, "appName": ev.app || "App", "summary": trim(ev.summary, 200), "body": trim(ev.body, 1200),
            "icon": resolveIcon(ev.app, ""), "image": "", "urgency": 2, "ts": ev.ts || Date.now(),
            "actionsJson": errorActions, "timeout": 14000,
            "kind": ev.kind || "crash", "logPath": ev.log || "", "repeat": 1, "saved": ""
        });
    }

    // Shell-internal failure: `text` is the report body (kept in memory only
    // until the user saves or dismisses it).
    function reportInternal(app, summary, text) {
        demoSeq++;
        details[demoSeq] = String(text || summary);
        push({
            "nid": demoSeq, "appName": app, "summary": summary, "body": trim(text, 600),
            "icon": resolveIcon(app, ""), "image": "", "urgency": 2, "ts": Date.now(),
            "actionsJson": errorActions, "timeout": 14000,
            "kind": "shell", "logPath": "", "repeat": 1, "saved": ""
        });
    }

    property Process saveProc: Process {
        property int nid: 0
        stdout: StdioCollector { onStreamFinished: root.onSaved(saveProc.nid, text) }
        onExited: function (code) { if (code !== 0 && code !== 1) root.onSaved(saveProc.nid, "") }
    }
    property Process copyProc: Process {}

    function saveLog(nid) {
        var i = indexOfId(items, nid);
        if (i < 0 || saveProc.running) return;
        var r = items.get(i);
        saveProc.nid = nid;
        saveProc.environment = ({ "KINETIX_ERR_TEXT": details[nid] || "" });
        saveProc.command = r.logPath !== ""
            ? ["python3", script, "save", r.logPath, r.appName]
            : ["python3", script, "save-text", r.appName];
        saveProc.running = true;
    }

    function onSaved(nid, text) {
        var res = null;
        try { res = JSON.parse(String(text).trim().split("\n").pop()); } catch (e) {}
        if (res && res.ok) {
            errorDir = res.dir;
            setRow(nid, { "saved": res.path, "actionsJson": savedActions });
        } else {
            setRow(nid, { "saved": "", "body": "Could not save the log" + (res && res.error ? ": " + res.error : ".") });
        }
    }

    function localAction(nid, actionId) {
        var i = indexOfId(items, nid);
        if (i < 0) return;
        var r = items.get(i);
        if (actionId === "@save-log") saveLog(nid);
        else if (actionId === "@diagnose") diagnoseCrash(nid);
        else if (actionId === "@copy-log") {
            copyProc.environment = ({ "KINETIX_ERR_TEXT": details[nid] || "" });
            copyProc.command = r.logPath !== ""
                ? ["sh", "-c", "wl-copy < \"$1\"", "sh", r.logPath]
                : ["sh", "-c", "printf %s \"$KINETIX_ERR_TEXT\" | wl-copy"];
            copyProc.running = false; copyProc.running = true;
        } else if (actionId === "@copy-path") {
            copyProc.environment = ({ "KINETIX_ERR_TEXT": r.saved });
            copyProc.command = ["sh", "-c", "printf %s \"$KINETIX_ERR_TEXT\" | wl-copy"];
            copyProc.running = false; copyProc.running = true;
        } else if (actionId === "@open-dir") openErrorDir();
    }

    // Reads the captured log for the diagnose action. The log lives on disk
    // (kinetix-errors.py captures it at crash time), so it is read on demand
    // rather than kept in memory with the notification.
    property Process diagnoseProc: Process {
        property int nid: 0
        stdout: StdioCollector {
            onStreamFinished: root.finishDiagnose(diagnoseProc.nid, this.text)
        }
    }

    // Hand a captured crash to the agent. The prompt is deliberately the same
    // packet `kinetix diagnose-crash` prints, so what the agent sees and what a
    // human would see by hand are identical facts.
    function diagnoseCrash(nid) {
        var i = indexOfId(items, nid);
        if (i < 0) return;
        var r = items.get(i);
        if (r.logPath !== "" && r.logPath !== undefined) {
            diagnoseProc.nid = nid;
            // Capped at 8k: a full coredump backtrace alone can swallow the
            // whole context before the agent reads a word of the question.
            diagnoseProc.command = ["sh", "-c", "head -c 8000 -- \"$1\"", "sh", r.logPath];
            diagnoseProc.running = false;
            diagnoseProc.running = true;
        } else {
            finishDiagnose(nid, details[nid] || r.body || r.summary);
        }
        dismiss(nid);
    }

    function finishDiagnose(nid, text) {
        var packet = (text && String(text).trim() !== "") ? text : "\u2014 no details were captured for this crash \u2014";
        var prompt = "A process crashed on this KinetixOS system. Establish the facts "
            + "from the report below, decide whether it is a KinetixOS bug worth "
            + "reporting upstream, and say plainly if it is instead a bug in the "
            + "application itself or an out-of-memory kill.\n\n" + packet;
        AgentState.panelOpen = true;
        AgentState.setTab("chat");
        ArgusBridge.send(prompt);
    }

    function openErrorDir() {
        var d = errorDir !== "" ? errorDir
              : (Quickshell.env("XDG_DATA_HOME") || (Quickshell.env("HOME") + "/.local/share")) + "/kinetix/error-logs";
        Quickshell.execDetached(["sh", "-c", "mkdir -p \"$1\" && xdg-open \"$1\"", "sh", d]);
    }

    // ── previews (work without a notification daemon) ──────────
    function demo() {
        var base = Date.now();
        var rows = [
            { "appName": "Kinetix Agent", "summary": "Refactor finished", "body": "12 files updated across shell/ and runtime/. All gates green — ready for your review.",
              "urgency": 1, "actions": [ { "id": "review", "text": "Review" }, { "id": "undo", "text": "Undo" } ], "age": 20 },
            { "appName": "Konsole", "summary": "Build succeeded", "body": "distro/build-iso.sh completed in 4m 12s.", "urgency": 1, "actions": [], "age": 180 },
            { "appName": "Konsole", "summary": "Build started", "body": "distro/build-iso.sh", "urgency": 0, "actions": [], "age": 470 },
            { "appName": "System", "summary": "Battery is low", "body": "12% remaining. Plug in your charger soon.", "urgency": 2,
              "actions": [ { "id": "saver", "text": "Power saver" } ], "age": 600 },
            { "appName": "Dolphin", "summary": "Copy complete", "body": "3 items copied to Documents.", "urgency": 0, "actions": [], "age": 3800 }
        ];
        for (var i = rows.length - 1; i >= 0; i--) {
            var r = rows[i];
            demoSeq++;
            push({
                "nid": demoSeq, "appName": r.appName, "summary": r.summary, "body": r.body,
                "icon": resolveIcon(r.appName, ""), "image": "", "urgency": r.urgency,
                "ts": base - r.age * 1000, "actionsJson": JSON.stringify(r.actions),
                "timeout": r.urgency === 2 ? 0 : 6500, "kind": "app", "logPath": "", "repeat": 1, "saved": ""
            });
        }
    }

    // ── live server ────────────────────────────────────────────
    function register(n) {
        n.tracked = true;
        var nid = push(rowFrom(n));
        if (nid < 0) { n.dismiss(); return; }     // coalesced into an existing row
        sources[n.id] = n;
        n.closed.connect(function () { root.removeEntry(n.id); });
    }

    property NotificationServer server: NotificationServer {
        keepOnReload: true
        actionsSupported: true
        bodySupported: true
        bodyMarkupSupported: true
        bodyHyperlinksSupported: true
        imageSupported: true
        persistenceSupported: true
        inlineReplySupported: true
        // Without tracking, every notification is discarded the moment the
        // handler returns — the "notifications just vanish" bug.
        onNotification: function (n) { root.register(n); }
    }
}
