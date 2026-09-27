pragma Singleton
import QtQuick
import Quickshell
import "../common"

// TaskStore — shared helpers for the left-side task manager.
//
// The live window list itself comes from TaskRunner (shell/common/
// TaskRunner.qml), which streams scripts/kinetix-tasks.py rather than
// using Quickshell.Wayland.ToplevelManager — KWin doesn't implement the
// wlr-foreign-toplevel protocol family that API depends on, so it's always
// empty under KWin (see TaskRunner.qml). This singleton only owns the
// stateless helpers every task surface needs: icon + display-name
// resolution, title filtering, grouping keys, and the activate /
// minimize-toggle / close verbs (each a request to the daemon by uuid).
//
// Icon/name resolution reuses AppIndex (shell/common/AppIndex.qml) — the
// same desktop-file index the launcher and the old dock already use —
// rather than Quickshell's DesktopEntries/iconPath APIs, which aren't
// used anywhere else in this codebase and (confirmed live) crash
// qmllint outright when referenced here, which is a strong sign they
// don't resolve in this Quickshell build.
QtObject {
    id: root

    // ── filtering ──────────────────────────────────────────────
    // Mirrors the kinetix-tasks.py daemon rules: skip empty captions and
    // shell surfaces so the rail only ever shows real user windows.
    function isValid(appId, title) {
        var t = (title || "").trim();
        if (t === "" || t === "Desktop" || t === "Plasma") return false;
        var c = (appId || "").toLowerCase();
        if (c === "" ) return true;
        if (c.indexOf("plasmashell") >= 0) return false;
        if (c.indexOf("quickshell") >= 0) return false;
        if (c === "kinetix" || c === "argus") return false;
        return true;
    }

    // ── grouping ───────────────────────────────────────────────
    function groupKey(appId, title) {
        var c = (appId || "").trim();
        if (c !== "") return c.toLowerCase();
        return ("title:" + (title || "").trim().toLowerCase());
    }

    // ── display name ───────────────────────────────────────────
    // Prefers the freedesktop entry name ("Visual Studio Code"), falls
    // back to a prettified appId ("org.kde.dolphin" → "Dolphin").
    function displayName(appId, title) {
        var entry = lookupEntry(appId, title);
        if (entry && entry.name && String(entry.name).trim() !== "")
            return String(entry.name);
        return prettyAppId(appId, title);
    }

    function prettyAppId(appId, title) {
        var c = (appId || "").trim();
        if (c === "") {
            var t = (title || "").trim();
            return t !== "" ? t : "Unknown";
        }
        // Strip reverse-DNS prefixes: org.kde.dolphin → dolphin,
        // com.mitchellh.ghostty → ghostty.
        // ("short" is an ECMAScript reserved word — using it as a variable
        // name here previously crashed qmllint outright instead of merely
        // warning, confirmed live by bisecting this exact file.)
        var stem = c;
        if (stem.indexOf(".") >= 0) {
            var parts = stem.split(".");
            stem = parts[parts.length - 1];
        }
        // Strip common suffixes: firefox-esr → firefox.
        stem = stem.replace(/-(esr|bin|app|desktop)$/i, "");
        if (stem.length === 0) return c;
        return stem.charAt(0).toUpperCase() + stem.slice(1);
    }

    // ── icon resolution ────────────────────────────────────────
    // Returns a QML image source ready for IconImage / Image, straight
    // from AppIndex's already-resolved absolute icon path (populated by
    // scripts/argus-appscan.py) — "" falls back to a glyph in the caller.
    function iconSource(appId, title) {
        var entry = lookupEntry(appId, title);
        return entry && entry.icon ? "file://" + entry.icon : "";
    }

    // Fuzzy match against AppIndex.apps by desktop-file id — the same
    // approach the launcher and the old dock's favorite tiles use: strip
    // ".desktop" from both sides and accept a substring match either way,
    // since a toplevel's reported appId doesn't always exactly match the
    // installed .desktop file's stem (case, a missing/extra vendor prefix).
    function lookupEntry(appId, title) {
        var desktopId = String(appId || "").toLowerCase().replace(/\.desktop$/, "");
        if (desktopId === "") return null;
        var apps = AppIndex.apps || [];
        for (var i = 0; i < apps.length; i++) {
            var file = String(apps[i].file || "").split("/").pop()
                .toLowerCase().replace(/\.desktop$/, "");
            if (file === desktopId || file.indexOf(desktopId) >= 0 || desktopId.indexOf(file) >= 0)
                return apps[i];
        }
        return null;
    }

    // ── window verbs ─────────────────────────────────────────────
    // Windows here are plain data from TaskRunner (kinetix-tasks.py), not
    // live Wayland Toplevel handles — every verb is a request routed to
    // the daemon by uuid, not a property mutation with a compositor-side
    // effect.
    function activate(win) { if (win) TaskRunner.activate(win.uuid); }
    function toggleMinimize(win) { if (win) TaskRunner.toggle(win.uuid); }
    function setMinimized(win, mini) { if (win) TaskRunner.setMinimized(win.uuid, mini); }
    function toggleMaximize(win) { if (win) TaskRunner.toggleMaximize(win.uuid); }
    function requestClose(win) { if (win) TaskRunner.close(win.uuid); }
}
