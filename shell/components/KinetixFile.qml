import QtQuick
import QtQuick.Shapes

// KinetixFile — the KinetixOS file icon, a companion to KinetixFolder. A sheet
// of paper with a folded corner, content lines that suggest the file's kind,
// and a coloured badge carrying its extension. The top edge carries the
// system's red → green → blue light. Hover lifts the sheet and the fold.
// Drawn in vector; nothing animates at rest.
Item {
    id: root

    property real size: 52
    property bool hovered: false
    property string suffix: ""       // file extension, shown on the badge

    implicitWidth: size
    implicitHeight: size
    width: size
    height: size

    readonly property string ext: suffix.toLowerCase()
    readonly property string kind: {
        var map = {
            text: ["txt", "md", "log", "rst", "csv", "conf", "ini", "cfg", "toml", "yaml", "yml"],
            script: ["sh", "bash", "zsh", "fish", "ps1", "bat"],
            code: ["py", "js", "ts", "qml", "c", "h", "cpp", "hpp", "rs", "go", "java", "json", "html", "css", "lua", "rb", "php", "kt", "swift", "frag", "vert"],
            archive: ["zip", "tar", "gz", "xz", "zst", "bz2", "7z", "rar", "tgz", "deb", "rpm"],
            pdf: ["pdf"],
            audio: ["mp3", "flac", "wav", "ogg", "opus", "m4a", "aac"],
            video: ["mp4", "mkv", "webm", "mov", "avi"],
            doc: ["odt", "doc", "docx", "rtf", "ods", "xls", "xlsx", "odp", "ppt", "pptx"],
            disk: ["iso", "img", "qcow2", "vdi", "vmdk"]
        };
        for (var k in map) if (map[k].indexOf(ext) >= 0) return k;
        return "generic";
    }
    readonly property color badge: ({
        text: "#4285F4", script: "#34A853", code: "#12B5CB", archive: "#F9AB00",
        pdf: "#EA4335", audio: "#1ABC9C", video: "#FA7B17", doc: "#5C6BC0",
        disk: "#8D98A8", generic: "#8D98A8"
    })[kind]
    readonly property string label: ext === "" ? "FILE" : (ext.length > 4 ? ext.slice(0, 4) : ext).toUpperCase()

    property real lift: hovered ? 1 : 0
    Behavior on lift { NumberAnimation { duration: 240; easing.type: Easing.OutBack; easing.overshoot: 1.3 } }

    Item {
        width: 100
        height: 100
        scale: root.size / 100
        transformOrigin: Item.TopLeft

        // soft contact shadow (widens as the sheet lifts)
        Rectangle {
            x: 20 - 2 * root.lift; y: 86
            width: 60 + 4 * root.lift; height: 9
            radius: 4.5
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.45 - 0.12 * root.lift) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        Item {
            id: sheet
            anchors.fill: parent
            transform: Translate { y: -3 * root.lift }

            // ── the page, with its corner cut for the fold ──
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: Qt.rgba(0, 0, 0, 0.18)
                    strokeWidth: 0.8
                    fillGradient: LinearGradient {
                        x1: 0; y1: 8; x2: 0; y2: 90
                        GradientStop { position: 0.0; color: "#FFFFFF" }
                        GradientStop { position: 1.0; color: "#DCD1D5" }
                    }
                    startX: 24; startY: 8
                    PathLine { x: 60; y: 8 }
                    PathLine { x: 80; y: 28 }
                    PathLine { x: 80; y: 84 }
                    PathQuad { x: 75; y: 89; controlX: 80; controlY: 89 }
                    PathLine { x: 25; y: 89 }
                    PathQuad { x: 20; y: 84; controlX: 20; controlY: 89 }
                    PathLine { x: 20; y: 12 }
                    PathQuad { x: 24; y: 8; controlX: 20; controlY: 8 }
                }
            }
            // the system's light along the top edge
            Rectangle {
                x: 24; y: 8
                width: 34; height: 1.6
                radius: 0.8
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "#EA4335" }
                    GradientStop { position: 0.5; color: "#34A853" }
                    GradientStop { position: 1.0; color: "#4285F4" }
                }
                opacity: 0.8
            }
            // folded corner (lifts a touch on hover)
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "transparent"
                    fillGradient: LinearGradient {
                        x1: 60; y1: 8; x2: 80; y2: 28
                        GradientStop { position: 0.0; color: "#BEB2B7" }
                        GradientStop { position: 1.0; color: "#F4EEF0" }
                    }
                    startX: 60; startY: 8
                    PathLine { x: 60 - 2 * root.lift; y: 26 + 2 * root.lift }
                    PathQuad { x: 62; y: 28; controlX: 60 - 2 * root.lift; controlY: 28 }
                    PathLine { x: 80; y: 28 }
                    PathLine { x: 60; y: 8 }
                }
            }

            // ── content lines, suggesting the kind ──
            Item {
                x: 28; y: 32
                width: 44; height: 30
                // text / doc / generic: ruled lines
                Column {
                    visible: ["text", "doc", "generic", "pdf"].indexOf(root.kind) >= 0
                    spacing: 5
                    Repeater {
                        model: 4
                        Rectangle {
                            required property int index
                            width: [40, 44, 30, 38][index]; height: 2.4; radius: 1.2
                            color: Qt.rgba(0.3, 0.26, 0.3, 0.28)
                        }
                    }
                }
                // script / code: indented code lines + a prompt/bracket
                Column {
                    visible: root.kind === "script" || root.kind === "code"
                    spacing: 5
                    Repeater {
                        model: 4
                        Row {
                            required property int index
                            spacing: 3
                            Item { width: [0, 7, 7, 0][parent.index]; height: 1 }
                            Rectangle {
                                width: [16, 24, 18, 12][parent.index]; height: 2.4; radius: 1.2
                                color: Qt.rgba(root.badge.r, root.badge.g, root.badge.b, 0.55)
                            }
                            Rectangle {
                                width: [12, 8, 14, 0][parent.index]; height: 2.4; radius: 1.2
                                color: Qt.rgba(0.3, 0.26, 0.3, 0.28)
                            }
                        }
                    }
                }
                // archive: a zipper down the middle
                Column {
                    visible: root.kind === "archive"
                    x: 16
                    spacing: 2
                    Repeater {
                        model: 7
                        Rectangle {
                            required property int index
                            x: index % 2 ? 4 : 0
                            width: 8; height: 2.4; radius: 1
                            color: Qt.rgba(0.35, 0.3, 0.2, 0.45)
                        }
                    }
                }
                // audio: a waveform
                Row {
                    visible: root.kind === "audio"
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2.5
                    Repeater {
                        model: 11
                        Rectangle {
                            required property int index
                            anchors.verticalCenter: parent.verticalCenter
                            width: 2.4; radius: 1.2
                            height: [6, 12, 20, 14, 26, 18, 24, 10, 16, 8, 5][index]
                            color: Qt.rgba(root.badge.r, root.badge.g, root.badge.b, 0.7)
                        }
                    }
                }
                // video: a play triangle in a frame
                Rectangle {
                    visible: root.kind === "video"
                    anchors.centerIn: parent
                    width: 34; height: 24; radius: 4
                    color: Qt.rgba(0.2, 0.18, 0.22, 0.14)
                    border.width: 1.4
                    border.color: Qt.rgba(root.badge.r, root.badge.g, root.badge.b, 0.7)
                    Shape {
                        anchors.fill: parent
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: "transparent"
                            fillColor: Qt.rgba(root.badge.r, root.badge.g, root.badge.b, 0.9)
                            startX: 14; startY: 7
                            PathLine { x: 23; y: 12 }
                            PathLine { x: 14; y: 17 }
                            PathLine { x: 14; y: 7 }
                        }
                    }
                }
                // disk image: a disc
                Rectangle {
                    visible: root.kind === "disk"
                    anchors.centerIn: parent
                    width: 28; height: 28; radius: 14
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "#E7EEF5" }
                        GradientStop { position: 1.0; color: "#A9B4C2" }
                    }
                    border.width: 1
                    border.color: Qt.rgba(0, 0, 0, 0.18)
                    Rectangle { anchors.centerIn: parent; width: 7; height: 7; radius: 3.5; color: "#DCD1D5"; border.width: 1; border.color: Qt.rgba(0, 0, 0, 0.2) }
                }
            }

            // ── type badge ──
            Rectangle {
                x: 14; y: 66
                width: Math.max(30, badgeText.implicitWidth + 12)
                height: 15
                radius: 4
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.lighter(root.badge, 1.15) }
                    GradientStop { position: 1.0; color: Qt.darker(root.badge, 1.25) }
                }
                border.width: 0.8
                border.color: Qt.rgba(1, 1, 1, 0.35)
                Rectangle {   // gloss
                    anchors { top: parent.top; left: parent.left; right: parent.right; margins: 1 }
                    height: parent.height / 2 - 1
                    radius: 3
                    color: Qt.rgba(1, 1, 1, 0.18)
                }
                Text {
                    id: badgeText
                    anchors.centerIn: parent
                    text: root.label
                    color: "white"
                    font { family: "Inter"; pixelSize: 9; weight: Font.Black; letterSpacing: 0.4 }
                }
            }
        }
    }
}
