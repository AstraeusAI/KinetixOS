pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// State + backend bridge for the live-ISO graphical installer
// (shell/installer/Installer.qml, scripts/kinetix-installer.py).
QtObject {
    id: root

    property bool open: false
    property int step: 0            // 0 welcome 1 region 2 disk 3 account 4 review 5 install 6 done
    readonly property var stepNames: ["Welcome", "Region", "Disk", "Account", "Review", "Install"]

    property var disks: []
    property var timezones: ["UTC"]
    property var keymaps: ["us"]

    property string disk: ""
    property string timezone: "UTC"
    property string keyboard: "us"
    property string fullname: ""
    property string username: ""
    property bool usernameEdited: false
    property string hostname: "kinetixos"
    property string password: ""
    property string password2: ""
    property bool eraseConfirmed: false

    property real percent: 0
    property string stageLabel: ""
    property var logLines: []
    property string error: ""
    property bool running: false
    property bool simulated: Quickshell.env("KINETIX_INSTALLER_SIMULATE") === "1"

    readonly property string script: Quickshell.shellDir + "/../scripts/kinetix-installer.py"

    // ── validation (mirrors the backend; backend re-validates) ──
    readonly property bool usernameOk: /^[a-z_][a-z0-9_-]{0,30}$/.test(username)
        && ["root", "daemon", "bin", "sys", "nobody", "kinetix"].indexOf(username) < 0
    readonly property bool hostnameOk: /^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/.test(hostname)
    readonly property bool passwordOk: password.length >= 8
    readonly property bool passwordsMatch: password === password2 && password2.length > 0
    readonly property bool accountOk: usernameOk && hostnameOk && passwordOk && passwordsMatch
    readonly property var selectedDisk: {
        for (var i = 0; i < disks.length; i++) if (disks[i].path === disk) return disks[i];
        return null;
    }

    function humanSize(b) {
        var gb = b / 1e9;
        return gb >= 1000 ? (gb / 1000).toFixed(1) + " TB" : Math.round(gb) + " GB";
    }

    function suggestUsername(full) {
        if (usernameEdited) return;
        var u = String(full).toLowerCase().split(" ")[0].replace(/[^a-z0-9_-]/g, "");
        if (/^[0-9-]/.test(u)) u = "";
        username = u;
    }

    function show() {
        error = ""; step = 0; open = true;
        disksProc.running = false; disksProc.running = true;
        regionsProc.running = false; regionsProc.running = true;
    }
    function close() { if (!running) open = false; }

    function canAdvance() {
        if (step === 2) return disk !== "";
        if (step === 3) return accountOk;
        if (step === 4) return eraseConfirmed;
        return true;
    }
    function next() {
        if (!canAdvance()) return;
        if (step === 4) { startInstall(); return; }
        step++;
    }
    function back() { if (step > 0 && step < 5) step--; }

    function startInstall() {
        percent = 0; stageLabel = "Starting"; logLines = []; error = "";
        step = 5; running = true;
        installProc.environment = ({
            "KINETIX_SPEC": JSON.stringify({
                "disk": disk, "hostname": hostname, "fullname": fullname,
                "username": username, "password": password,
                "timezone": timezone, "keyboard": keyboard }),
            "SUDO_ASKPASS": "/usr/bin/ksshaskpass"
        });
        installProc.command = simulated
            ? ["python3", script, "install", "@env", "--simulate"]
            : ["sudo", "-A", "--preserve-env=KINETIX_SPEC", "python3", script, "install", "@env"];
        installProc.running = true;
    }

    function reboot() { Quickshell.execDetached(["systemctl", "reboot"]); }

    property Process disksProc: Process {
        command: ["python3", root.script, "disks"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    root.disks = JSON.parse(text);
                    if (root.disk === "" && root.disks.length > 0) {
                        var pick = root.disks.filter(function (d) { return !d.inUse; });
                        root.disk = (pick.length ? pick[0] : root.disks[0]).path;
                    }
                } catch (e) { root.disks = []; }
            }
        }
    }
    property Process regionsProc: Process {
        command: ["python3", root.script, "regions"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var r = JSON.parse(text);
                    root.timezones = r.timezones; root.keymaps = r.keymaps;
                } catch (e) {}
            }
        }
    }
    property Process installProc: Process {
        stdout: SplitParser {
            onRead: function (line) {
                var ev;
                try { ev = JSON.parse(line); } catch (e) { return; }
                if (ev.type === "stage") { root.percent = ev.percent; root.stageLabel = ev.label; }
                else if (ev.type === "log") {
                    var l = root.logLines.slice(-400); l.push(ev.line); root.logLines = l;
                } else if (ev.type === "error") { root.error = ev.message; }
                else if (ev.type === "done") { root.percent = 100; root.step = 6; }
            }
        }
        onExited: function (code) {
            root.running = false;
            if (code !== 0 && root.error === "") root.error = "The installer stopped unexpectedly (exit " + code + ").";
        }
    }
}
