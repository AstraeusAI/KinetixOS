//@ pragma UseQApplication
import Quickshell
import Quickshell.Io
import "bar"
import "agent"
import "overlay"
import "common"

ShellRoot {
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
            WidgetStore.catalogOpen = false;
            AgentState.sysOpen = false;
            AgentState.appCenterOpen = false;
        }
        function toggleSys() { AgentState.toggleSys(); }
        function toggleAppCenter() { AgentState.toggleAppCenter(); }
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
        function toggleCatalog() { WidgetStore.catalogOpen = !WidgetStore.catalogOpen; }
        function toggleEditMode() { WidgetStore.editMode = !WidgetStore.editMode; }
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
    Variants {
        model: Quickshell.screens
        Bar {}
    }
    Variants {
        model: Quickshell.screens
        AgentPanel {}
    }
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
        SysPopup {}
    }
    Variants {
        model: Quickshell.screens
        AppCenterPopup {}
    }
    Variants {
        model: Quickshell.screens
        CommandPalette {}
    }
    Variants {
        model: Quickshell.screens
        AppLauncher {}
    }
    Variants {
        model: Quickshell.screens
        Notifications {}
    }
    Variants {
        model: Quickshell.screens
        WidgetCatalog {}
    }

    // desktop widgets float over applications — one window per instance
    WidgetLayer {}
}
