#!/usr/bin/env python3
"""kinetix-installer.py — backend for the graphical KinetixOS installer.

  kinetix-installer.py disks            list installable disks (JSON)
  kinetix-installer.py regions          timezones + keyboard layouts (JSON)
  kinetix-installer.py install SPEC     run the install; newline-delimited JSON events on stdout
  kinetix-installer.py install SPEC --dry-run   build + validate config, touch nothing

SPEC is a JSON file (or `@env` to read it from $KINETIX_SPEC, keeping the password out of argv): {disk, hostname, fullname, username, password, timezone, keyboard}.
The disk layout comes from archinstall's own single-disk layout code (ESP + ext4 root, wiped),
the base config from kinetix-config.json, so partitioning stays archinstall's tested path.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_CONFIG = Path(os.environ.get(
    "KINETIX_BASE_CONFIG", "/usr/share/kinetix/archinstall/kinetix-config.json"))
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
RESERVED = {"root", "daemon", "bin", "sys", "nobody", "kinetix"}


def emit(**event):
    print(json.dumps(event), flush=True)


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def list_disks():
    r = _run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,MODEL,TYPE,RM,TRAN,RO,MOUNTPOINTS,FSTYPE,LABEL"])
    tree = json.loads(r.stdout or "{}").get("blockdevices", [])
    disks = []
    for d in tree:
        if d.get("type") != "disk" or d.get("ro"):
            continue
        if d["name"].startswith(("zram", "loop", "sr", "ram")):
            continue

        def mounts(node):
            out = [m for m in (node.get("mountpoints") or []) if m]
            for c in node.get("children") or []:
                out += mounts(c)
            return out

        active = mounts(d)
        # The live medium (mounted at /run/archiso/bootmnt) must never be offered.
        if any(m.startswith("/run/archiso") for m in active):
            continue
        parts = [
            {"path": c["path"], "size": int(c.get("size") or 0),
             "fstype": c.get("fstype") or "", "label": c.get("label") or ""}
            for c in d.get("children") or []
        ]
        disks.append({
            "path": d["path"],
            "size": int(d.get("size") or 0),
            "model": (d.get("model") or "").strip() or "Unknown disk",
            "removable": bool(d.get("rm")),
            "transport": d.get("tran") or "",
            "partitions": parts,
            "inUse": bool(active),
        })
    return disks


def list_regions():
    tz = _run(["timedatectl", "list-timezones"]).stdout.split()
    km = _run(["localectl", "list-keymaps"]).stdout.split()
    return {"timezones": tz or ["UTC"], "keymaps": km or ["us"]}


def validate(spec, disks=None):
    errors = {}
    user = spec.get("username", "")
    if not USERNAME_RE.match(user) or user in RESERVED:
        errors["username"] = "Lowercase letters, digits, - and _ only; must start with a letter."
    if not HOSTNAME_RE.match(spec.get("hostname", "")):
        errors["hostname"] = "Letters, digits and - only."
    pw = spec.get("password", "")
    if len(pw) < 8:
        errors["password"] = "Use at least 8 characters."
    if disks is not None and spec.get("disk") not in {d["path"] for d in disks}:
        errors["disk"] = "Selected disk is not available."
    return errors


def hash_password(password):
    r = subprocess.run(["openssl", "passwd", "-6", "-stdin"], input=password,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0 or not r.stdout.startswith("$6$"):
        raise RuntimeError("could not hash password")
    return r.stdout.strip()


async def _disk_layout(disk_path):
    from archinstall.lib.disk.device_handler import device_handler
    from archinstall.lib.disk.disk_menu import suggest_single_disk_layout
    from archinstall.lib.models.device import DiskLayoutConfiguration, DiskLayoutType, FilesystemType

    device = device_handler.get_device(Path(disk_path))
    if device is None:
        raise RuntimeError(f"archinstall cannot see {disk_path}")
    mod = await suggest_single_disk_layout(device, FilesystemType.EXT4, separate_home=False)
    return DiskLayoutConfiguration(config_type=DiskLayoutType.Default, device_modifications=[mod]).json()


def build_config(spec):
    cfg = json.loads(BASE_CONFIG.read_text())
    cfg["hostname"] = spec["hostname"]
    cfg["timezone"] = spec.get("timezone", "UTC")
    cfg["locale_config"] = {
        "kb_layout": spec.get("keyboard", "us"),
        "sys_lang": "en_US.UTF-8",
        "sys_enc": "UTF-8",
    }
    cfg["disk_config"] = asyncio.run(_disk_layout(spec["disk"]))
    cfg["silent"] = True
    creds = {
        "users": [{
            "username": spec["username"],
            "enc_password": hash_password(spec["password"]),
            "sudo": True,
            "groups": [],
        }]
    }
    return cfg, creds


# (substring of archinstall output, percent, label) — coarse: archinstall reports no numeric progress.
STAGES = [
    ("Partitioning", 5, "Partitioning disk"),
    ("Formatting", 10, "Formatting"),
    ("pacstrap", 20, "Installing base system"),
    ("Installing packages", 35, "Installing packages"),
    ("linux-cachyos", 45, "Installing kernel"),
    ("Configuring", 70, "Configuring system"),
    ("bootloader", 80, "Installing bootloader"),
    ("Adding user", 85, "Creating your account"),
    ("post_install", 92, "Installing Kinetix desktop"),
    ("provision", 96, "Finishing up"),
]


def simulate():
    import time
    for pct, label in [(5, "Partitioning disk"), (20, "Installing base system"),
                       (45, "Installing kernel"), (70, "Configuring system"),
                       (85, "Creating your account"), (96, "Finishing up")]:
        emit(type="stage", percent=pct, label=label)
        emit(type="log", line=f"[simulated] {label}")
        time.sleep(0.6)
    emit(type="stage", percent=100, label="Installation complete")
    emit(type="done", dryRun=True)
    return 0


def install(spec_path, dry_run, sim=False):
    if sim:
        return simulate()
    spec = json.loads(os.environ["KINETIX_SPEC"] if spec_path == "@env" else Path(spec_path).read_text())
    disks = list_disks()
    errors = validate(spec, disks)
    if errors:
        emit(type="error", message="Invalid installer settings", errors=errors)
        return 2
    emit(type="stage", percent=2, label="Preparing installation")
    try:
        cfg, creds = build_config(spec)
    except Exception as exc:
        emit(type="error", message=f"Could not prepare install: {exc}")
        return 3
    if dry_run:
        redacted = {**creds, "users": [{**u, "enc_password": "<hash>"} for u in creds["users"]]}
        emit(type="dry-run", config=cfg, creds=redacted)
        emit(type="done", dryRun=True)
        return 0

    with tempfile.TemporaryDirectory(prefix="kinetix-install-") as tmp:
        cfg_path, creds_path = Path(tmp) / "config.json", Path(tmp) / "creds.json"
        cfg_path.write_text(json.dumps(cfg))
        creds_path.write_text(json.dumps(creds))
        creds_path.chmod(0o600)
        proc = subprocess.Popen(
            ["archinstall", "--config", str(cfg_path), "--creds", str(creds_path), "--silent"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        percent = 2
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            emit(type="log", line=line)
            for needle, pct, label in STAGES:
                if needle.lower() in line.lower() and pct > percent:
                    percent = pct
                    emit(type="stage", percent=pct, label=label)
        code = proc.wait()
    if code != 0:
        emit(type="error", message=f"archinstall exited with status {code}")
        return code
    emit(type="stage", percent=100, label="Installation complete")
    emit(type="done", dryRun=False)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("disks")
    sub.add_parser("regions")
    ins = sub.add_parser("install")
    ins.add_argument("spec")
    ins.add_argument("--dry-run", action="store_true")
    ins.add_argument("--simulate", action="store_true", help="fake progress, for UI testing")
    a = ap.parse_args()
    if a.cmd == "disks":
        print(json.dumps(list_disks()))
    elif a.cmd == "regions":
        print(json.dumps(list_regions()))
    else:
        sys.exit(install(a.spec, a.dry_run, a.simulate))


if __name__ == "__main__":
    main()
