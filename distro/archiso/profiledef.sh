#!/usr/bin/env bash
# Archiso profile metadata for the KinetixOS live-session bring-up image.
# Build from a pinned Archiso releng profile via ../build-iso.sh.

_epoch="${SOURCE_DATE_EPOCH:-$(date +%s)}"
iso_name="kinetixos"
iso_label="KINETIX_$(date -u --date="@${_epoch}" +%Y%m)"
iso_publisher="KinetixOS"
iso_application="KinetixOS Wayland desktop live image"
iso_version="${KINETIX_VERSION:-$(date -u --date="@${_epoch}" +%Y.%m.%d)}"
install_dir="kinetix"
arch="x86_64"
buildmodes=('iso')
bootmodes=('bios.syslinux' 'uefi.systemd-boot')
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
# zstd, not xz: this squashfs is decompressed on every single file access for
# the entire live session (every icon load, every shared library, every git
# operation), not just once at boot — xz's slow decompression throughput is
# therefore a standing runtime I/O bottleneck for the whole session, not a
# one-time cost. zstd decompresses roughly an order of magnitude faster than
# xz at comparable settings, and its decompression speed barely changes with
# the compression LEVEL used at build time — level 19 buys a strong ratio
# with zero runtime penalty for it, unlike xz where cranking the ratio also
# slows decompression. Trades a somewhat larger ISO for a snappier session,
# which is the right side of that tradeoff for a live/desktop image.
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '19' '-b' '1M')

file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/root/.gnupg"]="0:0:700"
  ["/etc/sudoers.d/kinetix-live"]="0:0:440"
  ["/usr/bin/kinetix-session"]="0:0:755"
  ["/usr/bin/kinetix-shell"]="0:0:755"
  ["/usr/bin/kinetix-keyring-init"]="0:0:755"
  ["/usr/bin/kinetix-install"]="0:0:755"
)
