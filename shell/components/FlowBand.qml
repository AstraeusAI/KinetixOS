import QtQuick
import "../common"

// Ambient gradient shimmer for the main bar's bottom edge, in the vein of
// Gemini/NotebookLM's "AI is working" glow: a soft, Gaussian-blurred band
// whose hue drifts continuously along the bar's own crimson family. There is
// no traveling point highlight — the only motion is the slow, steady color
// drift itself, so it reads as ambient rather than busy. Colors come
// straight from Theme so the rail always matches the bar's actual palette.
Item {
    id: root

    // "bottomEdge" for edge-to-edge docked top bar rail; "loop" for floating pill perimeter
    property string mode: "bottomEdge"

    // 0 = invisible … 1 = full brightness
    property real amplitude: 1.0
    property int periodMs: 10000
    property bool boosted: false
    property string status: "idle"
    property bool hovered: false

    readonly property bool isWorking: status === "working" || boosted
    readonly property bool isWatching: status === "watching"
    readonly property bool isBlocked: status === "blocked"

    // Responsive boost scaling
    property real boost: isWorking ? 1.55
                       : isWatching ? 1.28
                       : isBlocked ? 1.38
                       : hovered ? 1.30 : 1.0
    Behavior on boost { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutCubic } }

    readonly property real effectiveAmplitude: Math.min(1.0, amplitude * boost)

    // Keep the idle rail as a fine ambient seam; reserve the brighter bloom
    // for actual agent activity or deliberate pointer attention.
    property real glowLevel: isWorking ? 1.0
                           : isWatching ? 0.88
                           : isBlocked ? 0.92
                           : hovered ? 0.72 : 0.50
    Behavior on glowLevel { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.InOutSine } }

    // Dynamic drift speed multiplier
    property real speedMult: isWorking ? 1.8
                           : isWatching ? 1.2
                           : isBlocked ? 0.8
                           : hovered ? 1.15 : 1.0
    Behavior on speedMult { NumberAnimation { duration: Theme.durMed } }

    // ── Continuous motion drivers ─────────────────────────────────────────
    // sweepMs is deliberately long — this is a slow ambient hue drift, not a
    // sweeping beam, so it should never feel like it's "racing" the bar.
    readonly property real sweepMs: Math.max(5200, Math.round(periodMs / Math.max(0.5, speedMult)))
    readonly property real breathMs: isWorking ? Theme.durAmbient * 2 : Theme.durAmbient * 3.5

    property real phase: 0
    property real breath: 0

    FrameAnimation {
        property real sinceRepaint: 0
        running: root.visible
        onTriggered: {
            var dt = Math.min(frameTime, 0.1);
            root.phase = (root.phase + dt * 1000 / root.sweepMs) % 1;
            root.breath = (root.breath + dt * 1000 / root.breathMs) % 1;
            sinceRepaint += dt;
            // 15 FPS at idle (the drift is slow enough that this is
            // indistinguishable from 60 FPS but costs ~1/4 the paint time),
            // 60 FPS when active or hovered
            var targetInterval = (root.isWorking || root.hovered) ? 0.016 : 0.066;
            if (sinceRepaint >= targetInterval) {
                sinceRepaint = 0;
                canvas.requestPaint();
            }
        }
    }

    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
    onEffectiveAmplitudeChanged: canvas.requestPaint()
    onGlowLevelChanged: canvas.requestPaint()
    onStatusChanged: canvas.requestPaint()
    onModeChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        renderTarget: Canvas.FramebufferObject
        renderStrategy: Canvas.Immediate
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();

            var w = width;
            var h = height;
            if (w <= 24 || h <= 10) return;

            var r = h / 2; // Exact pill cap radius (e.g. 26px for h=52)
            var breathSin = 0.5 + 0.5 * Math.sin(root.breath * Math.PI * 2);
            var amp = root.effectiveAmplitude * (0.92 + 0.08 * breathSin);
            if (amp <= 0.01) return;

            function triple(c) { return [c.r, c.g, c.b]; }

            // Status-adaptive palette, always drawn from the bar's own crimson
            // family in Theme — never colors invented outside it. Every stop
            // stays lit; nothing dips to near-black, so the shimmer never shows
            // a dead patch as it drifts.
            var palette = root.isBlocked ? [
                triple(Theme.alarm),
                triple(Theme.warn),
                triple(Theme.alarm)
            ] : root.isWatching ? [
                triple(Theme.gilded),
                triple(Theme.ember),
                triple(Theme.alarm),
                triple(Theme.gilded)
            ] : [
                triple(Theme.crimson),
                triple(Theme.crimsonText),
                triple(Theme.ember),
                triple(Theme.gilded),
                triple(Theme.alarm),
                triple(Theme.crimson)
            ];

            // Hermite color interpolation with a small mid-blend saturation
            // lift so the interpolated midpoint doesn't read as washed out.
            function colorAt(progress, alpha) {
                var p = (((progress % 1) + 1) % 1) * (palette.length - 1);
                var index = Math.min(palette.length - 2, Math.floor(p));
                var mix = p - index;
                var s = mix * mix * (3 - 2 * mix); // smoothstep Hermite

                var a = palette[index];
                var b = palette[index + 1];

                var rCol = a[0] + (b[0] - a[0]) * s;
                var gCol = a[1] + (b[1] - a[1]) * s;
                var bCol = a[2] + (b[2] - a[2]) * s;

                var midBump = 1.0 + 0.12 * Math.sin(mix * Math.PI);
                rCol *= midBump;
                gCol *= midBump;
                bCol *= midBump;

                return Qt.rgba(
                    Math.max(0, Math.min(1, rCol)),
                    Math.max(0, Math.min(1, gCol)),
                    Math.max(0, Math.min(1, bCol)),
                    Math.max(0, Math.min(1, alpha))
                );
            }

            // How many times the palette repeats across the shape: a single
            // pass of 6 similar warm hues over a wide bar barely changes
            // per-pixel, so the drift reads as static. Repeating the palette
            // and letting phase slide it gives a clearly visible flowing
            // band — still smooth and ambient, just actually perceptible.
            var repeats = Math.max(2, Math.min(6, Math.round(w / 220)));

            // ── Seamless Closed-Loop Pill Stroke ────────────────────
            function drawPillLoop(inset, lineWidth, baseAlpha) {
                var R = Math.max(0.5, r - inset);
                var cxLeft = r;
                var cxRight = w - r;
                var cy = r;
                var straight = Math.max(1, cxRight - cxLeft);
                var arc = Math.PI * R;
                var perimeter = 2 * straight + 2 * arc;

                var sRight = (straight + arc) / perimeter;
                var sBot = (2 * straight + arc) / perimeter;
                var alpha = amp * root.glowLevel * baseAlpha;

                ctx.lineWidth = lineWidth;
                ctx.lineCap = "butt";
                ctx.lineJoin = "round";

                // 1. Top Straight Edge (Left -> Right) via Linear Gradient
                var gradTop = ctx.createLinearGradient(cxLeft, 0, cxRight, 0);
                var nStops = Math.max(16, Math.min(32, Math.round(straight / 65)));
                for (var k = 0; k <= nStops; k++) {
                    var u = k / nStops;
                    var s = u * (straight / perimeter);
                    var wavePhase = (((s * repeats - root.phase) % 1) + 1) % 1;
                    gradTop.addColorStop(u, colorAt(wavePhase, alpha));
                }
                ctx.strokeStyle = gradTop;
                ctx.beginPath();
                ctx.moveTo(cxLeft, inset);
                ctx.lineTo(cxRight, inset);
                ctx.stroke();

                // 2. Right Semicircular Cap (-PI/2 -> +PI/2)
                var nArc = 10;
                for (var j = 0; j < nArc; j++) {
                    var a0 = -Math.PI / 2 + (j / nArc) * Math.PI;
                    var a1 = -Math.PI / 2 + ((j + 1.004) / nArc) * Math.PI;
                    var aMid = (a0 + a1) / 2;
                    var dist = straight + R * (aMid + Math.PI / 2);
                    var sArc = dist / perimeter;
                    var wavePhaseArc = (((sArc * repeats - root.phase) % 1) + 1) % 1;
                    ctx.strokeStyle = colorAt(wavePhaseArc, alpha);
                    ctx.beginPath();
                    ctx.arc(cxRight, cy, R, a0, a1);
                    ctx.stroke();
                }

                // 3. Bottom Straight Edge (Right -> Left) via Linear Gradient
                var gradBot = ctx.createLinearGradient(cxRight, 0, cxLeft, 0);
                for (var m = 0; m <= nStops; m++) {
                    var ub = m / nStops;
                    var sb = sRight + ub * (sBot - sRight);
                    var wavePhaseB = (((sb * repeats - root.phase) % 1) + 1) % 1;
                    gradBot.addColorStop(ub, colorAt(wavePhaseB, alpha));
                }
                ctx.strokeStyle = gradBot;
                ctx.beginPath();
                ctx.moveTo(cxRight, h - inset);
                ctx.lineTo(cxLeft, h - inset);
                ctx.stroke();

                // 4. Left Semicircular Cap (+PI/2 -> +3PI/2)
                for (var q = 0; q < nArc; q++) {
                    var la0 = Math.PI / 2 + (q / nArc) * Math.PI;
                    var la1 = Math.PI / 2 + ((q + 1.004) / nArc) * Math.PI;
                    var laMid = (la0 + la1) / 2;
                    var distL = 2 * straight + arc + R * (laMid - Math.PI / 2);
                    var sLeft = distL / perimeter;
                    var wavePhaseL = (((sLeft * repeats - root.phase) % 1) + 1) % 1;
                    ctx.strokeStyle = colorAt(wavePhaseL, alpha);
                    ctx.beginPath();
                    ctx.arc(cxLeft, cy, R, la0, la1);
                    ctx.stroke();
                }
            }

            // ── Edge-to-Edge Linear Rail Mode ──────────────────────────────────
            function drawBottomRail(inset, lineWidth, baseAlpha) {
                var y = h - inset;
                ctx.lineWidth = lineWidth;
                ctx.lineCap = "butt";
                ctx.lineJoin = "miter";

                var grad = ctx.createLinearGradient(0, y, w, y);
                var nStops = Math.max(36, Math.min(108, Math.round(w / 35)));
                var alpha = amp * root.glowLevel * baseAlpha;
                for (var k = 0; k <= nStops; k++) {
                    var u = k / nStops;
                    var wavePhase = (((u * repeats - root.phase) % 1) + 1) % 1;
                    grad.addColorStop(u, colorAt(wavePhase, alpha));
                }
                ctx.strokeStyle = grad;
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
                ctx.stroke();
            }

            // A single flat-color halo (the shape's alpha channel, Gaussian-blurred
            // and tinted by shadowColor) is the whole visual: a soft ambient band,
            // no distinct traveling highlight riding on top of it.
            var haloColor = root.isBlocked ? Theme.alarm : root.isWatching ? Theme.gilded : Theme.crimson;
            var haloAlpha = amp * root.glowLevel * (root.isWorking ? 0.52 : (root.hovered ? 0.34 : 0.20));
            var haloBlur = root.isWorking ? 12 : (root.hovered ? 9 : 6);

            ctx.shadowColor = Qt.rgba(haloColor.r, haloColor.g, haloColor.b, haloAlpha);
            ctx.shadowBlur = haloBlur;

            var lwCore = root.isWorking ? 1.6 : (root.hovered ? 1.15 : 1.0);
            var coreAlpha = root.isWorking ? 1.0 : (root.hovered ? 0.82 : 0.62);

            if (root.mode === "bottomEdge") {
                drawBottomRail(0.9, lwCore, coreAlpha);
            } else {
                drawPillLoop(0.9, lwCore, coreAlpha);
            }

            ctx.shadowBlur = 0;
            ctx.shadowColor = "transparent";
        }
    }
}
