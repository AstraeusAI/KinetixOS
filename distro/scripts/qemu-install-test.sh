#!/usr/bin/env bash
# QEMU install test: boots the newest ISO in distro/out against a blank
# virtual disk (UEFI, KVM, VNC on :1 = port 5901). Run the installer inside
# the VM, power off, then run `qemu-install-test.sh boot` to boot the result.
#   qemu-install-test.sh [install]   fresh disk + boot ISO
#   qemu-install-test.sh boot        boot the installed disk (no ISO)
#   qemu-install-test.sh clean       delete the test disk
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="${KINETIX_QEMU_DIR:-$HOME/.cache/kinetix-qemu}"
DISK="$WORK/install-test.qcow2"
VARS="$WORK/OVMF_VARS.fd"
CODE=/usr/share/edk2/x64/OVMF_CODE.4m.fd
VARS_SRC=/usr/share/edk2/x64/OVMF_VARS.4m.fd
ISO="$(ls -1t "$ROOT"/distro/out/*.iso | head -n1)"
mode="${1:-install}"
mkdir -p "$WORK"

case "$mode" in
    clean) rm -f "$DISK" "$VARS"; echo "removed $DISK"; exit 0 ;;
    install)
        rm -f "$DISK" "$VARS"
        qemu-img create -f qcow2 "$DISK" 40G
        cp "$VARS_SRC" "$VARS"
        cdrom=(-drive "file=$ISO,media=cdrom,if=none,id=iso,readonly=on" -device ide-cd,drive=iso,bootindex=1)
        ;;
    boot) cdrom=() ;;
    *) echo "usage: $0 [install|boot|clean]" >&2; exit 2 ;;
esac

echo "ISO: $ISO"
echo "VNC: localhost:5901"
exec qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 4096 \
    -machine q35 \
    -drive if=pflash,format=raw,readonly=on,file="$CODE" \
    -drive if=pflash,format=raw,file="$VARS" \
    -drive file="$DISK",if=none,id=hd,format=qcow2 -device virtio-blk-pci,drive=hd,bootindex=2 \
    "${cdrom[@]}" \
    -device virtio-vga -device qemu-xhci -device usb-tablet -device usb-kbd \
    -nic user,model=virtio-net-pci \
    -vnc 127.0.0.1:1
