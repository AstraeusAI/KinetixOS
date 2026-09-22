import QtQuick
import Quickshell
import "../common"
import "../components"

// Aero-style glass widget chrome: drag handle, title badge, settings/close,
// content slot, and illuminated corner resize grip.
GlassPanel {
    id: frame
    property var widget
    property var cfg: widget.config || {}
    property bool settingsOpen: false

    radius: Theme.rM
    level: 2
    clipContent: true
    tinted: moveMa.pressed || resizeMa.pressed || frame.settingsOpen || WidgetStore.editMode
    tint: moveMa.pressed ? Theme.accent2 : Theme.accent
    interactive: !WidgetStore.editMode

    scale: moveMa.pressed ? 1.012 : (frameHov.hovered ? 1.004 : 1.0)
    Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutQuint } }

    HoverHandler {
        id: frameHov
        enabled: !WidgetStore.editMode
    }

    // ── header / drag handle ──
    Item {
        id: header
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: 34
        z: 10

        // Subtly highlighted header surface
        Rectangle {
            anchors.fill: parent
            radius: frame.radius
            color: moveMa.pressed ? Theme.alpha(Theme.accent2, 0.08)
                 : headerHov.hovered ? Theme.surfaceLow : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }

        // Bottom hairline gradient stroke
        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 1
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.15; color: Theme.strokeStrong }
                GradientStop { position: 0.85; color: Theme.stroke }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // Title chip
        Row {
            anchors { left: parent.left; leftMargin: Theme.s3; verticalCenter: parent.verticalCenter }
            spacing: Theme.s2

            Rectangle {
                height: 22
                implicitWidth: badgeRow.implicitWidth + Theme.s2 * 2
                radius: Theme.rXS
                color: Theme.surfaceLow
                border.width: 1
                border.color: Theme.stroke
                anchors.verticalCenter: parent.verticalCenter

                Row {
                    id: badgeRow
                    anchors.centerIn: parent
                    spacing: 5

                    Text {
                        text: WidgetStore.typeInfo(frame.widget.type).glyph
                        color: Theme.accent2
                        font.pixelSize: 12
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: WidgetStore.typeInfo(frame.widget.type).label.toUpperCase()
                        color: Theme.textDim
                        font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.4; weight: Font.DemiBold }
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }

        // Action buttons
        Row {
            anchors { right: parent.right; rightMargin: Theme.s2; verticalCenter: parent.verticalCenter }
            spacing: 4

            // Settings button
            Rectangle {
                visible: (WidgetStore.typeInfo(frame.widget.type).fields || []).length > 0
                width: 24; height: 24; radius: 7
                color: frame.settingsOpen ? Theme.alpha(Theme.accent, 0.25)
                     : settingsMa.containsMouse ? Theme.surfaceHigh : "transparent"
                border.width: 1
                border.color: frame.settingsOpen ? Theme.alpha(Theme.accent, 0.50)
                            : settingsMa.containsMouse ? Theme.stroke : "transparent"
                anchors.verticalCenter: parent.verticalCenter
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                Text {
                    anchors.centerIn: parent
                    text: "⚙"
                    color: frame.settingsOpen ? Theme.accent
                         : settingsMa.containsMouse ? Theme.text : Theme.textFaint
                    font.pixelSize: 13
                    transform: Rotation {
                        angle: frame.settingsOpen ? 45 : (settingsMa.containsMouse ? 25 : 0)
                        Behavior on angle { NumberAnimation { duration: Theme.durMed; easing.type: Easing.OutBack } }
                    }
                }
                MouseArea {
                    id: settingsMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: frame.settingsOpen = !frame.settingsOpen
                }
            }

            // Close button
            Rectangle {
                width: 24; height: 24; radius: 7
                color: closeMa.containsMouse ? Theme.alpha(Theme.danger, 0.22) : "transparent"
                border.width: 1
                border.color: closeMa.containsMouse ? Theme.alpha(Theme.danger, 0.45) : "transparent"
                anchors.verticalCenter: parent.verticalCenter
                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                Text {
                    anchors.centerIn: parent
                    text: "✕"
                    color: closeMa.containsMouse ? Theme.danger : Theme.textFaint
                    font { family: Theme.fontUi; pixelSize: 11; weight: Font.Medium }
                }
                MouseArea {
                    id: closeMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: WidgetStore.remove(frame.widget.id)
                }
            }
        }

        HoverHandler { id: headerHov }

    }

    // Dedicated topmost move surface. Keeping it outside the header's visual
    // children guarantees title text, gradients, and buttons cannot steal the
    // drag grab. The parent layer-shell window is fixed to the screen, so
    // screen-space deltas remain stable while the frame moves.
    Item {
        id: moveSurface
        x: 0; y: 0
        width: Math.max(1, parent.width - 64)
        height: 34
        z: 100
        MouseArea {
            id: moveMa
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            preventStealing: true
            cursorShape: Qt.SizeAllCursor
            property real pressSceneX: 0
            property real pressSceneY: 0
            property real startX: 0
            property real startY: 0
            onPressed: function(mouse) {
                // sceneX/Y are window-scene coords; for a full-screen
                // layer-shell surface they equal screen coords. Using
                // local x/y would create a feedback loop: frame moves →
                // surface moves → local mouse pos shifts → frame jumps.
                pressSceneX = mouse.sceneX;
                pressSceneY = mouse.sceneY;
                startX = frame.x; startY = frame.y;
                WidgetStore.bringToFront(frame.widget.id);
            }
            onPositionChanged: function(mouse) {
                if (!pressed) return;
                var dx = mouse.sceneX - pressSceneX;
                var dy = mouse.sceneY - pressSceneY;
                WidgetStore.move(frame.widget.id,
                                 Math.max(0, startX + dx),
                                 Math.max(0, startY + dy));
            }
            onReleased: {
                WidgetStore.bringToFront(frame.widget.id);
            }
        }
    }

    // ── content ──
    WidgetHost {
        id: host
        anchors {
            top: header.bottom
            left: parent.left
            right: parent.right
            bottom: parent.bottom
        }
        widget: frame.widget
        visible: !frame.settingsOpen
    }

    // ── settings sheet (slide down drawer) ──
    Rectangle {
        id: settings
        anchors { fill: parent; topMargin: 34 }
        visible: frame.settingsOpen
        color: Theme.glassBaseHigh
        z: 20

        Column {
            anchors { fill: parent; margins: Theme.s4 }
            spacing: Theme.s3

            Row {
                width: parent.width
                spacing: Theme.s2

                Rectangle {
                    width: 5; height: 5; radius: 3
                    color: Theme.accent
                    anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                    text: "WIDGET SETTINGS"
                    color: Theme.textDim
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.4; weight: Font.DemiBold }
                    anchors.verticalCenter: parent.verticalCenter
                }

                Item { width: Math.max(1, parent.width - x - settClose.width); height: 1 }

                CloseButton {
                    id: settClose
                    box: 22
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: frame.settingsOpen = false
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.stroke }

            Flickable {
                width: parent.width
                height: Math.max(40, parent.height - y - 36)
                contentWidth: width
                contentHeight: formCol.implicitHeight
                clip: true

                Column {
                    id: formCol
                    width: parent.width
                    spacing: Theme.s3

                    Repeater {
                        model: WidgetStore.typeInfo(frame.widget.type).fields || []
                        delegate: Column {
                            required property var modelData
                            width: parent.width
                            spacing: 4

                            Text {
                                text: parent.modelData.l
                                color: Theme.textDim
                                font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.Medium }
                            }

                            Rectangle {
                                width: parent.width
                                height: 32
                                radius: Theme.rS
                                color: Theme.surfaceLow
                                border.width: 1
                                border.color: field.activeFocus ? Theme.alpha(Theme.accent, 0.6) : Theme.stroke
                                Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

                                TextInput {
                                    id: field
                                    anchors { fill: parent; leftMargin: Theme.s3; rightMargin: Theme.s3 }
                                    verticalAlignment: TextInput.AlignVCenter
                                    color: Theme.text
                                    font { family: Theme.fontMono; pixelSize: Theme.tBody }
                                    text: String(frame.cfg[parent.parent.modelData.k] === undefined
                                                 ? "" : frame.cfg[parent.parent.modelData.k])
                                    onEditingFinished: {
                                        WidgetStore.setConfig(frame.widget.id, parent.parent.modelData.k, text);
                                        frame.settingsOpen = false;
                                    }
                                    Keys.onReturnPressed: {
                                        field.editingFinished();
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Row {
                width: parent.width
                spacing: Theme.s2

                Text {
                    text: "Press ↵ or click Done to save"
                    color: Theme.textFaint
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                    anchors.verticalCenter: parent.verticalCenter
                }

                Item { width: Math.max(1, parent.width - x - doneBtn.width); height: 1 }

                PillButton {
                    id: doneBtn
                    text: "Done"
                    implicitHeight: 26
                    highlighted: true
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: frame.settingsOpen = false
                }
            }
        }
    }

    // ── resize grip (illuminated corner) ──
    Item {
        anchors { right: parent.right; bottom: parent.bottom }
        width: 22
        height: 22
        z: 15

        Canvas {
            id: gripCanvas
            anchors.fill: parent
            antialiasing: true

            property bool hov: resizeMa.containsMouse || resizeMa.pressed
            onHovChanged: requestPaint()

            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                ctx.strokeStyle = hov ? Theme.accent2 : Theme.alpha(Theme.textFaint, 0.6);
                ctx.lineWidth = 1.4;
                ctx.lineCap = "round";

                for (var i = 1; i <= 3; i++) {
                    ctx.beginPath();
                    ctx.moveTo(width - 3, height - 3 - i * 4.5);
                    ctx.lineTo(width - 3 - i * 4.5, height - 3);
                    ctx.stroke();
                }
            }
        }

        MouseArea {
            id: resizeMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.SizeFDiagCursor
            property real pressSceneX: 0
            property real pressSceneY: 0
            property real startW: 0
            property real startH: 0

            onPressed: function(mouse) {
                pressSceneX = mouse.sceneX; pressSceneY = mouse.sceneY;
                startW = frame.widget.w; startH = frame.widget.h;
            }
            onPositionChanged: function(mouse) {
                if (!pressed) return;
                WidgetStore.resize(frame.widget.id,
                                   Math.max(200, startW + mouse.sceneX - pressSceneX),
                                   Math.max(120, startH + mouse.sceneY - pressSceneY));
            }
        }
    }
}
