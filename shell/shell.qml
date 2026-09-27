//@ pragma UseQApplication
import QtQuick
import Quickshell
import Quickshell.Io
import "bar"
import "agent"
import "overlay"
import "common"
import "desktop"
import "taskbar"
import "dock"
import "installer"

ShellRoot {
    id: shellRoot

    // Referencing singletons instantiates them at root startup:
    readonly property bool errorWatchActive: ErrorWatch.active
    readonly property var taskRunnerRef: TaskRunner
    readonly property bool widgetSystemEnabled: Quickshell.env("KINETIX_ENABLE_WIDGETS") === "1"

    // Cross-process control: keybinds / scripts talk to the live shell
    // without polling marker files. Verify with `qs -p shell ipc show`.
    //   qs -p shell ipc call argus togglePanel
    //   qs -p shell ipc call argus toggleLauncher | togglePalette | toggleCatalog | panic
    // (Bare `qs ipc ...` only works once installed as ~/.config/quickshell.)
    IpcHandler {
        id: argusIpc
        target: "argus"
        function togglePanel() { AgentState.panelOpen = !AgentState.panelOpen; }
        function openPanel() { AgentState.panelOpen = true; }
        function closeAll() {
            AgentState.panelOpen = false;
            AgentState.paletteOpen = false;
            AgentState.launcherOpen = false;
            if (shellRoot.widgetSystemEnabled) WidgetStore.catalogOpen = false;
            AgentState.sysOpen = false;
            AgentState.appCenterOpen = false;
            AgentState.notifOpen = false;
            if (AgentState.terminalOpen) AgentState.toggleTerminal();
        }
        function openInstaller() { InstallerState.show(); }
        function toggleNotifs() { AgentState.toggleNotifs(); }
        function notifDemo() { Notif.demo(); }
        function notifClear() { Notif.clearAll(); }
        function notifTestError() { ErrorWatch.simulate(); }
        function openErrorLogs() { Notif.openErrorDir(); }
        function notifInvoke(nid: int, action: string) { Notif.invoke(nid, action); }
        function toggleDnd() { Notif.toggleDnd(); }
        function toggleSys() { AgentState.toggleSys(); }
        function toggleAppCenter() { AgentState.toggleAppCenter(); }
        function toggleTerminal() { AgentState.toggleTerminal(); }
        function openAppCenter() { AgentState.appCenterOpen = true; }
        function setAppCenterTab(t: string) { AppCenterState.activeTab = t; }
        function searchAppCenter(q: string) {
            AgentState.appCenterOpen = true;
            AppCenterState.setSearch(q);
        }
        function openLauncher() { AgentState.launcherOpen = true; }
        function toggleLauncher() { AgentState.toggleLauncher(); }
        function openPalette() { AgentState.paletteOpen = true; }
        function togglePalette() { AgentState.togglePalette(); }
        function toggleCatalog() {
            if (shellRoot.widgetSystemEnabled) WidgetStore.catalogOpen = !WidgetStore.catalogOpen;
        }
        function toggleEditMode() {
            if (shellRoot.widgetSystemEnabled) WidgetStore.editMode = !WidgetStore.editMode;
        }
        function setAgentTab(t: string) { AgentState.setTab(t); }
        function toggleAgentSettings() { AgentState.toggleSettings(); }
        function send(prompt: string) {
            AgentState.panelOpen = true;
            AgentState.setTab("chat");
            ArgusBridge.send(prompt);
        }
        function clearSession() { AgentState.clearMessages(); }
        function panic() { ArgusBridge.panic(); }
    }

    // ── Lazy overlay loading ─────────────────────────────────────────
    // The five large popup surfaces are instantiated on open and torn
    // down 450ms after close (covers the 240ms exit animations). Their
    // QML trees plus per-window GL contexts are the largest RAM block
    // after the engine itself; a closed surface now costs nothing. IPC
    // stays live throughout — the handlers above only touch AgentState /
    // store singletons, and each Loader is keyed to its open flag.
    Timer { id: appCenterLinger; interval: 450 }
    Timer { id: paletteLinger; interval: 450 }
    Timer { id: launcherLinger; interval: 450 }
    Timer { id: catalogLinger; interval: 450 }
    Connections {
        target: AgentState
        function onAppCenterOpenChanged() { if (!AgentState.appCenterOpen) appCenterLinger.restart(); }
        function onPaletteOpenChanged() { if (!AgentState.paletteOpen) paletteLinger.restart(); }
        function onLauncherOpenChanged() { if (!AgentState.launcherOpen) launcherLinger.restart(); }
    }
    Connections {
        target: shellRoot.widgetSystemEnabled ? WidgetStore : null
        function onCatalogOpenChanged() { if (!WidgetStore.catalogOpen) catalogLinger.restart(); }
    }

    Variants {
        model: Quickshell.screens
        KinetixDesktop {}
    }
    Variants {
        model: Quickshell.screens
        Bar {}
    }
    Variants {
        model: Quickshell.screens
        Taskbar {}
    }
    Variants {
        model: Quickshell.screens
        Dock {}
    }
    Variants {
        model: Quickshell.screens
        InstallPrompt {}
    }
    Variants {
        model: Quickshell.screens
        Installer {}
    }
    Variants {
        model: Quickshell.screens
        AgentPanel {}
    }
    // EdgeGlow / Osd / Notifications stay eager: tiny trees, and they must
    // catch events the instant they fire.
    Variants {
        model: Quickshell.screens
        EdgeGlow {}
    }
    Variants {
        model: Quickshell.screens
        Osd {}
    }
    Variants {
        model: Quickshell.screens
        Notifications {}
    }
    Variants {
        model: Quickshell.screens
        NotificationCenter {}
    }
    Variants {
        model: Quickshell.screens
        SysPopup {}
    }
    Variants {
        model: Quickshell.screens
        delegate: Loader {
            id: appCenterLoader
            required property ShellScreen modelData
            active: AgentState.appCenterOpen || appCenterLinger.running
            sourceComponent: AppCenterPopup { modelData: appCenterLoader.modelData }
        }
    }
    Variants {
        model: Quickshell.screens
        delegate: Loader {
            id: paletteLoader
            required property ShellScreen modelData
            active: AgentState.paletteOpen || paletteLinger.running
            sourceComponent: CommandPalette { modelData: paletteLoader.modelData }
        }
    }
    Variants {
        model: Quickshell.screens
        delegate: Loader {
            id: launcherLoader
            required property ShellScreen modelData
            active: AgentState.launcherOpen || launcherLinger.running
            sourceComponent: AppLauncher { modelData: launcherLoader.modelData }
        }
    }
    Variants {
        model: Quickshell.screens
        delegate: Loader {
            id: catalogLoader
            required property ShellScreen modelData
            active: shellRoot.widgetSystemEnabled && (WidgetStore.catalogOpen || catalogLinger.running)
            sourceComponent: WidgetCatalog { modelData: catalogLoader.modelData }
        }
    }

    // Desktop widget windows are the user-configurable layer above the art.
    WidgetLayer {}

    // Top-most transient overlay; its own timer fades it off after startup.
    Variants {
        model: Quickshell.screens
        BootSplash {}
    }
}
