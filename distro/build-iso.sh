#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE_SOURCE="${ARCHISO_PROFILE_SOURCE:-/usr/share/archiso/configs/releng}"
OUTPUT_DIR="${KINETIX_OUT_DIR:-$ROOT/distro/out}"

if (( EUID != 0 )); then
    printf 'Build as root: sudo %s\n' "$0" >&2
    exit 1
fi
if ! command -v mkarchiso >/dev/null 2>&1; then
    printf 'Missing mkarchiso. Install the Arch Linux archiso package first.\n' >&2
    exit 1
fi
CACHY_KEY_ID="F3B607488DB35A47"
CACHY_KEY_FINGERPRINT="882DCFE48E2051D48E2562ABF3B607488DB35A47"
if ! pacman -Q cachyos-keyring >/dev/null 2>&1 || [[ ! -r /etc/pacman.d/cachyos-mirrorlist ]]; then
    printf 'Install the official CachyOS keyring and baseline mirrorlist on the build host.\n' >&2
    exit 1
fi
CACHY_KEY_INFO="$(pacman-key --finger "$CACHY_KEY_ID" 2>/dev/null || true)"
CACHY_KEY_INFO="${CACHY_KEY_INFO//[[:space:]]/}"
if [[ "$CACHY_KEY_INFO" != *"$CACHY_KEY_FINGERPRINT"* ]]; then
    printf 'CachyOS signing-key fingerprint is missing or unexpected. Refusing unsigned/untrusted kernel packages.\n' >&2
    exit 1
fi
if [[ ! -d "$PROFILE_SOURCE" || ! -f "$PROFILE_SOURCE/profiledef.sh" || ! -f "$PROFILE_SOURCE/packages.x86_64" ]]; then
    printf 'Archiso releng profile not found or incomplete: %s\n' "$PROFILE_SOURCE" >&2
    exit 1
fi
if [[ ! -f "$ROOT/kinetixOS.png" ]]; then
    printf 'Required KinetixOS design reference is missing: %s\n' "$ROOT/kinetixOS.png" >&2
    exit 1
fi
if [[ ! -f "$ROOT/distro/assets/kinetix-wallpaper.png" ]]; then
    printf 'Required standalone KinetixOS wallpaper is missing: %s\n' \
        "$ROOT/distro/assets/kinetix-wallpaper.png" >&2
    exit 1
fi

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/kinetixos-build.XXXXXX")"
cleanup() { rm -rf -- "$STAGE"; }
trap cleanup EXIT
PROFILE="$STAGE/profile"
WORK="$STAGE/work"
mkdir -p "$PROFILE" "$WORK" "$OUTPUT_DIR"
cp -a "$PROFILE_SOURCE/." "$PROFILE/"
install -m 0644 "$ROOT/distro/archiso/profiledef.sh" "$PROFILE/profiledef.sh"
# Build-time pacman.conf: the same file minus [kinetix]. That repo's mirrorlist
# only exists inside the image (/etc/pacman.d/kinetix-mirrorlist), so on the
# build host pacman cannot parse it, and nothing the ISO installs comes from
# it anyway. The image keeps the full file (config/pacman.conf below, put in
# place by the 99-kinetix-pacman-config hook).
awk '/^\[kinetix\]/{skip=1; next} /^\[/{skip=0} !skip' \
    "$ROOT/distro/archiso/pacman.conf" > "$PROFILE/pacman.conf"
chmod 0644 "$PROFILE/pacman.conf"
install -d "$PROFILE/efiboot/loader/entries" "$PROFILE/syslinux"
install -m 0644 "$ROOT/distro/archiso/efiboot/loader/loader.conf" \
    "$PROFILE/efiboot/loader/loader.conf"
install -m 0644 "$ROOT/distro/archiso/efiboot/loader/entries/01-kinetix-bore.conf" \
    "$PROFILE/efiboot/loader/entries/01-kinetix-bore.conf"
install -m 0644 "$ROOT/distro/archiso/efiboot/loader/entries/02-archiso-fallback.conf" \
    "$PROFILE/efiboot/loader/entries/02-archiso-fallback.conf"
install -m 0644 "$ROOT/distro/archiso/efiboot/loader/entries/03-kinetix-nvidia.conf" \
    "$PROFILE/efiboot/loader/entries/03-kinetix-nvidia.conf"
install -m 0644 "$ROOT/distro/archiso/syslinux/archiso_sys-linux.cfg" \
    "$PROFILE/syslinux/archiso_sys-linux.cfg"
install -m 0644 "$ROOT/distro/archiso/syslinux/archiso_sys.cfg" \
    "$PROFILE/syslinux/archiso_sys.cfg"

# Merge Kinetix additions into releng while preserving base order.
python3 "$ROOT/distro/scripts/merge-packages.py" \
    "$PROFILE/packages.x86_64" \
    "$ROOT/distro/archiso/packages.x86_64" \
    "$PROFILE/packages.x86_64"

cp -a "$ROOT/distro/archiso/airootfs/." "$PROFILE/airootfs/"
install -d "$PROFILE/airootfs/usr/share/kinetix/reference" \
    "$PROFILE/airootfs/usr/share/kinetix/config" \
    "$PROFILE/airootfs/usr/share/backgrounds/kinetixos"
