pragma Singleton
import QtQuick
import Quickshell

// Argus design tokens v2 — see docs/02-design-system.md
QtObject {
    id: theme
    // ── palette ───────────────────────────────────────────
    readonly property color bg: "#07080C"
    readonly property color bgElevated: "#0C0E15"

    // glass recipes (layered: base + wash + sheen + rim)
    readonly property color glassBase: Qt.rgba(0.055, 0.063, 0.086, 0.74)
    readonly property color glassBaseHigh: Qt.rgba(0.082, 0.094, 0.125, 0.84)
    readonly property color glassWashTop: Qt.rgba(1, 1, 1, 0.06)
    readonly property color glassWashBottom: Qt.rgba(0, 0, 0, 0.12)
    readonly property color sheen: Qt.rgba(1, 1, 1, 0.075)
    readonly property color rimTop: Qt.rgba(1, 1, 1, 0.20)
    readonly property color stroke: Qt.rgba(1, 1, 1, 0.10)
    readonly property color strokeStrong: Qt.rgba(1, 1, 1, 0.20)

    // flat surfaces (insets, wells)
    readonly property color surfaceLow: Qt.rgba(1, 1, 1, 0.045)
    readonly property color surface: Qt.rgba(1, 1, 1, 0.07)
    readonly property color surfaceHigh: Qt.rgba(1, 1, 1, 0.115)

    // text
    readonly property color text: Qt.rgba(1, 1, 1, 0.94)
    readonly property color textDim: Qt.rgba(1, 1, 1, 0.62)
    readonly property color textFaint: Qt.rgba(1, 1, 1, 0.38)

    // accents
    readonly property color accent: "#8A7CFF"
    readonly property color accent2: "#5EEAD4"
    readonly property color accent3: "#FF7AC6"
    readonly property color warn: "#FFB454"
    readonly property color danger: "#FF6B6B"

    // Shared Kinetix crimson family for the agent and main bar. The legacy
    // accent/accent2 tokens remain available to semantic surfaces that still
    // use them; bar-specific fills stay isolated in the bar* tokens below.
    readonly property color crimson: "#E01A3C"
    readonly property color crimsonText: "#FF4D6D"
    readonly property color ember: "#FF7324"
    readonly property color gilded: "#C98F2E"
    readonly property color alarm: "#FF2E43"
    readonly property color glowDeep: "#3D0711"

    // main bar identity — the bar's own glass, panel-wide, now carries the
    // same crimson family (docs/02, "Main bar palette"), instead of the
    // neutral glassBase every other surface uses. Deliberately its own
    // tokens rather than reusing glassBase/surfaceHigh directly: those stay
    // neutral for every non-bar panel (overlays, widgets, launcher), so a
    // future change to one palette can never silently bleed into the other.
    // Workspace dots, the status orb, and other semantic state colors are
    // untouched — this is chrome, not signal.
    // main bar glassmorphism identity — translucent dark oxblood glass that
    // allows KWin compositor blur to diffuse whatever is behind the bar,
    // combined with multi-layer specular chamfers and volumetric depth.
    readonly property color barBase: Qt.rgba(0.052, 0.025, 0.034, 0.58)
    readonly property color barBaseHigh: Qt.rgba(0.115, 0.045, 0.058, 0.48)
    readonly property color barHoverGlow: alpha(crimson, 0.20)
    readonly property color barStroke: alpha(crimson, 0.26)
    readonly property color barStrokeStrong: alpha(alarm, 0.44)

    // ── shape & space ─────────────────────────────────────
    readonly property int rXS: 6
    readonly property int rS: 9
    readonly property int rM: 14
    readonly property int rL: 20
    readonly property int rXL: 26
    readonly property int rPill: 999
    readonly property int s1: 4
    readonly property int s2: 8
    readonly property int s3: 12
    readonly property int s4: 16
    readonly property int s5: 24
    readonly property int s6: 32
    readonly property int s7: 48

    // ── type ──────────────────────────────────────────────
    readonly property string fontUi: "Inter"
    readonly property string fontMono: "JetBrains Mono"
    readonly property int tMicro: 9
    readonly property int tCaption: 10
    readonly property int tBody: 12
    readonly property int tLabel: 12
    readonly property int tTitle: 14
    readonly property int tHeading: 17
    readonly property int tDisplay: 20
    readonly property int tHero: 30

    // ── motion ────────────────────────────────────────────
    readonly property int durFast: 130
    readonly property int durMed: 240
    readonly property int durSlow: 420
    readonly property int durAmbient: 1600
    readonly property int easeOut: Easing.OutQuint
    readonly property int easeInOut: Easing.InOutSine
    readonly property int easeSoft: Easing.OutCubic
    readonly property int easeSpring: Easing.OutBack

    // ── motion preference ──────────────────────────────────
    // Whether decorative and ambient motion is allowed at all. QML has no
    // prefers-reduced-motion media query, so the shell reads the setting the
    // way every other Linux desktop surface does — an environment variable,
    // exported by the session or written by the installer, following the same
    // pattern as InstallerState's KINETIX_INSTALLER_SIMULATE.
    //
    // Default is motion ON: this is an opt-out for people who need it, not an
    // opt-in nobody notices. Nothing here is load-bearing for comprehension —
    // every place the preference removes motion has to keep the *information*
    // that motion was carrying, which is why it is paired with `ms` and
    // `ambient` rather than a blanket "set every duration to 0".
    readonly property bool reduceMotion: {
        var v = (Quickshell.env("KINETIX_REDUCE_MOTION") || "").toLowerCase();
        return v === "1" || v === "true" || v === "yes" || v === "on";
    }
    // Ambient loops — the heartbeat, shimmer sweeps, continuous drift — stop
    // rather than merely shortening. A 1s pulse repeating forever is the exact
    // thing the setting exists to suppress, so this gates `running:` and not
    // `duration:`.
    readonly property bool ambient: !reduceMotion
    // Duration helper for finite transitions. Collapses to ~instant rather
    // than rescaling: a 400ms fade shortened to 90ms is still a fade, so the
    // value has to be *changed* when motion is reduced, not made smaller.
    // 1ms rather than 0 because a zero-duration QPropertyAnimation is a
    // degenerate case whose "apply the end value immediately" behaviour is not
    // something to hang a whole reveal on; 1ms is imperceptible and
    // unconditionally applies the target.
    function ms(n) { return reduceMotion ? 1 : n; }

    // ── elevation ─────────────────────────────────────────
    // soft multi-layer shadow spec: {dy: vertical offset, a: alpha, grow: outward growth}
    function shadowFor(level) {
        switch (level) {
        case 0:  return [ { "dy": 1,  "a": 0.22, "grow": 0 },
                          { "dy": 2,  "a": 0.12, "grow": 1 } ];
        case 1:  return [ { "dy": 2,  "a": 0.26, "grow": 0 },
                          { "dy": 5,  "a": 0.16, "grow": 2 },
                          { "dy": 10, "a": 0.10, "grow": 5 } ];
        case 2:  return [ { "dy": 4,  "a": 0.30, "grow": 1 },
                          { "dy": 9,  "a": 0.20, "grow": 3 },
                          { "dy": 18, "a": 0.12, "grow": 8 } ];
        case 3:  return [ { "dy": 6,  "a": 0.36, "grow": 2 },
                          { "dy": 15, "a": 0.24, "grow": 6 },
                          { "dy": 30, "a": 0.14, "grow": 14 } ];
        }
        return [];
    }

    // gradient helpers
    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a); }

    // Accent colour for an app icon from ColorQuantizer.colors: the most
    // vivid mid-lightness colour, lifted so it reads on dark glass; crimson
    // when the icon is monochrome or not loaded yet.
    function appAccent(colors) {
        var best = crimsonText, bestScore = 0.16;
        var cs = colors || [];
        for (var i = 0; i < cs.length; i++) {
            var c = cs[i];
            var mx = Math.max(c.r, c.g, c.b), mn = Math.min(c.r, c.g, c.b);
            var l = (mx + mn) / 2;
            var sat = mx === mn ? 0 : (mx - mn) / (1 - Math.abs(2 * l - 1));
            var score = sat * (1 - Math.abs(l - 0.56) * 1.6);
            if (score > bestScore) { bestScore = score; best = c; }
        }
        return Qt.hsla(best.hslHue, Math.min(1, best.hslSaturation * 1.05),
                       Math.max(0.52, Math.min(0.68, best.hslLightness)), 1);
    }

    function statusColor(status) {
        switch (status) {
        case "working": return accent;
        case "watching": return warn;
        case "blocked": return danger;
        default: return accent2;
        }
    }

    // ── Global Synchronized Heartbeat Clock ──────────────────────────────
    // A single, shared oscillator driving all glowing indicator beacons,
    // pips, and subtle status pulses across the desktop.
    // A modest 20 Hz timer is enough for decorative pulses/spinners and
    // avoids driving the whole shell's render loop at display refresh rate.
    property real heartbeatPhase: 0
    readonly property real heartbeatSin: 0.5 + 0.5 * Math.sin(heartbeatPhase * 2 * Math.PI)
    property Timer heartbeatTimer: Timer {
        interval: 50
        running: true
        repeat: true
        onTriggered: theme.heartbeatPhase = (theme.heartbeatPhase + interval / 1800) % 1
    }
}
