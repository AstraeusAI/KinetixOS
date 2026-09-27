# KinetixOS distribution build

This directory begins the Arch-based distribution build. The first artifact is a KinetixOS live-session bring-up image: it boots KWin as the Wayland compositor and launches the repository's existing Quickshell tree as the desktop shell. The shell tree is copied as-is, including the main Kinetix bar, agent surfaces, and App Center; the distro work must not redesign `shell/bar/Bar.qml` or replace its capsules and behavior.

`kinetixOS.png` is packaged at `/usr/share/kinetix/reference/kinetixOS.png` as the composition guide, not used literally as wallpaper. The ISO uses a separately rendered landscape wallpaper inspired by its eclipse, mountain, city, water and crimson palette, with no mockup UI baked in. Quickshell layers the Kinetix wordmark/greeting around the existing main bar, plus a full-width, bottom-docked taskbar (`shell/taskbar/`) with an application-launcher button and live KWin window management (activate, minimize, close, hover previews, a right-click window menu) — a conventional flush rectangular bar reserving its own screen space, the Windows/Cinnamon/KDE shape, not a floating overlay. A short animated KinetixOS splash appears at session startup. Desktop widgets are not shown by default; the optional widget framework is enabled only with `KINETIX_ENABLE_WIDGETS=1`. Ghostty is the only default terminal: `xdg-terminal-exec` is pinned to Ghostty, `TERMINAL=ghostty`, and the bar's quick terminal is Ghostty. The mockup remains a guide and does not supersede or restyle the main bar.

## Build

On an Arch-based build host, install `archiso`, then run:

```sh
sudo ./distro/build-iso.sh
```

The script starts from the host's packaged `/usr/share/archiso/configs/releng` profile, overlays the Kinetix session and packages, and writes the ISO under `distro/out/` by default. Set `ARCHISO_PROFILE_SOURCE`, `KINETIX_OUT_DIR`, or `KINETIX_VERSION` to override the corresponding defaults.

## Updates

`kinetix update` is the supported way to keep a system current. It takes a rollback snapshot, runs one `pacman -Syu` over Arch, CachyOS and Kinetix's own repo, then runs any pending Kinetix migrations. `kinetix check` reports what is waiting (and is what the bar's update badge runs). Running `pacman -Syu` by hand skips the snapshot and the migrations, which is why the command exists.

There are two layers. OS packages come from Arch and CachyOS as before. Kinetix's *own* payload — the shell, the agent runtime, the `scripts/`, the desktop config and the `kinetix` command — is a real pacman package (`kinetix`, plus `kinetix-keyring`) published to a signed repository. Packaging is what makes updates possible at all: package ownership lets pacman replace those files cleanly, which the installer's loose copies cannot do. A system installed from an earlier ISO adopts them into the package on its first `kinetix update`.

### Publishing (the maintainer side)

**Every commit on `stable` is published automatically.** `.github/workflows/publish.yml` builds the `kinetix` and `kinetix-keyring` packages from the pushed commit, runs the distro tests, signs the packages with the KinetixOS key and publishes them to the signed repo. Installed systems pick the update up through `kinetix update` / the bar's update badge. Day-to-day work lands on `master`; ship it with:

```sh
git push origin master:stable
```

Each build is versioned `<distro/version>.r<commit count>.g<sha>` (e.g. `0.1.0.r58.g1a2b3c4`), which pacman orders by commit; bump `distro/version` for a named release and it outranks all of them. The job needs three repository secrets: `KINETIX_SIGNING_KEY` (the armored private key), `KINETIX_SIGNING_PASSPHRASE`, and `KINETIX_PKGS_DEPLOY_KEY` (the private half of a write deploy key on `kinetix-pkgs`).

Publishing by hand still works, for a machine that holds the key:

One-time, on the machine that publishes:

```sh
./distro/setup-signing.sh     # creates the signing key, writes the keyring files
```

Back up the private key it prints instructions for. Then, for every release:

```sh
./distro/publish.sh           # stage, build, sign, repo-add, push to GitHub Pages
./distro/publish.sh --local   # same, but stop before pushing
```

