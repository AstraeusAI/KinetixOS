import QtQuick
import "../common"

// High-fidelity perimeter outline for the main floating bar: multi-tier flowing
// chromatic light-pipe (Azure → Crimson → Solar Gold → Emerald Aurora) traveling
// clockwise around the full pill perimeter with dual orbiting specular photon glints,
// multi-tier atmospheric bloom, and status-adaptive harmonics.
Item {
    id: root

    // "bottomEdge" for edge-to-edge docked top bar rail; "loop" for floating pill perimeter
    property string mode: "bottomEdge"

    // 0 = invisible … 1 = full brightness
    property real amplitude: 0.96
    property int periodMs: 10000
    property bool boosted: false
    property string status: "idle"
    property bool hovered: false

    readonly property bool isWorking: status === "working" || boosted
    readonly property bool isWatching: status === "watching"
    readonly property bool isBlocked: status === "blocked"

    // Responsive boost scaling
    property real boost: isWorking ? 1.45
                       : isWatching ? 1.22
                       : isBlocked ? 1.30
                       : hovered ? 1.25 : 1.0
    Behavior on boost { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutCubic } }

    readonly property real effectiveAmplitude: Math.min(1.0, amplitude * boost)

    property real glowLevel: isWorking ? 1.0
                           : isWatching ? 0.94
                           : isBlocked ? 0.96
                           : hovered ? 0.95 : 0.88
    Behavior on glowLevel { NumberAnimation { duration: Theme.durSlow; easing.type: Easing.InOutSine } }

    // Dynamic animation speed multiplier
    property real speedMult: isWorking ? 2.2
                           : isWatching ? 1.25
                           : isBlocked ? 0.75
                           : hovered ? 1.25 : 1.0
    Behavior on speedMult { NumberAnimation { duration: Theme.durMed } }

    // ── Continuous motion drivers ─────────────────────────────────────────
    readonly property real sweepMs: Math.max(3200, Math.round(periodMs / Math.max(0.5, speedMult)))
    readonly property real glintMs: Math.round(sweepMs * 0.72)
    readonly property real breathMs: isWorking ? Theme.durAmbient * 1.5 : Theme.durAmbient * 3

    property real phase: 0
    property real glintPhase: 0
    property real breath: 0

    FrameAnimation {
        property real sinceRepaint: 0
        running: root.visible
        onTriggered: {
            var dt = Math.min(frameTime, 0.1);
            root.phase = (root.phase + dt * 1000 / root.sweepMs) % 1;
            root.glintPhase = (root.glintPhase + dt * 1000 / root.glintMs) % 1;
            root.breath = (root.breath + dt * 1000 / root.breathMs) % 1;
            sinceRepaint += dt;
            // 25 FPS at idle (cinema-smooth, ultra-efficient ~5% CPU), 60 FPS when active or hovered
            var targetInterval = (root.isWorking || root.hovered) ? 0.016 : 0.040;
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
            var amp = root.effectiveAmplitude * (0.88 + 0.12 * breathSin);
            if (amp <= 0.01) return;

            // ── Palette: Google's iconic four brand hues, HDR emissive calibrated ─
            // Tuned for dark-mode OLED/LCD displays with lifted chroma and luminous flux
            // so transitions remain rich, pure, and vibrant without muddy midpoint dropoff.
            var palette = [
                [0.22, 0.54, 1.00], // Electric Azure   (#388AFF)
                [0.96, 0.24, 0.24], // Neon Crimson     (#F53D3D)
                [1.00, 0.76, 0.03], // Solar Gold       (#FFC208)
                [0.15, 0.78, 0.40], // Emerald Aurora   (#26C766)
                [0.22, 0.54, 1.00]  // Seamless loop closure
            ];

            // Hermite color interpolation with mid-blend saturation lift & specular highlight
            function colorAt(progress, alpha, glintIntensity) {
                var p = (((progress % 1) + 1) % 1) * (palette.length - 1);
                var index = Math.min(palette.length - 2, Math.floor(p));
                var mix = p - index;
                var s = mix * mix * (3 - 2 * mix); // smoothstep Hermite

                var a = palette[index];
                var b = palette[index + 1];

                // Interpolated color channels
                var rCol = a[0] + (b[0] - a[0]) * s;
                var gCol = a[1] + (b[1] - a[1]) * s;
                var bCol = a[2] + (b[2] - a[2]) * s;

                // Saturation preservation: lift midpoint luminance to prevent desaturation dip
                var midBump = 1.0 + 0.12 * Math.sin(mix * Math.PI);
                rCol *= midBump;
                gCol *= midBump;
                bCol *= midBump;

                // Traveling specular photon glint modulation
                if (glintIntensity > 0.005) {
                    var g = Math.min(1.0, glintIntensity);
                    // Luminous color vibrancy surge
                    var vBoost = 1.0 + g * 0.35;
                    // Diamond-bright specular highlight at the center of the photon crest
                    var spec = Math.pow(g, 2.2) * 0.50;
                    rCol = Math.min(1.0, rCol * vBoost + spec);
                    gCol = Math.min(1.0, gCol * vBoost + spec);
                    bCol = Math.min(1.0, bCol * vBoost + spec);
                    // Slight alpha expansion for atmospheric flare
                    alpha = Math.min(1.0, alpha * (1.0 + g * 0.35));
                }

                return Qt.rgba(
                    Math.max(0, Math.min(1, rCol)),
                    Math.max(0, Math.min(1, gCol)),
                    Math.max(0, Math.min(1, bCol)),
                    Math.max(0, Math.min(1, alpha))
                );
            }

            // Shortest cyclic distance Gaussian glint profile for dual orbiting photons
            function glintAt(s) {
                var d1 = Math.abs(s - root.glintPhase);
                if (d1 > 0.5) d1 = 1.0 - d1;
                var d2 = Math.abs(s - ((root.glintPhase + 0.5) % 1));
                if (d2 > 0.5) d2 = 1.0 - d2;
                var dMin = Math.min(d1, d2);
                var sigma = 0.042; // ~320px smooth Gaussian crest
                return Math.exp(- (dMin * dMin) / (2 * sigma * sigma));
            }

            // ── Seamless Closed-Loop Pill Stroke ────────────────────
            // Top/bottom straight edges use GPU-rasterized linear gradients
            // (zero banding, zero segment gaps). Semicircular caps use continuous
            // butt-cap tangent arcs that meet flush without beads.
            function drawPillLoop(inset, lineWidth, baseAlpha) {
                var R = Math.max(0.5, r - inset);
                var cxLeft = r;
                var cxRight = w - r;
                var cy = r;
                var straight = Math.max(1, cxRight - cxLeft);
                var arc = Math.PI * R;
                var perimeter = 2 * straight + 2 * arc;

                var sTop = straight / perimeter;
                var sRight = (straight + arc) / perimeter;
                var sBot = (2 * straight + arc) / perimeter;

                ctx.lineWidth = lineWidth;
                ctx.lineCap = "butt";
                ctx.lineJoin = "round";

                // 1. Top Straight Edge (Left -> Right) via Linear Gradient
                var gradTop = ctx.createLinearGradient(cxLeft, 0, cxRight, 0);
                var nStops = Math.max(16, Math.min(32, Math.round(straight / 65)));
                for (var k = 0; k <= nStops; k++) {
                    var u = k / nStops;
                    var s = u * sTop;
                    var wavePhase = (((s - root.phase) % 1) + 1) % 1;
                    var glint = glintAt(s);
                    var alpha = amp * root.glowLevel * baseAlpha;
                    var col = colorAt(wavePhase, alpha, glint);
                    gradTop.addColorStop(u, col);
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
                    var wavePhaseArc = (((sArc - root.phase) % 1) + 1) % 1;
                    var glintArc = glintAt(sArc);
                    var alphaArc = amp * root.glowLevel * baseAlpha;
                    var colArc = colorAt(wavePhaseArc, alphaArc, glintArc);
                    ctx.strokeStyle = colArc;
                    ctx.beginPath();
                    ctx.arc(cxRight, cy, R, a0, a1);
                    ctx.stroke();
                }

                // 3. Bottom Straight Edge (Right -> Left) via Linear Gradient
                var gradBot = ctx.createLinearGradient(cxRight, 0, cxLeft, 0);
                for (var m = 0; m <= nStops; m++) {
                    var ub = m / nStops;
                    var sb = sRight + ub * (sBot - sRight);
                    var wavePhaseB = (((sb - root.phase) % 1) + 1) % 1;
                    var glintB = glintAt(sb);
                    var alphaB = amp * root.glowLevel * baseAlpha;
                    var colB = colorAt(wavePhaseB, alphaB, glintB);
                    gradBot.addColorStop(ub, colB);
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
                    var wavePhaseL = (((sLeft - root.phase) % 1) + 1) % 1;
                    var glintL = glintAt(sLeft);
                    var alphaL = amp * root.glowLevel * baseAlpha;
                    var colL = colorAt(wavePhaseL, alphaL, glintL);
                    ctx.strokeStyle = colL;
                    ctx.beginPath();
                    ctx.arc(cxLeft, cy, R, la0, la1);
                    ctx.stroke();
                }
            }

            // ── Edge-to-Edge Linear Rail Mode ──────────────────────────────────
            // Continuous horizontal chromatic laser rail along the bottom edge
            // (y = h - inset) with dual orbiting specular photon crests, multi-tier
            // atmospheric diffusion, and status-adaptive harmonics.
            function drawBottomRail(inset, lineWidth, baseAlpha) {
                var y = h - inset;
                ctx.lineWidth = lineWidth;
                ctx.lineCap = "butt";
                ctx.lineJoin = "miter";

                var grad = ctx.createLinearGradient(0, y, w, y);
                var nStops = Math.max(32, Math.min(96, Math.round(w / 40)));
                for (var k = 0; k <= nStops; k++) {
                    var u = k / nStops;
                    var s = u; // spatial progress [0, 1] along bottom boundary
                    var wavePhase = (((s - root.phase) % 1) + 1) % 1;
                    var glint = glintAt(s);
                    var alpha = amp * root.glowLevel * baseAlpha;
                    var col = colorAt(wavePhase, alpha, glint);
                    grad.addColorStop(u, col);
                }
                ctx.strokeStyle = grad;
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
                ctx.stroke();
            }

            if (root.mode === "bottomEdge") {
                // Pass 1: Diffuse Atmospheric Haze (ethereal upward dispersion into obsidian glass)
                var lwHaze = root.isWorking ? 10.0 : 8.0;
                var hazeAlpha = root.isWorking ? 0.35 : (root.hovered ? 0.28 : 0.20);
                drawBottomRail(lwHaze * 0.4, lwHaze, hazeAlpha);

                // Pass 2: Volumetric Bloom Core
                var lwBloomB = root.isWorking ? 6.0 : 4.5;
                var bloomAlphaB = root.isWorking ? 0.60 : (root.hovered ? 0.50 : 0.40);
                drawBottomRail(lwBloomB * 0.45, lwBloomB, bloomAlphaB);

                // Pass 3: Saturated Chromatic Light-Pipe Ribbon
                var lwCoreB = root.isWorking ? 2.8 : 2.2;
                var coreAlphaB = root.isWorking ? 1.0 : (root.hovered ? 0.96 : 0.90);
                drawBottomRail(lwCoreB * 0.5, lwCoreB, coreAlphaB);

                // Pass 4: Precision Crystalline Laser Hairline (razor specular boundary)
                var lwLaserB = 1.15;
                var laserAlphaB = root.isWorking ? 1.0 : (root.hovered ? 0.98 : 0.95);
                drawBottomRail(0.6, lwLaserB, laserAlphaB);
            } else {
                // Pass 1: Volumetric Atmospheric Bloom
                var lwBloom = root.isWorking ? 7.5 : 6.0;
                var bloomAlpha = root.isWorking ? 0.55 : (root.hovered ? 0.45 : 0.35);
                drawPillLoop(lwBloom * 0.5, lwBloom, bloomAlpha);

                // Pass 2: Chromatic Core Light-Pipe Ribbon
                var lwCore = root.isWorking ? 3.0 : 2.5;
                var coreAlpha = root.isWorking ? 1.0 : (root.hovered ? 0.96 : 0.88);
                drawPillLoop(lwCore * 0.5, lwCore, coreAlpha);

                // Pass 3: Precision Crystalline Laser Hairline
                var lwLaser = 1.15;
                var laserAlpha = root.isWorking ? 1.0 : (root.hovered ? 0.98 : 0.94);
                drawPillLoop(0.65, lwLaser, laserAlpha);
            }
        }
    }
}
