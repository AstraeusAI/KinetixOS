import QtQuick
import "../../common"

// High-fidelity image gadget: aspect-cropped frame with rounded glass styling
// and elegant placeholder dropzone.
Item {
    id: root
    property var widget
    property var cfg: ({})

    readonly property string imgPath: root.cfg.path || ""

    // Image Frame
    Rectangle {
        anchors { fill: parent; margins: Theme.s2 }
        radius: Theme.rS
        color: Theme.surfaceLow
        border.width: 1
        border.color: Theme.stroke
        clip: true

        Image {
            id: img
            anchors.fill: parent
            visible: root.imgPath !== ""
            source: root.imgPath !== "" ? (root.imgPath.indexOf("://") >= 0 ? root.imgPath : "file://" + root.imgPath) : ""
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            mipmap: true
            // Cap decode size: without this a 4K wallpaper widget decodes the
            // full image (~33MB RAM + VRAM) to draw a ~300px tile.
            sourceSize.width: img.width * 2
            sourceSize.height: img.height * 2
            onStatusChanged: {
                if (img.status === Image.Error) {
                    console.warn("ImageWidget: failed to load " + root.imgPath + " - " + img.errorString);
                }
            }

            // Inner glass shadow / vignette overlay
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                border.width: 1
                border.color: Theme.stroke
            }
        }

        // Empty state dropzone
        Column {
            anchors.centerIn: parent
            visible: root.imgPath === ""
            spacing: Theme.s2

            Rectangle {
                width: 44; height: 44; radius: Theme.rS
                color: Theme.surfaceLow
                border.width: 1
                border.color: Theme.stroke
                anchors.horizontalCenter: parent.horizontalCenter

                Text {
                    anchors.centerIn: parent
                    text: "🖼"
                    font.pixelSize: 22
                }
            }

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 2
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "No image selected"
                    color: Theme.textDim
                    font { family: Theme.fontUi; pixelSize: Theme.tCaption; weight: Font.Medium }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Click the ⚙ gear icon to set path"
                    color: Theme.textFaint
                    font { family: Theme.fontMono; pixelSize: Theme.tMicro }
                }
            }
        }
    }
}
