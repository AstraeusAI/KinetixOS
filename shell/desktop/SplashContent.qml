//@ pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import Quickshell
import "../common"
import "../components"

// SplashContent — the visual composition of the startup splash, with no
// knowledge of timers, screens or readiness. BootSplash.qml owns the
// fullscreen layer surface and decides *when* to leave; this decides only
// what it looks like on the way out.
//
// The split exists for two reasons. It makes the composition hostable in a
// small window for a real screenshot (a fullscreen overlay cannot be
// inspected without taking over the machine that is running it), and it
// keeps the startup logic — which has to consult AppIndex and SysInfo —
// away from the drawing, so neither half has to know the other's business.
Item {
    id: content

    // One entry per subsystem the session actually waits on, in order:
    //   { label: string, caption: string, done: bool }
    // BootSplash derives these from live signals; this only renders them.
    property var stages: []
    // 0..1, the fraction of stages that are done. Indeterminate is not
    // offered: the splash knows how many things it is waiting for, so a
    // sweeping bar would be a less honest animation than a filling one.
    property real progress: 0
    // Wrong screen? Then the brand composition is skipped and only the
    // wallpaper and scrim are drawn, so a multi-monitor session does not
    // run N copies of the same shader-heavy mark.
    property bool primary: true
    // Drives the exit animation; BootSplash sets it and hides the window
    // after the fade has run.
    property bool dismissed: false
    // True when the splash is leaving with stages still outstanding — the
    // ceiling was reached and something never reported ready. The departure
    // says so instead of looking identical to a clean boot, because "this
    // took the full budget and one subsystem never answered" and "everything
    // came up fine" are different facts and the user is entitled to both.
    property bool stalled: false

    // Everything scales from the short edge so the composition reads the
    // same on a laptop panel and a 4K monitor instead of being a small
    // island in the middle of a large screen.
    readonly property real unit: Math.max(0.8, Math.min(2.1, Math.min(width, height) / 900))

    readonly property int doneCount: {
        var n = 0;
        for (var i = 0; i < stages.length; i++)
            if (stages[i].done) n++;
        return n;
    }
    readonly property var activeStage: {
        for (var i = 0; i < stages.length; i++)
            if (!stages[i].done) return stages[i];
        return null;
    }
    readonly property bool allComplete: stages.length > 0 && activeStage === null
    // The window in which the stall is worth saying out loud: after the
    // departure has begun and the ceiling is the reason. Before that a slow
    // stage is just a slow stage, and saying "not ready" during a normal boot
    // would be crying wolf on every launch.
    readonly property bool stalledNow: dismissed && stalled && !allComplete
    // The caption line has to keep ticking for the elapsed figure to mean
    // anything, so this drives a text-only update. It is deliberately the
    // cheapest thing in the file — one property write per 100ms, no bindings
    // re-evaluated beyond the two Texts that read `elapsed` — and it stops the
    // moment the composition is gone, so a hidden splash costs nothing.
    Timer {
        interval: 100
        repeat: true
        running: content.visible && !content.dismissed && !content.allComplete
        onTriggered: content.elapsed = (Date.now() - content.shownAt) / 1000
    }
    // Seconds since the composition appeared, for the caption line. This is
    // the liveness signal that does not depend on motion: the shimmer sweep it
    // supplements is decorative, but a boot that is visibly not progressing is
    // information, and a user who has reduced motion turned off has not lost
    // the ability to tell a fast boot from a stuck one. Driven by the timer
    // below rather than bound to Date.now(), which would never re-evaluate.
    property real elapsed: 0
    readonly property double shownAt: Date.now()

    // The exit moves the *brand*, not the backdrop. Fading the whole item
    // took the wallpaper down with it, so for the length of the fade the
    // overlay was translucent and the desktop's own wallpaper showed through
    // a second copy of the same image — a dip in the middle of a handoff that
    // exists to be invisible. The wallpaper and scrim are byte-identical to
    // KinetixDesktop's and already sit at their final framing, so holding
    // them at full opacity and dropping only the composition makes the
    // hand-off exact: the mark dissolves, then there is simply the desktop.
    opacity: 1
    Behavior on opacity {
        NumberAnimation { duration: Theme.ms(420); easing.type: Theme.easeInOut }
    }

    // ── wallpaper ────────────────────────────────────────────────────────
    // The same source, crop mode and destination as KinetixDesktop, so the
    // moment this fades away the desktop is already in exactly this place
    // and the handoff is invisible. The slow zoom ("Ken Burns") is the only
    // difference, and it settles at 1.0 so it lands on the desktop's own
    // framing rather than drifting past it.
    Image {
        id: wallpaper
        anchors.fill: parent
        source: "file://" + (Quickshell.env("KINETIX_WALLPAPER") || (Quickshell.shellDir + "/../distro/assets/kinetix-wallpaper.png"))
        fillMode: Image.PreserveAspectCrop
        smooth: true
        // Decode at the display size — a 4K wallpaper was being decoded at
        // full resolution for a surface that then fades out in under 10s.
        sourceSize.width: Math.max(1, width)
        sourceSize.height: Math.max(1, height)
        scale: 1.0
        NumberAnimation on scale {
            from: 1.075; to: 1.0; duration: 11000
            easing.type: Easing.OutSine
            // Eleven seconds of continuous zoom is the single most sustained
            // motion in the product and it carries no information, so it is
            // the first thing the motion preference stops. The wall still
            // appears — via the opacity fade below — it just stops drifting.
            running: content.visible && !content.dismissed && Theme.ambient
        }
        NumberAnimation on opacity {
            from: 0; to: 1; duration: Theme.ms(1400)
            running: content.visible && !content.dismissed
        }
    }

    // Scrim: near-black at the edges, lifted through the middle so the mark
    // has somewhere to sit. Tuned to the same family as the desktop art so
    // it reads as one picture rather than a panel over a wallpaper.
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.00; color: Qt.rgba(3 / 255, 5 / 255, 9 / 255, 0.86) }
            GradientStop { position: 0.46; color: Qt.rgba(5 / 255, 6 / 255, 11 / 255, 0.62) }
            GradientStop { position: 1.00; color: Qt.rgba(2 / 255, 4 / 255, 8 / 255, 0.92) }
        }
    }

    // Brand field: a soft radial darkening under the composition. The
    // wallpaper has a bright eclipse ring and fine linework through exactly
    // the middle of the frame, and the mark's own machined ring lands on top
    // of it — two concentric rings fighting each other, and a tagline set
    // over a line drawing. This gives the brand its own small piece of night
    // to stand on without hiding the art at the edges.
    //
    // A Shape rather than a Rectangle: QtQuick's Rectangle.gradient only
    // accepts a plain linear Gradient, and the radial types live in
    // QtQuick.Shapes — the same place KinetixMark gets its LinearGradient.
    Shape {
        id: brandField
        anchors.centerIn: stack
        width: Math.max(stack.width, stack.height) * 1.65
        height: width
        visible: content.primary
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: brandField.width / 2
                centerY: brandField.height / 2
                centerRadius: brandField.width / 2
                GradientStop { position: 0.00; color: Qt.rgba(2 / 255, 3 / 255, 7 / 255, 0.74) }
                GradientStop { position: 0.52; color: Qt.rgba(2 / 255, 3 / 255, 7 / 255, 0.42) }
                GradientStop { position: 1.00; color: "transparent" }
            }
            startX: 0
            startY: 0
            PathLine { x: brandField.width; y: 0 }
            PathLine { x: brandField.width; y: brandField.height }
            PathLine { x: 0; y: brandField.height }
            PathLine { x: 0; y: 0 }
        }
    }

    // ── the brand composition (primary screen only) ──────────────────────
    Column {
        id: stack
        anchors.centerIn: parent
        // Nudged up slightly: the progress block adds height below the
        // wordmark, and true-centering puts the mark visually low.
        anchors.verticalCenterOffset: -6 * content.unit
        spacing: 19 * content.unit
        visible: content.primary
        width: Math.min(parent.width * 0.86, 620 * content.unit)
        // The departure, and the only place `dismissed` is consumed. Lifts and
        // dissolves rather than dissolving in place, so the handoff has a
        // direction; the lift is small on purpose, because anything larger
        // reads as the splash being thrown at the desktop rather than
        // replaced by it.
        opacity: content.dismissed ? 0 : 1
        y: content.dismissed ? -14 * content.unit : 0
        Behavior on opacity {
            NumberAnimation { duration: Theme.ms(520); easing.type: Theme.easeInOut }
        }
        Behavior on y {
            NumberAnimation { duration: Theme.ms(620); easing.type: Theme.easeOut }
        }

        // The real brand mark — the same faceted, gradient-filled K with the
        // orbiting comet laser that the bar and taskbar use, rather than a
        // second, simpler logo invented for this screen. The startup moment
        // is where the brand gets to be most itself, and it was the one
        // surface drawing a different mark from everywhere else.
        KinetixMark {
            id: mark
            anchors.horizontalCenter: parent.horizontalCenter
            size: 168 * content.unit
            // KinetixMark's internal comet/glint loops are ambient motion; its
            // entrance is not, so the two are gated separately rather than
            // collapsing `animated` and losing the arrival.
            animated: content.visible && !content.dismissed && Theme.ambient
            opacity: 0
            NumberAnimation on opacity {
                from: 0; to: 1; duration: Theme.ms(800)
                easing.type: Easing.OutCubic
                running: content.visible
            }
            scale: 0.86
            NumberAnimation on scale {
                from: 0.86; to: 1.0; duration: Theme.ms(900)
                easing.type: Easing.OutBack; easing.overshoot: 1.4
                running: content.visible
            }
        }

        // Wordmark, one letter at a time so it assembles rather than
        // appearing. Same face and case as the desktop's centre wordmark.
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 5 * content.unit
            Repeater {
                model: ["K", "I", "N", "E", "T", "I", "X", "O", "S"]
                delegate: Text {
                    id: letter
                    required property string modelData
                    required property int index
                    text: modelData
                    color: modelData === "O" ? Theme.crimsonText : Theme.text
                    font {
                        family: Theme.fontUi
                        pixelSize: Math.round(34 * content.unit)
                        weight: Font.Light
                    }
                    opacity: 0
                    // Rise into place, staggered left to right. Delay and
                    // duration are in the letter's own terms so the stagger
                    // survives the unit scaling.
                    y: 16 * content.unit
                    // Explicit target rather than `parent`: inside the
                    // nested ParallelAnimation `parent` is the animation,
                    // not this Text, so the inherited-target shorthand would
                    // animate the wrong object.
                    SequentialAnimation {
                        running: content.visible
                        PauseAnimation { duration: Theme.ms(300 + letter.index * 55) }
                        ParallelAnimation {
                            NumberAnimation {
                                target: letter
                                property: "opacity"
                                from: 0; to: 1; duration: Theme.ms(520)
                                easing.type: Easing.OutCubic
                            }
                            NumberAnimation {
                                target: letter
                                property: "y"
                                from: 16 * content.unit; to: 0; duration: Theme.ms(560)
                                easing.type: Easing.OutCubic
                            }
                        }
                    }
                }
            }
        }

        Text {
            id: tagline
            anchors.horizontalCenter: parent.horizontalCenter
            text: "YOUR DESKTOP. YOUR AGENTS."
            color: Theme.textDim
            font {
                family: Theme.fontMono
                pixelSize: Math.round(Theme.tCaption * content.unit)
                letterSpacing: 2.8
                weight: Font.Medium
            }
            opacity: 0
            SequentialAnimation {
                running: content.visible
                PauseAnimation { duration: Theme.ms(860) }
                NumberAnimation {
                    target: tagline
                    property: "opacity"
                    from: 0; to: 1; duration: Theme.ms(560)
                }
            }
        }

        // ── boot stages ──────────────────────────────────────────────────
        // What the session is actually waiting for, not a decorative sweep.
        // Each pill is a real subsystem; BootSplash wires each `done` to a
        // live signal (app index parsed, first telemetry sample, ...).
        Item {
            id: stageBlock
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width
            height: 46 * content.unit
            opacity: 0
            SequentialAnimation {
                running: content.visible
                PauseAnimation { duration: Theme.ms(1080) }
                NumberAnimation {
                    target: stageBlock
                    property: "opacity"
                    from: 0; to: 1; duration: Theme.ms(560)
                }
            }

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                spacing: 10 * content.unit
                Repeater {
                    model: content.stages
                    delegate: Row {
                        id: stageRow
                        required property var modelData
                        required property int index
                        spacing: 7 * content.unit
                        // One named handle on the stage, read by everything
                        // below. These pips used to reach *up two levels* with
                        // `parent.parent.modelData` — which qmllint flags as a
                        // missing property, correctly: `modelData` is not a
                        // member of the item two levels up, it is a member of
                        // this Row, so the lookup only worked because the
                        // nesting happened to stay fixed. Inserting a wrapper
                        // would have turned every stage's fill into a silent
                        // reference error.
                        readonly property bool done: modelData.done

                        // Pip: hollow ring while pending, filled while the
                        // stage is the one being waited on, and a solid
                        // filled dot once done — with a ring pulse so the
                        // active stage is unmistakable without a spinner.
                        Item {
                            id: pip
                            anchors.verticalCenter: parent.verticalCenter
                            width: 11 * content.unit
                            height: 11 * content.unit
                            Rectangle {
                                anchors.centerIn: parent
                                width: 9 * content.unit
                                height: width
                                radius: width / 2
                                color: stageRow.done
                                    ? Theme.crimsonText
                                    : "transparent"
                                border.width: 1.4
                                border.color: stageRow.done
                                    ? Theme.crimsonText
                                    : Theme.alpha(Theme.textFaint, 0.85)
                                opacity: stageRow.done ? 1 : 0.9
                                Behavior on opacity {
                                    NumberAnimation { duration: Theme.ms(Theme.durMed) }
                                }
                            }
                            // Only the active stage breathes. With motion
                            // reduced the ring is still drawn, at a fixed
                            // size and opacity: the pulse is the decoration,
                            // but "which stage am I waiting on" is not, and a
                            // hollow pip that never fills and never pulses
                            // would leave that unreadable.
                            Rectangle {
                                anchors.centerIn: parent
                                width: (15 + (Theme.ambient ? 2.5 : 0)) * content.unit
                                height: width
                                radius: width / 2
                                color: "transparent"
                                border.width: 1
                                border.color: Theme.alpha(Theme.crimsonText, 0.5)
                                visible: !stageRow.done
                                    && content.activeStage === stageRow.modelData
                                opacity: Theme.ambient
                                    ? 0.25 + 0.55 * Theme.heartbeatSin
                                    : 0.7
                                scale: Theme.ambient
                                    ? 0.9 + 0.25 * Theme.heartbeatSin
                                    : 1.0
                            }
                        }

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: stageRow.modelData.label
                            color: stageRow.done ? Theme.text : Theme.textFaint
                            font {
                                family: Theme.fontMono
                                pixelSize: Math.round(9 * content.unit)
                                letterSpacing: 1.5
                                weight: stageRow.done ? Font.Medium : Font.Normal
                            }
                            Behavior on color {
                                ColorAnimation { duration: Theme.ms(Theme.durMed) }
                            }
                        }
                    }
                }
            }

            // Caption and count share one line under the pills: what it is
            // doing on the left, how far along on the right. Held to the
            // progress bar's width rather than the column's, so the pills,
            // the line and the bar stack as one column instead of the line
            // running out to the edges of a much wider block.
            Item {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 26 * content.unit
                width: Math.min(parent.width, 300 * content.unit)
                height: 12 * content.unit

                Text {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    // On the way out, an unfinished stage stops being a
                    // progress caption and becomes the reason the splash is
                    // leaving. "Indexing installed applications" frozen
                    // mid-boot told the user nothing; "APPS not ready —
                    // continuing" names the subsystem and is actionable,
                    // which is the whole difference between a splash that
                    // times out and one that reports.
                    text: content.stalledNow && content.activeStage
                        ? content.activeStage.label + " not ready — continuing"
                        : (content.activeStage ? content.activeStage.caption : "Ready")
                    color: content.stalledNow ? Theme.warn : Theme.textDim
                    font {
                        family: Theme.fontMono
                        pixelSize: Math.round(9 * content.unit)
                        letterSpacing: 1.4
                    }
                    Behavior on color { ColorAnimation { duration: Theme.ms(200) } }
                }
                Text {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    visible: content.stages.length > 0
                    // Count, then elapsed. The elapsed figure is the
                    // non-motion liveness signal: the shimmer sweep it
                    // supplements is decorative, but a boot sitting at "1 / 4"
                    // for nine seconds is a fact the user can act on, and it
                    // stays legible with animation off. One decimal is enough
                    // to show it is moving without flickering the layout.
                    text: content.doneCount + " / " + content.stages.length
                        + (content.stages.length > 0
                           && !content.allComplete
                           ? "  ·  " + content.elapsed.toFixed(1) + "s"
                           : "")
                    color: Theme.textFaint
                    font {
                        family: Theme.fontMono
                        pixelSize: Math.round(9 * content.unit)
                        letterSpacing: 1.2
                    }
                }
            }
        }

        // ── progress ─────────────────────────────────────────────────────
        Item {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width, 300 * content.unit)
            height: 16 * content.unit

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: 2 * content.unit
                radius: height / 2
                color: Theme.alpha(Theme.text, 0.10)

                // Determinate fill, springy so a stage completing has a
                // little weight to it.
                Rectangle {
                    width: parent.width * Math.max(0, Math.min(1, content.progress))
                    height: parent.height
                    radius: parent.radius
                    color: Theme.crimsonText
                    Behavior on width {
                        NumberAnimation {
                            duration: Theme.ms(640)
                            easing.type: Theme.easeSoft
                        }
                    }

                    // Light travelling the filled length, so a stalled
                    // stage still reads as alive without pretending to
                    // progress it isn't making.
                    Rectangle {
                        id: shimmer
                        width: 64 * content.unit
                        height: parent.height
                        radius: parent.radius
                        visible: parent.width > 2 && !content.dismissed
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "transparent" }
                            GradientStop { position: 0.5; color: Theme.alpha(Theme.text, 0.75) }
                            GradientStop { position: 1.0; color: "transparent" }
                        }
                        x: -shimmer.width
                        NumberAnimation on x {
                            from: -shimmer.width; to: shimmer.parent.width
                            duration: 1400
                            loops: Animation.Infinite
                            // An endless sweep is the definition of ambient
                            // motion, so this stops under the motion preference
                            // rather than running slower. What it was standing
                            // in for — "this is still working" — is now carried
                            // by the elapsed counter on the caption line, which
                            // works with motion off.
                            running: content.visible && !content.dismissed
                                && Theme.ambient
                        }
                    }
                }
            }
        }
    }
}
