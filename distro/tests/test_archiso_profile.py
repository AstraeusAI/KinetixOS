import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DISTRO = ROOT / "distro"
PROFILE = DISTRO / "archiso"


class ArchisoProfileTests(unittest.TestCase):
    def test_profile_targets_kinetix_x86_64_with_bios_and_uefi_boot(self):
        text = (PROFILE / "profiledef.sh").read_text()
        self.assertIn('iso_name="kinetixos"', text)
        self.assertIn('install_dir="kinetix"', text)
        self.assertIn("'bios.syslinux'", text)
        self.assertIn("'uefi.systemd-boot'", text)

    def test_broad_compatibility_cachyos_bore_kernel_uses_baseline_repo(self):
        packages = {
            line.strip()
            for line in (PROFILE / "packages.x86_64").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        pacman_conf = (PROFILE / "pacman.conf").read_text()
        self.assertTrue(
            {"cachyos-keyring", "cachyos-mirrorlist", "linux-cachyos-bore"}.issubset(packages)
        )
        self.assertIn("[cachyos]", pacman_conf)
        self.assertIn("/etc/pacman.d/cachyos-mirrorlist", pacman_conf)
        self.assertNotIn("[cachyos-v3]", pacman_conf)
        self.assertNotIn("[cachyos-v4]", pacman_conf)

    def test_bore_kernel_is_the_bios_and_uefi_default_with_arch_fallbacks(self):
        syslinux = (PROFILE / "syslinux/archiso_sys-linux.cfg").read_text()
        loader = (PROFILE / "efiboot/loader/loader.conf").read_text()
        bore_entry = (PROFILE / "efiboot/loader/entries/01-kinetix-bore.conf").read_text()
        fallback_entry = (PROFILE / "efiboot/loader/entries/02-archiso-fallback.conf").read_text()
        builder = (DISTRO / "build-iso.sh").read_text()
        self.assertIn("DEFAULT arch", (PROFILE / "syslinux/archiso_sys.cfg").read_text())
        self.assertIn("vmlinuz-linux-cachyos-bore", syslinux)
        self.assertIn("initramfs-linux-cachyos-bore.img", syslinux)
        self.assertIn("LABEL arch-fallback", syslinux)
        self.assertIn("default 01-kinetix-bore.conf", loader)
        self.assertIn("vmlinuz-linux-cachyos-bore", bore_entry)
        self.assertIn("initramfs-linux-cachyos-bore.img", bore_entry)
        self.assertIn("vmlinuz-linux", fallback_entry)
        self.assertIn("initramfs-linux.img", fallback_entry)
        self.assertIn('"$ROOT/distro/archiso/syslinux/archiso_sys-linux.cfg"', builder)
        self.assertIn('"$ROOT/distro/archiso/syslinux/archiso_sys.cfg"', builder)

    def test_builder_persists_cachy_repo_config_for_the_live_system(self):
        builder = (DISTRO / "build-iso.sh").read_text()
        self.assertIn('"$ROOT/distro/archiso/pacman.conf"', builder)
        self.assertIn(
            '"$PROFILE/airootfs/usr/share/kinetix/config/pacman.conf"', builder
        )
        self.assertIn("/etc/pacman.d/cachyos-mirrorlist", builder)
        self.assertIn("882DCFE48E2051D48E2562ABF3B607488DB35A47", builder)

    def test_live_image_contains_kinetix_shell_and_default_terminal(self):
        packages = {
            line.strip()
            for line in (PROFILE / "packages.x86_64").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertTrue(
            {
                "kwin",
                "quickshell",
                "ghostty",
                "sddm",
                "networkmanager",
                "pipewire",
                "wireplumber",
                "xdg-desktop-portal",
                "xdg-desktop-portal-gtk",
                "mesa",
                "swaybg",
                "iptables",
                "gnu-free-fonts",
                "qt6-multimedia-ffmpeg",
                "pipewire-jack",
                "tesseract-data-eng",
            }.issubset(packages)
        )
        self.assertNotIn("plasma-meta", packages)
        self.assertNotIn("plasma-desktop", packages)
        self.assertNotIn("xdg-desktop-portal-kde", packages)

    def test_ghostty_is_the_only_configured_default_terminal(self):
        packages = {
            line.strip()
            for line in (PROFILE / "packages.x86_64").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        terminals = (PROFILE / "airootfs/etc/xdg/xdg-terminals.list").read_text()
        session = (PROFILE / "airootfs/usr/bin/kinetix-session").read_text()
        forbidden = {"alacritty", "foot", "kitty", "konsole", "gnome-terminal", "xterm", "xfce4-terminal"}
        self.assertIn("ghostty", packages)
        self.assertIn("xdg-terminal-exec", packages)
        self.assertEqual(["com.mitchellh.ghostty.desktop"], [line.strip() for line in terminals.splitlines() if line.strip() and not line.lstrip().startswith("#")])
        self.assertTrue(forbidden.isdisjoint(packages))
        self.assertIn("export TERMINAL=ghostty", session)

    def test_kinetix_session_launches_the_existing_quickshell_config_under_kwin(self):
        session = (PROFILE / "airootfs/usr/bin/kinetix-session").read_text()
        shell = (PROFILE / "airootfs/usr/bin/kinetix-shell").read_text()
        self.assertIn("kwin_wayland", session)
        self.assertIn("systemd-detect-virt --quiet --vm", session)
        self.assertIn("LIBGL_ALWAYS_SOFTWARE=1", session)
        self.assertIn("--drm", session)
        self.assertIn("--exit-with-session", session)
        self.assertIn("/usr/bin/kinetix-shell", session)
        self.assertIn("XDG_CURRENT_DESKTOP=Kinetix", session)
        self.assertNotIn("KDE:", session)
        self.assertIn("quickshell -p /usr/share/kinetix/shell", shell)

    def test_kwin_uses_the_direct_drm_backend_unconditionally(self):
        # Round 18: KWin used to be nested in an X11 server in VMs (first
        # SDDM's own greeter Xorg, then a private per-session Xorg), on the
        # assumption emulated adapters lack DRM/KMS. That assumption is
        # stale for modern QEMU — its default `-vga std` adapter is backed
        # by the bochs-drm kernel driver, a real (if unaccelerated) KMS
        # device, confirmed live (/dev/dri/card0, DRIVER=bochs-drm) with a
        # correctly rendered desktop over --drm in that exact VM. The
        # nested-X11 indirection was also where the actual black-screen bug
        # lived (VT-ownership mismatches, then non-root Xorg seat/logind
        # permission failures) — --drm unconditionally removes that whole
        # class along with the packages/config it needed.
        session = (PROFILE / "airootfs/usr/bin/kinetix-session").read_text()
        sddm = (PROFILE / "airootfs/etc/sddm.conf").read_text()
        packages = (PROFILE / "packages.x86_64").read_text()
        self.assertFalse((PROFILE / "airootfs/usr/local/lib/kinetix/sddm-xsetup").exists())
        self.assertNotIn("--x11-display", session)
        self.assertNotIn("XDG_VTNR", session)
        self.assertNotIn("/usr/lib/Xorg", session)
        self.assertNotIn("DisplayCommand", sddm)
        self.assertNotIn("xhost", session)
        self.assertNotIn("xorg-xhost", packages)

    def test_shell_registers_mockup_desktop_surfaces_without_replacing_the_bar(self):
        shell = (ROOT / "shell/shell.qml").read_text()
        desktop_dir = ROOT / "shell/desktop"
        self.assertIn('import "desktop"', shell)
        self.assertIn("Bar {}", shell)
        self.assertNotIn("KinetixSystemPanel {}", shell)
        self.assertFalse((desktop_dir / "KinetixSystemPanel.qml").exists())
        # Round 17: the old left-side task manager (KinetixDock, then
        # KinetixTaskbar) was replaced by a standalone taskbar
        # (shell/taskbar/) — a separate top-level component tree, not one
        # of the "desktop" surfaces this test covers.
        self.assertNotIn("KinetixTaskbar {}", shell)
        self.assertNotIn("KinetixDock {}", shell)
        self.assertFalse((desktop_dir / "KinetixTaskbar.qml").exists())
        self.assertFalse((desktop_dir / "KinetixDock.qml").exists())
        for component in ("KinetixDesktop", "BootSplash"):
            self.assertIn(f"{component} {{}}", shell)
            self.assertTrue((desktop_dir / f"{component}.qml").is_file())

    def test_shell_registers_a_bottom_docked_taskbar_with_a_launcher_button(self):
        shell = (ROOT / "shell/shell.qml").read_text()
        taskbar_dir = ROOT / "shell/taskbar"
        self.assertIn('import "taskbar"', shell)
        self.assertIn("Taskbar {}", shell)
        for component in ("Taskbar", "TaskButton", "TaskPreview", "TaskStore"):
            self.assertTrue((taskbar_dir / f"{component}.qml").is_file())
        taskbar = (taskbar_dir / "Taskbar.qml").read_text()
        # The two explicit asks: a main button that opens the application
        # drawer (the same launcher every other surface opens, not a
        # second competing one), and a conventional full-width bottom bar
        # — not a floating rounded dock.
        self.assertIn("AgentState.toggleLauncher()", taskbar)
        self.assertIn("ToplevelManager", taskbar)
        self.assertIn("anchors { left: true; right: true; bottom: true }", taskbar)
        self.assertIn("exclusiveZone: 56", taskbar)
        self.assertIn("radius: 0", taskbar)

    def test_taskbar_sources_windows_from_kinetix_tasks_not_toplevelmanager(self):
        # Round 18: Quickshell.Wayland.ToplevelManager speaks the
        # zwlr-foreign-toplevel-management (or ext-foreign-toplevel-list)
        # protocol family; KWin only implements its own
        # org_kde_plasma_window_management protocol — confirmed by grepping
        # both binaries' symbols, neither references the other's protocol
        # at all. ToplevelManager.toplevels is therefore permanently empty
        # under KWin (confirmed live: a window visibly open on screen,
        # taskbar still reporting "No windows open"), independent of any
        # iteration fallback chain. The fix routes the taskbar and the
        # active-window bar capsule through TaskRunner (shell/common/
        # TaskRunner.qml), which streams scripts/kinetix-tasks.py — a
        # daemon that talks to KWin directly via its scripting/KRunner
        # D-Bus interfaces. Verified live end-to-end in this round: opening
        # and closing a real window correctly appeared/disappeared in the
        # taskbar, and toggle-minimize/close both round-tripped through the
        # daemon's KWin-scripting calls.
        taskbar = (ROOT / "shell/taskbar/Taskbar.qml").read_text()
        task_store = (ROOT / "shell/taskbar/TaskStore.qml").read_text()
        task_runner = (ROOT / "shell/common/TaskRunner.qml").read_text()
        active_window = (ROOT / "shell/bar/ActiveWindow.qml").read_text()
        qmldir = (ROOT / "shell/common/qmldir").read_text()
        tasks_daemon = (ROOT / "scripts/kinetix-tasks.py").read_text()
        self.assertNotIn("ToplevelManager.toplevels", taskbar)
        self.assertNotIn("ToplevelManager.activeToplevel", active_window)
        self.assertIn("TaskRunner.windows", taskbar)
        self.assertIn("TaskRunner.activate", task_store)
        self.assertIn("TaskRunner.activeWindow", active_window)
        self.assertIn("singleton TaskRunner", qmldir)
        self.assertIn("kinetix-tasks.py", task_runner)
        self.assertIn("def minimize_window", tasks_daemon)

    def test_taskbar_controls_are_keyboard_accessible(self):
        # Round 18 polish: the launcher and show-desktop buttons had no
        # Accessible.*/keyboard-activation properties at all (a real
        # regression versus the removed dock, which had them) — confirmed
        # by grepping the whole taskbar/ tree and finding zero hits.
        taskbar = (ROOT / "shell/taskbar/Taskbar.qml").read_text()
        task_button = (ROOT / "shell/taskbar/TaskButton.qml").read_text()
        for text in (taskbar, task_button):
            self.assertIn("Accessible.role: Accessible.Button", text)
            self.assertIn("activeFocusOnTab: true", text)
            self.assertIn("Keys.onReturnPressed", text)
            self.assertIn("Keys.onSpacePressed", text)
        self.assertIn('Accessible.name: "Open applications"', taskbar)
        self.assertIn('Accessible.name: "Show desktop"', taskbar)

    def test_task_buttons_match_the_task_rows_actual_height(self):
        # Round 18 fix: TaskButton was still 52px tall (left over from the
        # old floating rail) while the task row's Flickable was set to the
        # 44px chip size — a clipped Flickable taller than its own bound
        # crops every icon top and bottom. Both must agree.
        taskbar = (ROOT / "shell/taskbar/Taskbar.qml").read_text()
        task_button = (ROOT / "shell/taskbar/TaskButton.qml").read_text()
        self.assertIn("readonly property int chipSize: 44", taskbar)
        # collapsed tabs are 44px squares; only the focused tab widens
        self.assertRegex(task_button, r"implicitWidth: expanded \? .+ : 44\n")
        self.assertIn("implicitHeight: 44", task_button)
        # The Flickable must be taller than the chips (hover-scale + bloom
        # headroom), never merely equal or smaller.
        self.assertIn("height: rail.chipSize + 12", taskbar)

    def test_task_button_tooltip_is_layershell_safe_not_builtin_tooltip(self):
        # Round 18 required QtQuick.Controls here for a built-in ToolTip
        # instance showing the app's name on hover. Round 19: that
        # ToolTip — like every other one in this shell — rendered on top
        # of the tile instead of above it inside Taskbar.qml's PanelWindow
        # (wlr-layer-shell), eating the click meant for the tile (reported
        # live: hovering a taskbar icon to read its name made it
        # unclickable). Replaced with the same layer-shell-safe Quickshell
        # PopupWindow pattern used everywhere else in this shell now —
        # QtQuick.Controls is no longer needed in this file at all.
        task_button = (ROOT / "shell/taskbar/TaskButton.qml").read_text()
        self.assertNotIn("import QtQuick.Controls", task_button)
        self.assertNotIn("ToolTip {", task_button)
        self.assertIn("PopupWindow {", task_button)
        self.assertIn("anchor.edges: Edges.Top", task_button)
        self.assertIn("anchor.window: root.anchorWindow", task_button)
        self.assertIn("anchorWindow: taskbar", (ROOT / "shell/taskbar/Taskbar.qml").read_text())
        self.assertIn("text: root.title", task_button)

    def test_main_bar_geometry_is_untouched_by_desktop_surface_changes(self):
        bar = (ROOT / "shell/bar/Bar.qml").read_text()
        self.assertIn("implicitHeight: 56", bar)

    def test_desktop_text_line_height_uses_text_property_not_font(self):
        desktop = (ROOT / "shell/desktop/KinetixDesktop.qml").read_text()
        self.assertNotRegex(desktop, r"font\s*\{[^}]*lineHeight")
        self.assertIn("lineHeight: 1.35", desktop)

    def test_widget_system_is_disabled_by_default_and_opt_in(self):
        shell = (ROOT / "shell/shell.qml").read_text()
        layer = (ROOT / "shell/overlay/WidgetLayer.qml").read_text()
        palette = (ROOT / "shell/overlay/CommandPalette.qml").read_text()
        self.assertIn('Quickshell.env("KINETIX_ENABLE_WIDGETS") === "1"', shell)
        self.assertIn('Quickshell.env("KINETIX_ENABLE_WIDGETS") === "1"', layer)
        self.assertIn("model: widgetSystemEnabled ? WidgetStore.order : []", layer)
        self.assertIn("active: shellRoot.widgetSystemEnabled &&", shell)
        self.assertIn("widgetSystemEnabled", palette)
        self.assertIn('c.exec === "widgets" || c.exec === "widgetedit"', palette)
        self.assertNotIn("KinetixSystemPanel", shell)

    def test_startup_splash_is_branded_animated_and_dismisses(self):
        # The composition and the startup logic are deliberately separate
        # files: BootSplash owns the fullscreen layer and decides when to
        # leave, SplashContent owns what it looks like. The old test read
        # only BootSplash and pinned `interval: 4800` — a fixed duration that
        # was the whole dismissal policy. It is replaced by readiness plus a
        # floor and a ceiling, asserted below.
        splash = (ROOT / "shell/desktop/BootSplash.qml").read_text()
        content = (ROOT / "shell/desktop/SplashContent.qml").read_text()
        self.assertIn("WlrLayer.Overlay", splash)
        self.assertIn("Timer", splash)
        # Branded. The wordmark is assembled letter by letter for the
        # staggered entrance, so the literal "KINETIXOS" is not a substring
        # of the file — the sequence it is built from is.
        self.assertIn('"K", "I", "N", "E", "T", "I", "X", "O", "S"', content)
        self.assertIn("Theme.crimson", content)
        # Animated.
        self.assertIn("NumberAnimation", content)

    def test_splash_dismissal_is_readiness_driven_not_a_fixed_duration(self):
        # The point of the change: a duration is not a readiness condition.
        # Every stage must be wired to a live signal, and the only fixed
        # numbers left are the floor and the ceiling that bound it.
        splash = (ROOT / "shell/desktop/BootSplash.qml").read_text()
        self.assertNotIn("interval: 4800", splash)
        for signal in ("AppIndex.ready", "SysInfo.ready", "ArgusBridge.caps"):
            with self.subTest(signal=signal):
                self.assertIn(signal, splash)
        for bound in ("minVisibleMs", "maxVisibleMs", "allDone"):
            with self.subTest(bound=bound):
                self.assertIn(bound, splash)

    def test_splash_reuses_the_real_brand_mark(self):
        # The splash drew its own ad-hoc logo (concentric circles and a
        # rotating dot) while every other surface used the faceted K. The
        # startup screen is where the brand gets to be most itself, so it
        # borrows the same component rather than inventing a second mark.
        content = (ROOT / "shell/desktop/SplashContent.qml").read_text()
        self.assertIn("KinetixMark {", content)
        self.assertIn('import "../components"', content)

    def test_splash_is_only_branded_on_the_first_output(self):
        # A full composition per monitor is N copies of the shader-backed
        # mark for one screen that is actually being watched during boot.
        splash = (ROOT / "shell/desktop/BootSplash.qml").read_text()
        content = (ROOT / "shell/desktop/SplashContent.qml").read_text()
        self.assertIn("Quickshell.screens[0]", splash)
        self.assertIn("visible: content.primary", content)

    def test_live_session_uses_a_clean_kinetixos_wallpaper_asset(self):
        asset = DISTRO / "assets/kinetix-wallpaper.png"
        builder = (DISTRO / "build-iso.sh").read_text()
        session = (PROFILE / "airootfs/usr/bin/kinetix-shell").read_text()
        self.assertTrue(asset.is_file())
        self.assertIn('"$ROOT/distro/assets/kinetix-wallpaper.png"', builder)
        self.assertIn("/usr/share/backgrounds/kinetixos/wallpaper.png", builder)
        self.assertIn(
            'KINETIX_WALLPAPER="${KINETIX_WALLPAPER:-/usr/share/backgrounds/kinetixos/wallpaper.png}"',
            session,
        )
        self.assertIn(
            '/usr/bin/swaybg -i "$KINETIX_WALLPAPER" -m fill',
            session,
        )
        self.assertNotIn("swaybg -c '#07080C'", session)

    def test_quickshell_layers_share_the_standalone_wallpaper_asset(self):
        desktop = (ROOT / "shell/desktop/KinetixDesktop.qml").read_text()
        # The splash's wallpaper lives in the composition half, which
        # BootSplash hosts; SplashContent is where the source is now read.
        splash = (ROOT / "shell/desktop/SplashContent.qml").read_text()
        builder = (DISTRO / "build-iso.sh").read_text()
        asset_env = 'Quickshell.env("KINETIX_WALLPAPER")'
        self.assertIn(asset_env, desktop)
        self.assertIn(asset_env, splash)
        self.assertNotIn("usr/share/kinetix/distro/assets/kinetix-wallpaper.png", builder)

    def test_iso_builder_copies_existing_shell_and_reference_without_reworking_bar(self):
        builder = (DISTRO / "build-iso.sh").read_text()
        self.assertIn('"$ROOT/shell"', builder)
        self.assertIn('"$ROOT/kinetixOS.png"', builder)
        self.assertIn(
            'cp -a "$ROOT/shell" "$PROFILE/airootfs/usr/share/kinetix/"',
            builder,
        )
        self.assertIn("/usr/share/kinetix/reference/kinetixOS.png", builder)

    def test_live_sddm_user_is_listable_by_the_greeter(self):
        sysusers = (PROFILE / "airootfs/etc/sysusers.d/kinetix-live.conf").read_text()
        sddm = (PROFILE / "airootfs/etc/sddm.conf.d/kinetix-live.conf").read_text()
        self.assertRegex(sysusers, r"(?m)^u kinetix 1000 ")
        self.assertIn("m kinetix video", sysusers)
        self.assertIn("m kinetix render", sysusers)
        self.assertIn("User=kinetix", sddm)
        self.assertRegex(sddm, r"(?m)^Session=kinetix\.desktop$")

    def test_sddm_primary_config_enables_live_autologin(self):
        sddm = (PROFILE / "airootfs/etc/sddm.conf").read_text()
        self.assertIn("[Autologin]", sddm)
        self.assertRegex(sddm, r"(?m)^User=kinetix$")
        self.assertRegex(sddm, r"(?m)^Session=kinetix\.desktop$")

    def test_live_autologin_pam_keeps_normal_account_checks(self):
        pam = (PROFILE / "airootfs/usr/share/kinetix/config/sddm-autologin.pam").read_text()
        hook = (PROFILE / "airootfs/etc/pacman.d/hooks/zzzz-kinetix-sddm-autologin.hook").read_text()
        self.assertRegex(pam, r"(?m)^account\s+include\s+system-local-login$")
        self.assertIn("session     include     system-local-login", pam)
        self.assertIn("Target = sddm", hook)
        self.assertIn("/etc/pam.d/sddm-autologin", hook)

    def test_cachy_keyring_is_initialized_before_the_live_desktop_starts(self):
        service = (PROFILE / "airootfs/usr/lib/systemd/system/kinetix-keyring.service").read_text()
        script_path = PROFILE / "airootfs/usr/bin/kinetix-keyring-init"
        script = script_path.read_text()
        builder = (DISTRO / "build-iso.sh").read_text()
        self.assertIn("Before=sddm.service", service)
        self.assertIn("kinetix-keyring-init", service)
        self.assertTrue(os.access(script_path, os.X_OK))
        self.assertIn("pacman-key --init", script)
        self.assertIn("pacman-key --populate archlinux cachyos", script)
        profiledef = (PROFILE / "profiledef.sh").read_text()
        self.assertIn('"/usr/bin/kinetix-keyring-init"]="0:0:755"', profiledef)
        self.assertIn("multi-user.target.wants/kinetix-keyring.service", builder)
        self.assertIn("kinetix-keyring-init", builder)

    def test_design_mockup_is_not_reused_as_live_wallpaper(self):
        builder = (DISTRO / "build-iso.sh").read_text()
        shell = (PROFILE / "airootfs/usr/bin/kinetix-shell").read_text()
        self.assertNotIn("/usr/share/backgrounds/kinetix/kinetixOS.png", builder)
        self.assertNotIn("kinetixOS.png", shell)
        self.assertIn("KINETIX_WALLPAPER:-/usr/share/backgrounds/kinetixos/wallpaper.png", shell)
        self.assertIn('swaybg -i "$KINETIX_WALLPAPER" -m fill', shell)

    def test_live_desktop_offers_install_button_and_archinstall_is_packaged(self):
        prompt = (ROOT / "shell/desktop/InstallPrompt.qml").read_text()
        shell = (ROOT / "shell/shell.qml").read_text()
        packages = (PROFILE / "packages.x86_64").read_text().split()
        script = (PROFILE / "airootfs/usr/bin/kinetix-install").read_text()
        self.assertIn("/run/archiso", prompt)
        self.assertIn("InstallerState.show()", prompt)
        self.assertIn("InstallPrompt {}", shell)
        self.assertIn("archinstall", packages)
        self.assertIn("sudo archinstall", script)

    def test_taskbar_has_blur_google_glow_and_animated_logo(self):
        taskbar = (ROOT / "shell/taskbar/Taskbar.qml").read_text()
        mark = (ROOT / "shell/components/KinetixMark.qml").read_text()
        glow = (ROOT / "shell/components/RgbFlow.qml").read_text()
        self.assertIn("BackgroundEffect.blurRegion: Region { item: rail }", taskbar)
        self.assertIn("RgbFlow {", taskbar)
        self.assertIn("edgeGlow.flash()", taskbar)
        self.assertIn("KinetixMark {", taskbar)
        self.assertIn("QtQuick.Shapes", mark)
        self.assertIn("property bool animated", mark)
        self.assertIn("function flash()", glow)
        self.assertIn("ShaderEffect {", glow)
        self.assertIn("FrameAnimation {", glow)
        mark_src = (ROOT / "shell/components/KinetixMark.qml").read_text()
        self.assertIn("property real glint", mark_src)
        self.assertIn("function engage()", mark_src)
        self.assertIn("innerOrbit", mark_src)

    def test_notification_system_is_wired_end_to_end(self):
        notif = (ROOT / "shell/common/Notif.qml").read_text()
        card = (ROOT / "shell/components/NotifCard.qml").read_text()
        toasts = (ROOT / "shell/overlay/Notifications.qml").read_text()
        center = (ROOT / "shell/overlay/NotificationCenter.qml").read_text()
        bar = (ROOT / "shell/bar/Bar.qml").read_text()
        shell = (ROOT / "shell/shell.qml").read_text()
        state = (ROOT / "shell/common/AgentState.qml").read_text()
        # tracking must stay on or notifications vanish the instant the handler returns
        self.assertIn("n.tracked = true", notif)
        self.assertIn("property ListModel items", notif)
        self.assertIn("property ListModel toasts", notif)
        for fn in ("function dismiss(", "function clearAll(", "function invoke(", "function toggleDnd(", "function demo("):
            self.assertIn(fn, notif)
        # toasts time out without dismissing; DND spares critical
        self.assertIn("function hideToast(", notif)
        self.assertIn("row.urgency === 2", notif)
        self.assertIn("onFinished: Notif.hideToast", card)
        self.assertIn("DragHandler", card)
        self.assertIn("NotifCard {", toasts)
        self.assertIn("NotifCard {", center)
        self.assertIn("AgentState.notifOpen", center)
        self.assertIn("Notif.toasts.clear()", toasts)
        self.assertIn("NotificationCenter {}", shell)
        for ipc in ("toggleNotifs", "notifDemo", "toggleDnd"):
            self.assertIn(ipc, shell)
        self.assertIn("AgentState.notifOpen = false", shell)   # closeAll
        self.assertIn("notifOpen", state)
        self.assertIn("id: notifBell", bar)
        self.assertIn("Notif.count", bar)

    def test_notification_polish_and_error_reporting_are_wired(self):
        notif = (ROOT / "shell/common/Notif.qml").read_text()
        card = (ROOT / "shell/components/NotifCard.qml").read_text()
        toasts = (ROOT / "shell/overlay/Notifications.qml").read_text()
        center = (ROOT / "shell/overlay/NotificationCenter.qml").read_text()
        watch = (ROOT / "shell/common/ErrorWatch.qml").read_text()
        shell = (ROOT / "shell/shell.qml").read_text()
        runner = (ROOT / "shell/common/TaskRunner.qml").read_text()
        # efficiency: capped history, coalesced bursts, clock only ticks while visible
        self.assertIn("readonly property int maxItems", notif)
        self.assertIn("coalesceMs", notif)
        self.assertIn("running: AgentState.notifOpen || root.toasts.count > 0", notif)
        # errors: crash/service events -> rows with Save log / Copy, saved through the script
        for needle in ("function reportError(", "function reportInternal(", "@save-log", "@copy-log",
                       "@open-dir", "kinetix-errors.py"):
            self.assertIn(needle, notif)
        self.assertIn("ErrorWatch.simulate", center)
        self.assertIn('"watch"', watch)
        self.assertIn("Notif.reportError", watch)
        self.assertIn("ErrorWatch.active", shell)             # instantiates the watcher
        self.assertIn("Notif.reportInternal", runner)         # shell-internal failure path
        # design: grouped + collapsible center, error styling, saved confirmation
        self.assertIn("section.property: \"appName\"", center)
        self.assertIn("Notif.toggleGroup", center)
        self.assertIn("Notif.openErrorDir", center)
        self.assertIn("isError", card)
        self.assertIn("Saved to", card)
        # toast stack must be a positioner (a ListView left stale positions -> overlapping cards)
        self.assertIn("Column {", toasts)
        self.assertNotIn("ListView {", toasts)
        self.assertIn("Notif.finalizeToast", toasts)

    def test_graphical_installer_is_wired_end_to_end(self):
        state = (ROOT / "shell/common/InstallerState.qml").read_text()
        ui = (ROOT / "shell/installer/Installer.qml").read_text()
        shell = (ROOT / "shell/shell.qml").read_text()
        prompt = (ROOT / "shell/desktop/InstallPrompt.qml").read_text()
        backend = (ROOT / "scripts/kinetix-installer.py").read_text()
        entry = (PROFILE / "airootfs/usr/share/applications/kinetix-install.desktop").read_text()
        self.assertIn("singleton InstallerState", (ROOT / "shell/common/qmldir").read_text())
        self.assertIn("Installer {}", shell)
        self.assertIn("openInstaller", shell)
        self.assertNotIn("tmpStep", shell)
        self.assertIn("InstallerState.show()", prompt)
        self.assertIn("openInstaller", entry)
        # password travels via env, never argv
        self.assertIn("KINETIX_SPEC", state)
        self.assertIn('"@env"', state)
        self.assertIn("--preserve-env=KINETIX_SPEC", state)
        self.assertIn('"SUDO_ASKPASS": "/usr/bin/ksshaskpass"', state)
        self.assertIn('["sudo", "-A", "--preserve-env=KINETIX_SPEC"', state)
        self.assertNotIn('["sudo", "-n"', state)
        self.assertIn("ksshaskpass", (DISTRO / "archiso/packages.x86_64").read_text())
        # destructive step needs explicit confirmation and never runs on in-use disks
        self.assertIn("eraseConfirmed", ui)
        self.assertIn("enabled: !modelData.inUse", ui)
        self.assertIn("/run/archiso", backend)
        self.assertIn("suggest_single_disk_layout", backend)
        self.assertIn("--silent", backend)

    def test_kinetix_install_wires_archinstall_to_the_kinetix_profile(self):
        # Round 18: "archinstall is on the ISO but doesn't install the
        # Kinetix desktop" (distro/README.md's own stated gap). Closed via
        # archinstall's real custom-profile extension point: a Profile
        # subclass loaded by profile_config.profile.path, registered as a
        # Desktop Environment choice (ProfileType.DesktopEnv) alongside the
        # built-in ones, selected via main="Desktop", details=["Kinetix"] —
        # exactly how "KDE Plasma" is selected. Verified live in this round
        # by installing the real archinstall 4.4 package (the version this
        # ISO ships, per `pacman -Si archinstall`) into an isolated venv and
        # running the actual kinetix-config.json through
        # archinstall.lib.args.ArchConfig.from_config(): hostname, kernels,
        # bootloader, and profile_config all resolved correctly, and Kinetix
        # appeared as profile_config.profile.current_selection[0] with its
        # real packages/services attached — not just a lint check on the
        # JSON shape. Disk partitioning/a full real install were not
        # exercised (too destructive/slow to script here) — that remains
        # genuinely unverified, same as every other QEMU-smoke-tested path
        # this README already flags as "not a substitute for real hardware
        # testing."
        install_script = (PROFILE / "airootfs/usr/bin/kinetix-install").read_text()
        profile_py = (
            PROFILE / "airootfs/usr/share/kinetix/archinstall/kinetix_profile.py"
        ).read_text()
        config = json.loads(
            (PROFILE / "airootfs/usr/share/kinetix/archinstall/kinetix-config.json").read_text()
        )
        builder = (DISTRO / "build-iso.sh").read_text()
        profiledef = (PROFILE / "profiledef.sh").read_text()
        desktop_entry = (
            PROFILE / "airootfs/usr/share/applications/kinetix-install.desktop"
        ).read_text()

        exec_lines = [
            line for line in install_script.splitlines()
            if line.strip().startswith("exec archinstall")
        ]
        self.assertEqual(len(exec_lines), 1)
        self.assertIn("--config", exec_lines[0])
        self.assertNotIn("--silent", exec_lines[0])  # disk confirmation stays interactive

        profile = config["profile_config"]["profile"]
        self.assertEqual(profile["main"], "Desktop")
        self.assertIn("Kinetix", profile["details"])
        self.assertEqual(profile["path"], "/usr/share/kinetix/archinstall/kinetix_profile.py")
        self.assertEqual(config["profile_config"]["greeter"], "sddm")
        self.assertIn("linux-cachyos-bore", config["kernels"])

        self.assertIn("ProfileType.DesktopEnv", profile_py)
        self.assertIn("class KinetixProfile", profile_py)
        self.assertIn("def post_install", profile_py)
        self.assertIn("def provision", profile_py)
        # The live-only shortcuts (autologin, NOPASSWD-root sudoers for the
        # passwordless live account) must never be carried onto a real
        # persistent install — check no copy_file() call actually sources
        # either one (the module's own comments name them to say why not,
        # so a bare substring check would false-positive on that prose).
        collapsed = " ".join(profile_py.split())
        self.assertNotIn('copy_file( "etc/sddm.conf', collapsed)
        self.assertNotIn('copy_file("etc/sudoers.d', collapsed)

        self.assertIn('"/usr/bin/kinetix-install"]="0:0:755"', profiledef)
        self.assertIn('"$PROFILE/airootfs/usr/bin/kinetix-install"', builder)
        text_entry = (PROFILE / "airootfs/usr/share/applications/kinetix-install-text.desktop").read_text()
        self.assertIn("Exec=kinetix-install", text_entry)

    def test_taskbar_tooltips_do_not_use_the_builtin_tooltip_under_layershell(self):
        # A QtQuick.Controls ToolTip attached to an item inside this
        # PanelWindow's own wlr-layer-shell surface positioned itself over
        # the button instead of above it, eating the click meant for the
        # button underneath (confirmed live: hovering the launcher button
        # to read its "Applications" tooltip made it unclickable). Fixed by
        # using the same pattern this file already uses successfully for
        # previewPop/menuPop: a real Quickshell PopupWindow, explicitly
        # anchored above the button via Edges.Top, which this repo's own
        # code already proves works correctly for this exact panel.
        taskbar = (ROOT / "shell/taskbar/Taskbar.qml").read_text()
        self.assertNotIn("ToolTip.visible", taskbar)
        self.assertNotIn("ToolTip.text", taskbar)
        self.assertIn('id: launcherTip', taskbar)
        self.assertIn('id: deskTip', taskbar)
        self.assertIn("anchor.item: launcherBtn", taskbar)
        self.assertIn("anchor.item: deskBtn", taskbar)
        self.assertIn("anchor.edges: Edges.Top", taskbar)

    def test_preview_close_tooltip_uses_its_own_quickshell_popup_window(self):
        preview = (ROOT / "shell/taskbar/TaskPreview.qml").read_text()
        taskbar = (ROOT / "shell/taskbar/Taskbar.qml").read_text()
        self.assertIn("property var popupWindow: null", preview)
        self.assertIn("anchor.window: root.popupWindow", preview)
        self.assertIn("popupWindow: previewPop", taskbar)
        self.assertNotIn("anchor.window: winClose.Window.window", preview)

    def test_source_checkout_wallpaper_has_a_packaged_asset_fallback(self):
        # BootSplash is the layer, SplashContent is the picture — the
        # fallback path is read by whichever one holds the Image.
        for name in ("KinetixDesktop.qml", "SplashContent.qml"):
            text = (ROOT / "shell/desktop" / name).read_text()
            self.assertIn('Quickshell.env("KINETIX_WALLPAPER")', text)
            self.assertIn('Quickshell.shellDir + "/../distro/assets/kinetix-wallpaper.png"', text)

    def test_global_pulse_is_rate_limited_below_display_refresh(self):
        theme = (ROOT / "shell/common/Theme.qml").read_text()
        self.assertIn("interval: 50", theme)
        self.assertNotIn("NumberAnimation on heartbeatPhase", theme)

    def test_taskbar_preview_maximize_is_real_not_a_dead_property_mutation(self):
        # Round 20: the preview card's ZOOM button set `tl.maximized =
        # !tl.maximized` — a plain-object property with no compositor-side
        # effect once TaskRunner replaced live Toplevel handles with
        # kinetix-tasks.py's JSON data (round 18), so it silently did
        # nothing. Confirmed live via KWin scripting on this host that
        # `w.setMaximize(true, true)` is a real, working *toggle* (not a
        # "set to state" call — calling it twice restores) and that
        # `w.maximizeMode` reports the real state. Wired a MAXIMIZE command
        # through the same daemon/TaskRunner/TaskStore verb chain as every
        # other window action, and the button now shows real state
        # (ZOOM/RESTORE) instead of a label that never actually changed.
        tasks_daemon = (ROOT / "scripts/kinetix-tasks.py").read_text()
        task_runner = (ROOT / "shell/common/TaskRunner.qml").read_text()
        task_store = (ROOT / "shell/taskbar/TaskStore.qml").read_text()
        task_preview = (ROOT / "shell/taskbar/TaskPreview.qml").read_text()
        self.assertIn("def toggle_maximize", tasks_daemon)
        self.assertIn("w.setMaximize(true, true)", tasks_daemon)
        self.assertIn('"maximized":', tasks_daemon)
        self.assertIn('cmd.startswith("MAXIMIZE ")', tasks_daemon)
        self.assertIn("function toggleMaximize", task_runner)
        self.assertIn("function toggleMaximize", task_store)
        self.assertIn("TaskStore.toggleMaximize(winCard.tl)", task_preview)
        self.assertNotIn("tl.maximized = !", task_preview)
        self.assertIn('"RESTORE" : "ZOOM"', task_preview)

    def test_taskbar_preview_thumbnail_is_honest_not_a_broken_capture_attempt(self):
        # Round 20: the preview card tried Quickshell's ScreencopyView with
        # TaskRunner's plain window data as captureSource — never a valid
        # Wayland Toplevel handle, so it silently never worked and the card
        # claimed "LIVE PREVIEW" while showing nothing live. Confirmed live
        # on this host that a real fix isn't available to this shell: KWin's
        # ScreenShot2 D-Bus interface (the one that could capture an
        # arbitrary background window) refused an unauthorized caller
        # ("The process is not authorized to take a screenshot"), and
        # Spectacle, which *is* authorized, can only capture the active
        # window or the one under the cursor — not an arbitrary background
        # preview target without stealing focus. Replaced with an honest
        # identity-card design instead of a broken live-capture attempt.
        task_preview = (ROOT / "shell/taskbar/TaskPreview.qml").read_text()
        self.assertNotIn("ScreencopyView {", task_preview)
        self.assertNotIn("captureSource:", task_preview)
        # No new rendering dependency: nothing else in this shell imports
        # Qt5Compat.GraphicalEffects, so the glow behind the icon is a
        # plain Gradient (already used throughout this file), not a real
        # RadialGradient from that module.
        self.assertNotIn("import Qt5Compat", task_preview)
        self.assertNotIn("RadialGradient {", task_preview)
        readme = (ROOT / "README.md").read_text()
        self.assertIn("Actual window thumbnails are not implemented yet.", readme)
        self.assertNotIn("rail on the left", readme)

    def test_taskbar_task_row_is_backed_by_a_real_listmodel(self):
        # Round 21: the task row's Repeater bound directly to
        # `taskbar.groups` — a plain JS array rebuilt from scratch (new
        # array, new object literals) on every TaskRunner push (every
        # window focus/minimize/maximize change) and every 1.2s tick.
        # Repeater can't diff a reassigned plain array by identity, so this
        # meant the entire task row — every tile, every in-flight hover/
        # press animation — was destroyed and recreated on essentially
        # every update. This shell already hit and fixed the identical
        # problem for the agent chat's message list (AgentState.qml's own
        # `messages` ListModel comment); same fix applied here, including
        # its `itemsJson`-not-a-plain-array-role workaround (confirmed
        # live: ListModel.setProperty silently drops an array-of-objects
        # role value back to undefined, even though append() accepts one —
        # same limitation AgentState.qml worked around with
        # `argsJson`/`detailJson`).
        taskbar = (ROOT / "shell/taskbar/Taskbar.qml").read_text()
        self.assertIn("ListModel { id: taskModel }", taskbar)
        self.assertIn("function syncTaskModel(groups)", taskbar)
        self.assertIn("onGroupsChanged: syncTaskModel(groups)", taskbar)
        self.assertIn("model: taskModel", taskbar)
        self.assertIn("itemsJson", taskbar)
        self.assertIn("JSON.parse(itemsJson)", taskbar)
        self.assertNotIn("model: taskbar.groups", taskbar)

    def test_taskbar_task_row_add_move_transitions_not_remove(self):
        # Round 21: Row/Column positioners don't support a `remove`
        # transition at all — confirmed live via quickshell's actual QML
        # engine (qmllint did not catch this): "Cannot assign to
        # non-existent property \"remove\"", a hard load failure that would
        # have taken the whole taskbar down. Unlike ListView/GridView, a
        # plain positioner has nowhere to keep a departed item visible
        # while it animates out. add/move are real and load cleanly.
        taskbar = (ROOT / "shell/taskbar/Taskbar.qml").read_text()
        self.assertIn("add: Transition {", taskbar)
        self.assertIn("move: Transition {", taskbar)
        self.assertNotIn("remove: Transition {", taskbar)


if __name__ == "__main__":
    unittest.main()
