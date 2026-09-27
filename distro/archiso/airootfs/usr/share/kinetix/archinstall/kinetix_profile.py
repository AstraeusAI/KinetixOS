"""kinetix_profile.py — archinstall custom profile for the Kinetix desktop.

Loaded by archinstall via profile_config.profile.path (see kinetix-config.json
in this same directory). Registers "Kinetix" as a Desktop Environment choice
alongside the built-in ones (KDE Plasma, GNOME, ...), selected the same way:
profile_config.profile = {"main": "Desktop", "details": ["Kinetix"]}.

The umbrella DesktopProfile (archinstall's own default_profiles/desktop.py)
drives the actual install: it calls add_additional_packages(profile.packages),
enable_service(profile.services), profile.install(), then later
profile.post_install() and profile.provision() once the base system exists.
post_install/provision here replicate, onto the freshly installed target,
what distro/build-iso.sh bakes into the live ISO's airootfs — minus the
live-session-only shortcuts (autologin and its boot-time password setup)
that must never end up on a real persistent install.

This copies from the LIVE session's own filesystem (this script is executed
by an archinstall process running inside the live ISO), not from anything
bundled separately — /usr/share/kinetix/{shell,runtime,scripts} etc. are the
exact same files the live session itself runs.
"""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, override

from archinstall.default_profiles.profile import DisplayServerType, GreeterType, Profile, ProfileType

if TYPE_CHECKING:
    from archinstall.lib.installer import Installer
    from archinstall.lib.models.users import User

LIVE_ROOT = Path("/")

# Same additions list as distro/archiso/packages.x86_64, minus the kernel
# packages (those go through archinstall's own "kernels" config key, which
# wires up mkinitcpio/bootloader entries correctly) and minus sddm/xorg-server
# (archinstall's own greeter installation, driven by default_greeter_type
# below, already pulls those in for whichever greeter is chosen).
PACKAGES = [
    "cachyos-keyring",
    "cachyos-mirrorlist",
    "kwin",
    "quickshell",
    "qt6-wayland",
    "qt6-tools",
    "ghostty",
    "xdg-terminal-exec",
    "swaybg",
    "pipewire",
    "pipewire-pulse",
    "wireplumber",
    "xdg-desktop-portal",
    "xdg-desktop-portal-gtk",
    "mesa",
    "vulkan-radeon",
    "vulkan-intel",
    "flatpak",
    "iptables",
    "gnu-free-fonts",
    "qt6-multimedia-ffmpeg",
    "pipewire-jack",
    "tesseract-data-eng",
    "inter-font",
    "ttf-jetbrains-mono",
    "ydotool",
    "wl-clipboard",
    "at-spi2-core",
    "spectacle",
    "zram-generator",
    "irqbalance",
    "ananicy-cpp",
    "cachyos-ananicy-rules",
    "power-profiles-daemon",
    "gamemode",
    "lib32-gamemode",
    "mangohud",
    "lib32-mangohud",
    "gamescope",
]

# Config-driven or one-shot-install daemons: no systemd unit to flip on.
SERVICES = [
    "irqbalance.service",
    "ananicy-cpp.service",
    "power-profiles-daemon.service",
    "systemd-oomd.service",
    "fstrim.timer",
]


