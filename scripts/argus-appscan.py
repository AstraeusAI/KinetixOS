#!/usr/bin/env python3
"""
argus-appscan.py — High-speed installed application enumerator for Kinetix OS.
Scans all standard XDG application directories (including Flatpaks),
resolves freedesktop icon names to absolute paths using an icon index,
and outputs TSV lines: name \t exec \t icon \t comment \t categories \t desktop_file.
"""
import os
import sys
import json
import time
import glob
import re

APP_DIRS = [
    os.path.expanduser("~/.local/share/applications"),
    "/usr/local/share/applications",
    "/usr/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
]

# Include any extra directories from XDG_DATA_DIRS
if "XDG_DATA_DIRS" in os.environ and os.environ["XDG_DATA_DIRS"]:
    for p in os.environ["XDG_DATA_DIRS"].split(":"):
        p = p.strip()
        if p:
            app_p = os.path.join(p, "applications")
            if app_p not in APP_DIRS and os.path.isdir(app_p):
                APP_DIRS.append(app_p)

ICON_DIRS = [
    os.path.expanduser("~/.local/share/icons"),
    os.path.expanduser("~/.icons"),
    "/usr/share/icons/hicolor",
    "/usr/share/pixmaps",
    "/usr/share/icons/breeze",
    "/usr/share/icons/breeze-dark",
    "/usr/share/icons/Papirus",
    "/usr/share/icons/Papirus-Dark",
    "/usr/share/icons/Adwaita",
    "/var/lib/flatpak/exports/share/icons",
    os.path.expanduser("~/.local/share/flatpak/exports/share/icons"),
]

def load_icon_cache():
    cache_dir = os.path.expanduser("~/.cache/argus")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, "icon-index.json")

    icon_map = {}
    # Use cache if less than 6 hours old
    if os.path.exists(cache_file):
        try:
            if time.time() - os.path.getmtime(cache_file) < 21600:
                with open(cache_file, "r", encoding="utf-8") as f:
                    icon_map = json.load(f)
                    if icon_map:
                        return icon_map, cache_file
        except Exception:
            pass
    # Fallback to system pre-seeded cache if user cache is absent
    system_cache = "/usr/share/kinetix/icon-index.json"
    if not icon_map and os.path.isfile(system_cache):
        try:
            with open(system_cache, "r", encoding="utf-8") as f:
                icon_map = json.load(f)
                if icon_map:
                    try:
                        with open(cache_file, "w", encoding="utf-8") as out_f:
                            json.dump(icon_map, out_f)
                    except Exception:
                        pass
                    return icon_map, cache_file
        except Exception:
            pass

    # Build fresh icon map
    for d in ICON_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith((".png", ".svg", ".xpm")):
                    base = os.path.splitext(f)[0]
                    # Prefer scalable and high-resolution icons
                    is_scalable = "scalable" in root
                    is_hi_res = "256x256" in root or "128x128" in root
                    if base not in icon_map or is_scalable or is_hi_res:
                        icon_map[base] = os.path.join(root, f)

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(icon_map, f)
    except Exception:
        pass

    return icon_map, cache_file

def main():
    icon_map, cache_file = load_icon_cache()
    seen_desktop_ids = set()
    apps = []

    # Strip freedesktop field codes (%f, %u, %U, %F, %i, %c, %k, etc.)
    field_code_re = re.compile(r" *%[a-zA-Z]")

    for app_dir in APP_DIRS:
        if not os.path.isdir(app_dir):
            continue

        for root, _, files in os.walk(app_dir):
            for filename in files:
                if not filename.endswith(".desktop"):
                    continue

                desktop_id = filename
                if desktop_id in seen_desktop_ids:
                    continue

                full_path = os.path.join(root, filename)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fp:
                        content = fp.read()
                except Exception:
                    continue

                # Must be Type=Application and not NoDisplay=true
                if "Type=Application" not in content or "NoDisplay=true" in content:
                    continue

                name, exec_cmd, icon, comment, cats = "", "", "", "", ""
                in_entry = False

                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("[Desktop Entry]"):
                        in_entry = True
                        continue
                    elif line.startswith("[") and line.endswith("]"):
                        in_entry = False
                        continue

                    if not in_entry:
                        continue

                    if line.startswith("Name=") and not name:
                        name = line[5:].strip()
                    elif line.startswith("Exec=") and not exec_cmd:
                        raw_exec = line[5:].strip()
                        exec_cmd = field_code_re.sub("", raw_exec).strip()
                    elif line.startswith("Icon=") and not icon:
                        icon = line[5:].strip()
                    elif line.startswith("Comment=") and not comment:
                        comment = line[8:].strip()
                    elif line.startswith("Categories=") and not cats:
                        cats = line[11:].strip()

                if not name:
                    continue

                seen_desktop_ids.add(desktop_id)

                # Resolve icon
                ipath = ""
                if icon:
                    if os.path.isabs(icon) and os.path.isfile(icon):
                        ipath = icon
                    elif icon in icon_map:
                        ipath = icon_map[icon]
                    else:
                        # Fallback search in standard icon directories for newly added icons
                        for idir in [os.path.expanduser("~/.local/share/icons"), "/usr/share/pixmaps", "/usr/share/icons/hicolor/scalable/apps", "/usr/share/icons/hicolor/48x48/apps"]:
                            for ext in [".png", ".svg", ".xpm"]:
                                cand = os.path.join(idir, icon + ext)
                                if os.path.isfile(cand):
                                    ipath = cand
                                    icon_map[icon] = cand
                                    break
                            if ipath:
                                break

                apps.append((name, exec_cmd, ipath, comment, cats, full_path))

    # Sort alphabetically by name
    apps.sort(key=lambda a: a[0].lower())

    for app in apps:
        cols = [str(c).replace("\t", " ").replace("\n", " ") for c in app]
        sys.stdout.write("\t".join(cols) + "\n")

if __name__ == "__main__":
    main()
