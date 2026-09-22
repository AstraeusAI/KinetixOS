pragma Singleton
import QtQuick

// Argus design tokens v2 — see docs/02-design-system.md
QtObject {
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

    // agent identity — the deep ominous crimson family (docs/02, "Agent Panel
    // palette"). Single source of truth: the Agent Panel aliases these as its
    // pAccent* tokens, and the bar's agent pill uses them directly. Every
    // other surface keeps iris/teal.
    readonly property color crimson: "#B3283A"
    readonly property color crimsonText: "#D6556A"
    readonly property color ember: "#E8752E"
    readonly property color gilded: "#C98F2E"
    readonly property color alarm: "#FF2E43"
    readonly property color glowDeep: "#2A070C"

    // main bar identity — the bar's own glass, panel-wide, now carries the
    // same crimson family (docs/02, "Main bar palette"), instead of the
    // neutral glassBase every other surface uses. Deliberately its own
    // tokens rather than reusing glassBase/surfaceHigh directly: those stay
    // neutral for every non-bar panel (overlays, widgets, launcher), so a
    // future change to one palette can never silently bleed into the other.
    // Workspace dots, the status orb, and other semantic state colors are
    // untouched — this is chrome, not signal.
    readonly property color barBase: Qt.rgba(0.094, 0.020, 0.027, 0.98)
    readonly property color barBaseHigh: Qt.rgba(0.150, 0.032, 0.043, 0.97)
    readonly property color barStroke: alpha(crimson, 0.22)
    readonly property color barStrokeStrong: alpha(alarm, 0.40)
    readonly property color barHoverGlow: alpha(crimson, 0.16)

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
    // Consolidating independent SequentialAnimations into this single driver
    // eliminates dozens of timer wakeups per second.
    property real heartbeatPhase: 0
    readonly property real heartbeatSin: 0.5 + 0.5 * Math.sin(heartbeatPhase * 2 * Math.PI)
    NumberAnimation on heartbeatPhase {
        from: 0
        to: 1
        duration: 1800
        loops: Animation.Infinite
        running: true
    }
}
