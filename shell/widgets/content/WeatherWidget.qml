import QtQuick
import Quickshell.Io
import "../../common"

// High-fidelity weather gadget via wttr.in: animated weather glyphs,
// large hero temperatures, and frosted telemetry metric cards.
Item {
    id: root
    property var widget
    property var cfg: ({})
    property string raw: ""
    property bool loading: true
    property bool failed: false

    readonly property string location: cfg.location || ""

    function refresh() {
        root.loading = true;
        var loc = root.location || "";
        // Sanitize location for shell safety: only alphanumerics, spaces, hyphens, underscores, dots, commas, slashes
        var safeLoc = loc.replace(/[^a-zA-Z0-9 _\-\.,\/]/g, "");
        proc.command = ["sh", "-c",
            "curl -s --max-time 12 'wttr.in/" +
            safeLoc +
            "?format=%C|%t|%f|%w|%h|%p' 2>/dev/null"];
        proc.running = true;
    }

    Component.onCompleted: refresh()
    onLocationChanged: refresh()

    Timer {
        id: refreshTimer
        interval: 900000 // 15 minutes
        running: true
        repeat: true
        onTriggered: root.refresh()
    }

    Process {
        id: proc
        stdout: StdioCollector {
            onStreamFinished: {
                root.loading = false;
                root.raw = this.text.trim();
                root.failed = root.raw === "" || root.raw.indexOf("|") < 0;
            }
        }
    }

    Component.onDestruction: {
        proc.running = false;
        refreshTimer.running = false;
    }

    property var parts: raw.split("|")
    readonly property string condition: parts.length > 0 ? parts[0].trim() : ""
    readonly property string temp: parts.length > 1 ? parts[1].trim().replace(/^\+/, "") : "—"
    readonly property string feelsLike: parts.length > 2 ? parts[2].trim().replace(/^\+/, "") : "—"
    readonly property string wind: parts.length > 3 ? parts[3].trim() : "—"
    readonly property string humidity: parts.length > 4 ? parts[4].trim() : "—"
    readonly property string precip: parts.length > 5 ? parts[5].trim() : "—"

    function weatherIcon(c) {
        var s = (c || "").toLowerCase();
        if (s.indexOf("thunder") >= 0 || s.indexOf("storm") >= 0) return "⛈";
        if (s.indexOf("snow") >= 0 || s.indexOf("ice") >= 0 || s.indexOf("blizzard") >= 0) return "❄";
        if (s.indexOf("rain") >= 0 || s.indexOf("shower") >= 0 || s.indexOf("drizzle") >= 0) return "🌧";
        if (s.indexOf("partly") >= 0) return "⛅";
        if (s.indexOf("cloud") >= 0 || s.indexOf("overcast") >= 0) return "☁";
        if (s.indexOf("fog") >= 0 || s.indexOf("mist") >= 0 || s.indexOf("haze") >= 0) return "🌫";
        if (s.indexOf("clear") >= 0 || s.indexOf("sun") >= 0) return "☀";
        return "🌤";
    }

    function weatherColor(c) {
        var s = (c || "").toLowerCase();
        if (s.indexOf("thunder") >= 0) return Theme.accent;
        if (s.indexOf("snow") >= 0) return "#A0E7E5";
        if (s.indexOf("rain") >= 0) return Theme.accent2;
        if (s.indexOf("clear") >= 0 || s.indexOf("sun") >= 0) return Theme.warn;
        return Theme.text;
    }

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentCol.implicitHeight + Theme.s4 * 2
        boundsBehavior: Flickable.StopAtBounds
        clip: true

        Column {
            id: contentCol
            anchors {
                left: parent.left
                right: parent.right
                top: parent.top
                margins: Theme.s4
            }
            spacing: Theme.s3

            // Loading / Error State
            Item {
                visible: root.loading || root.failed
                width: parent.width
                height: 120

                Column {
                    anchors.centerIn: parent
                    spacing: Theme.s2
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.failed ? "⚠" : "◌"
                        color: root.failed ? Theme.warn : Theme.accent2
                        font.pixelSize: 28
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.failed ? "Weather data unavailable" : "Connecting to weather service…"
                        color: Theme.textFaint
                        font { family: Theme.fontUi; pixelSize: Theme.tCaption }
                    }
                }
            }

            // Normal Content
            Column {
                visible: !root.loading && !root.failed
                width: parent.width
                spacing: Theme.s3

                // Hero Row: Icon + Temp + Condition
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: Theme.s3

                    // Glowing Icon Pill
                    Rectangle {
                        width: 52; height: 52; radius: Theme.rM
                        color: Theme.surfaceLow
                        border.width: 1
                        border.color: Theme.stroke
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                            anchors.centerIn: parent
                            text: root.weatherIcon(root.condition)
                            font.pixelSize: 28
                        }
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 1

                        Text {
                            text: root.temp
                            color: Theme.text
                            font { family: Theme.fontUi; pixelSize: 34; weight: Font.Light; letterSpacing: -0.5 }
                        }

                        Text {
                            text: root.condition.toUpperCase()
                            color: root.weatherColor(root.condition)
                            font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.4; weight: Font.DemiBold }
                        }
                    }
                }

                // 2x2 Telemetry Cards
                Grid {
                    width: parent.width
                    columns: 2
                    spacing: Theme.s2

                    component WeatherCell: Rectangle {
                        property string k
                        property string v
                        width: Math.floor((parent.width - Theme.s2) / 2)
                        height: 42
                        radius: Theme.rS
                        color: Theme.surfaceLow
                        border.width: 1
                        border.color: Theme.stroke

                        Column {
                            anchors.centerIn: parent
                            spacing: 1
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: parent.parent.k
                                color: Theme.textFaint
                                font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.0 }
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: parent.parent.v
                                color: Theme.textDim
                                font { family: Theme.fontMono; pixelSize: Theme.tCaption; weight: Font.Medium }
                            }
                        }
                    }

                    WeatherCell { k: "FEELS LIKE"; v: root.feelsLike }
                    WeatherCell { k: "WIND"; v: root.wind }
                    WeatherCell { k: "HUMIDITY"; v: root.humidity }
                    WeatherCell { k: "PRECIP"; v: root.precip }
                }

                // Location Pill
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 4

                    Text {
                        text: "📍"
                        color: Theme.textFaint
                        font.pixelSize: 10
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Text {
                        text: root.location === "" ? "Auto-detected location" : root.location
                        color: Theme.textFaint
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }
    }
}
