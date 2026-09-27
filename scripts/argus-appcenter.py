#!/usr/bin/env python3
"""
argus-appcenter.py — Backend engine for Kinetix OS App Center.
Provides unified search across Arch Linux official repos, AUR (Arch User Repository),
and Flathub (Flatpak), plus package manager status, 1-click install/uninstall orchestration,
and system-wide update checking.
"""

import sys
import os
import json
import re
import shlex
import shutil
import subprocess
import urllib.request
import urllib.parse
import concurrent.futures
import time

CACHE_DIR = os.path.expanduser("~/.cache/argus")
os.makedirs(CACHE_DIR, exist_ok=True)
STATUS_CACHE_FILE = os.path.join(CACHE_DIR, "appcenter_status.json")
INSTALLED_CACHE_FILE = os.path.join(CACHE_DIR, "appcenter_installed.json")
SEARCH_CACHE_FILE = os.path.join(CACHE_DIR, "appcenter_search_cache.json")

def _read_installed_cache():
    if os.path.exists(INSTALLED_CACHE_FILE):
        try:
            with open(INSTALLED_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if time.time() - data.get("timestamp", 0) < 45:
                    return data
        except Exception:
            pass
    return None

def _write_installed_cache(pacman=None, flatpak=None):
    current = {}
    if os.path.exists(INSTALLED_CACHE_FILE):
        try:
            with open(INSTALLED_CACHE_FILE, "r", encoding="utf-8") as f:
                current = json.load(f)
        except Exception:
            current = {}
    if pacman is not None:
        current["pacman"] = list(pacman)
    if flatpak is not None:
        current["flatpak"] = list(flatpak)
    current["timestamp"] = time.time()
    try:
        with open(INSTALLED_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f)
    except Exception:
        pass

def get_installed_pacman_packages(force=False):
    """Return set of all packages installed via pacman/paru with 45s TTL caching."""
    if not force:
        cached = _read_installed_cache()
        if cached and "pacman" in cached:
            return set(cached["pacman"])
    try:
        out = subprocess.check_output(["pacman", "-Qq"], text=True, stderr=subprocess.DEVNULL)
        pkgs = set(line.strip() for line in out.splitlines() if line.strip())
        _write_installed_cache(pacman=pkgs)
        return pkgs
    except Exception:
        return set()

def get_installed_flatpaks(force=False):
    """Return set of all app IDs installed via flatpak with 45s TTL caching."""
    if not shutil.which("flatpak"):
        return set()
    if not force:
        cached = _read_installed_cache()
        if cached and "flatpak" in cached:
            return set(cached["flatpak"])
    try:
        out = subprocess.check_output(
            ["flatpak", "list", "--app", "--columns=application"],
            text=True, stderr=subprocess.DEVNULL
        )
        fps = set(line.strip() for line in out.splitlines() if line.strip())
        _write_installed_cache(flatpak=fps)
        return fps
    except Exception:
        return set()

def get_cached_search(query, source_filter):
    key = f"{source_filter}:{query.lower().strip()}"
    if os.path.exists(SEARCH_CACHE_FILE):
        try:
            with open(SEARCH_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                entry = data.get(key)
                if entry and time.time() - entry.get("timestamp", 0) < 180:
                    return entry.get("results")
        except Exception:
            pass
    return None

def save_cached_search(query, source_filter, results):
    key = f"{source_filter}:{query.lower().strip()}"
    data = {}
    if os.path.exists(SEARCH_CACHE_FILE):
        try:
            with open(SEARCH_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    if len(data) > 60:
        oldest = sorted(data.keys(), key=lambda k: data[k].get("timestamp", 0))[:25]
        for k in oldest:
            data.pop(k, None)
    data[key] = {"results": results, "timestamp": time.time()}
    try:
        with open(SEARCH_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass

def invalidate_caches():
    """Clear transient caches on install/uninstall actions."""
    for path in [STATUS_CACHE_FILE, INSTALLED_CACHE_FILE, SEARCH_CACHE_FILE]:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

def get_package_managers():
    """Detect available package managers and their statuses."""
    paru_inst = shutil.which("paru") is not None
    yay_inst = shutil.which("yay") is not None
    flatpak_inst = shutil.which("flatpak") is not None
    snap_inst = shutil.which("snap") is not None
    pacman_inst = shutil.which("pacman") is not None
    gearlever_inst = shutil.which("gearlever") is not None or shutil.which("appimagelauncher") is not None

    managers = {
        "pacman": {
            "name": "Pacman (ALPM)",
            "installed": pacman_inst,
            "desc": "Official Arch Linux package manager for core, extra, and system binaries."
        },
        "aur": {
            "name": "AUR Community",
            "installed": paru_inst or yay_inst,
            "helper": "paru" if paru_inst else ("yay" if yay_inst else None),
            "desc": "Access to 90,000+ community packages in the Arch User Repository."
        },
        "paru": {
            "name": "Paru (AUR Helper)",
            "installed": paru_inst,
            "desc": "Blazing fast Rust-based AUR helper with pacman ALPM integration and rich syntax."
        },
        "yay": {
            "name": "Yay (AUR Helper)",
            "installed": yay_inst,
            "desc": "Popular Go-based AUR helper with interactive search and minimal dependencies."
        },
        "flatpak": {
            "name": "Flatpak & Flathub",
            "installed": flatpak_inst,
            "flathub": False,
            "desc": "Sandboxed desktop applications from Flathub with complete dependency isolation."
        },
        "snap": {
            "name": "Snapd",
            "installed": snap_inst,
            "desc": "Canonical universal snap packages with strict AppArmor containment."
        },
        "appimage": {
            "name": "AppImage Support",
            "installed": gearlever_inst or shutil.which("appimage-builder") is not None,
            "desc": "Portable standalone Linux desktop applications and runtimes."
        }
    }

    if managers["flatpak"]["installed"]:
        try:
            remotes = subprocess.check_output(
                ["flatpak", "remotes"], text=True, stderr=subprocess.DEVNULL
            )
            managers["flatpak"]["flathub"] = "flathub" in remotes.lower()
        except Exception:
            pass

    return managers

def check_updates(force=False):
    """Fetch pending updates concurrently from checkupdates, paru/yay, and flatpak with 90s caching."""
    if not force and os.path.exists(STATUS_CACHE_FILE):
        try:
            with open(STATUS_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if time.time() - data.get("timestamp", 0) < 90:
                    return data
        except Exception:
            pass

    updates = []
    seen = set()

    def _check_arch():
        arch_upd = []
        if shutil.which("checkupdates"):
            try:
                res = subprocess.run(
                    ["checkupdates"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, timeout=8
                )
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 4 and parts[2] == "->":
                        arch_upd.append({
                            "name": parts[0],
                            "current": parts[1],
                            "new": parts[3],
                            "source": "arch"
                        })
            except Exception:
                pass
        return arch_upd

    def _check_aur():
        aur_upd = []
        aur_helper = "paru" if shutil.which("paru") else ("yay" if shutil.which("yay") else None)
        if aur_helper:
            try:
                res = subprocess.run(
                    [aur_helper, "-Qua"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, timeout=8
                )
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 4 and parts[2] == "->":
                        aur_upd.append({
                            "name": parts[0],
                            "current": parts[1],
                            "new": parts[3],
                            "source": "aur"
                        })
            except Exception:
                pass
        return aur_upd

    def _check_flatpak():
        flatpak_upd = []
        if shutil.which("flatpak"):
            try:
                res = subprocess.run(
                    ["flatpak", "remote-ls", "--updates", "--columns=name,application,version"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5
                )
                for line in res.stdout.splitlines():
                    parts = [p.strip() for p in line.split("\t") if p.strip()]
                    if len(parts) >= 2:
                        flatpak_upd.append({
                            "name": parts[0],
                            "app_id": parts[1],
                            "current": "installed",
                            "new": parts[2] if len(parts) > 2 else "latest",
                            "source": "flatpak"
                        })
            except Exception:
                pass
        return flatpak_upd

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f_arch = pool.submit(_check_arch)
        f_aur = pool.submit(_check_aur)
        f_flatpak = pool.submit(_check_flatpak)

        for item in f_arch.result():
            if item["name"] not in seen:
                seen.add(item["name"])
                updates.append(item)

        for item in f_aur.result():
            if item["name"] not in seen:
                seen.add(item["name"])
                updates.append(item)

        for item in f_flatpak.result():
            updates.append(item)

    payload = {
        "updates": updates,
        "count": len(updates),
        "timestamp": time.time()
    }
    try:
        with open(STATUS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass

    return payload

def search_aur(query, installed_set):
    """Query the official AUR RPC v5."""
    results = []
    try:
        url = f"https://aur.archlinux.org/rpc/v5/search/{urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "ArgusOS/1.0 (AppCenter)"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            raw = data.get("results", [])
            # Sort by exact name match first, then by Popularity
            q_lower = query.lower()
            raw.sort(
                key=lambda x: (
                    x.get("Name", "").lower() == q_lower,
                    q_lower in x.get("Name", "").lower(),
                    x.get("Popularity", 0)
                ),
                reverse=True
            )
            for item in raw[:20]:
                pkg_name = item.get("Name", "")
                results.append({
                    "id": pkg_name,
                    "name": pkg_name,
                    "title": pkg_name,
                    "version": item.get("Version", ""),
                    "description": item.get("Description") or "No description provided.",
                    "source": "aur",
                    "installed": pkg_name in installed_set,
                    "popularity": round(float(item.get("Popularity", 0)), 1),
                    "votes": item.get("NumVotes", 0),
                    "maintainer": item.get("Maintainer") or "orphan"
                })
    except Exception:
        pass
    return results

def search_pacman(query, installed_set):
    """Search official Arch/CachyOS local database via pacman -Ss."""
    results = []
    try:
        res = subprocess.run(
            ["pacman", "-Ss", query],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=3
        )
        lines = res.stdout.splitlines()
        i = 0
        while i < len(lines):
            header = lines[i].strip()
            desc = lines[i+1].strip() if i + 1 < len(lines) else ""
            i += 2
            if not header:
                continue
            parts = header.split(maxsplit=2)
            if len(parts) < 2:
                continue
            repo_pkg = parts[0]
            version = parts[1]
            repo, pkg_name = repo_pkg.split("/", 1) if "/" in repo_pkg else ("arch", repo_pkg)
            results.append({
                "id": pkg_name,
                "name": pkg_name,
                "title": pkg_name,
                "version": version,
                "description": desc,
                "source": "arch",
                "repo": repo,
                "installed": pkg_name in installed_set,
                "popularity": 10.0 if pkg_name == query else 5.0
            })
            if len(results) >= 15:
                break
    except Exception:
        pass
    return results

def search_flathub(query, installed_flatpaks):
    """Query Flathub v2 search API."""
    results = []
    try:
        url = "https://flathub.org/api/v2/search"
        payload = json.dumps({"query": query}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "ArgusOS/1.0 (AppCenter)"}
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            hits = data.get("hits", [])
            for h in hits[:15]:
                app_id = h.get("app_id") or ""
                results.append({
                    "id": app_id,
                    "name": app_id,
                    "title": h.get("name") or app_id,
                    "version": "latest",
                    "description": h.get("summary") or (h.get("description") or "Flathub application.")[:140],
                    "source": "flatpak",
                    "installed": app_id in installed_flatpaks,
                    "icon": h.get("icon") or "",
                    "popularity": 8.0
                })
    except Exception:
        pass
    return results

def get_featured(installed_set, installed_flatpaks):
    """Curated list of premium Linux desktop applications."""
    apps = [
        # Development
        {
            "id": "cursor-bin", "name": "cursor-bin", "title": "Cursor AI",
            "category": "Development", "source": "aur",
            "description": "AI-powered code editor built on VS Code with agentic coding capabilities.",
            "version": "latest", "icon": "cursor"
        },
        {
            "id": "visual-studio-code-bin", "name": "visual-studio-code-bin", "title": "VS Code",
            "category": "Development", "source": "aur",
            "description": "Code editing redefined. Powerful developer environment by Microsoft.",
            "version": "official", "icon": "code"
        },
        {
            "id": "zed", "name": "zed", "title": "Zed Editor",
            "category": "Development", "source": "arch",
            "description": "High-performance, multiplayer code editor written in Rust.",
            "version": "latest", "icon": "zed"
        },
        {
            "id": "postman-bin", "name": "postman-bin", "title": "Postman",
            "category": "Development", "source": "aur",
            "description": "Comprehensive API platform for building, testing, and debugging APIs.",
            "version": "latest", "icon": "postman"
        },

        # Communication
        {
            "id": "vesktop-bin", "name": "vesktop-bin", "title": "Vesktop (Discord)",
            "category": "Communication", "source": "aur",
            "description": "Custom Discord client with Vencord pre-installed, screen audio & smooth Wayland support.",
            "version": "latest", "icon": "discord"
        },
        {
            "id": "telegram-desktop", "name": "telegram-desktop", "title": "Telegram",
            "category": "Communication", "source": "arch",
            "description": "Fast, secure cloud-based mobile and desktop messaging app.",
            "version": "latest", "icon": "telegram"
        },
        {
            "id": "slack-desktop", "name": "slack-desktop", "title": "Slack",
            "category": "Communication", "source": "aur",
            "description": "Productivity platform connecting teams and workspaces.",
            "version": "latest", "icon": "slack"
        },

        # Media & Creativity
        {
            "id": "spotify", "name": "spotify", "title": "Spotify",
            "category": "Media", "source": "aur",
            "description": "Digital music and podcast streaming service.",
            "version": "latest", "icon": "spotify"
        },
        {
            "id": "blender", "name": "blender", "title": "Blender 3D",
            "category": "Media", "source": "arch",
            "description": "Open source 3D creation suite: modeling, rigging, animation, and rendering.",
            "version": "latest", "icon": "blender"
        },
        {
            "id": "obs-studio", "name": "obs-studio", "title": "OBS Studio",
            "category": "Media", "source": "arch",
            "description": "Free and open source software for video recording and live streaming.",
            "version": "latest", "icon": "obs"
        },
        {
            "id": "vlc", "name": "vlc", "title": "VLC Media Player",
            "category": "Media", "source": "arch",
            "description": "Universal multimedia player that plays most codecs and DVD/audio formats.",
            "version": "latest", "icon": "vlc"
        },

        # Productivity & Browsers
        {
            "id": "obsidian", "name": "obsidian", "title": "Obsidian",
            "category": "Productivity", "source": "arch",
            "description": "Extensible knowledge base and second brain built on local plain text Markdown.",
            "version": "latest", "icon": "obsidian"
        },
        {
            "id": "brave-bin", "name": "brave-bin", "title": "Brave Browser",
            "category": "Browsers", "source": "aur",
            "description": "Privacy-focused browser with built-in ad blocker and Web3 integration.",
            "version": "latest", "icon": "brave"
        },
        {
            "id": "zen-browser-bin", "name": "zen-browser-bin", "title": "Zen Browser",
            "category": "Browsers", "source": "aur",
            "description": "Beautiful, distraction-free Firefox-based browser with vertical tabs.",
            "version": "latest", "icon": "zen"
        },

        # Gaming & System
        {
            "id": "steam", "name": "steam", "title": "Steam",
            "category": "Gaming", "source": "arch",
            "description": "The ultimate gaming platform with Proton Windows-compatibility layer.",
            "version": "latest", "icon": "steam"
        },
        {
            "id": "heroic-games-launcher-bin", "name": "heroic-games-launcher-bin", "title": "Heroic Games",
            "category": "Gaming", "source": "aur",
            "description": "Native GUI launcher for Epic Games, GOG, and Amazon Games on Linux.",
            "version": "latest", "icon": "heroic"
        },
        {
            "id": "btop", "name": "btop", "title": "btop++",
            "category": "System", "source": "arch",
            "description": "Resource monitor that shows usage and stats for processor, memory, disks, and network.",
            "version": "latest", "icon": "btop"
        }
    ]

    for a in apps:
        if a["source"] == "flatpak":
            a["installed"] = a["id"] in installed_flatpaks
        else:
            a["installed"] = a["id"] in installed_set
    return apps

PARU_BOOTSTRAP = (
    "echo '1. Installing compilation dependencies...' && "
    "sudo pacman -S --needed --noconfirm base-devel git && "
    "echo '2. Cloning paru-bin repository from AUR...' && "
    "rm -rf /tmp/paru-bin && "
    "git clone https://aur.archlinux.org/paru-bin.git /tmp/paru-bin && "
    "echo '3. Building and installing paru package...' && "
    "(cd /tmp/paru-bin && makepkg -si --noconfirm)"
)
FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"
# Per-user Flathub remote: installs need no root and no polkit agent.
FLATHUB_SETUP = (
    "{ which flatpak >/dev/null 2>&1 || sudo pacman -S --needed --noconfirm flatpak; } && "
    f"flatpak remote-add --user --if-not-exists flathub {FLATHUB_URL}"
)


# Arch package names and Flatpak app IDs only ever use these characters;
# anything else is refused before it can reach a shell command line.
PKG_ID_RE = re.compile(r"^[A-Za-z0-9@._+-]{1,255}$")


def repo_helper():
    """Tool for official-repo packages: an AUR helper if present, else pacman."""
    return "paru" if shutil.which("paru") else ("yay" if shutil.which("yay") else "sudo pacman")


def aur_helper():
    return "paru" if shutil.which("paru") else ("yay" if shutil.which("yay") else None)


def _terminal_argv(title, script):
    """argv for the first available terminal. Each one runs in the foreground
    (no single-instance handoff) so the caller can wait for the job to end."""
    candidates = []
    env_term = os.environ.get("TERMINAL", "").strip()
    if env_term:
        candidates.append(os.path.basename(env_term.split()[0]))
    candidates += ["ghostty", "konsole", "kitty", "alacritty", "foot", "wezterm", "xterm"]
    for term in candidates:
        path = shutil.which(term)
        if not path:
            continue
        if term == "ghostty":
            return [path, "--gtk-single-instance=false", f"--title={title}", "-e", "bash", "-c", script]
        if term == "konsole":
            return [path, "--separate", "--hide-menubar", "-p", f"tabtitle={title}", "-e", "bash", "-c", script]
        if term == "kitty":
            return [path, "--title", title, "bash", "-c", script]
        if term == "alacritty":
            return [path, "--title", title, "-e", "bash", "-c", script]
        if term == "foot":
            return [path, "--title", title, "bash", "-c", script]
        if term == "wezterm":
            return [path, "start", "--always-new-process", "--", "bash", "-c", script]
        return [path, "-T", title, "-e", "bash", "-c", script]
    return None


def launch_in_terminal(title, cmd):
    """Run a package job in a terminal and wait for it to finish.

    A failed step keeps the window open with the exit code instead of the
    window vanishing mid-error. Returns the job's exit code (127 when no
    terminal exists)."""
    script = (
        f"{cmd}\nrc=$?\n"
        "if [ $rc -ne 0 ]; then echo; echo \"✗ Failed (exit $rc). Nothing else was changed.\"; "
        "read -r -p 'Press Enter to close.' _; fi\nexit $rc"
    )
    argv = _terminal_argv(title, script)
    if not argv:
        subprocess.Popen([
            "notify-send", "-a", "Kinetix App Center", "No terminal found",
            "Install ghostty, konsole, kitty, alacritty or foot to run package jobs.",
        ])
        return 127
    # Own session: a shell reload that kills this process must never take a
    # running pacman transaction down with it.
    proc = subprocess.Popen(argv, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.wait()

def execute_install(source, pkg_id):
    """Run the install in a terminal; returns its exit code."""
    q = shlex.quote(pkg_id)
    done = f"echo '' && echo 'Successfully installed {pkg_id}! Press Enter to close.' && read -r _"
    if source == "flatpak":
        cmd = (
            f"echo '=== Installing {pkg_id} via Flathub ===' && {FLATHUB_SETUP} && "
            f"flatpak install --user -y flathub {q} && {done}"
        )
    elif source == "aur":
        helper = aur_helper()
        if helper:
            cmd = f"echo '=== Installing {pkg_id} from the AUR via {helper} ===' && {helper} -S --noconfirm {q} && {done}"
        else:
            # pacman cannot build AUR packages; bootstrap paru first.
            cmd = (
                "echo '=== No AUR helper yet: installing paru first ===' && "
                f"{PARU_BOOTSTRAP} && echo '=== Installing {pkg_id} ===' && "
                f"paru -S --noconfirm {q} && {done}"
            )
    else:
        helper = repo_helper()
        cmd = f"echo '=== Installing {pkg_id} via {helper} ===' && {helper} -S --noconfirm {q} && {done}"

    return launch_in_terminal(f"Kinetix App Center — Installing {pkg_id}", cmd)

def execute_uninstall(source, pkg_id):
    """Launch terminal runner to uninstall package."""
    if source == "flatpak":
        cmd = f"flatpak uninstall -y {shlex.quote(pkg_id)} && echo 'Uninstalled {pkg_id}. Press Enter to close.' && read -r _"
    else:
        cmd = f"sudo pacman -R --noconfirm {shlex.quote(pkg_id)} && echo 'Uninstalled {pkg_id}. Press Enter to close.' && read -r _"

    return launch_in_terminal(f"Kinetix App Center — Removing {pkg_id}", cmd)

def execute_enable_manager(manager):
    """Enable / install package manager with 1-click terminal orchestration."""
    helper = repo_helper()
    rc = 0

    if manager == "flatpak":
        cmd = (
            "echo '===================================================' && "
            "echo '   Kinetix OS — Installing Flatpak & Flathub       ' && "
            "echo '===================================================' && "
            "echo 'Installing flatpak and adding the Flathub remote...' && "
            f"{FLATHUB_SETUP} && "
            "echo '' && echo '✓ Flatpak & Flathub successfully enabled!' && "
            "echo 'Press Enter to return to Kinetix OS.' && read -r _"
        )
        rc = launch_in_terminal("Kinetix App Center — Enabling Flatpak & Flathub", cmd)

    elif manager in ["snap", "snapd"]:
        cmd = (
            "echo '===================================================' && "
            "echo '   Kinetix OS — Installing Snapd Universal Store   ' && "
            "echo '===================================================' && "
            "echo '1. Installing snapd via package manager...' && "
            f"{helper} -S --noconfirm snapd && "
            "echo '2. Enabling and starting snapd system socket...' && "
            "sudo systemctl enable --now snapd.socket && "
            "sudo ln -sf /var/lib/snapd/snap /snap 2>/dev/null || true && "
            "echo '' && echo '✓ Snapd successfully installed and activated!' && "
            "echo 'Press Enter to return to Kinetix OS.' && read -r _"
        )
        rc = launch_in_terminal("Kinetix App Center — Installing Snapd", cmd)

    elif manager in ["paru", "aur"]:
        cmd = (
            "echo '===================================================' && "
            "echo '   Kinetix OS — Installing Paru (Rust AUR Helper)  ' && "
            "echo '===================================================' && "
            f"{PARU_BOOTSTRAP} && "
            "echo '' && echo '✓ Paru AUR helper successfully installed!' && "
            "echo 'Press Enter to return to Kinetix OS.' && read -r _"
        )
        rc = launch_in_terminal("Kinetix App Center — Installing Paru AUR Helper", cmd)

    elif manager == "yay":
        cmd = (
            "echo '===================================================' && "
            "echo '   Kinetix OS — Installing Yay (Go AUR Helper)     ' && "
            "echo '===================================================' && "
            "if which paru >/dev/null 2>&1; then "
            "  echo '1. Installing yay via paru...' && "
            "  paru -S --noconfirm yay-bin || paru -S --noconfirm yay; "
            "else "
            "  echo '1. Installing compilation dependencies...' && "
            "  sudo pacman -S --needed --noconfirm base-devel git go && "
            "  rm -rf /tmp/yay-bin && "
            "  echo '2. Cloning yay-bin repository from AUR...' && "
            "  git clone https://aur.archlinux.org/yay-bin.git /tmp/yay-bin && "
            "  cd /tmp/yay-bin && makepkg -si --noconfirm; "
            "fi && "
            "echo '' && echo '✓ Yay AUR helper successfully installed!' && "
            "echo 'Press Enter to return to Kinetix OS.' && read -r _"
        )
        rc = launch_in_terminal("Kinetix App Center — Installing Yay AUR Helper", cmd)

    elif manager == "appimage":
        cmd = (
            "echo '===================================================' && "
            "echo '   Kinetix OS — Installing AppImage & GearLever    ' && "
            "echo '===================================================' && "
            "echo '1. Installing FUSE2 compatibility runtime...' && "
            f"{helper} -S --noconfirm fuse2 && "
            "echo '2. Installing GearLever AppImage manager...' && "
            f"({helper} -S --noconfirm gearlever-bin || {helper} -S --noconfirm gearlever || true) && "
            "echo '' && echo '✓ AppImage support ready!' && "
            "echo 'Press Enter to return to Kinetix OS.' && read -r _"
        )
        rc = launch_in_terminal("Kinetix App Center — Installing AppImage Support", cmd)

    else:
        cmd = f"echo 'Unsupported package manager: {manager}' && read -r _"
        rc = launch_in_terminal(f"Kinetix App Center — {manager.title()}", cmd)

    return rc

def execute_update_all():
    """Run a full system update; returns its exit code."""
    helper = repo_helper()
    cmd = (
        "echo '=========================================' && "
        "echo '   KINETIX OS SYSTEM & APP UPDATE        ' && "
        "echo '=========================================' && "
        "echo '1. Updating Arch & AUR repositories...' && "
        f"{helper} -Syu --noconfirm && "
        "echo '' && "
        "if which flatpak >/dev/null 2>&1; then "
        "  echo '2. Updating Flatpak applications...' && "
        "  flatpak update -y; "
        "fi && "
        "echo '' && "
        "echo '=========================================' && "
        "echo '   All applications are up to date!      ' && "
        "echo '=========================================' && "
        "echo 'Press Enter to return to Kinetix OS.' && read -r _"
    )
    return launch_in_terminal("Kinetix App Center — Updating All Packages", cmd)

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No action specified"}))
        sys.exit(1)

    action = sys.argv[1]

    if action == "status":
        managers = get_package_managers()
        # Fast update count check from cache or quick check
        upd = check_updates(force=False)
        print(json.dumps({
            "managers": managers,
            "updates_count": upd["count"],
            "updates": upd["updates"][:20],
            "timestamp": time.time()
        }))

    elif action == "check-updates":
        res = check_updates(force=True)
        print(json.dumps(res))

    elif action == "featured":
        p_set = get_installed_pacman_packages()
        f_set = get_installed_flatpaks()
        featured_apps = get_featured(p_set, f_set)
        print(json.dumps({
            "apps": featured_apps,
            "total": len(featured_apps)
        }))

    elif action == "search":
        if len(sys.argv) < 3:
            print(json.dumps({"results": []}))
            return
        query = sys.argv[2].strip()
        source_filter = "all"
        if len(sys.argv) >= 4:
            source_filter = sys.argv[3].lower()

        # Check search cache first
        cached_results = get_cached_search(query, source_filter)
        if cached_results is not None:
            print(json.dumps({
                "query": query,
                "results": cached_results,
                "total": len(cached_results),
                "cached": True
            }))
            return

        p_set = get_installed_pacman_packages()
        f_set = get_installed_flatpaks()

        all_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {}
            if source_filter in ("all", "arch"):
                futures[pool.submit(search_pacman, query, p_set)] = "arch"
            if source_filter in ("all", "aur"):
                futures[pool.submit(search_aur, query, p_set)] = "aur"
            if source_filter in ("all", "flatpak"):
                futures[pool.submit(search_flathub, query, f_set)] = "flatpak"

            for fut in concurrent.futures.as_completed(futures):
                try:
                    all_results.extend(fut.result())
                except Exception:
                    pass

        # Deduplicate results by id + source
        seen = set()
        deduped = []
        for item in all_results:
            key = (item["source"], item["id"])
            if key not in seen:
                seen.add(key)
                deduped.append(item)

        # Sort: exact matches first, then installed, then popularity
        q_lower = query.lower()
        deduped.sort(
            key=lambda x: (
                x.get("title", "").lower() == q_lower or x.get("id", "").lower() == q_lower,
                q_lower in x.get("title", "").lower() or q_lower in x.get("id", "").lower(),
                x.get("installed", False),
                x.get("popularity", 0)
            ),
            reverse=True
        )

        top_results = deduped[:40]
        save_cached_search(query, source_filter, top_results)

        print(json.dumps({
            "query": query,
            "results": top_results,
            "total": len(deduped)
        }))

    elif action == "install":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Missing source or package ID"}))
            sys.exit(1)
        source = sys.argv[2]
        pkg_id = sys.argv[3]
        if not PKG_ID_RE.match(pkg_id) or source not in ("arch", "aur", "flatpak"):
            print(json.dumps({"error": "Invalid source or package ID"}))
            sys.exit(2)
        rc = execute_install(source, pkg_id)
        invalidate_caches()
        print(json.dumps({"status": "done" if rc == 0 else "failed", "rc": rc, "source": source, "id": pkg_id}))

    elif action == "uninstall":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Missing source or package ID"}))
            sys.exit(1)
        source = sys.argv[2]
        pkg_id = sys.argv[3]
        if not PKG_ID_RE.match(pkg_id) or source not in ("arch", "aur", "flatpak"):
            print(json.dumps({"error": "Invalid source or package ID"}))
            sys.exit(2)
        rc = execute_uninstall(source, pkg_id)
        invalidate_caches()
        print(json.dumps({"status": "done" if rc == 0 else "failed", "rc": rc, "source": source, "id": pkg_id}))

    elif action == "update-all":
        rc = execute_update_all()
        invalidate_caches()
        print(json.dumps({"status": "done" if rc == 0 else "failed", "rc": rc}))

    elif action == "enable-manager":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Missing manager name"}))
            sys.exit(1)
        manager = sys.argv[2]
        rc = execute_enable_manager(manager)
        invalidate_caches()
        print(json.dumps({"status": "done" if rc == 0 else "failed", "rc": rc, "manager": manager}))

    else:
        print(json.dumps({"error": f"Unknown action: {action}"}))
        sys.exit(1)

if __name__ == "__main__":
    main()
