import QtQuick
import Quickshell
import "../common"

// One notification — used by popup toasts and the Notification Center.
// Glass card: app icon (or initial), urgency accent, relative time, ×N repeat
// badge, summary/body with show-more, action buttons, swipe-right to dismiss.
// Error kinds (crash / failed service / shell error) get a warning treatment,
// a kind pill, and — once "Save log" runs — a saved-path confirmation line.
// In `toast` mode a timeout bar drains (paused on hover) and finally hides the
// toast without dismissing the entry.
Item {
    id: card

    property int nid: 0
    property string appName: ""
    property string summary: ""
    property string body: ""
    property string icon: ""
    property string image: ""
    property int urgency: 1               // 0 low · 1 normal · 2 critical
    property real ts: 0
    property string actionsJson: "[]"
    property int timeout: 0               // ms, toast mode only; 0 = sticky
    property string kind: "app"           // app | crash | service | shell
    property int repeat: 1
    property string saved: ""
    property bool toast: false
    property bool expanded: false

    readonly property var actions: { try { return JSON.parse(actionsJson); } catch (e) { return []; } }
    readonly property bool isError: kind !== "app"
    readonly property string kindLabel: kind === "crash" ? "CRASH" : (kind === "service" ? "FAILED" : (kind === "shell" ? "ERROR" : ""))
    readonly property color accent: isError ? "#FF5C5C"
                                  : (urgency === 2 ? Theme.alarm : (urgency === 0 ? Theme.textDim : Theme.crimsonText))
    readonly property color okColor: "#34A853"
    readonly property bool hovered: hover.hovered
    readonly property string savedShort: saved.replace(Quickshell.env("HOME") || "\u0000", "~")

    implicitHeight: slab.implicitHeight
    height: implicitHeight

    // ── swipe-to-dismiss ──
    property real swipeX: 0
    Behavior on swipeX { enabled: !drag.active; NumberAnimation { duration: 240; easing.type: Easing.OutBack } }
    function fling() { flingAnim.start(); }
    NumberAnimation { id: flingAnim; target: card; property: "swipeX"; to: card.width + 40; duration: 220; easing.type: Easing.InCubic
        onFinished: Notif.dismiss(card.nid) }

    Item {
        id: slab
        width: parent.width
        implicitHeight: bg.implicitHeight
        x: card.swipeX
        opacity: 1 - Math.min(0.85, Math.max(0, card.swipeX) / Math.max(1, card.width))

        // soft, cheap shadow (two rects)
        Repeater {
            model: [ { "g": 8, "a": 0.06, "dy": 5 }, { "g": 3, "a": 0.10, "dy": 2 } ]
            Rectangle {
                required property var modelData
                anchors.fill: bg
                anchors.margins: -modelData.g
                anchors.topMargin: -modelData.g + modelData.dy
                radius: bg.radius + modelData.g
                color: Qt.rgba(0, 0, 0, modelData.a)
            }
        }

        Rectangle {
            id: bg
            width: parent.width
            implicitHeight: content.implicitHeight + 28
            height: implicitHeight
            radius: 16
            clip: true
            color: card.hovered ? Qt.rgba(0.11, 0.055, 0.075, 0.97) : Qt.rgba(0.075, 0.040, 0.055, 0.95)
            border.width: 1
            border.color: card.isError ? Theme.alpha(card.accent, card.hovered ? 0.7 : 0.45)
                        : (card.urgency === 2 ? Theme.alpha(Theme.alarm, 0.55)
                        : Qt.rgba(1, 1, 1, card.hovered ? 0.17 : 0.10))
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

            // depth wash + top specular
            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.075) }
                    GradientStop { position: 0.45; color: Qt.rgba(1, 1, 1, 0.0) }
                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.18) }
                }
            }
            // error tint from the accent edge
            Rectangle {
                visible: card.isError
                anchors.fill: parent
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Theme.alpha(card.accent, 0.13) }
                    GradientStop { position: 0.55; color: Theme.alpha(card.accent, 0.0) }
                }
            }
            // accent edge
            Rectangle {
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                width: 3
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Theme.alpha(card.accent, 0.95) }
                    GradientStop { position: 1.0; color: Theme.alpha(card.accent, 0.25) }
                }
                opacity: (card.urgency === 2 || card.isError) ? (0.72 + 0.28 * Theme.heartbeatSin) : 1
            }

            // click = activate (default action)
            MouseArea {
                anchors.fill: parent
                z: -1
                cursorShape: card.isError ? Qt.ArrowCursor : Qt.PointingHandCursor
                onClicked: Notif.activate(card.nid)
            }

            Column {
                id: content
                anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 18; rightMargin: 14; topMargin: 14 }
                spacing: 10

                Row {
                    spacing: 12
                    width: parent.width

                    // icon badge (+ warning dot for errors)
                    Item {
                        id: badge
                        width: 38; height: 38
                        Rectangle {
                            anchors.fill: parent
                            radius: 12
                            color: Theme.alpha(card.accent, 0.16)
                            border.width: 1
                            border.color: Theme.alpha(card.accent, 0.35)
                        }
                        Image {
                            anchors.centerIn: parent
                            width: 24; height: 24
                            source: card.image !== "" ? card.image : card.icon
                            visible: source != ""
                            sourceSize: Qt.size(48, 48)
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                            mipmap: true
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: card.icon === "" && card.image === ""
                            text: (card.appName || "?").charAt(0).toUpperCase()
                            color: card.accent
                            font { family: Theme.fontUi; pixelSize: 17; weight: Font.Bold }
                        }
                        Rectangle {   // warning dot
                            visible: card.isError
                            width: 16; height: 16; radius: 8
                            anchors { right: parent.right; bottom: parent.bottom; rightMargin: -4; bottomMargin: -4 }
                            color: card.accent
                            border.width: 2; border.color: Qt.rgba(0.06, 0.03, 0.04, 1)
                            Text { anchors.centerIn: parent; text: "!"; color: "white"; font { pixelSize: 10; weight: Font.Black } }
                        }
                    }

                    Column {
                        width: parent.width - badge.width - parent.spacing
                        spacing: 4

                        // header: APP  [KIND]                ×3  now  ✕
                        Item {
                            width: parent.width
                            height: 14
                            Row {
                                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                spacing: 7
                                Text {
                                    id: appLabel
                                    text: card.appName.toUpperCase()
                                    color: card.accent
                                    elide: Text.ElideRight
                                    width: Math.min(implicitWidth, card.width - 250)
                                    font { family: Theme.fontMono; pixelSize: 10; letterSpacing: 1.4; weight: Font.DemiBold }
                                }
                                Rectangle {
                                    visible: card.kindLabel !== ""
                                    height: 14; radius: 7; width: kindTxt.implicitWidth + 12
                                    color: Theme.alpha(card.accent, 0.20)
                                    border.width: 1; border.color: Theme.alpha(card.accent, 0.5)
                                    Text { id: kindTxt; anchors.centerIn: parent; text: card.kindLabel; color: card.accent
                                        font { family: Theme.fontMono; pixelSize: 9; letterSpacing: 1.1; weight: Font.Bold } }
                                }
                            }
                            Row {
                                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                                spacing: 8
                                Rectangle {
                                    visible: card.repeat > 1
                                    height: 14; radius: 7; width: repTxt.implicitWidth + 10
                                    color: Qt.rgba(1, 1, 1, 0.10)
                                    Text { id: repTxt; anchors.centerIn: parent; text: "×" + card.repeat; color: Theme.textDim
                                        font { family: Theme.fontMono; pixelSize: 9; weight: Font.Bold } }
                                }
                                Text {
                                    text: Notif.ago(card.ts)
                                    color: Theme.textFaint
                                    font { family: Theme.fontMono; pixelSize: 10 }
                                }
                                Text {
                                    text: "✕"
                                    color: closeMa.containsMouse ? Theme.text : Theme.textFaint
                                    font.pixelSize: 10
                                    opacity: card.hovered || !card.toast ? 1 : 0
                                    Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
                                    MouseArea {
                                        id: closeMa
                                        anchors.fill: parent; anchors.margins: -7
                                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: Notif.dismiss(card.nid)
                                    }
                                }
                            }
                        }

                        Text {
                            width: parent.width
                            text: card.summary
                            visible: text !== ""
                            color: Theme.text
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                            font { family: Theme.fontUi; pixelSize: 14; weight: Font.DemiBold }
                        }
                        Text {
                            id: bodyText
                            width: parent.width
                            text: card.body
                            visible: text !== ""
                            color: Theme.textDim
                            wrapMode: Text.WordWrap
                            maximumLineCount: card.expanded ? 40 : (card.toast ? 3 : 4)
                            elide: Text.ElideRight
                            textFormat: Text.StyledText
                            font { family: Theme.fontUi; pixelSize: 13 }
                            lineHeight: 1.15
                        }
                        Text {
                            visible: !card.toast && (bodyText.truncated || card.expanded)
                            text: card.expanded ? "Show less" : "Show more"
                            color: showMa.containsMouse ? Theme.text : card.accent
                            font { family: Theme.fontMono; pixelSize: 10; letterSpacing: 0.6 }
                            MouseArea { id: showMa; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor; onClicked: card.expanded = !card.expanded }
                        }
                    }
                }

                // saved-log confirmation
                Rectangle {
                    visible: card.saved !== ""
                    width: parent.width; height: visible ? 26 : 0
                    radius: 9
                    color: Theme.alpha(card.okColor, 0.12)
                    border.width: 1; border.color: Theme.alpha(card.okColor, 0.4)
                    Row {
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 10; rightMargin: 10 }
                        spacing: 7
                        Text { text: "✓"; color: card.okColor; font { pixelSize: 12; weight: Font.Bold } anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            width: parent.width - 20
                            text: "Saved to " + card.savedShort
                            elide: Text.ElideMiddle
                            color: Theme.textDim
                            font { family: Theme.fontMono; pixelSize: 10 }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }

                // actions
                Row {
                    visible: card.actions.length > 0
                    spacing: 8
                    height: visible ? 30 : 0
                    Repeater {
                        model: card.actions
                        Rectangle {
                            required property var modelData
                            required property int index
                            height: 28; radius: 14
                            width: actLabel.implicitWidth + 26
                            color: actMa.pressed ? Theme.alpha(card.accent, 0.34)
                                 : actMa.containsMouse ? Theme.alpha(card.accent, 0.22)
                                 : (index === 0 ? Theme.alpha(card.accent, 0.14) : Qt.rgba(1, 1, 1, 0.06))
                            border.width: 1
                            border.color: index === 0 ? Theme.alpha(card.accent, 0.5) : Qt.rgba(1, 1, 1, 0.12)
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Text {
                                id: actLabel
                                anchors.centerIn: parent
                                text: modelData.text
                                color: index === 0 ? Theme.text : Theme.textDim
                                font { family: Theme.fontUi; pixelSize: 12; weight: Font.DemiBold }
                            }
                            MouseArea {
                                id: actMa
                                anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: Notif.invoke(card.nid, modelData.id)
                            }
                        }
                    }
                }
            }

            // toast timeout bar
            Rectangle {
                visible: card.toast && card.timeout > 0
                anchors { left: parent.left; bottom: parent.bottom; leftMargin: 3 }
                height: 2
                width: (parent.width - 3) * remaining
                property real remaining: 1
                color: Theme.alpha(card.accent, 0.75)
                NumberAnimation on remaining {
                    from: 1; to: 0
                    duration: Math.max(1, card.timeout)
                    running: card.toast && card.timeout > 0
                    paused: running && (card.hovered || drag.active)
                    onFinished: Notif.hideToast(card.nid)
                }
            }
        }
    }

    HoverHandler { id: hover }
    DragHandler {
        id: drag
        target: null
        yAxis.enabled: false
        xAxis.enabled: true
        onTranslationChanged: if (active) card.swipeX = Math.max(0, translation.x)
        onActiveChanged: {
            if (!active) {
                if (card.swipeX > card.width * 0.32) card.fling();
                else card.swipeX = 0;
            }
        }
    }
}