class KinetixProfile(Profile):
    def __init__(self) -> None:
        super().__init__(
            "Kinetix",
            ProfileType.DesktopEnv,
            support_gfx_driver=True,
            support_greeter=True,
            display_server=DisplayServerType.Wayland,
        )

    @property
    @override
    def packages(self) -> list[str]:
        return PACKAGES

    @property
    @override
    def services(self) -> list[str]:
        return SERVICES

    @property
    @override
    def default_greeter_type(self) -> GreeterType | None:
        return GreeterType.Sddm

    @override
    def post_install(self, install_session: "Installer") -> None:
        target = install_session.target

        def copy_tree(src: str, dst: str) -> None:
            source = LIVE_ROOT / src
            if source.is_dir():
                shutil.copytree(source, target / dst, dirs_exist_ok=True)

        def copy_file(src: str, dst: str, mode: int | None = None) -> None:
            source = LIVE_ROOT / src
            if not source.is_file():
                return
            dest = target / dst
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            if mode is not None:
                dest.chmod(mode)

        # The desktop itself: shell config, agent runtime, backend scripts —
        # identical to what the live ISO ships, at the identical paths, so
        # Quickshell.shellDir-relative lookups (../runtime, ../scripts)
        # resolve the same way on an installed system as on the live one.
        copy_tree("usr/share/kinetix/shell", "usr/share/kinetix/shell")
        copy_tree("usr/share/kinetix/runtime", "usr/share/kinetix/runtime")
        copy_tree("usr/share/kinetix/scripts", "usr/share/kinetix/scripts")

        copy_file("usr/bin/kinetix-session", "usr/bin/kinetix-session", 0o755)
        copy_file("usr/bin/kinetix-shell", "usr/bin/kinetix-shell", 0o755)
        copy_file(
            "usr/share/wayland-sessions/kinetix.desktop",
            "usr/share/wayland-sessions/kinetix.desktop",
        )
        copy_file(
            "usr/share/backgrounds/kinetixos/wallpaper.png",
            "usr/share/backgrounds/kinetixos/wallpaper.png",
        )

        # Performance tuning (round 14 on the live ISO) — plain config, no
        # live-only assumptions, worth carrying onto a persistent install.
        copy_file(
            "etc/systemd/zram-generator.conf",
            "etc/systemd/zram-generator.conf",
        )
        copy_file(
            "etc/sysctl.d/99-kinetix-performance.conf",
            "etc/sysctl.d/99-kinetix-performance.conf",
        )
        copy_file(
            "etc/udev/rules.d/60-kinetix-ioscheduler.rules",
            "etc/udev/rules.d/60-kinetix-ioscheduler.rules",
        )
        copy_file(
            "etc/tmpfiles.d/thp.conf",
            "etc/tmpfiles.d/thp.conf",
        )
        copy_file(
            "etc/systemd/system.conf.d/00-timeout.conf",
            "etc/systemd/system.conf.d/00-timeout.conf",
        )
        copy_file(
            "etc/systemd/system.conf.d/10-limits.conf",
            "etc/systemd/system.conf.d/10-limits.conf",
        )
        copy_file(
            "etc/systemd/user.conf.d/00-timeout.conf",
            "etc/systemd/user.conf.d/00-timeout.conf",
        )
        copy_file(
            "etc/systemd/user.conf.d/10-limits.conf",
            "etc/systemd/user.conf.d/10-limits.conf",
        )

        # Deliberately NOT copied: sddm.conf.d/kinetix-live.conf (autologin +
        # the live account it assumes), sudoers.d/kinetix-live, and the
        # live password setup service. These remain live-session-only and are documented in distro/README.md
        # — an installed system logs in normally through SDDM with a real
        # password, using the account(s) archinstall itself creates.

        # Keep the CachyOS repo reachable after install (pacstrap resolves
        # packages via the live session's own already-configured pacman, so
        # linux-cachyos-bore installs fine now regardless, but the target's
        # own /etc/pacman.conf needs this too or `pacman -Syu` breaks on
        # first boot). Append rather than overwrite: preserves whatever
        # mirror_config the guided install already wrote.
        pacman_conf = target / "etc/pacman.conf"
        if pacman_conf.is_file() and "[cachyos]" not in pacman_conf.read_text():
            with pacman_conf.open("a") as f:
                f.write("\n[cachyos]\nInclude = /etc/pacman.d/cachyos-mirrorlist\n")
        copy_file("etc/pacman.d/cachyos-mirrorlist", "etc/pacman.d/cachyos-mirrorlist")

        # KinetixOS's own signed repo, so `kinetix update` can replace the
        # desktop files the loose copies below install. The files are copied
        # as loose, unowned files here so the install works offline and before
        # a repo exists at all; the first `kinetix update` adopts them into the
        # `kinetix` package (see kinetix-update's adopt step) and they are
        # package-managed from then on.
        copy_file("etc/pacman.d/kinetix-mirrorlist", "etc/pacman.d/kinetix-mirrorlist")
        if pacman_conf.is_file() and "[kinetix]" not in pacman_conf.read_text():
            with pacman_conf.open("a") as f:
                f.write(
                    "\n[kinetix]\nSigLevel = Required DatabaseOptional\n"
                    "Include = /etc/pacman.d/kinetix-mirrorlist\n"
                )
        # The public signing key, so the repo above can be verified. Absent if
        # the ISO was built before setup-signing.sh ran; `copy_file` no-ops.
        for keyring in ("kinetix.gpg", "kinetix-trusted", "kinetix-revoked"):
            copy_file(
                f"usr/share/pacman/keyrings/{keyring}",
                f"usr/share/pacman/keyrings/{keyring}",
            )

    @override
    def provision(self, install_session: "Installer", users: list["User"]) -> None:
        # KWin's DRM backend and ydotool/AT-SPI computer-use both need real
        # hardware device access — the same groups the live ISO's `kinetix`
        # account gets (distro/README.md), now for whoever was actually
        # created during the guided install.
        for user in users:
            install_session.arch_chroot(f"usermod -a -G video,render {user.username}")

        # Populate the KinetixOS signing key so the [kinetix] repo verifies,
        # and turn on the default-deny firewall. Both are best-effort: a build
        # made before the key existed, or a target without ufw, must not fail
        # the install over it — `kinetix firewall enable` and `pacman-key
        # --populate kinetix` remain available to run later.
        #
        # Each is wrapped in `sh -c` rather than passed bare because
        # arch_chroot hands the string to arch-chroot unparsed, so compound
        # shell (if/fi, ||) needs its own shell to run in.
        install_session.arch_chroot(
            "sh -c 'pacman-key --populate kinetix >/dev/null 2>&1 || true'"
        )
        install_session.arch_chroot(
            "sh -c 'command -v ufw >/dev/null 2>&1 || exit 0; "
            "ufw default deny incoming; ufw default allow outgoing; "
            "ufw allow 53317/tcp; ufw allow 53317/udp; "
            "ufw --force enable' >/dev/null 2>&1 || true"
        )
