import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland
import "../common"

// Fullscreen graphical installer (live ISO). Steps: welcome, region, disk,
// account, review, install, done. Backend: scripts/kinetix-installer.py.
PanelWindow {
    id: win
    required property ShellScreen modelData
    screen: modelData
    visible: InstallerState.open && (Quickshell.screens.length < 2 || modelData === Quickshell.screens[0])

    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "kinetix:installer"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

    readonly property var st: InstallerState
    readonly property int pad: 28

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0.02, 0.012, 0.018, 0.94)
    }

    // ── shared field styling ──
    component Field: TextField {
        color: Theme.text
        placeholderTextColor: Theme.textFaint
        selectionColor: Theme.crimson
        font { family: Theme.fontUi; pixelSize: 15 }
        leftPadding: 14; rightPadding: 14
        implicitHeight: 44
        background: Rectangle {
            radius: 8
            color: Theme.surfaceLow
            border.width: 1
            border.color: parent.activeFocus ? Theme.crimson : Theme.stroke
        }
    }
    component Label2: Text {
        color: Theme.textDim
        font { family: Theme.fontMono; pixelSize: 11; letterSpacing: 1.4 }
    }
    component Btn: Rectangle {
        id: b
        property string text: ""
        property bool primary: false
        property bool enabled2: true
        signal clicked()
        implicitWidth: Math.max(110, t.implicitWidth + 40)
        implicitHeight: 42
        radius: 8
        opacity: enabled2 ? 1 : 0.4
        color: primary ? (ma.containsMouse && enabled2 ? Theme.crimsonText : Theme.crimson)
                       : (ma.containsMouse && enabled2 ? Theme.surfaceHigh : Theme.surface)
        border.width: primary ? 0 : 1
        border.color: Theme.stroke
        Text {
            id: t; anchors.centerIn: parent; text: b.text; color: "white"
            font { family: Theme.fontUi; pixelSize: 14; weight: Font.DemiBold }
        }
        MouseArea {
            id: ma; anchors.fill: parent; hoverEnabled: true
            cursorShape: b.enabled2 ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: if (b.enabled2) b.clicked()
        }
    }

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 900)
        height: Math.min(parent.height - 80, 640)
        radius: 16
        color: Qt.rgba(0.07, 0.035, 0.05, 0.97)
        border.width: 1
        border.color: Qt.rgba(0.88, 0.10, 0.24, 0.55)

        // ── header: brand + step rail ──
        Item {
            id: header
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 84
            Text {
                anchors { left: parent.left; leftMargin: win.pad; verticalCenter: parent.verticalCenter }
                text: "KINETIX"
                color: Theme.crimsonText
                font { family: Theme.fontMono; pixelSize: 16; letterSpacing: 4; weight: Font.Bold }
            }
            Row {
                anchors { right: parent.right; rightMargin: win.pad; verticalCenter: parent.verticalCenter }
                spacing: 6
                Repeater {
                    model: win.st.stepNames
                    Rectangle {
                        required property int index
                        required property string modelData
                        readonly property int cur: Math.min(win.st.step, 5)
                        width: lbl.implicitWidth + 22; height: 26; radius: 13
                        color: index === cur ? Theme.crimson : "transparent"
                        border.width: 1
                        border.color: index <= cur ? Theme.crimson : Theme.stroke
                        Text {
                            id: lbl; anchors.centerIn: parent; text: parent.modelData
                            color: parent.index <= parent.cur ? "white" : Theme.textFaint
                            font { family: Theme.fontMono; pixelSize: 10; letterSpacing: 1 }
                        }
                    }
                }
            }
            Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 1; color: Theme.stroke }
        }

        // ── footer nav ──
        Item {
            id: footer
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 72
            visible: win.st.step < 5
            Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top } height: 1; color: Theme.stroke }
            Btn {
                anchors { left: parent.left; leftMargin: win.pad; verticalCenter: parent.verticalCenter }
                text: win.st.step === 0 ? "Cancel" : "Back"
                onClicked: win.st.step === 0 ? win.st.close() : win.st.back()
            }
            Btn {
                anchors { right: parent.right; rightMargin: win.pad; verticalCenter: parent.verticalCenter }
                primary: true
                text: win.st.step === 0 ? "Get started" : win.st.step === 4 ? "Erase disk and install" : "Continue"
                enabled2: win.st.canAdvance()
                onClicked: win.st.next()
            }
        }

        // ── pages ──
        Item {
            anchors { left: parent.left; right: parent.right; top: header.bottom; bottom: footer.visible ? footer.top : parent.bottom }
            anchors.margins: win.pad

            // 0 · welcome
            Column {
                visible: win.st.step === 0
                anchors.centerIn: parent
                spacing: 16
                width: parent.width * 0.8
                Text { text: "Install KinetixOS"; color: Theme.text; font { family: Theme.fontUi; pixelSize: 34; weight: Font.Light } }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: "This will install KinetixOS onto a disk in this computer. It takes about ten minutes. You will choose a disk, your region and keyboard, and create your user account."
                    color: Theme.textDim; font { family: Theme.fontUi; pixelSize: 15 } lineHeight: 1.3
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: "Nothing is changed on your disks until the final confirmation on the Review step."
                    color: Theme.textFaint; font { family: Theme.fontUi; pixelSize: 13 }
                }
            }

            // 1 · region
            Column {
                visible: win.st.step === 1
                anchors.fill: parent
                spacing: 12
                Text { text: "Region and keyboard"; color: Theme.text; font { family: Theme.fontUi; pixelSize: 24; weight: Font.Light } }
                Row {
                    spacing: 20; width: parent.width; height: parent.height - 50
                    Column {
                        width: (parent.width - 20) / 2; height: parent.height; spacing: 8
                        Label2 { text: "TIME ZONE" }
                        Field { id: tzSearch; width: parent.width; placeholderText: "Search time zones"; onTextChanged: tzList.filterText = text.toLowerCase() }
                        ListView {
                            id: tzList
                            property string filterText: ""
                            width: parent.width; height: parent.height - 90; clip: true
                            model: win.st.timezones.filter(function (z) { return z.toLowerCase().indexOf(filterText) >= 0; })
                            ScrollBar.vertical: ScrollBar {}
                            delegate: Rectangle {
                                required property string modelData
                                width: ListView.view.width; height: 34; radius: 6
                                color: win.st.timezone === modelData ? Qt.rgba(0.88, 0.10, 0.24, 0.30) : (tzMa.containsMouse ? Theme.surface : "transparent")
                                Text { anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter } text: parent.modelData; color: Theme.text; font { family: Theme.fontUi; pixelSize: 13 } }
                                MouseArea { id: tzMa; anchors.fill: parent; hoverEnabled: true; onClicked: win.st.timezone = parent.modelData }
                            }
                        }
                    }
                    Column {
                        width: (parent.width - 20) / 2; height: parent.height; spacing: 8
                        Label2 { text: "KEYBOARD LAYOUT" }
                        Field { id: kbSearch; width: parent.width; placeholderText: "Search layouts"; onTextChanged: kbList.filterText = text.toLowerCase() }
                        ListView {
                            id: kbList
                            property string filterText: ""
                            width: parent.width; height: parent.height - 90; clip: true
                            model: win.st.keymaps.filter(function (k) { return k.toLowerCase().indexOf(filterText) >= 0; })
                            ScrollBar.vertical: ScrollBar {}
                            delegate: Rectangle {
                                required property string modelData
                                width: ListView.view.width; height: 34; radius: 6
                                color: win.st.keyboard === modelData ? Qt.rgba(0.88, 0.10, 0.24, 0.30) : (kbMa.containsMouse ? Theme.surface : "transparent")
                                Text { anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter } text: parent.modelData; color: Theme.text; font { family: Theme.fontUi; pixelSize: 13 } }
                                MouseArea { id: kbMa; anchors.fill: parent; hoverEnabled: true; onClicked: win.st.keyboard = parent.modelData }
                            }
                        }
                    }
                }
            }

            // 2 · disk
            Column {
                visible: win.st.step === 2
                anchors.fill: parent
                spacing: 12
                Text { text: "Where should KinetixOS go?"; color: Theme.text; font { family: Theme.fontUi; pixelSize: 24; weight: Font.Light } }
                Text { text: "The whole selected disk will be erased and repartitioned."; color: Theme.textDim; font { family: Theme.fontUi; pixelSize: 13 } }
                Text {
                    visible: win.st.disks.length === 0
                    text: "No installable disks were found."; color: Theme.warn; font { family: Theme.fontUi; pixelSize: 14 }
                }
                ListView {
                    width: parent.width; height: parent.height - 70; clip: true; spacing: 8
                    model: win.st.disks
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool sel: win.st.disk === modelData.path
                        width: ListView.view.width; height: 74; radius: 10
                        opacity: modelData.inUse ? 0.5 : 1
                        color: sel ? Qt.rgba(0.88, 0.10, 0.24, 0.20) : (dMa.containsMouse ? Theme.surface : Theme.surfaceLow)
                        border.width: 1; border.color: sel ? Theme.crimson : Theme.stroke
                        Column {
                            anchors { left: parent.left; leftMargin: 18; verticalCenter: parent.verticalCenter }
                            spacing: 4
                            Text { text: modelData.model + "  ·  " + win.st.humanSize(modelData.size); color: Theme.text; font { family: Theme.fontUi; pixelSize: 15; weight: Font.DemiBold } }
                            Text {
                                text: modelData.path + (modelData.removable ? "  ·  removable" : "") + "  ·  "
                                      + (modelData.partitions.length === 0 ? "empty" : modelData.partitions.length + " existing partition" + (modelData.partitions.length > 1 ? "s" : ""))
                                color: Theme.textDim; font { family: Theme.fontMono; pixelSize: 11 }
                            }
                        }
                        Text {
                            visible: modelData.inUse
                            anchors { right: parent.right; rightMargin: 18; verticalCenter: parent.verticalCenter }
                            text: "IN USE"; color: Theme.warn; font { family: Theme.fontMono; pixelSize: 11; letterSpacing: 1.5 }
                        }
                        MouseArea { id: dMa; anchors.fill: parent; hoverEnabled: true; enabled: !modelData.inUse; onClicked: win.st.disk = modelData.path }
                    }
                }
            }

            // 3 · account
            Flickable {
                visible: win.st.step === 3
                anchors.fill: parent
                contentHeight: acct.implicitHeight; clip: true
                Column {
                    id: acct
                    width: Math.min(parent.width, 520)
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 10
                    Text { text: "Create your account"; color: Theme.text; font { family: Theme.fontUi; pixelSize: 24; weight: Font.Light } }
                    Label2 { text: "YOUR NAME" }
                    Field { width: parent.width; placeholderText: "Full name"; text: win.st.fullname
                        onTextEdited: { win.st.fullname = text; win.st.suggestUsername(text); } }
                    Label2 { text: "USERNAME" }
                    Field { width: parent.width; placeholderText: "username"; text: win.st.username
                        onTextEdited: { win.st.usernameEdited = true; win.st.username = text; } }
                    Text { visible: win.st.username !== "" && !win.st.usernameOk; color: Theme.warn; font.pixelSize: 12
                        text: "Lowercase letters, digits, - and _; must start with a letter." }
                    Label2 { text: "COMPUTER NAME" }
                    Field { width: parent.width; text: win.st.hostname; onTextEdited: win.st.hostname = text }
                    Text { visible: !win.st.hostnameOk; color: Theme.warn; font.pixelSize: 12; text: "Letters, digits and - only." }
                    Label2 { text: "PASSWORD" }
                    Field { width: parent.width; echoMode: TextInput.Password; placeholderText: "At least 8 characters"; text: win.st.password; onTextEdited: win.st.password = text }
                    Field { width: parent.width; echoMode: TextInput.Password; placeholderText: "Confirm password"; text: win.st.password2; onTextEdited: win.st.password2 = text }
                    Text { visible: win.st.password !== "" && !win.st.passwordOk; color: Theme.warn; font.pixelSize: 12; text: "Use at least 8 characters." }
                    Text { visible: win.st.password2 !== "" && !win.st.passwordsMatch; color: Theme.warn; font.pixelSize: 12; text: "Passwords do not match." }
                    Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.textFaint; font.pixelSize: 12
                        text: "This account is an administrator (sudo). The root account is locked." }
                }
            }

            // 4 · review
            Column {
                visible: win.st.step === 4
                anchors.fill: parent
                spacing: 10
                Text { text: "Review"; color: Theme.text; font { family: Theme.fontUi; pixelSize: 24; weight: Font.Light } }
                Repeater {
                    model: [
                        ["Disk", win.st.selectedDisk ? (win.st.selectedDisk.model + " (" + win.st.disk + ", " + win.st.humanSize(win.st.selectedDisk.size) + ")") : win.st.disk],
                        ["Account", win.st.username + (win.st.fullname ? " (" + win.st.fullname + ")" : "")],
                        ["Computer name", win.st.hostname],
                        ["Time zone", win.st.timezone],
                        ["Keyboard", win.st.keyboard]
                    ]
                    Row {
                        required property var modelData
                        spacing: 16
                        Text { width: 140; text: parent.modelData[0]; color: Theme.textDim; font { family: Theme.fontUi; pixelSize: 14 } }
                        Text { text: parent.modelData[1]; color: Theme.text; font { family: Theme.fontUi; pixelSize: 14 } }
                    }
                }
                Rectangle {
                    width: parent.width; height: warnText.implicitHeight + 28; radius: 10
                    color: Qt.rgba(1, 0.2, 0.25, 0.12); border.width: 1; border.color: Theme.danger
                    Text {
                        id: warnText
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 16 }
                        wrapMode: Text.WordWrap; color: Theme.text; font { family: Theme.fontUi; pixelSize: 14 }
                        text: "Everything on " + win.st.disk + " will be permanently erased, including any other operating systems on it."
                    }
                }
                Row {
                    spacing: 10
                    Rectangle {
                        width: 22; height: 22; radius: 5; color: win.st.eraseConfirmed ? Theme.crimson : "transparent"
                        border.width: 1; border.color: win.st.eraseConfirmed ? Theme.crimson : Theme.strokeStrong
                        Text { anchors.centerIn: parent; text: "✓"; color: "white"; visible: win.st.eraseConfirmed; font.pixelSize: 14 }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: win.st.eraseConfirmed = !win.st.eraseConfirmed }
                    }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: "I understand this disk will be erased"; color: Theme.text; font { family: Theme.fontUi; pixelSize: 14 } }
                }
            }

            // 5 · installing
            Column {
                visible: win.st.step === 5
                anchors.fill: parent
                spacing: 14
                Text { text: win.st.error === "" ? "Installing KinetixOS" : "Installation failed"; color: win.st.error === "" ? Theme.text : Theme.danger; font { family: Theme.fontUi; pixelSize: 24; weight: Font.Light } }
                Text { text: win.st.error !== "" ? win.st.error : win.st.stageLabel; color: Theme.textDim; font { family: Theme.fontUi; pixelSize: 14 } }
                Rectangle {
                    width: parent.width; height: 8; radius: 4; color: Theme.surface
                    Rectangle { width: parent.width * win.st.percent / 100; height: parent.height; radius: 4; color: win.st.error === "" ? Theme.crimson : Theme.danger
                        Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } } }
                }
                Rectangle {
                    width: parent.width; height: parent.height - 130; radius: 8; color: Qt.rgba(0, 0, 0, 0.35); border.width: 1; border.color: Theme.stroke
                    ListView {
                        id: logView
                        anchors.fill: parent; anchors.margins: 10; clip: true
                        model: win.st.logLines
                        onCountChanged: positionViewAtEnd()
                        delegate: Text { required property string modelData; width: ListView.view.width; text: modelData; wrapMode: Text.WrapAnywhere
                            color: Theme.textDim; font { family: Theme.fontMono; pixelSize: 11 } }
                    }
                }
                Row {
                    spacing: 10; visible: win.st.error !== ""
                    Btn { text: "Back to review"; onClicked: { win.st.error = ""; win.st.step = 4; } }
                    Btn { text: "Close"; onClicked: win.st.close() }
                }
            }

            // 6 · done
            Column {
                visible: win.st.step === 6
                anchors.centerIn: parent
                spacing: 18
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "KinetixOS is installed"; color: Theme.text; font { family: Theme.fontUi; pixelSize: 32; weight: Font.Light } }
                Text { anchors.horizontalCenter: parent.horizontalCenter; horizontalAlignment: Text.AlignHCenter
                    text: "Restart and remove the install media, then sign in as " + win.st.username + "."; color: Theme.textDim; font { family: Theme.fontUi; pixelSize: 15 } }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter; spacing: 12
                    Btn { primary: true; text: "Restart now"; onClicked: win.st.reboot() }
                    Btn { text: "Keep exploring"; onClicked: { win.st.open = false; } }
                }
            }
        }
    }
}