`publish.sh` reads `distro/version` (rewriting the PKGBUILDs' `pkgver` from it), stages the payload tree, builds both packages with `makepkg`, signs them, builds the `kinetix.db` repo database with `repo-add`, signs the database, and pushes the `x86_64/` directory to the `kinetix-pkgs` repository, which GitHub Pages serves. The repository coordinates and the resulting mirror URL both come from `distro/repo.conf`; a test asserts the mirrorlist matches it. A user needs none of this — for them it is `kinetix update`.

### Bootstrapping on the ISO

The ISO bakes in the `[kinetix]` stanza, the mirrorlist and the signing public key, and `kinetix-keyring-init` populates the key before the desktop starts, so the repo verifies on the live session and on a fresh install. The installer writes the same repo config onto the target and enables the default-deny firewall; the payload is still copied loose as well, so an install works before any package has been published. `archinstall`'s install remains the same interactive flow.

## Current scope and explicit gaps

This remains a live-desktop bring-up image, not an installable KinetixOS release. The live ISO boots `linux-cachyos-bore` by default in both BIOS and UEFI, with Arch's generic `linux` entry retained as a fallback. The CachyOS signing key is fingerprint-pinned by the builder; the live keyring is populated before SDDM starts. The temporary UID-1000 live account belongs to `wheel`, `video`, and `render`, and uses SDDM autologin. Before SDDM starts, a tty1 setup step requires the user to choose a live-session administrator password; no credential is embedded in the ISO. `sudoers.d/kinetix-live` requires authentication for every privileged command, and the graphical installer uses `ksshaskpass` to obtain that credential. The password hash lives only in the ephemeral live root and must be set again after reboot. These live-only settings must not be copied verbatim onto an installed system. The round-16 security review also flagged the missing default firewall and `pacman.conf`'s `LocalFileSigLevel = Optional` (Arch's own upstream default) as open items not yet acted on. In VMs, KWin runs its normal direct-DRM session with software rendering forced on, the same as bare metal (round 18 — see `kinetix-session`); this needs no X server or cross-user X access grant. The package source is the baseline `cachyos` x86_64 repo only—never `cachyos-v3`/`v4`—so older x86_64 CPUs are not excluded. That baseline kernel can lag the optimized repo, so releases must track its updates explicitly.

NVIDIA now has a boot path, but not automatic selection. `linux-cachyos-bore-nvidia-open` is an exact-version match for the BORE kernel and targets Turing-or-newer GPUs; it also pulls a large `nvidia-utils` userspace package, so the ISO installs it unconditionally (the same way it already carries the vanilla `linux` fallback kernel alongside BORE) but never boots it by default or auto-detects it — whoever knows they have matching hardware picks "KinetixOS live (BORE, NVIDIA open, UEFI)" / `arch-nvidia` at the boot menu explicitly (`efiboot/loader/entries/03-kinetix-nvidia.conf`, `archiso_sys-linux.cfg`'s `arch-nvidia` label). This closes the "no NVIDIA boot path exists" gap without penalizing AMD/Intel-only systems with a driver package they'd never load; it does not close the larger gap below. Older GPUs need a maintained legacy branch where available or the Nouveau fallback; some end-of-life GPUs no longer have a maintained proprietary driver. AMD uses the included AMDGPU/Mesa stack. Automatic hardware detection, driver selection, and a tested support matrix still belong in the installer and are still outstanding — the boot menu choice above is a manual stopgap, not that system. See the [NVIDIA open-module compatibility list](https://github.com/NVIDIA/open-gpu-kernel-modules#compatible-gpus) and [ArchWiki driver matrix](https://wiki.archlinux.org/title/NVIDIA) when implementing selection.

## Performance, stability, and gaming tuning

Applies to every CPU/GPU vendor the ISO targets — nothing here is
hardware-specific except where noted:

- **Memory**: `zram-generator` (config: `airootfs/etc/systemd/zram-generator.conf`)
  compresses cold pages into RAM instead of leaving them resident or
  swapping to disk, sized to installed RAM (`min(ram/2, 8192)` MB) so it
  scales from small to large machines without needing per-machine tuning.
  `vm.swappiness=100` (`airootfs/etc/sysctl.d/99-kinetix-performance.conf`)
  is deliberately paired with zram — swapping to it early is nearly free
  and keeps more real memory available, the opposite of the classic
  low-swappiness advice tuned for slow disk swap. `vm.page-cluster=0` disables
  swap readahead on zram to avoid decompressing unneeded adjacent pages on swap-in.
  `vm.watermark_boost_factor=0` prevents kswapd memory thrashing and premature
  page cache drop under memory fragmentation. Transparent hugepages use
  deferred background defragmentation (`defer+madvise` via `etc/tmpfiles.d/thp.conf`)
  to prevent foreground allocation freezes. `systemd-oomd` is enabled for
  proactive, PSI-based OOM handling instead of waiting on the kernel's reactive OOM killer.
- **I/O**: a udev rule (`airootfs/etc/udev/rules.d/60-kinetix-ioscheduler.rules`)
  assigns `none` to NVMe, `mq-deadline` to non-rotational SATA/SAS and eMMC, and
  `bfq` to rotational disks — matched to what each device class actually
  benefits from rather than one scheduler for everything. Fast flash devices
  disable random entropy feed overhead (`add_random=0`) with generous queue depth.
  Live SquashFS loop devices use 2MB read-ahead (`read_ahead_kb=2048`) matching the
  1MB compressed block size to prevent split-request I/O stalls during app and library
  loading from boot media. SATA Active Link Power Management is set to `max_performance`
  to eliminate 50-200ms link wakeup latency stalls. Dirty-writeback thresholds are
  fixed-byte, not percentage-of-RAM, with writeback wakeup paced to 15s (`vm.dirty_writeback_centisecs=1500`)
  for smooth streaming writes without periodic stalls.
- **Scheduling/background load**: `ananicy-cpp` with `cachyos-ananicy-rules`
  auto-renices known background/bloat processes down and interactive processes
  (compositor, shell, audio, games) up without per-app manual tuning; `irqbalance`
  spreads interrupt load across cores; `power-profiles-daemon` gives an easy
  performance/balanced/power-saver toggle instead of hardcoding one governor for every machine.
  Systemd timeout limits (`00-timeout.conf`) cap shutdown wait to 10s to eliminate
  90s reboot hangs.
- **Gaming**: `gamemode` + `lib32-gamemode`, `mangohud` + `lib32-mangohud`,
  and `gamescope` are all opt-in at the point of use (gamemode only acts
  when a game requests it; mangohud only draws when launched with it;
  gamescope is a compositor you choose to run under) — near-zero idle
  cost when not gaming. `vm.max_map_count` is raised well past the kernel
  default because several game engines and Proton/Wine need more mapped
  regions than that default allows. `kernel.split_lock_mitigate=0` trades
  a narrow Intel security mitigation for eliminating a documented
  stutter class in specific games/emulators that hit split-lock traps —
  a no-op on AMD, disclosed here rather than silently applied.

The ISO includes Arch's `archinstall`, wired to a real Kinetix profile (round 18): `kinetix-install` (also in the app launcher as "Install KinetixOS") runs `archinstall --config` pre-seeded with `usr/share/kinetix/archinstall/kinetix-config.json`, which registers `kinetix_profile.py`'s `KinetixProfile` as a Desktop Environment choice the same way built-in ones like KDE Plasma are — selectable, not silent-installed; disk selection, partitioning confirmation, locale, timezone, and user creation all stay fully interactive, matching archinstall's own safety model. `post_install`/`provision` copy the live ISO's `shell/`/`runtime/`/`scripts/` and session files onto the target and add the installed user(s) to `video`/`render`, but deliberately do **not** carry over the live-only autologin/`sddm.conf.d/kinetix-live.conf` or the passwordless account's NOPASSWD sudoers rule — an installed system logs in normally with a real password. Verified in this round by running the real `archinstall` 4.4 package (the version this ISO ships) against `kinetix-config.json` through its actual `ArchConfig.from_config()` in an isolated venv — profile resolution, packages, services, kernels, and bootloader config all parsed correctly — but an actual disk partitioning + install was not exercised end-to-end (too destructive to script safely here); that remains genuinely unverified, on top of everything else this section already flags as QEMU-smoke-tested only. The ISO itself is not release-signed, and QEMU smoke tests do not replace physical-hardware testing. Do not publish this as a finished installer.

Build prerequisites are `archiso`, the trusted `cachyos-keyring`, and the baseline `cachyos-mirrorlist`; the build script checks the CachyOS signing-key fingerprint before allowing the kernel package. `qemu-system-x86` and `edk2-ovmf` are used for VM smoke tests. The development host has these installed. The live session runs KWin directly via its DRM/KMS backend on both hardware and VMs (software rendering is forced on when a VM is detected, since emulated adapters typically expose KMS without 3D acceleration); it does not launch Plasma Shell. GTK's general portal backend is used for portal requests; KWin-specific capture currently uses the existing runtime adapter.
