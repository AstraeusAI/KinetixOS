import QtQuick
import Qt.labs.folderlistmodel
import Quickshell
import Quickshell.Io
import "../common"
import "../components"

// DesktopIcons — the contents of the user's desktop folder, live.
//
// FolderListModel watches the directory itself (inotify), so a folder or file
// appears the moment it is created, and renames/deletions follow at once —
// no polling. The folder is XDG_DESKTOP_DIR from ~/.config/user-dirs.dirs
// (localized or moved desktops work), falling back to ~/Desktop.
//
//   click          select          double-click   open (default app)
//   right-click    Open · Show in Files · Move to Trash (recoverable)
//
// Laid out column-major from the top-left, clear of the dock, the bars and
// the greeting. The owning PanelWindow puts `hitArea` and `menuBox` in its
// input mask; everything else on the desktop stays click-through.
Item {
    id: root

    // area the grid may use (set by the desktop window)
    property real topInset: 250
    property real leftInset: 96
    property real bottomInset: 90

    readonly property Item hitArea: grid
    readonly property Item menuBox: menu

    // ── which folder ──
    readonly property string home: Quickshell.env("HOME")
    property string desktopDir: home + "/Desktop"
    FileView {
        path: root.home + "/.config/user-dirs.dirs"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            var m = text().match(/^XDG_DESKTOP_DIR="([^"]+)"/m);
            if (m) root.desktopDir = m[1].replace("$HOME", root.home);
        }
    }

    FolderListModel {
        id: files
        folder: "file://" + root.desktopDir
        showDirsFirst: true
        showHidden: false
        showDotAndDotDot: false
        sortField: FolderListModel.Name
        sortCaseSensitive: false
    }

    // ── icons: KinetixFolder / KinetixFile, real thumbnails for images ──
    readonly property var imageSuffixes: ["png", "jpg", "jpeg", "webp", "gif", "bmp", "svg", "avif"]

    // ── actions ──
    property string selected: ""
    function open(path) { Quickshell.execDetached(["gio", "open", path]); }
    function showInFiles(path) {
        // the file manager's own "select this item" call; gio open of the
        // folder is the fallback when no FileManager1 service answers
        Quickshell.execDetached(["sh", "-c",
            "gdbus call --session --dest org.freedesktop.FileManager1 " +
            "--object-path /org/freedesktop/FileManager1 " +
            "--method org.freedesktop.FileManager1.ShowItems \"['file://$1']\" '' >/dev/null 2>&1 " +
            "|| gio open \"$(dirname \"$1\")\"", "sh", path]);
    }
    function trash(path) { Quickshell.execDetached(["gio", "trash", path]); }

    // ── grid ──
    GridView {
        id: grid
        x: root.leftInset
        y: root.topInset
        readonly property real availH: root.height - root.topInset - root.bottomInset
        readonly property int rows: Math.max(1, Math.floor(availH / cellHeight))
        height: Math.min(availH, count * cellHeight)
        width: Math.max(cellWidth, Math.ceil(count / rows) * cellWidth)
        flow: GridView.FlowTopToBottom
        cellWidth: 100
        cellHeight: 108
        interactive: false
        model: files

        delegate: Item {
            id: cell
            required property string fileName
            required property string filePath
            required property bool fileIsDir
            required property string fileSuffix
            required property int index
            width: grid.cellWidth
            height: grid.cellHeight
            readonly property bool hot: ma.containsMouse
            readonly property bool sel: root.selected === filePath
            readonly property bool isImage: !fileIsDir && root.imageSuffixes.indexOf(fileSuffix.toLowerCase()) >= 0

            // appear with a small rise when created (also on first load)
            opacity: 0
            property real rise: 8
            transform: Translate { y: cell.rise }
            Component.onCompleted: appear.start()
            ParallelAnimation {
                id: appear
                NumberAnimation { target: cell; property: "opacity"; to: 1; duration: 260; easing.type: Easing.OutCubic }
                NumberAnimation { target: cell; property: "rise"; to: 0; duration: 320; easing.type: Easing.OutQuint }
            }

            // glass tile + logo-style rim, only while hovered / selected
            Item {
                id: tileWrap
                anchors { fill: parent; margins: 4 }
                opacity: cell.sel || cell.hot ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: 160 } }
                GlowRim {
                    anchors.fill: tile
                    radius: tile.radius
                    drawRim: false
                    glowBlurMax: 16
                    rgb: cell.sel
                    color: Qt.rgba(1, 1, 1, 1)
                    glowOpacity: cell.sel ? 0.9 : 0
                }
                Rectangle {
                    id: tile
                    anchors.fill: parent
                    radius: 16
                    color: Qt.rgba(0.02, 0.022, 0.032, cell.sel ? 0.62 : 0.45)
                    Rectangle {
                        anchors { top: parent.top; topMargin: 1; left: parent.left; right: parent.right; leftMargin: 12; rightMargin: 12 }
                        height: 1
                        color: Qt.rgba(1, 1, 1, 0.18)
                    }
                }
                GlowRim {
                    anchors.fill: tile
                    radius: tile.radius
                    drawGlow: false
                    thickness: cell.sel ? 1.8 : 1.2
                    rgb: cell.sel
                    color: Qt.rgba(1, 1, 1, 0.5)
                    rimOpacity: cell.sel ? 1 : 0.6
                }
            }

            // icon (or a real thumbnail for images)
            Item {
                id: iconBox
                width: 52; height: 52
                anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 10 }
                scale: ma.pressed ? 0.92 : (cell.hot ? 1.06 : 1)
                Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }
                // folders: the Kinetix folder; files: theme icons
                KinetixFolder {
                    anchors.centerIn: parent
                    visible: cell.fileIsDir
                    size: 52
                    hovered: cell.hot
                    open: cell.sel
                }
                KinetixFile {
                    anchors.centerIn: parent
                    visible: !cell.isImage && !cell.fileIsDir
                    size: 52
                    hovered: cell.hot
                    suffix: cell.fileSuffix
                }
                Rectangle {
                    anchors.centerIn: parent
                    visible: cell.isImage
                    width: 50; height: 40; radius: 6
                    color: Qt.rgba(0, 0, 0, 0.35)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.35)
                    clip: true
                    Image {
                        anchors { fill: parent; margins: 1 }
                        source: cell.isImage ? "file://" + cell.filePath : ""
                        sourceSize: Qt.size(128, 128)
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        mipmap: true
                    }
                }
            }

            // label, legible over any wallpaper
            Text {
                anchors { top: iconBox.bottom; topMargin: 6; horizontalCenter: parent.horizontalCenter }
                width: parent.width - 12
                text: cell.fileName
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
                color: "white"
                style: Text.Outline
                styleColor: Qt.rgba(0, 0, 0, 0.55)
                font { family: Theme.fontUi; pixelSize: 12; weight: cell.sel ? Font.DemiBold : Font.Medium }
            }

            MouseArea {
                id: ma
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                cursorShape: Qt.PointingHandCursor
                onClicked: function(mouse) {
                    root.selected = cell.filePath;
                    if (mouse.button === Qt.RightButton)
                        menu.openFor(cell, cell.filePath, cell.fileName, cell.fileIsDir);
                    else menu.close();
                }
                onDoubleClicked: function(mouse) {
                    if (mouse.button === Qt.LeftButton) { menu.close(); root.open(cell.filePath); }
                }
            }
        }
    }

    // clicking empty space in the grid area clears the selection
    MouseArea {
        anchors.fill: grid
        z: -1
        onClicked: { root.selected = ""; menu.close(); }
    }

    // ── context menu (drawn in this surface) ──
    Item {
        id: menu
        property bool open: false
        property string path: ""
        property string name: ""
        property bool isDir: false
        function openFor(item, p, n, d) {
            path = p; name = n; isDir = d;
            var pt = item.mapToItem(root, item.width - 8, 18);
            x = Math.min(root.width - 230, pt.x);
            y = Math.min(root.height - menuCol.implicitHeight - 24, pt.y);
            open = true;
        }
        function close() { open = false; }
        width: open ? 210 : 0
        height: open ? menuCol.implicitHeight + 14 : 0
        opacity: open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
        clip: true

        Rectangle {
            anchors.fill: parent
            radius: 14
            color: Qt.rgba(0.043, 0.046, 0.063, 0.97)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.10)
        }
        Column {
            id: menuCol
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 7 }
            spacing: 1
            Text {
                width: parent.width
                leftPadding: 10; topPadding: 6; bottomPadding: 6
                text: menu.name
                elide: Text.ElideMiddle
                color: Theme.text
                font { family: Theme.fontUi; pixelSize: 12; weight: Font.DemiBold }
            }
            Rectangle { width: parent.width; height: 1; color: Qt.rgba(1, 1, 1, 0.08) }
            component Row_: Rectangle {
                id: r
                property string label
                property bool danger: false
                signal activated()
                width: menuCol.width
                height: 32
                radius: 9
                color: rma.containsMouse ? (danger ? Theme.alpha(Theme.crimson, 0.24) : Qt.rgba(1, 1, 1, 0.08)) : "transparent"
                Text {
                    anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                    text: r.label
                    color: r.danger ? Theme.crimsonText : Theme.text
                    font { family: Theme.fontUi; pixelSize: 12 }
                }
                MouseArea {
                    id: rma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { r.activated(); menu.close(); }
                }
            }
            Row_ { label: "Open"; onActivated: root.open(menu.path) }
            Row_ { label: "Show in Files"; onActivated: root.showInFiles(menu.path) }
            Row_ { label: "Move to Trash"; danger: true; onActivated: root.trash(menu.path) }
        }
    }
}
