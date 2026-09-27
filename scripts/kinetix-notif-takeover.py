#!/usr/bin/env python3
"""kinetix-notif-takeover.py — make the Kinetix shell the ONLY notification system on a Plasma host.

On a machine that still runs plasmashell (a dev box — the KinetixOS ISO never starts it),
plasmashell claims org.freedesktop.Notifications through its system-tray "Notifications"
applet, so whichever process starts first wins and Kinetix's notification center stays empty.
This removes that applet from Plasma's tray config so Plasma never claims the bus name and
the Kinetix shell (Quickshell NotificationServer) owns it every login.

  apply     stop plasmashell, drop the Notifications applet from the tray config (backup kept),
            start plasmashell again        [--no-restart: edit only, plasmashell must be stopped]
  restore   put the original tray config back and restart plasmashell
  status    show whether the applet is enabled and who owns the bus name right now

Reversible: the original config is saved once to <config>.kinetix-backup.
"""

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

CFG = Path.home() / ".config/plasma-org.kde.plasma.desktop-appletsrc"
BACKUP = CFG.with_name(CFG.name + ".kinetix-backup")
PLUGIN = "org.kde.plasma.notifications"
UNIT = "plasma-plasmashell.service"


def sh(*cmd, check=False):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def bus_owner():
    r = sh("busctl", "--user", "status", "org.freedesktop.Notifications")
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if line.startswith("Comm="):
            return line.split("=", 1)[1]
    return "unknown"


def applet_enabled(text):
    return f"plugin={PLUGIN}" in text


def strip_applet(text):
    """Remove the applet's own config section and its entry in the tray's enabled list."""
    out, skipping = [], False
    sections = re.split(r"(?m)^(?=\[)", text)
    for sec in sections:
        if re.search(rf"(?m)^plugin={re.escape(PLUGIN)}\s*$", sec):
            continue                       # drop the applet instance section entirely
        # only the ENABLED list changes. knownItems must keep the plugin: if it goes
        # missing there, plasmashell treats it as a brand-new default and re-enables it.
        sec = re.sub(r"(?m)^(extraItems=.*)$",
                     lambda m: ",".join(t for t in m.group(1).split(",") if t != PLUGIN),
                     sec)
        out.append(sec)
    return "".join(out)


def stop_plasma():
    sh("systemctl", "--user", "stop", UNIT)
    for _ in range(50):
        if sh("pgrep", "-x", "plasmashell").returncode != 0:
            return
        time.sleep(0.2)
    sh("pkill", "-x", "plasmashell")


def start_plasma():
    sh("systemctl", "--user", "start", UNIT)


def apply(restart=True):
    if not CFG.exists():
        print("no Plasma applet config found — nothing to change")
        return 0
    if restart:
        stop_plasma()
    elif sh("pgrep", "-x", "plasmashell").returncode == 0:
        print("plasmashell is running and would overwrite the edit; stop it or drop --no-restart", file=sys.stderr)
        return 1
    text = CFG.read_text()
    if not BACKUP.exists():
        shutil.copy2(CFG, BACKUP)
        print(f"backup saved: {BACKUP}")
    if applet_enabled(text) or PLUGIN in text:
        CFG.write_text(strip_applet(text))
        print("removed the Plasma Notifications applet from the tray")
    else:
        print("Plasma Notifications applet already disabled")
    if restart:
        start_plasma()
    return 0


def restore():
    if not BACKUP.exists():
        print("no backup found — nothing to restore")
        return 1
    stop_plasma()
    shutil.copy2(BACKUP, CFG)
    start_plasma()
    print("original Plasma tray config restored")
    return 0


def status():
    text = CFG.read_text() if CFG.exists() else ""
    print(f"Plasma Notifications applet: {'ENABLED (will claim the bus name)' if applet_enabled(text) else 'disabled'}")
    print(f"org.freedesktop.Notifications owner: {bus_owner() or 'nobody'}")
    print(f"backup present: {BACKUP.exists()}")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "apply":
        sys.exit(apply(restart="--no-restart" not in sys.argv))
    if cmd == "restore":
        sys.exit(restore())
    if cmd == "status":
        sys.exit(status())
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
