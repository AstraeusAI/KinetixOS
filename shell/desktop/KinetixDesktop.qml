import QtQuick
import Quickshell
import Quickshell.Wayland
import "../common"
import "../components"

// Non-interactive desktop dressing inspired by the KinetixOS reference.
// The established top bar remains its own unchanged surface above this layer.
PanelWindow {
    id: root
    required property ShellScreen modelData
    screen: modelData

    anchors { top: true; right: true; bottom: true; left: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    mask: Region {}

    WlrLayershell.namespace: "kinetix:desktop-art"
    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    property int localHour: (new Date()).getHours()
    readonly property string greeting: localHour < 12 ? "GOOD MORNING"
        : localHour < 18 ? "GOOD AFTERNOON" : "GOOD EVENING"

    Timer {
        interval: 60000
        running: true
        repeat: true
        onTriggered: root.localHour = (new Date()).getHours()
    }

    // The image itself contains only landscape art. Live shell surfaces,
    // widgets and branding are rendered separately so nothing is duplicated.
    Item {
        anchors.fill: parent

        Image {
            anchors.fill: parent
            source: "file://" + (Quickshell.env("KINETIX_WALLPAPER") || (Quickshell.shellDir + "/../distro/assets/kinetix-wallpaper.png"))
            fillMode: Image.PreserveAspectCrop
            smooth: true
            mipmap: true
        }

        // Subtle dark vignette gradient to guarantee typography contrast over mountain ridges
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0.02, 0.02, 0.04, 0.35) }
                GradientStop { position: 0.3; color: "transparent" }
                GradientStop { position: 0.7; color: "transparent" }
                GradientStop { position: 1.0; color: Qt.rgba(0.01, 0.01, 0.03, 0.45) }
            }
        }

        Column {
            anchors { left: parent.left; top: parent.top; leftMargin: Math.max(54, root.width * 0.04); topMargin: 92 }
            spacing: 5
            opacity: 0.95

            Text {
                text: root.greeting + ","
                color: Theme.crimsonText
                font { family: Theme.fontMono; pixelSize: Theme.tCaption; letterSpacing: 2.8; weight: Font.DemiBold }
            }
            Text {
                text: "Build More."
                color: Theme.text
                font { family: Theme.fontUi; pixelSize: Math.min(30, Math.max(22, root.width * 0.024)); weight: Font.Light }
            }
            Rectangle {
                width: 76
                height: 2
                radius: 1
                color: Theme.crimson
                opacity: 0.78
            }
            Text {
                text: "\"DISCIPLINE TODAY\nFREEDOM TOMORROW.\""
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.5 }
                lineHeight: 1.35
                lineHeightMode: Text.ProportionalHeight
            }
        }

        Column {
            width: Math.min(660, root.width * 0.55)
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.horizontalCenterOffset: -Math.min(92, root.width * 0.07)
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: root.height * 0.055
            spacing: 13

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: Math.max(7, root.width * 0.007)
                Repeater {
                    model: ["K", "I", "N", "E", "T", "I", "X", "O", "S"]
                    delegate: Text {
                        required property string modelData
                        text: modelData
                        leftPadding: modelData === "O" ? Math.max(8, root.width * 0.008) : 0
                        color: (modelData === "O" || modelData === "S") ? Theme.crimsonText : Theme.text
                        font { family: Theme.fontUi; pixelSize: Math.min(43, Math.max(24, root.width * 0.035)); weight: Font.Light }
                        opacity: (modelData === "O" || modelData === "S") ? 1 : 0.9
                    }
                }
            }

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(420, parent.width * 0.76)
                height: 1
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 0.48; color: Theme.alpha(Theme.crimson, 0.72) }
                    GradientStop { position: 1; color: "transparent" }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "CONTROL   ·   CREATE   ·   EVOLVE"
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 3.2; weight: Font.Medium }
            }
        }

        // Top right quote from reference concept art
        Column {
            anchors { right: parent.right; top: parent.top; rightMargin: Math.max(54, root.width * 0.04); topMargin: 92 }
            spacing: 5
            opacity: 0.95

            Text {
                text: "\"A HIGHER MIND\nA DARKER PATH.\""
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.5 }
                horizontalAlignment: Text.AlignRight
                lineHeight: 1.35
                lineHeightMode: Text.ProportionalHeight
            }
        }

        // Bottom left signature
        Row {
            anchors { left: parent.left; bottom: parent.bottom; leftMargin: Math.max(54, root.width * 0.04); bottomMargin: 76 }
            spacing: 8
            Column {
                spacing: 5
                Rectangle { width: 30; height: 2; radius: 1; color: Theme.crimson; opacity: 0.82 }
                Text {
                    text: "\"SAME SYSTEM.\nDIFFERENT BREED.\""
                    color: Theme.textFaint
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.3 }
                    lineHeight: 1.4
                    lineHeightMode: Text.ProportionalHeight
                }
            }
        }

        // Bottom right signature from reference concept art
        Column {
            anchors { right: parent.right; bottom: parent.bottom; rightMargin: Math.max(54, root.width * 0.04); bottomMargin: 76 }
            spacing: 5
            opacity: 0.95

            Text {
                text: "MORE THAN A DESKTOP.\nA HIGHER STANDARD."
                color: Theme.textFaint
                font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.3 }
                horizontalAlignment: Text.AlignRight
                lineHeight: 1.4
                lineHeightMode: Text.ProportionalHeight
            }
        }
    }
}
