pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// AppCenterState: reactive state and process orchestrator for the Kinetix App Center.
// Manages package manager detection, AUR/Flathub search, update checking,
// and 1-click install/uninstall runners.
QtObject {
    id: root

    readonly property string scriptPath: Quickshell.shellDir + "/../scripts/argus-appcenter.py"

    // ── Package Managers State ──────────────────────────────────────────
    property var managers: ({
        "pacman": { "name": "Pacman (ALPM)", "installed": true, "desc": "Official Arch Linux package manager." },
        "aur": { "name": "AUR (Paru)", "installed": true, "helper": "paru", "desc": "Arch User Repository community packages." },
        "paru": { "name": "Paru (AUR Helper)", "installed": true, "desc": "Blazing fast Rust-based AUR helper." },
        "yay": { "name": "Yay (AUR Helper)", "installed": false, "desc": "Popular Go-based AUR helper." },
        "flatpak": { "name": "Flatpak & Flathub", "installed": false, "flathub": false, "desc": "Sandboxed universal desktop apps." },
        "snap": { "name": "Snapd", "installed": false, "desc": "Canonical snap store." },
        "appimage": { "name": "AppImage Support", "installed": false, "desc": "Portable standalone Linux desktop apps." }
    })

    property int updatesCount: 0
    property var updates: []
    property var featuredApps: []
    property var searchResults: []
    property string searchQuery: ""
    property string activeTab: "discover"    // "discover" | "search" | "updates" | "engines"
    property string sourceFilter: "all"     // "all" | "arch" | "aur" | "flatpak"
    property bool searching: false
    property bool checkingUpdates: false
    property bool ready: false
    property string installingId: ""
    property string enablingManager: ""

    property string selectedCategory: "all" // "all" | "Development" | "Communication" | "Media" | "Browsers" | "Productivity" | "Gaming" | "System"
    property bool updatingAll: false

    readonly property var filteredFeaturedApps: {
        if (!featuredApps || featuredApps.length === 0) return [];
        if (!selectedCategory || selectedCategory === "all") return featuredApps;
        var cat = selectedCategory.toLowerCase();
        return featuredApps.filter(function(app) {
            return (app.category || "").toLowerCase() === cat;
        });
    }

    function setCategory(cat) {
        selectedCategory = cat;
        if (activeTab !== "discover") activeTab = "discover";
    }

    function countForCategory(cat) {
        if (!featuredApps || featuredApps.length === 0) return 0;
        if (!cat || cat === "all") return featuredApps.length;
        var c = cat.toLowerCase();
        var n = 0;
        for (var i = 0; i < featuredApps.length; i++) {
            if ((featuredApps[i].category || "").toLowerCase() === c) n++;
        }
        return n;
    }

    // ── Search Debounce Timer ───────────────────────────────────────────
    property Timer searchTimer: Timer {
        interval: 320
        repeat: false
        onTriggered: root.executeSearch()
    }

    function setSearch(q) {
        searchQuery = q;
        if (q.trim() === "") {
            searchTimer.stop();
            searching = false;
            searchResults = [];
            if (activeTab === "search") activeTab = "discover";
            return;
        }
        activeTab = "search";
        searching = true;
        searchTimer.restart();
    }

    function setFilter(f) {
        sourceFilter = f;
        if (searchQuery.trim() !== "") {
            searching = true;
            searchTimer.restart();
        }
    }

    // ── Background Processes ────────────────────────────────────────────
    property Process statusProc: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                root.checkingUpdates = false;
                try {
                    var d = JSON.parse(this.text);
                    if (d.managers) root.managers = d.managers;
                    if (d.updates_count !== undefined) root.updatesCount = d.updates_count;
                    if (d.updates) root.updates = d.updates;
                    root.ready = true;
                } catch (e) {}
            }
        }
    }

    property Process featuredProc: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var d = JSON.parse(this.text);
                    if (d.apps) root.featuredApps = d.apps;
                } catch (e) {}
            }
        }
    }

    property Process searchProc: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                root.searching = false;
                try {
                    var d = JSON.parse(this.text);
                    if (d.results) root.searchResults = d.results;
                } catch (e) {
                    root.searchResults = [];
                }
            }
        }
    }

    property Process actionProc: Process {}

    function refreshStatus() {
        statusProc.command = ["python3", scriptPath, "status"];
        statusProc.running = true;
    }

    function refreshFeatured() {
        featuredProc.command = ["python3", scriptPath, "featured"];
        featuredProc.running = true;
    }

    function checkUpdates() {
        checkingUpdates = true;
        statusProc.command = ["python3", scriptPath, "check-updates"];
        statusProc.running = true;
    }

    function executeSearch() {
        if (searchQuery.trim() === "") {
            searching = false;
            return;
        }
        searchProc.command = ["python3", scriptPath, "search", searchQuery.trim(), sourceFilter];
        searchProc.running = true;
    }

    function installApp(source, id) {
        installingId = id;
        actionProc.command = ["python3", scriptPath, "install", source, id];
        actionProc.running = true;
        // Schedule refresh after 4 seconds
        refreshTimer.restart();
    }

    function uninstallApp(source, id) {
        actionProc.command = ["python3", scriptPath, "uninstall", source, id];
        actionProc.running = true;
        refreshTimer.restart();
    }

    function enableManager(manager) {
        enablingManager = manager;
        actionProc.command = ["python3", scriptPath, "enable-manager", manager];
        actionProc.running = true;
        refreshTimer.restart();
    }

    function updateAll() {
        updatingAll = true;
        actionProc.command = ["python3", scriptPath, "update-all"];
        actionProc.running = true;
        refreshTimer.restart();
    }

    property Timer refreshTimer: Timer {
        interval: 3500
        repeat: false
        onTriggered: {
            root.installingId = "";
            root.enablingManager = "";
            root.updatingAll = false;
            root.checkingUpdates = false;
            root.refreshStatus();
            root.refreshFeatured();
            if (typeof AppIndex !== "undefined" && AppIndex && AppIndex.rescan) {
                AppIndex.rescan();
            }
        }
    }

    // Initial load at shell startup
    Component.onCompleted: {
        refreshStatus();
        refreshFeatured();
    }
}