cp -a "$ROOT/shell" "$PROFILE/airootfs/usr/share/kinetix/"
cp -a "$ROOT/runtime" "$PROFILE/airootfs/usr/share/kinetix/"
cp -a "$ROOT/scripts" "$PROFILE/airootfs/usr/share/kinetix/"
# The kinetix command set (kinetix update/check/...), its systemd units and the
# migrations dir, plus the version file. Same files the package ships, present
# in the live root so the live session can update itself before any package is
# installed on a target.
cp -a "$ROOT/distro/payload/." "$PROFILE/airootfs/"
install -m 0644 "$ROOT/distro/version" \
    "$PROFILE/airootfs/usr/share/kinetix/version"
install -Dm644 "$ROOT/distro/repo/kinetix-mirrorlist" \
    "$PROFILE/airootfs/etc/pacman.d/kinetix-mirrorlist"
# The KinetixOS signing public key, so the [kinetix] repo in pacman.conf can be
# verified on the live session. Absent until setup-signing.sh has run once; the
# build notes that rather than failing, since a live image without it still
# works, it just cannot pull from the repo yet.
if [[ -s "$ROOT/distro/package/kinetix-keyring/kinetix.gpg" ]]; then
    for kf in kinetix.gpg kinetix-trusted kinetix-revoked; do
        install -Dm644 "$ROOT/distro/package/kinetix-keyring/$kf" \
            "$PROFILE/airootfs/usr/share/pacman/keyrings/$kf"
    done
else
    printf 'Note: no KinetixOS signing key yet; run distro/setup-signing.sh to\n' >&2
    printf '      make the [kinetix] repo usable. Building the ISO without it.\n' >&2
fi
install -m 0644 "$ROOT/kinetixOS.png" "$PROFILE/airootfs/usr/share/kinetix/reference/kinetixOS.png"
install -m 0644 "$ROOT/distro/assets/kinetix-wallpaper.png" \
    "$PROFILE/airootfs/usr/share/backgrounds/kinetixos/wallpaper.png"
install -m 0644 "$ROOT/distro/archiso/pacman.conf" \
    "$PROFILE/airootfs/usr/share/kinetix/config/pacman.conf"
chmod 0755 \
    "$PROFILE/airootfs/usr/bin/kinetix-session" \
    "$PROFILE/airootfs/usr/bin/kinetix-shell" \
    "$PROFILE/airootfs/usr/bin/kinetix-keyring-init" \
    "$PROFILE/airootfs/usr/bin/kinetix-install" \
    "$PROFILE/airootfs/usr/bin/kinetix-live-password"
# The update command set (kinetix update/check/...), added with the packaging
# work. Globbed rather than listed: it is exactly "the kinetix-* helpers the
# payload ships", and a new helper should not need a second edit here.
chmod 0755 "$PROFILE"/airootfs/usr/bin/kinetix "$PROFILE"/airootfs/usr/bin/kinetix-*
find "$PROFILE/airootfs/usr/share/kinetix/migrations" -type f -name '*.sh' \
    -exec chmod 0755 {} + 2>/dev/null || true
chmod 0440 "$PROFILE/airootfs/etc/sudoers.d/kinetix-live"

# Start Kinetix's own Wayland session by default in the live environment.
SYSTEMD="$PROFILE/airootfs/etc/systemd/system"
mkdir -p "$SYSTEMD/graphical.target.wants" "$SYSTEMD/multi-user.target.wants" \
    "$SYSTEMD/timers.target.wants"
ln -sfn /usr/lib/systemd/system/graphical.target "$SYSTEMD/default.target"
ln -sfn /usr/lib/systemd/system/sddm.service "$SYSTEMD/display-manager.service"
ln -sfn /usr/lib/systemd/system/sddm.service "$SYSTEMD/graphical.target.wants/sddm.service"
ln -sfn /usr/lib/systemd/system/NetworkManager.service "$SYSTEMD/multi-user.target.wants/NetworkManager.service"
ln -sfn /usr/lib/systemd/system/kinetix-keyring.service "$SYSTEMD/multi-user.target.wants/kinetix-keyring.service"
ln -sfn /usr/lib/systemd/system/kinetix-live-password.service "$SYSTEMD/multi-user.target.wants/kinetix-live-password.service"
# Performance/stability daemons (round 14): proactive OOM handling under
# memory pressure, IRQ spreading across cores, and auto-nice for
# background/interactive process priority. zram itself needs no enable
# step — zram-generator.conf is read by a systemd generator at boot.
ln -sfn /usr/lib/systemd/system/systemd-oomd.service "$SYSTEMD/multi-user.target.wants/systemd-oomd.service"
ln -sfn /usr/lib/systemd/system/irqbalance.service "$SYSTEMD/multi-user.target.wants/irqbalance.service"
ln -sfn /usr/lib/systemd/system/ananicy-cpp.service "$SYSTEMD/multi-user.target.wants/ananicy-cpp.service"
ln -sfn /usr/lib/systemd/system/power-profiles-daemon.service "$SYSTEMD/multi-user.target.wants/power-profiles-daemon.service"
# Periodic TRIM rather than a per-write discard mount option: batches the
# discard cost into one weekly pass instead of paying it inline on every
# delete, and matters most once this base is used by an installed system
# rather than the ephemeral live root.
ln -sfn /usr/lib/systemd/system/fstrim.timer "$SYSTEMD/timers.target.wants/fstrim.timer"
# The releng console autologin and SDDM must not compete for tty1; tty2 stays
# available as a text recovery console if the graphical session fails.
ln -sfn /dev/null "$SYSTEMD/getty@tty1.service"

export KINETIX_VERSION="${KINETIX_VERSION:-$(date -u +%Y.%m.%d)}"
mkarchiso -v -w "$WORK" -o "$OUTPUT_DIR" "$PROFILE"
printf 'KinetixOS live image created under %s\n' "$OUTPUT_DIR"
