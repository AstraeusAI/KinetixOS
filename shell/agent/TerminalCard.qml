import QtQuick
import "../common"

// A terminal-styled output card for tool-call results (shell stdout/stderr,
// diffs, file content). Originally this embedded real xterm.js in a
// WebEngineView, but QtWebEngine requires QtWebEngineQuick::initialize()
// before the application starts — a generic `quickshell -p` process never
// calls it, and creating a WebEngineView without it is a hard qFatal() abort
// in libQt6WebEngineCore (verified: it took the whole shell down, confirmed
// via the crash reporter's stacktrace). This renders the same ANSI SGR color
// codes Argus's runtime emits (see argusd.py's tool_detail()/_ANSI_RED) as
// QML rich text instead — monospace, dark, scrollable, no extra process.
Rectangle {
    id: root
    property string text: ""
    property int minHeight: 30
    property int maxHeight: 240

    color: "#0C0505"
    radius: Theme.rS
    border.width: 1
    border.color: Theme.stroke
    clip: true
    height: Math.max(minHeight, Math.min(maxHeight, body.implicitHeight + 16))

    // Thin rim highlight, same recipe as every other well/card in the panel —
    // the one detail that keeps a flat terminal well from reading as a hole.
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
        height: 1
        radius: parent.radius
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 0.2; color: Qt.rgba(1, 1, 1, 0.10) }
            GradientStop { position: 0.8; color: Qt.rgba(1, 1, 1, 0.02) }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    // Minimal ANSI SGR → rich text. Argus only ever emits `\x1b[31m` (red,
    // for stderr/errors) and `\x1b[0m` (reset) itself; the broader color
    // table is here for whatever a wrapped shell command's own output
    // contains (ls --color, etc., when not stripped by non-tty detection).
    readonly property var _sgrColors: ({
        30: "#3a3d46", 31: "#FF6B6B", 32: "#5EEAD4", 33: "#FFB454",
        34: "#8A7CFF", 35: "#FF7AC6", 36: "#5EEAD4", 37: "rgba(255,255,255,0.94)",
        90: "rgba(255,255,255,0.45)", 91: "#FF8A8A", 92: "#7FF5DE", 93: "#FFC97A",
        94: "#A79BFF", 95: "#FF9AD6", 96: "#7FF5DE", 97: "#FFFFFF"
    })

    function _esc(s) {
        return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function ansiToRich(t) {
        if (!t) return "";
        var out = "", last = 0, open = false, bold = false;
        var re = /\x1b\[([0-9;]*)m/g;
        var m;
        while ((m = re.exec(t)) !== null) {
            out += _esc(t.slice(last, m.index));
            last = re.lastIndex;
            var codes = m[1] === "" ? [0] : m[1].split(";").map(function (s) { return parseInt(s, 10); });
            for (var i = 0; i < codes.length; i++) {
                var c = codes[i];
                if (c === 0) {
                    if (open) { out += "</span>"; open = false; }
                    bold = false;
                } else if (c === 1) {
                    bold = true;
                } else if (_sgrColors[c] !== undefined) {
                    if (open) out += "</span>";
                    out += '<span style="color:' + _sgrColors[c] + (bold ? ";font-weight:bold" : "") + '">';
                    open = true;
                }
            }
        }
        out += _esc(t.slice(last));
        if (open) out += "</span>";
        return out;
    }

    // Top rim specular highlight
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
        height: 1
        radius: parent.radius
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 0.25; color: Qt.rgba(1, 1, 1, 0.08) }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    Flickable {
        id: termFlick
        anchors.fill: parent
        anchors.margins: 8
        contentWidth: width
        contentHeight: body.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Text {
            id: body
            width: parent.width - 6
            text: root.ansiToRich(root.text)
            textFormat: Text.RichText
            wrapMode: Text.Wrap
            color: Theme.text
            font { family: Theme.fontMono; pixelSize: 11 }
        }
    }

    // Ultra-slim glass scrollbar
    Rectangle {
        id: termScrollBar
        anchors { right: parent.right; rightMargin: 2; top: parent.top; bottom: parent.bottom; margins: 4 }
        width: 2.5
        radius: 1.25
        color: Qt.rgba(1, 1, 1, 0.04)
        visible: body.implicitHeight > termFlick.height

        Rectangle {
            width: parent.width
            radius: parent.radius
            height: Math.max(14, (termFlick.height / Math.max(body.implicitHeight, 1)) * termFlick.height)
            y: (termFlick.contentY / Math.max(body.implicitHeight - termFlick.height, 1)) * (termFlick.height - height)
            // crimson-family thumb, matching the agent panel's palette — this
            // card lives inside the panel and should not carry the OS violet
            color: Theme.alpha(Theme.crimson, 0.55)
            opacity: (termFlick.moving || termFlick.flicking) ? 1.0 : 0.4
            Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
        }
    }
}
