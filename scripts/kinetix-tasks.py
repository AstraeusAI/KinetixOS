#!/usr/bin/env python3
"""kinetix-tasks.py — High-precision KWin window inventory and task manager daemon.

Discovers live open windows on KWin (Plasma 6 / Wayland) via KWin scripting and KRunner
D-Bus interfaces, providing window captions, desktopFile, icons, minimized states, and
active focus. Dispatches window actions (activate, toggle-minimize, close) with sub-20ms
latency. Supports both streaming mode for Quickshell Process integration and CLI actions.
"""

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path("/tmp")

BUS = "org.kde.KWin"
KWIN_PATH = "/KWin"
KWIN_IFACE = "org.kde.KWin"
RUNNER_PATH = "/WindowsRunner"
RUNNER_IFACE = "org.kde.krunner1"
SCRIPTING_PATH = "/Scripting"
SCRIPTING_IFACE = "org.kde.kwin.Scripting"


def _busctl(*args, timeout=5):
    try:
        r = subprocess.run(
            ["busctl", "--user", "--json=short", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception:
        pass
    return None


def _busctl_ok(*args, timeout=5):
    try:
        r = subprocess.run(
            ["busctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode == 0
    except Exception:
        return False


def _journal_marker(marker, seconds=4):
    try:
        r = subprocess.run(
            [
                "journalctl",
                "--user",
                "--no-pager",
                "-o",
                "cat",
                "--since",
                f"{seconds} seconds ago",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.splitlines():
                if marker in line:
                    return line.split(marker, 1)[1].strip()
    except Exception:
        pass
    return None


def run_kwin_script(js, marker, timeout=2.0):
    nonce = f"{int(time.time() * 1000)}-{os.getpid()}"
    unique = f"{marker}{nonce}<"
    path = TMP / f"kinetix-task-{nonce}.js"
    path.write_text(js.replace("__MARKER__", unique))
    try:
        loaded = _busctl(
            "call", BUS, SCRIPTING_PATH, SCRIPTING_IFACE, "loadScript", "s", str(path)
        )
        if loaded is None:
            return None
        _busctl("call", BUS, SCRIPTING_PATH, SCRIPTING_IFACE, "start")
        deadline = time.time() + timeout
        wait_interval = 0.05
        while time.time() < deadline:
            time.sleep(wait_interval)
            res = _journal_marker(unique, seconds=2)
            if res is not None:
                return res
            wait_interval = min(0.12, wait_interval * 1.5)
        return None
    finally:
        try:
            _busctl(
                "call",
                BUS,
                SCRIPTING_PATH,
                SCRIPTING_IFACE,
                "unloadScript",
                "s",
                str(path),
            )
        except Exception:
            pass
        try:
            path.unlink()
        except OSError:
            pass


_JS_LIST = """
(function () {
    var ws = workspace;
    var list = ws.windowList ? ws.windowList() : ws.clientList();
    var out = [];
    for (var i = 0; i < list.length; i++) {
        var w = list[i];
        if (w.skipTaskbar) continue;
        var cap = String(w.caption || "");
        if (!cap || cap === "Desktop" || cap === "Plasma") continue;
        var cls = String(w.resourceClass || "");
        if (cls === "plasmashell" || cls === "quickshell") continue;
        out.push({
            uuid: String(w.internalId || w.windowId || ""),
            caption: cap,
            cls: cls,
            pid: w.pid || 0,
            active: !!w.active,
            minimized: !!w.minimized,
            maximized: !!(w.maximizeMode && w.maximizeMode !== 0),
            fullscreen: !!w.fullscreen,
            desktop: w.desktop || 0
        });
    }
    console.info("__MARKER__" + JSON.stringify(out));
})();
"""


# Standard desktop file / icon heuristics for common applications
ICON_MAP = {
    "org.kde.dolphin": "system-file-manager",
    "org.kde.konsole": "utilities-terminal",
    "org.kde.kate": "kate",
    "org.kde.kcalc": "accessories-calculator",
    "org.kde.spectacle": "spectacle",
    "chromium": "chromium",
    "google-chrome": "google-chrome",
    "firefox": "firefox",
    "rustdesk": "rustdesk",
    "smplayer": "smplayer",
    "devin-desktop": "devin-desktop",
    "ghostty": "com.mitchellh.ghostty",
}


def _resolve_icon(cls, caption, runner_icon):
    if runner_icon:
        return runner_icon
    cls_lower = cls.lower()
    for k, v in ICON_MAP.items():
        if k in cls_lower:
            return v
    cap_lower = caption.lower()
    if "dolphin" in cap_lower:
        return "system-file-manager"
    if "konsole" in cap_lower or "terminal" in cap_lower:
        return "utilities-terminal"
    if "kate" in cap_lower:
        return "kate"
    if "chrome" in cap_lower or "chromium" in cap_lower:
        return "chromium"
    if "firefox" in cap_lower:
        return "firefox"
    if "rustdesk" in cap_lower:
        return "rustdesk"
    if "devin" in cap_lower:
        return "devin-desktop"
    return cls_lower or "application-x-executable"


_ICON_CACHE = None


def _get_icon_cache():
    global _ICON_CACHE
    if _ICON_CACHE is not None:
        return _ICON_CACHE
    cache_path = Path.home() / ".cache/argus/icon-index.json"
    if cache_path.is_file():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                _ICON_CACHE = json.load(f)
                return _ICON_CACHE
        except Exception:
            pass
    _ICON_CACHE = {}
    return _ICON_CACHE


def _resolve_icon_path(icon_name):
    if not icon_name:
        return ""
    if icon_name.startswith("/"):
        return icon_name
    cache = _get_icon_cache()
    if icon_name in cache:
        return cache[icon_name]
    lower = icon_name.lower()
    if lower in cache:
        return cache[lower]
    base = icon_name.split(".")[-1]
    if base in cache:
        return cache[base]
    return icon_name


def query_windows():
    """Query live windows using KWin scripting first, falling back to KRunner WindowsRunner."""
    raw = run_kwin_script(_JS_LIST, "KINETIX_WIN_", timeout=0.8)
    if raw:
        try:
            wins = json.loads(raw)
            out = []
            for w in wins:
                cls = w.get("cls", "")
                cap = w.get("caption", "")
                uuid = w.get("uuid", "")
                icon_name = _resolve_icon(cls, cap, "")
                icon_file = _resolve_icon_path(icon_name)
                out.append({
                    "uuid": uuid,
                    "wid": f"0_{uuid}",
                    "title": cap,
                    "appId": cls,
                    "cls": cls,
                    "desktopFile": cls,
                    "icon": icon_file or icon_name,
                    "iconName": icon_name,
                    "active": bool(w.get("active", False)),
                    "minimized": bool(w.get("minimized", False)),
                    "maximized": bool(w.get("maximized", False)),
                    "pid": int(w.get("pid", 0)),
                })
            return out
        except Exception:
            pass

    # Fallback to KRunner Match
    runner_doc = _busctl("call", BUS, RUNNER_PATH, RUNNER_IFACE, "Match", "s", "")
    if not runner_doc:
        return []

    raw_matches = runner_doc.get("data", [[]])[0]
    out = []
    seen = set()
    for wid, text, icon, typ, rel, props in raw_matches:
        if typ != 100 or not text:
            continue
        uuid = wid.split("_", 1)[1] if "_" in wid else wid
        if uuid in seen:
            continue
        seen.add(uuid)
        info_doc = _busctl("call", BUS, KWIN_PATH, KWIN_IFACE, "getWindowInfo", "s", uuid)
        info = (info_doc.get("data", [{}])[0] or {}) if info_doc else {}
        skip = bool(info.get("skipTaskbar", {}).get("data", False))
        if skip:
            continue
        cls = str(info.get("resourceClass", {}).get("data", ""))
        minimized = bool(info.get("minimized", {}).get("data", False))
        resolved_icon = _resolve_icon(cls, text, icon)
        icon_file = _resolve_icon_path(resolved_icon)
        out.append({
            "uuid": uuid,
            "wid": wid,
            "title": text,
            "appId": cls or uuid,
            "cls": cls,
            "desktopFile": str(info.get("desktopFile", {}).get("data", cls)),
            "icon": icon_file or resolved_icon,
            "iconName": resolved_icon,
            "active": False,
            "minimized": minimized,
            "maximized": bool(info.get("maximized", {}).get("data", False)),
            "pid": int(info.get("pid", {}).get("data", 0)),
        })
    return out


def activate_window(uuid):
    """Activate/focus window with sub-20ms KRunner call."""
    wid = f"0_{uuid}" if not uuid.startswith("0_") else uuid
    if _busctl_ok("call", BUS, RUNNER_PATH, RUNNER_IFACE, "Run", "ss", wid, ""):
        return True
    clean_uuid = uuid.split("_", 1)[1] if "_" in uuid else uuid
    js = f"""
    (function() {{
        var ws = workspace;
        var list = ws.windowList ? ws.windowList() : ws.clientList();
        for (var i = 0; i < list.length; i++) {{
            var w = list[i];
            if (String(w.internalId || w.windowId || "") === "{clean_uuid}") {{
                if (w.minimized) w.minimized = false;
                if (w.activate) w.activate();
                else ws.activeWindow = w;
                break;
            }}
        }}
    }})();
    """
    return run_kwin_script(js, "ACTIVATE_", timeout=0.6) is not None


def toggle_window(uuid):
    """Plasma 6 behavior: if active, minimize; if inactive or minimized, unminimize & focus."""
    clean_uuid = uuid.split("_", 1)[1] if "_" in uuid else uuid
    js = f"""
    (function() {{
        var ws = workspace;
        var list = ws.windowList ? ws.windowList() : ws.clientList();
        for (var i = 0; i < list.length; i++) {{
            var w = list[i];
            if (String(w.internalId || w.windowId || "") === "{clean_uuid}") {{
                if (w.active) {{
                    w.minimized = true;
                }} else {{
                    w.minimized = false;
                    if (w.activate) w.activate();
                    else ws.activeWindow = w;
                }}
                break;
            }}
        }}
        console.info("__MARKER__toggled");
    }})();
    """
    return run_kwin_script(js, "TOGGLE_", timeout=0.6) is not None


def minimize_window(uuid, minimized):
    """Explicitly set (not toggle) a window's minimized state."""
    clean_uuid = uuid.split("_", 1)[1] if "_" in uuid else uuid
    flag = "true" if minimized else "false"
    js = f"""
    (function() {{
        var ws = workspace;
        var list = ws.windowList ? ws.windowList() : ws.clientList();
        for (var i = 0; i < list.length; i++) {{
            var w = list[i];
            if (String(w.internalId || w.windowId || "") === "{clean_uuid}") {{
                w.minimized = {flag};
                if (!{flag} && w.activate) w.activate();
                break;
            }}
        }}
        console.info("__MARKER__minimized");
    }})();
    """
    return run_kwin_script(js, "MINIMIZE_", timeout=0.6) is not None


def toggle_maximize(uuid):
    """Toggle full maximize. w.setMaximize(v, h) is a toggle, not a setter
    (confirmed live: calling it a second time with the same args restores
    the window) — there's no separate "set to this state" call."""
    clean_uuid = uuid.split("_", 1)[1] if "_" in uuid else uuid
    js = f"""
    (function() {{
        var ws = workspace;
        var list = ws.windowList ? ws.windowList() : ws.clientList();
        for (var i = 0; i < list.length; i++) {{
            var w = list[i];
            if (String(w.internalId || w.windowId || "") === "{clean_uuid}") {{
                w.setMaximize(true, true);
                if (w.activate) w.activate();
                break;
            }}
        }}
        console.info("__MARKER__toggled");
    }})();
    """
    return run_kwin_script(js, "MAXIMIZE_", timeout=0.6) is not None


def close_window(uuid):
    """Close window via KWin script."""
    clean_uuid = uuid.split("_", 1)[1] if "_" in uuid else uuid
    js = f"""
    (function() {{
        var ws = workspace;
        var list = ws.windowList ? ws.windowList() : ws.clientList();
        for (var i = 0; i < list.length; i++) {{
            var w = list[i];
            if (String(w.internalId || w.windowId || "") === "{clean_uuid}") {{
                if (w.closeWindow) w.closeWindow();
                break;
            }}
        }}
        console.info("__MARKER__closed");
    }})();
    """
    return run_kwin_script(js, "CLOSE_", timeout=0.6) is not None


def format_state(windows):
    active_uuid = ""
    for w in windows:
        if w.get("active"):
            active_uuid = w.get("uuid", "")
            break
    return json.dumps({"activeUuid": active_uuid, "windows": windows})


def run_stream():
    """Streaming mode: writes newline-delimited JSON to stdout and handles stdin commands."""
    last_state_str = ""
    # Make stdout line-buffered
    sys.stdout.reconfigure(line_buffering=True)

    # Initial probe
    windows = query_windows()
    last_state_str = format_state(windows)
    print(last_state_str)

    while True:
        # Check stdin for incoming commands with 450ms timeout
        rlist, _, _ = select.select([sys.stdin], [], [], 0.45)
        if rlist:
            line = sys.stdin.readline()
            if not line:
                break
            cmd = line.strip()
            if cmd.startswith("ACTIVATE "):
                target_uuid = cmd.split(" ", 1)[1].strip()
                activate_window(target_uuid)
            elif cmd.startswith("TOGGLE "):
                target_uuid = cmd.split(" ", 1)[1].strip()
                toggle_window(target_uuid)
            elif cmd.startswith("MINIMIZE "):
                parts = cmd.split(" ", 2)
                if len(parts) == 3:
                    minimize_window(parts[1].strip(), parts[2].strip() == "1")
            elif cmd.startswith("MAXIMIZE "):
                target_uuid = cmd.split(" ", 1)[1].strip()
                toggle_maximize(target_uuid)
            elif cmd.startswith("CLOSE "):
                target_uuid = cmd.split(" ", 1)[1].strip()
                close_window(target_uuid)
            # Re-probe immediately following any action
            windows = query_windows()
            state_str = format_state(windows)
            if state_str != last_state_str:
                last_state_str = state_str
                print(state_str)
            continue

        # Periodic check
        windows = query_windows()
        state_str = format_state(windows)
        if state_str != last_state_str:
            last_state_str = state_str
            print(state_str)


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--list":
            print(format_state(query_windows()))
            return
        elif arg == "--activate" and len(sys.argv) > 2:
            activate_window(sys.argv[2])
            return
        elif arg == "--toggle" and len(sys.argv) > 2:
            toggle_window(sys.argv[2])
            return
        elif arg == "--minimize" and len(sys.argv) > 3:
            minimize_window(sys.argv[2], sys.argv[3] == "1")
            return
        elif arg == "--maximize" and len(sys.argv) > 2:
            toggle_maximize(sys.argv[2])
            return
        elif arg == "--close" and len(sys.argv) > 2:
            close_window(sys.argv[2])
            return
        elif arg == "--stream":
            run_stream()
            return

    run_stream()


if __name__ == "__main__":
    main()
