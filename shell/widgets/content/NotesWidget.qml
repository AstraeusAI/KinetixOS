import QtQuick
import "../../common"
import "../../components"

// High-fidelity desktop scratchpad: live word/char counters, auto-save pulse,
// frosted glass well, and custom scrollbar.
Item {
    id: root
    property var widget
    property var cfg: ({})

    Component.onCompleted: editor.text = cfg.text || ""

    readonly property int charCount: editor.text ? editor.text.length : 0
    readonly property int wordCount: editor.text && editor.text.trim().length > 0
                                     ? editor.text.trim().split(/\s+/).length : 0
    property bool saving: false

    Column {
        anchors { fill: parent; margins: Theme.s3 }
        spacing: Theme.s2

        // Header / Status Bar
        Item {
            width: parent.width
            height: 20

            Row {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                spacing: 6

                Text {
                    text: "📝"
                    font.pixelSize: 11
                    anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                    text: "SCRATCHPAD"
                    color: Theme.textDim
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro; letterSpacing: 1.2; weight: Font.DemiBold }
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            // Word / Char count pill
            Rectangle {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                height: 18
                implicitWidth: countText.implicitWidth + 12
                radius: Theme.rXS
                color: Theme.surfaceLow
                border.width: 1
                border.color: Theme.stroke

                Text {
                    id: countText
                    anchors.centerIn: parent
                    text: root.wordCount + "w · " + root.charCount + "c"
                    color: Theme.textFaint
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                }
            }
        }

        // Editor Card
        Rectangle {
            width: parent.width
            height: parent.height - y - 24
            radius: Theme.rS
            color: Theme.surfaceLow
            border.width: 1
            border.color: editor.activeFocus ? Theme.alpha(Theme.accent, 0.45) : Theme.stroke
            Behavior on border.color { ColorAnimation { duration: Theme.durFast } }

            Flickable {
                id: flick
                anchors { fill: parent; margins: Theme.s3 }
                contentWidth: width
                contentHeight: editor.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                clip: true

                TextEdit {
                    id: editor
                    width: parent.width
                    color: Theme.text
                    font { family: Theme.fontUi; pixelSize: Theme.tBody }
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                    selectionColor: Theme.alpha(Theme.accent, 0.40)

                    Text {
                        anchors.fill: parent
                        visible: !editor.text
                        text: "Type notes, commands, or scratch ideas here…"
                        color: Theme.textFaint
                        font: editor.font
                    }

                    onTextChanged: {
                        root.saving = true;
                        saveTimer.restart();
                    }
                }
            }
        }

        // Footer / Autosave indicator
        Item {
            width: parent.width
            height: 16

            Row {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                spacing: 5

                Rectangle {
                    width: 5; height: 5; radius: 3
                    color: root.saving ? Theme.warn : Theme.accent2
                    anchors.verticalCenter: parent.verticalCenter
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                }

                Text {
                    text: root.saving ? "Saving…" : "Saved"
                    color: Theme.textFaint
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }

    Timer {
        id: saveTimer
        interval: 600
        onTriggered: {
            WidgetStore.setConfig(root.widget.id, "text", editor.text);
            root.saving = false;
        }
    }

    Component.onDestruction: {
        saveTimer.running = false;
    }
}
