import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"

// The startup handoff: the desktop is already assembling beneath this
// non-interactive overlay, which leaves once the session has actually
// finished coming up.
//
// It used to leave after a fixed 4.8 seconds, which is a duration, not a
// readiness condition — the comment claimed it faded "once its greeting
// animation ends", and the animation was a timer. On a fast machine that is
// four wasted seconds; on a slow one the splash is gone while the launcher
// still has no application list. The stages below are wired to the startup
// work that genuinely is asynchronous (`argus-appscan.py`, `argus-sysmon.py`,
// the runtime doctor probe), so the progress it shows is the progress it is
// making, and it leaves when they are done rather than when a clock says so.
//
// Two bounds keep that honest in both directions: a minimum so it never
// flashes on an instant boot, and a maximum so a subsystem that never reports
// ready cannot hold the screen hostage. Leaving under the maximum with a
// stage still pending is correct — the pill is visibly unfilled, and the
// desktop is usable; the alternative is a splash that lies about loading
// something it is not.
PanelWindow {
    id: splash
    required property ShellScreen modelData
    screen: modelData

    // ── the four things the shell actually waits on ──────────────────────
    // Each is its own object with its own binding rather than an array of
    // literals, so `stages` keeps a stable identity: a Repeater whose model
    // changes would rebuild its delegates and replay their entrance
    // animation every time a stage completed.
    QtObject {
        id: stSession
        readonly property string label: "SESSION"
        readonly property string caption: "Starting the session"
        property bool done: splash.armed
    }
    QtObject {
        id: stApps
        readonly property string label: "APPS"
        readonly property string caption: "Indexing installed applications"
        property bool done: AppIndex.ready
    }
    QtObject {
        id: stTelemetry
        readonly property string label: "TELEMETRY"
        readonly property string caption: "Connecting system telemetry"
        property bool done: SysInfo.ready
    }
    QtObject {
        id: stRuntime
        readonly property string label: "RUNTIME"
        readonly property string caption: "Probing the agent runtime"
        // ArgusBridge.caps is populated from the doctor probe the bridge
        // runs on startup; an empty object means it has not answered yet.
        property bool done: Object.keys(ArgusBridge.caps).length > 0
    }
    readonly property var stages: [stSession, stApps, stTelemetry, stRuntime]

    readonly property bool allDone: {
        for (var i = 0; i < stages.length; i++)
            if (!stages[i].done) return false;
        return true;
    }
    readonly property int doneCount: {
        var n = 0;
        for (var i = 0; i < stages.length; i++)
            if (stages[i].done) n++;
        return n;
    }
    readonly property real progress: stages.length > 0 ? doneCount / stages.length : 0

    // Full composition on the first output; elsewhere the wallpaper alone.
    // Running the shader-backed mark on every monitor at once is cost with
    // nothing to look at, since only one screen is being watched during boot.
    readonly property bool primaryScreen:
        Quickshell.screens.length < 2 || modelData === Quickshell.screens[0]

    property bool splashShown: true
    property bool fading: false
    // Whether the splash is leaving because everything reported ready, or
    // because it ran out of budget with a stage still outstanding. Set once at
    // beginFade() and handed to the composition so the departure can say which
    // it was — see the comment on SplashContent.stalled.
    property bool stalled: false
    property bool armed: false
    readonly property double startedAt: Date.now()
    // The floor stops it flashing on an instant boot. The ceiling is the
    // previous fixed duration (4.8s), so this is never slower than what it
    // replaced: readiness normally ends it around 2.2-2.5s (the first
    // telemetry sample is the long pole at ~2.2s), and a subsystem that never
    // reports ready still leaves on the same clock the old splash did.
    readonly property int minVisibleMs: 2200
    readonly property int maxVisibleMs: 4800

    anchors { top: true; right: true; bottom: true; left: true }
    visible: splashShown
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    mask: Region { item: content }

    WlrLayershell.namespace: "kinetix:boot-splash"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    // "Session up" — not an assumption, since this component exists only
    // once the shell is running, but a small beat so the first stage reads
    // as a step rather than being pre-completed in the same frame.
    Timer {
        interval: 320
        running: splash.splashShown && !splash.armed
        onTriggered: splash.armed = true
    }

    // Readiness poll. Cheap: it compares booleans it is already bound to.
    Timer {
        interval: 120
        repeat: true
        running: splash.splashShown && !splash.fading
        onTriggered: {
            var elapsed = Date.now() - splash.startedAt;
            if (elapsed >= splash.maxVisibleMs
                    || (splash.allDone && elapsed >= splash.minVisibleMs))
                splash.beginFade();
        }
    }
    Timer {
        id: dismissTimer
        // Long enough for the composition's departure (620ms lift) plus its
        // trailing opacity settle, with margin. It was 780ms against a 760ms
        // fade on the old whole-item exit; the brand-only exit is shorter, so
        // this is unchanged rather than newly generous.
        interval: 780
        onTriggered: splash.splashShown = false
    }
    function beginFade() {
        if (splash.fading) return;
        // Latched before the fade starts, because `allDone` is sampled one
        // last time here and everything after this point is a departure
        // animation. Sampling it later would read the state *during* the exit
        // and could disagree with why the exit began.
        splash.stalled = !splash.allDone;
        splash.fading = true;
        dismissTimer.start();
    }

    SplashContent {
        id: content
        anchors.fill: parent
        stages: splash.stages
        progress: splash.progress
        primary: splash.primaryScreen
        dismissed: splash.fading
        stalled: splash.stalled
    }
}
