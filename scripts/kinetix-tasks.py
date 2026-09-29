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
        var g = w.frameGeometry;
        out.push({
            uuid: String(w.internalId || w.windowId || ""),
            caption: cap,
            cls: cls,
            pid: w.pid || 0,
            active: !!w.active,
            minimized: !!w.minimized,
            maximized: !!(w.maximizeMode && w.maximizeMode !== 0),
            fullscreen: !!w.fullscreen,
            desktop: w.desktop || 0,
            x: g ? Math.round(g.x) : 0,
            y: g ? Math.round(g.y) : 0,
            w: g ? Math.round(g.width) : 0,
            h: g ? Math.round(g.height) : 0
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
                    "x": int(w.get("x", 0)),
                    "y": int(w.get("y", 0)),
                    "w": int(w.get("w", 0)),
                    "h": int(w.get("h", 0)),
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
            "x": int(info.get("x", {}).get("data", 0)),
            "y": int(info.get("y", {}).get("data", 0)),
            "w": int(info.get("width", {}).get("data", 0)),
            "h": int(info.get("height", {}).get("data", 0)),
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


def _wait_until_active(uuid, timeout=1.2):
    """Block until KWin actually reports `uuid` as the active window.

    A blind `time.sleep(0.08)` after activate_window() is a race: the window
    may not have been raised or painted yet, so `spectacle -a` grabs whatever
    is on screen at that instant — frequently the *previous* window, or an
    unpainted surface. That is what produced 1x1 and sliver-sized thumbnails.

    Polling our own view of the window list is both faster in the common case
    (returns as soon as focus actually lands) and far more reliable than a
    fixed guess. Bounded, so a compositor that never reports the window as
    active cannot stall the stream.

    A minimized window never becomes active without first being un-minimized,
    so it returns immediately rather than burning the whole timeout — a
    hover over a group of minimized windows would otherwise pay 1.2s each.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            for win in query_windows():
                if win.get("uuid") == uuid:
                    if win.get("minimized"):
                        return False
                    if win.get("active"):
                        # One extra short settle so the first frame is
                        # presented before spectacle reads the surface.
                        time.sleep(0.05)
                        return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.03)


def _activate_window_sync(uuid):
    """Activate `uuid` and wait until KWin reports it active.

    Used for capture preparation only; normal window actions remain fire-and-forget.
    """
    activate_window(uuid)
    return _wait_until_active(uuid)


_capture_active_lock = False
_capture_pending_queue = []


def capture_window(uuid, geometry, output_path):
    """Capture a window thumbnail and crop it to its geometry.

    KWin/Spectacle cannot capture an arbitrary background window, so we
    briefly activate the target, use spectacle -a (active window), crop to
    the reported geometry with ImageMagick, then restore the previous focus.
    Geometry is in KWin logical pixels; spectacle screenshots are in physical
    pixels, so we scale the crop region by the output scale.

    Captures are fully serialised at the daemon level so that focus
    restoration for one request completes before the next request activates
    a different window. Concurrent captures race each other, overwrite the
    "previous" active window, and make hovering the taskbar appear to switch
    windows on its own.
    """
    import shutil

    if not shutil.which("spectacle"):
        return {"ok": False, "error": "spectacle not installed"}

    global _capture_active_lock, _capture_pending_queue
    entry = {"uuid": uuid, "geometry": geometry, "output_path": output_path}
    _capture_pending_queue.append(entry)

    def _process_capture(req):
        uuid = req["uuid"]
        geometry = req["geometry"]
        output_path = Path(req["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        x, y, w, h = geometry

        # Remember current active window so we can restore focus afterwards.
        prev_active = None
        state_before = query_windows()
        if state_before:
            for win in state_before:
                if win.get("active"):
                    prev_active = win.get("uuid")
                    break

        # Activate the target window and wait for focus to actually land on it.
        _activate_window_sync(uuid)

        # Capture the active window.
        tmp_capture = TMP / f"kinetix-thumb-{uuid}-{os.getpid()}.png"
        cmd = ["spectacle", "-b", "-n", "-a", "-o", str(tmp_capture)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        except subprocess.TimeoutExpired:
            _restore_focus(prev_active)
            return {"ok": False, "error": "spectacle timed out capturing active window"}
        if not tmp_capture.exists():
            _restore_focus(prev_active)
            return {"ok": False, "error": "spectacle failed to write capture file"}

        # Crop to the window geometry.
        #
        # Guarded, because `magick -crop 0x0+0+0` exits 0 and happily writes a
        # degenerate image: minimized / not-yet-mapped windows report w=0,h=0, and
        # the old `returncode == 0 and output_path.exists()` check called that a
        # success — so a 1x1 grey pixel got cached as the window's thumbnail and
        # displayed as a blank tile. Crop only when the geometry is real, and
        # verify the result is plausibly sized before trusting it; otherwise fall
        # back to the full capture, which is always better than a 1x1.
        crop_ok = False
        if w > 0 and h > 0:
            scale = _display_scale()
            crop_geom = f"{int(round(w * scale))}x{int(round(h * scale))}+{int(round(x * scale))}+{int(round(y * scale))}"
            conv = shutil.which("magick") or shutil.which("convert")
            if conv:
                try:
                    cr = subprocess.run(
                        [conv, str(tmp_capture), "-crop", crop_geom, "+repage", str(output_path)],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    crop_ok = (
                        cr.returncode == 0
                        and output_path.exists()
                        and _png_is_plausible(output_path, w, h)
                    )
                except Exception:
                    crop_ok = False

        if not crop_ok:
            # Fall back to the full active-window capture if cropping fails.
            shutil.copyfile(str(tmp_capture), str(output_path))

        try:
            tmp_capture.unlink(missing_ok=True)
        except OSError:
            pass

        _restore_focus(prev_active)

        if not output_path.exists():
            return {"ok": False, "error": "capture produced no output file"}
        return {"ok": True, "path": str(output_path)}

    # Drain the pending queue one at a time so focus restoration stays ordered.
    result = {"ok": False, "error": "capture queue was drained without processing request"}
    req = None
    while _capture_pending_queue:
        _capture_active_lock = True
        try:
            req = _capture_pending_queue.pop(0)
            result = _process_capture(req)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        finally:
            _capture_active_lock = False
        if req is entry:
            break
    return result


def _png_is_plausible(path, expect_w, expect_h, min_area_ratio=0.20):
    """True when `path` is a real image, not a degenerate crop artifact.

    `magick -crop 0x0+0+0` (and clamps that eat the whole frame) still exit 0,
    so exit status alone cannot distinguish a good crop from a 1x1 or a
    sliver — that is how a 1x1 grey pixel got cached as a thumbnail.

    Judged on *area* rather than exact size, deliberately: the requested
    geometry comes from the last state push and the window can have moved by
    the time the capture lands, in which case ImageMagick clamps the crop to
    whatever actually fits. A clamped-but-real crop is still far more useful
    than falling back to a full-screen shot, so this only rejects output that
    has collapsed to a negligible fraction of the window. Measured against the
    real artifacts: 1x1 (0%) and 58x490-of-800x600 (6%) are rejected, genuine
    crops (>95%) are kept.
    """
    try:
        r = subprocess.run(
            ["magick", "identify", "-format", "%w %h", str(path)],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return False
        parts = r.stdout.strip().split()
        if len(parts) != 2:
            return False
        aw, ah = int(parts[0]), int(parts[1])
    except Exception:
        return False
    if aw <= 1 or ah <= 1:
        return False
    expected_area = max(1, int(expect_w) * int(expect_h))
    return (aw * ah) >= expected_area * min_area_ratio


def _display_scale():
    """Best-effort display scale factor for physical-pixel cropping."""
    try:
        r = subprocess.run(
            ["kscreen-doctor", "-j"], capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0:
            doc = json.loads(r.stdout)
            for o in doc.get("outputs", []):
                if o.get("connected") and o.get("enabled"):
                    return float(o.get("scale") or 1.0) or 1.0
    except Exception:
        pass
    return 1.0


def _restore_focus(uuid):
    """Best-effort restore of the previously active window after a capture."""
    if uuid:
        activate_window(uuid)


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

    # Every idle poll costs a KWin script load/start/unload round trip over
    # D-Bus PLUS a `journalctl --user` scrape to read the script's printed
    # result back (see run_kwin_script/_journal_marker above) — four-plus
    # subprocess spawns. At 450ms that's a near-continuous background load
    # (confirmed live: KWin's own log fills with a fresh "js: KINETIX_WIN_..."
    # line every ~1.3s even with zero windows open) that competes with the
    # compositor for CPU and was implicated in reports of random flashing/
    # stutter switching windows. Any real user action (activate/close/...)
    # already forces an immediate re-probe right after it runs, so idle
    # polling only needs to catch external changes (a window opened/closed
    # by something other than this daemon) — safe to back it off hard.
    IDLE_POLL_SECONDS = 2.0
    while True:
        # Check stdin for incoming commands, polling at IDLE_POLL_SECONDS
        rlist, _, _ = select.select([sys.stdin], [], [], IDLE_POLL_SECONDS)
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
            elif cmd.startswith("CAPTURE "):
                parts = cmd.split(" ", 5)
                if len(parts) == 6:
                    target_uuid = parts[1].strip()
                    try:
                        geom = (
                            int(parts[2].strip()),
                            int(parts[3].strip()),
                            int(parts[4].strip()),
                            int(parts[5].strip()),
                        )
                    except ValueError:
                        geom = (0, 0, 0, 0)
                    cache_dir = Path.home() / ".cache" / "argus" / "thumbs"
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    out_path = cache_dir / f"{target_uuid}.png"
                    res = capture_window(target_uuid, geom, out_path)
                    print(json.dumps({
                        "type": "thumbnail",
                        "uuid": target_uuid,
                        "path": str(out_path) if res.get("ok") else "",
                        "ok": res.get("ok", False),
                        "error": res.get("error", ""),
                    }))
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
        elif arg == "--capture" and len(sys.argv) > 6:
            geom = (
                int(sys.argv[3]),
                int(sys.argv[4]),
                int(sys.argv[5]),
                int(sys.argv[6]),
            )
            cache_dir = Path.home() / ".cache" / "argus" / "thumbs"
            cache_dir.mkdir(parents=True, exist_ok=True)
            out_path = cache_dir / f"{sys.argv[2]}.png"
            res = capture_window(sys.argv[2], geom, out_path)
            print(json.dumps(res))
            return
        elif arg == "--stream":
            run_stream()
            return

    run_stream()


if __name__ == "__main__":
    main()
