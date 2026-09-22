import QtQuick
import "../common"

// Lightweight sparkline drawn from a numeric history array.
// Auto-scales to the data (with an optional fixed ceiling),
// with smooth curves, gradient area fills, and active head dot.
Item {
    id: root

    property var values: []
    property real ceiling: 100      // scale ceiling; <=0 → auto-scale to max
    property color lineColor: Theme.accent2
    property color fillColor: Theme.alpha(lineColor, 0.28)
    property real lineWidth: 1.4
    property bool smooth: true
    property bool gradientFill: true
    property bool showDot: true

    onValuesChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
    onLineColorChanged: canvas.requestPaint()
    onFillColorChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true
        renderStrategy: Canvas.Cooperative

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var v = root.values;
            var n = v ? v.length : 0;
            if (n < 2) return;

            var max = root.ceiling;
            if (max <= 0) {
                max = 1;
                for (var i = 0; i < n; i++) max = Math.max(max, v[i]);
                max *= 1.15;
            }

            var w = width, h = height;
            var step = w / (n - 1);
            var pad = root.lineWidth + 1;

            function px(idx) { return idx * step; }
            function py(val) { return h - pad - (Math.min(val, max) / max) * (h - pad * 2); }

            // fill (matching line curvature)
            ctx.beginPath();
            ctx.moveTo(0, h);
            ctx.lineTo(px(0), py(v[0]));
            for (var j = 1; j < n; j++) {
                if (root.smooth && j < n - 1) {
                    var xcj = (px(j) + px(j + 1)) / 2;
                    var ycj = (py(v[j]) + py(v[j + 1])) / 2;
                    ctx.quadraticCurveTo(px(j), py(v[j]), xcj, ycj);
                } else {
                    ctx.lineTo(px(j), py(v[j]));
                }
            }
            ctx.lineTo(px(n - 1), h);
            ctx.closePath();

            if (root.gradientFill) {
                var grad = ctx.createLinearGradient(0, 0, 0, h);
                grad.addColorStop(0.0, root.fillColor);
                grad.addColorStop(0.7, Theme.alpha(root.fillColor, 0.4));
                grad.addColorStop(1.0, "transparent");
                ctx.fillStyle = grad;
            } else {
                ctx.fillStyle = root.fillColor;
            }
            ctx.fill();

            // line
            ctx.beginPath();
            ctx.moveTo(px(0), py(v[0]));
            for (var k = 1; k < n; k++) {
                if (root.smooth && k < n - 1) {
                    var xc = (px(k) + px(k + 1)) / 2;
                    var yc = (py(v[k]) + py(v[k + 1])) / 2;
                    ctx.quadraticCurveTo(px(k), py(v[k]), xc, yc);
                } else {
                    ctx.lineTo(px(k), py(v[k]));
                }
            }
            ctx.strokeStyle = root.lineColor;
            ctx.lineWidth = root.lineWidth;
            ctx.lineJoin = "round";
            ctx.lineCap = "round";
            ctx.stroke();

            // active head dot at the latest point
            if (root.showDot && n > 0) {
                var lastX = px(n - 1);
                var lastY = py(v[n - 1]);

                // outer glow
                ctx.beginPath();
                ctx.arc(lastX, lastY, Math.max(2.4, root.lineWidth * 2.0), 0, 2 * Math.PI);
                ctx.fillStyle = Qt.rgba(root.lineColor.r, root.lineColor.g, root.lineColor.b, 0.30);
                ctx.fill();

                // solid inner core
                ctx.beginPath();
                ctx.arc(lastX, lastY, Math.max(1.2, root.lineWidth * 1.0), 0, 2 * Math.PI);
                ctx.fillStyle = root.lineColor;
                ctx.fill();
            }
        }
    }
}
