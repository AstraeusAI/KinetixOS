"""KWin (Plasma/Wayland) adapter for computer use.

KWin is not wlroots, so the wlroots-shaped tools do not apply: `grim` cannot
capture (no wlr-screencopy) and there is no `zwlr_foreign_toplevel` inventory.
What KWin does provide, and what this module uses:

  window inventory   KWin scripting (`workspace.windowList()`) executed via
                     `org.kde.kwin.Scripting`, with results returned through
                     `console.info` → the user journal. KWin 6 removed
                     `writeConfig`, so the journal is the output channel.
                     Fallback: the KRunner windows runner (`Match`/`Run`) plus
                     `org.kde.KWin.getWindowInfo` for geometry.
  window control     KWin scripting: activate, close, move/resize.
  screenshots        `spectacle` in background mode (fullscreen, monitor,
                     active window, window under cursor); regions are captured
                     fullscreen and cropped, since spectacle's `--region` is
                     interactive only.
  keyboard/text      `wtype` (zwp_virtual_keyboard_manager_v1) — works on KWin.
  pointer            `ydotool` (uinput). Requires the `uinput` kernel module
                     and a running `ydotoold`; both are reported honestly by
                     `pointer_status()` rather than failing silently.

Everything here is capability-detected. Nothing pretends to work.
"""

import csv
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import struct
import subprocess
import time
from pathlib import Path

BUS = "org.kde.KWin"
KWIN_PATH = "/KWin"
KWIN_IFACE = "org.kde.KWin"
RUNNER_PATH = "/WindowsRunner"
RUNNER_IFACE = "org.kde.krunner1"
SCRIPTING_PATH = "/Scripting"
SCRIPTING_IFACE = "org.kde.kwin.Scripting"

TMP = Path("/tmp")
_BIN: dict[str, object] = {}


def _have(name):
    """Cached `shutil.which(name)`, or None.

    Every capability in CAPABILITY_REQUIRES is expressed in terms of these
    names, so a capability's availability is computed from the same list the
    code path would actually shell out to. capabilities() used to answer by
    calling `shutil.which` itself, inline, per key — which is how `zoom` came
    to report yes whenever spectacle was installed even though zoom() needs
    ImageMagick and returns "ImageMagick (magick/convert) required for zoom
    crop" without it, and how `image_compare` came to report yes on `compare`
    alone even though compare_regions() requires `compare` *and* magick/convert
    together. Naming a capability after one of its two prerequisites is not a
    probe. Caching also matters because this runs on every task start.
    """
    if name not in _BIN:
        _BIN[name] = shutil.which(name)
    return _BIN[name]


def _imagemagick():
    """Path to the ImageMagick CLI, or None. Both spellings are accepted by
    the code below (`magick` on IM7, `convert` on IM6)."""
    return _have("magick") or _have("convert")



# ── D-Bus plumbing ───────────────────────────────────────────────────────


def _busctl(*args, timeout=15):
    try:
        r = subprocess.run(
            ["busctl", "--user", "--json=short", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def _busctl_ok(*args, timeout=15):
    """True when the call succeeds. Needed for void methods (Ping, start, Run),
    where there is no JSON body to parse."""
    try:
        r = subprocess.run(
            ["busctl", "--user", *args], capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0
    except Exception:
        return False


def _unbox(value):
    """busctl --json=short wraps values as {"type":..,"data":..}."""
    if isinstance(value, dict) and "data" in value and "type" in value:
        return value["data"]
    return value


def available():
    """True when KWin is reachable on the session bus.

    Ping lives on org.freedesktop.DBus.Peer, not org.kde.KWin — calling it on
    the KWin interface fails even though the service is up.
    """
    return _busctl_ok("call", BUS, KWIN_PATH, "org.freedesktop.DBus.Peer", "Ping")


# ── scripting channel ────────────────────────────────────────────────────


def _journal_text(seconds=20, marker=None):
    """Recent KWin log lines. The unit name varies between setups, so try the
    common ones and finally the whole user journal.

    `marker` is the string the caller is waiting for. When given, the scope whose
    output actually contains it wins even if another scope produced output first
    — returning the first non-empty scope instead made run_script's poll loop
    miss the marker (and burn its whole timeout) on any setup where KWin's
    scripting output lands in a different unit than the one that happens to log
    something else, which then looks like "scripting unavailable" while the
    compositor is perfectly healthy.
    """
    first_nonempty = ""
    for unit in (["-u", "plasma-kwin_wayland"], ["-u", "kwin_wayland"], []):
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
                    *unit,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            continue
        if r.returncode == 0 and r.stdout.strip():
            if marker and marker in r.stdout:
                return r.stdout
            if not first_nonempty:
                first_nonempty = r.stdout
    return first_nonempty


def run_script(js, marker, timeout=8):
    """Run a KWin script and return the text following `marker` in its output.

    The script must emit `console.info(marker + payload)`.

    The marker is made unique per call: it used to be only the caller's constant
    prefix (`ARGUS_WINDOWS_`, `ARGUS_ACTION_`) while the per-call nonce went into
    the temp *filename* and nowhere else, so a line logged by an earlier call
    still inside the rolling journal window satisfied the match and was returned
    as the output of this one — stale window inventories, and an activate/close
    that reported the previous call's "activated"/"notfound" without doing
    anything.
    """
    nonce = f"{int(time.time() * 1000)}-{os.getpid()}"
    unique = f"{marker}{nonce}<"
    path = TMP / f"argus-kwin-{nonce}.js"
    path.write_text(js.replace("__MARKER__", unique))
    try:
        loaded = _busctl(
            "call", BUS, SCRIPTING_PATH, SCRIPTING_IFACE, "loadScript", "s", str(path)
        )
        if loaded is None:
            return None
        _busctl("call", BUS, SCRIPTING_PATH, SCRIPTING_IFACE, "start")
        deadline = time.time() + timeout
        while time.time() < deadline:
            for line in _journal_text(seconds=25, marker=unique).splitlines():
                if unique in line:
                    return line.split(unique, 1)[1].strip()
            time.sleep(0.25)
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


# ── HiDPI/fractional-scale coordinate conversion ─────────────────────────
# spectacle's screenshots (and therefore observe_screen's images, and any
# coordinate a model or human reads off one) are physical/device pixels.
# KWin's own coordinate space — workspace.cursorPos, a window's
# frameGeometry, ydotool's absolute positioning — is logical pixels, which
# differ from physical pixels by the output's scale factor on any
# fractionally-scaled display. Confirmed live on this host (3840x2160
# physical, `kscreen-doctor -j` reports scale 1.7 → 2259x1271 logical):
# requesting a pointer placement at a screenshot-pixel coordinate walked
# the cursor 1.7x too far and pinned it at the logical screen's right edge,
# unable to converge no matter how many correction rounds ran. Every
# function here that accepts or reports a coordinate (pointer placement,
# window geometry) does so in screenshot-pixel space and converts
# internally, so a caller reasoning from a screenshot never has to know
# the scale factor exists.
_SCREEN_SCALE: dict[str, float] = {}


def _screen_scale():
    """Screenshot-pixel-to-logical-pixel ratio for the enabled output.
    Cached: a monitor's scale does not change mid-session, and this is one
    more subprocess per call otherwise. Multi-monitor setups with different
    per-output scales are not handled — this host (and the common case) has
    one — a wrong-but-consistent 1.0 fallback if the probe fails is safer
    than guessing, since it degrades to the old (already-verified) logical-
    space behavior instead of applying a made-up factor.
    """
    if "v" in _SCREEN_SCALE:
        return _SCREEN_SCALE["v"]
    scale = 1.0
    try:
        r = subprocess.run(
            ["kscreen-doctor", "-j"], capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            doc = json.loads(r.stdout)
            for o in doc.get("outputs", []):
                if o.get("connected") and o.get("enabled"):
                    scale = float(o.get("scale") or 1.0) or 1.0
                    break
    except Exception:
        pass
    _SCREEN_SCALE["v"] = scale
    return scale


def to_screenshot_px(x, y):
    """Logical (compositor) coordinates -> screenshot-pixel coordinates."""
    scale = _screen_scale()
    return round(x * scale), round(y * scale)


def to_logical_px(x, y):
    """Screenshot-pixel coordinates -> logical (compositor) coordinates —
    the inverse of to_screenshot_px, and what KWin/ydotool actually expect."""
    scale = _screen_scale()
    return round(x / scale), round(y / scale)


def _win_to_screenshot_space(w):
    """Convert one window dict's x/y/w/h from KWin's logical frameGeometry
    to screenshot-pixel space, in place. Every other field is untouched."""
    scale = _screen_scale()
    for key in ("x", "y", "w", "h"):
        if key in w:
            w[key] = round(w[key] * scale)
    return w


_JS_LIST = """
(function () {
    var ws = workspace;
    var list = ws.windowList ? ws.windowList() : ws.clientList();
    var out = [];
    for (var i = 0; i < list.length; i++) {
        var w = list[i];
        var g = w.frameGeometry;
        out.push({
            uuid: String(w.internalId || w.windowId || ""),
            caption: String(w.caption || ""),
            cls: String(w.resourceClass || ""),
            pid: w.pid || 0,
            x: g ? Math.round(g.x) : 0, y: g ? Math.round(g.y) : 0,
            w: g ? Math.round(g.width) : 0, h: g ? Math.round(g.height) : 0,
            active: !!w.active, minimized: !!w.minimized, fullscreen: !!w.fullscreen,
            desktop: w.desktop || 0
        });
    }
    console.info("__MARKER__" + JSON.stringify(out));
})();
"""


def list_windows(limit=60):
    """All windows with geometry and state, geometry in screenshot-pixel
    space (see _win_to_screenshot_space). Scripting first (one call,
    includes the active flag), KRunner + getWindowInfo as fallback."""
    raw = run_script(_JS_LIST, "ARGUS_WINDOWS_")
    if raw:
        try:
            wins = [_win_to_screenshot_space(w) for w in json.loads(raw)]
            return {
                "ok": True,
                "source": "scripting",
                "count": len(wins),
                "windows": wins[:limit],
            }
        except Exception:
            pass
    return _list_via_dbus(limit)


def _list_via_dbus(limit=60):
    d = _busctl("call", BUS, RUNNER_PATH, RUNNER_IFACE, "Match", "s", "")
    if not d:
        return {
            "ok": False,
            "error": "KWin window inventory unavailable "
            "(scripting and KRunner both failed)",
        }
    rows = d.get("data", [[]])[0]
    out = []
    for row in rows[:limit]:
        wid, text, _icon, _typ, _rel, _props = row
        uuid = wid.split("_", 1)[1] if "_" in wid else wid
        info = _busctl("call", BUS, KWIN_PATH, KWIN_IFACE, "getWindowInfo", "s", uuid)
        fields = {}
        if info:
            for k, v in (info.get("data", [{}])[0] or {}).items():
                fields[k] = _unbox(v)
        out.append(
            _win_to_screenshot_space(
                {
                    "uuid": uuid,
                    "caption": text,
                    "cls": fields.get("resourceClass", ""),
                    "pid": fields.get("pid", 0),
                    "x": int(fields.get("x", 0)),
                    "y": int(fields.get("y", 0)),
                    "w": int(fields.get("width", 0)),
                    "h": int(fields.get("height", 0)),
                    "active": False,
                    "minimized": bool(fields.get("minimized", False)),
                    "fullscreen": bool(fields.get("fullscreen", False)),
                    "desktop": 0,
                }
            )
        )
    return {"ok": True, "source": "dbus", "count": len(out), "windows": out}


def active_window():
    """The focused window (scripting only — KWin exposes no D-Bus property),
    geometry in screenshot-pixel space (see _win_to_screenshot_space)."""
    raw = run_script(_JS_LIST, "ARGUS_WINDOWS_")
    if not raw:
        return {"ok": False, "error": "KWin scripting unavailable"}
    try:
        for w in json.loads(raw):
            if w.get("active"):
                return {"ok": True, "window": _win_to_screenshot_space(w)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "window": None}


def _window_action(uuid, body, marker="ARGUS_ACTION_"):
    js = """
(function () {
    var ws = workspace;
    var list = ws.windowList ? ws.windowList() : ws.clientList();
    var target = null;
    for (var i = 0; i < list.length; i++) {
        var w = list[i];
        if (String(w.internalId || w.windowId || "") === %s) { target = w; break; }
    }
    if (!target) { console.info("__MARKER__notfound"); return; }
    %s
})();
""" % (json.dumps(uuid), body)
    raw = run_script(js, marker)
    if raw is None:
        return {"ok": False, "error": "KWin scripting unavailable"}
    if raw == "notfound":
        return {"ok": False, "error": "window not found: " + uuid}
    return {"ok": True, "result": raw}


def _active_uuid():
    try:
        return (active_window().get("window") or {}).get("uuid") or None
    except Exception:
        return None


def _wait_until_active(uuid, budget=2.0, step=0.1):
    """Poll the compositor's own idea of the focused window."""
    deadline = time.time() + budget
    while True:
        if _active_uuid() == uuid:
            return True
        if time.time() >= deadline:
            return False
        time.sleep(step)


def activate_window(uuid):
    """Focus a window — and only report success once the compositor agrees.

    Wayland activation is asynchronous, and the caller's very next action is to
    inject input into whatever holds focus. The script's own console.info line
    only proves the request was made (the JS logs "activated" unconditionally),
    and the KRunner fallback's Run() is a void D-Bus call whose status 0 proves
    even less, so both paths used to return ok:True for a focus change that had
    not happened or never would — with the next keystroke or URL going to the
    previously focused window, which is exactly what the focus guard in
    lib/tools.py exists to prevent.
    """
    r = _window_action(
        uuid,
        """
    if (target.minimized) { target.minimized = false; }
    if (target.activate) { target.activate(); }
    else { workspace.activeWindow = target; }
    console.info("__MARKER__activated");
""",
    )
    if r.get("ok") and _wait_until_active(uuid):
        return r
    # fallback: KRunner windows runner (void method — check status, not JSON)
    if _busctl_ok("call", BUS, RUNNER_PATH, RUNNER_IFACE, "Run", "ss", "0_" + uuid, ""):
        if _wait_until_active(uuid):
            return {"ok": True, "result": "activated via KRunner"}
        return {
            "ok": False,
            "error": f"activation requested, but {uuid} is still not the "
            f"focused window (focus: {_active_uuid() or 'none'})",
        }
    if r.get("ok"):
        return {
            "ok": False,
            "error": f"activate did not take effect — focus is on "
            f"{_active_uuid() or 'no window'}",
        }
    return r


def focus_or_launch(app_name, timeout=6.0, command=None):
    (
        """Focus an existing window matching app_name, or launch the app and wait """
        """for """
        """its window to gain focus."""
    )
    cand = str(app_name).strip().lower()

    # 1. Check existing windows
    wins = list_windows(limit=100)
    if wins.get("ok"):
        for w in wins.get("windows", []):
            if (
                cand in (w.get("cls") or "").lower()
                or cand in (w.get("caption") or "").lower()
            ):
                act = activate_window(w["uuid"])
                return {
                    "ok": bool(act.get("ok")),
                    "action": "focused_existing",
                    "window": w,
                    **({} if act.get("ok") else {"error": act.get("error")}),
                }

    # 2. Not running: launch
    if command:
        if isinstance(command, list):
            launch_cmd = [str(c) for c in command]
        else:
            launch_cmd = shlex.split(str(command))
    else:
        exe = shutil.which(app_name)
        if not exe:
            if shutil.which("gtk-launch"):
                desk_name = (
                    app_name if not app_name.endswith(".desktop") else app_name[:-8]
                )
                launch_cmd = ["gtk-launch", desk_name]
            else:
                return {
                    "ok": False,
                    "error": f"executable not found for app: {app_name!r}",
                }
        else:
            launch_cmd = [exe]

    try:
        subprocess.Popen(
            launch_cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return {"ok": False, "error": f"failed to launch {app_name!r}: {e}"}

    # Poll for window to appear and activate
    deadline = time.time() + max(1.0, min(float(timeout), 20.0))
    while time.time() < deadline:
        time.sleep(0.25)
        wins = list_windows(limit=100)
        if wins.get("ok"):
            for w in wins.get("windows", []):
                if (
                    cand in (w.get("cls") or "").lower()
                    or cand in (w.get("caption") or "").lower()
                ):
                    act = activate_window(w["uuid"])
                    return {
                        "ok": bool(act.get("ok")),
                        "action": "launched_and_focused",
                        "window": w,
                        **({} if act.get("ok") else {"error": act.get("error")}),
                    }

    return {
        "ok": False,
        "error": f"launched {app_name!r} but no matching window appeared within "
        f"{timeout}s",
    }


def close_window(uuid):
    return _window_action(
        uuid,
        """
    target.closeWindow();
    console.info("__MARKER__closed");
""",
    )


def move_window(uuid, x, y, w=None, h=None):
    """x/y/w/h are screenshot-pixel coordinates, like everything else here —
    converted to KWin's logical frameGeometry space before use."""
    scale = _screen_scale()
    lx, ly = round(int(x) / scale), round(int(y) / scale)
    lw = round(int(w) / scale) if w else None
    lh = round(int(h) / scale) if h else None
    body = "target.frameGeometry = { x: %d, y: %d, width: %s, height: %s };\n" % (
        lx,
        ly,
        lw if lw else "target.frameGeometry.width",
        lh if lh else "target.frameGeometry.height",
    )
    body += 'console.info("__MARKER__moved");'
    return _window_action(uuid, body)


def maximize_window(uuid, state=True):
    """Maximize (or unmaximize if state=False) a window by uuid."""
    val = "true" if state else "false"
    body = f"""
    if (target.setMaximize) {{
        target.setMaximize({val}, {val});
    }} else {{
        target.maximized = {val};
    }}
    console.info("__MARKER__maximized");
"""
    return _window_action(uuid, body)


def minimize_window(uuid, state=True):
    """Minimize (or unminimize/restore if state=False) a window by uuid."""
    val = "true" if state else "false"
    body = f"""
    target.minimized = {val};
    console.info("__MARKER__minimized");
"""
    return _window_action(uuid, body)


def resolve_window(win_identifier):
    """Find a window dict by the same flexible identifier every window-
    relative tool accepts: 'active'/empty, an exact UUID, or a substring of
    its caption/class. Returns None rather than raising when nothing
    matches, so callers report their own "window not found" with whatever
    context they have (the action name, the field it came from, ...).

    Pulled out of window_to_screen_px so window-op fallbacks (desktop_actions'
    move_window/resize_window, when only relative_to was given) can resolve
    'active' or a caption substring the same way coordinate translation
    already does, instead of passing that raw string straight to a KWin
    script that only ever matches an exact internalId — which silently
    reported "window not found: active" no matter how literally correct
    the identifier was.
    """
    if not win_identifier or str(win_identifier).strip().lower() == "active":
        act = active_window()
        if act.get("ok") and act.get("window"):
            return act["window"]
        return None
    wins = list_windows(limit=100)
    if not wins.get("ok"):
        return None
    cand = str(win_identifier).strip().lower()
    for w in wins.get("windows", []):
        if w.get("uuid") == str(win_identifier):
            return w
    for w in wins.get("windows", []):
        if (
            cand in (w.get("caption") or "").lower()
            or cand in (w.get("cls") or "").lower()
        ):
            return w
    return None


def window_to_screen_px(win_identifier, rx, ry):
    """Translate window-relative coordinates (rx, ry) to absolute
    screenshot-pixel coordinates.
    `win_identifier`: 'active', window UUID, or substring of window caption/class.
    If rx/ry are floats between 0.0 and 1.0, they are treated as fractional
    proportions of the window width/height.
    If integers or >= 1.0, they are treated as pixel offsets from the window's top-left.
    """
    target = resolve_window(win_identifier)
    if not target:
        return {"ok": False, "error": f"window not found: {win_identifier!r}"}

    wx = target.get("x", 0)
    wy = target.get("y", 0)
    ww = target.get("w", 0)
    wh = target.get("h", 0)

    # Support fractional relative coordinates (e.g. 0.5, 0.5 for window center)
    if isinstance(rx, float) and 0.0 <= rx <= 1.0:
        abs_x = wx + int(round(rx * ww))
    else:
        abs_x = wx + int(rx)

    if isinstance(ry, float) and 0.0 <= ry <= 1.0:
        abs_y = wy + int(round(ry * wh))
    else:
        abs_y = wy + int(ry)

    return {
        "ok": True,
        "x": abs_x,
        "y": abs_y,
        "window": {
            "uuid": target.get("uuid"),
            "caption": target.get("caption"),
            "cls": target.get("cls"),
        },
    }


# ── screenshots ──────────────────────────────────────────────────────────


def _read_image_dimensions(path):
    (
        """Read width/height directly from image header without loading full image """
        """pixels."""
    )
    try:
        p = Path(path)
        if not p.exists():
            return None, None
        with p.open("rb") as f:
            head = f.read(32)
            if len(head) >= 24 and head.startswith(b"\x89PNG\r\n\x1a\n"):
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
        conv = shutil.which("identify")
        if conv:
            r = subprocess.run(
                [conv, "-format", "%w %h", str(p)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split()
                if len(parts) >= 2:
                    return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None, None


def screenshot(
    path,
    mode="fullscreen",
    region=None,
    include_pointer=False,
    stamp_cursor=False,
    grid=False,
    grid_step=100,
    annotate=False,
    annotate_max=50,
):
    """Capture via spectacle. `mode`: fullscreen | monitor | active | cursor.
    `region` = (x, y, w, h) crops a fullscreen capture (spectacle's --region is
    interactive only). If `stamp_cursor` is True, draws a high-visibility cursor
    targeting indicator at the measured pointer position.
    If `grid` is True, draws an overlay coordinate grid with numerical pixel markers.
    If `annotate` is True, detects UI text/buttons and draws numbered
    Set-of-Marks badges.

    `cursor` (spectacle -u, window-under-cursor) is measurably less reliable
    in background mode than the other three: verified live on this host with
    the cursor genuinely resting over a real window (confirmed via KWin's own
    workspace.cursorPos plus the window list, not an empty-desktop guess) —
    one attempt hung for the full timeout, four immediately following it
    failed fast with returncode 2 and empty stderr/stdout. Prefer `active`
    when the goal is "whatever the user is looking at"; `cursor` is exposed
    because it's a real spectacle mode, not because it's dependable here.
    """
    # Element IDs belong to pixels from a particular annotated frame. Any
    # fresh capture invalidates them before a later click can use stale UI
    # coordinates after the desktop has changed.
    _LAST_ANNOTATED_ELEMENTS.clear()
    if not shutil.which("spectacle"):
        return {"ok": False, "error": "spectacle not installed"}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flag = {"fullscreen": "-f", "monitor": "-m", "active": "-a", "cursor": "-u"}.get(
        mode, "-f"
    )
    cmd = ["spectacle", "-b", "-n", flag, "-o", str(path)]
    if include_pointer:
        cmd.append("-p")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"spectacle timed out (mode={mode})"
            + (
                " — cursor mode is known to hang here; try mode=active instead"
                if mode == "cursor"
                else ""
            ),
        }
    if not path.exists():
        detail = (r.stderr or r.stdout or "").strip()[:300]
        if not detail:
            detail = f"spectacle exited {r.returncode} with no diagnostic output"
            if mode == "cursor":
                detail += (
                    " (cursor mode is known to be unreliable in background mode "
                    "— try mode=active)"
                )
        return {"ok": False, "error": "capture failed: " + detail}
    region_applied = None
    if region:
        x, y, w, h = (int(v) for v in region)
        conv = shutil.which("magick") or shutil.which("convert")
        if not conv:
            region_applied = False
        else:
            try:
                cr = subprocess.run(
                    [
                        conv,
                        str(path),
                        "-crop",
                        f"{w}x{h}+{x}+{y}",
                        "+repage",
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=25,
                )
                region_applied = cr.returncode == 0
            except Exception:
                region_applied = False
        if not region_applied:
            if grid:
                draw_coordinate_grid(path, step=grid_step)
            if stamp_cursor:
                stamp_cursor_marker(path)
            elements = None
            if annotate:
                ann = annotate_screen(path, max_elements=annotate_max)
                if ann.get("ok"):
                    elements = ann.get("elements", [])
            w, h = _read_image_dimensions(path)
            res = {
                "ok": True,
                "path": str(path),
                "mode": mode,
                "bytes": path.stat().st_size,
                "region_applied": False,
                "scale": _screen_scale(),
                "note": "region crop requested but not applied (need ImageMagick's "
                "magick/convert) — this is the full, uncropped capture",
            }
            if grid:
                res["grid"] = True
                res["grid_step"] = grid_step
            if annotate and elements is not None:
                res["annotate"] = True
                res["annotated"] = True
                res["elements"] = elements
            if w and h:
                res["width"], res["height"] = w, h
            return res
    if grid:
        draw_coordinate_grid(path, step=grid_step)
    if stamp_cursor:
        stamp_cursor_marker(path)
    elements = None
    if annotate:
        ann = annotate_screen(path, max_elements=annotate_max)
        if ann.get("ok"):
            elements = ann.get("elements", [])
    w, h = _read_image_dimensions(path)
    res = {
        "ok": True,
        "path": str(path),
        "mode": mode,
        "bytes": path.stat().st_size,
        "scale": _screen_scale(),
        **({"region_applied": True} if region else {}),
    }
    if grid:
        res["grid"] = True
        res["grid_step"] = grid_step
    if annotate and elements is not None:
        res["annotate"] = True
        res["annotated"] = True
        res["elements"] = elements
    if w and h:
        res["width"], res["height"] = w, h
    return res


def stamp_cursor_marker(image_path, x=None, y=None, output_path=None, show_label=True):
    """Draw a high-contrast visual cursor target (ring + crosshair) onto an image.
    If x/y are None, queries the current cursor position and converts to
    screenshot pixels.
    If show_label is True, draws a readable numerical (x,y) label next to the marker."""
    if x is None or y is None:
        cur = cursor_position()
        if cur.get("ok"):
            x, y = to_screenshot_px(cur["x"], cur["y"])
        else:
            return False
    conv = shutil.which("magick") or shutil.which("convert")
    if not conv:
        return False
    dst = str(output_path or image_path)
    r = 10
    cx, cy = int(round(x)), int(round(y))
    cmd = [
        conv,
        str(image_path),
        "-stroke",
        "#FF2222",
        "-strokewidth",
        "2",
        "-fill",
        "rgba(255,50,50,0.3)",
        "-draw",
        f"circle {cx},{cy} {cx + r},{cy}",
        "-stroke",
        "#FFFF00",
        "-strokewidth",
        "1",
        "-draw",
        f"line {cx - 14},{cy} {cx + 14},{cy}",
        "-draw",
        f"line {cx},{cy - 14} {cx},{cy + 14}",
    ]
    if show_label:
        cmd += [
            "-font",
            "DejaVu-Sans",
            "-pointsize",
            "10",
            "-stroke",
            "black",
            "-strokewidth",
            "2",
            "-fill",
            "white",
            "-draw",
            f'text {cx + 14},{cy - 6} "({cx},{cy})"',
            "-stroke",
            "none",
            "-fill",
            "#FFFF00",
            "-draw",
            f'text {cx + 14},{cy - 6} "({cx},{cy})"',
        ]
    cmd.append(dst)
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=10)
        return res.returncode == 0
    except Exception:
        return False


def draw_coordinate_grid(image_path, step=100, output_path=None):
    """Draw a subtle, high-legibility coordinate reference grid with pixel
    labels onto an image.
    `step` is the pixel interval (e.g. 100 or 200)."""
    conv = shutil.which("magick") or shutil.which("convert")
    if not conv:
        return False
    dst = str(output_path or image_path)
    w, h = _read_image_dimensions(image_path)
    if not w or not h:
        return False
    step = max(50, min(int(step), 500))
    draws = []
    # Vertical grid lines and top coordinate labels
    for x in range(step, w, step):
        draws.append(f"stroke rgba(0,255,255,0.22) stroke-width 1 line {x},0 {x},{h}")
        draws.append(f'stroke none fill rgba(0,255,255,0.85) text {x + 3},12 "{x}"')
    # Horizontal grid lines and left coordinate labels
    for y in range(step, h, step):
        draws.append(f"stroke rgba(0,255,255,0.22) stroke-width 1 line 0,{y} {w},{y}")
        draws.append(f'stroke none fill rgba(0,255,255,0.85) text 3,{y + 12} "{y}"')
    cmd = [
        conv,
        str(image_path),
        "-font",
        "DejaVu-Sans",
        "-pointsize",
        "10",
        "-draw",
        " ".join(draws),
        dst,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=15)
        return res.returncode == 0
    except Exception:
        return False


def zoom(path, region, out_path=None):
    """Extract a 1:1 high-resolution uncompressed crop of `region = (x, y, w, h)`.
    If path does not exist, captures a full screenshot first and then crops."""
    rx, ry, rw, rh = (int(v) for v in region)
    src = Path(path)
    if not src.exists():
        shot = screenshot(src, mode="fullscreen")
        if not shot.get("ok"):
            return shot
    dst = (
        Path(out_path)
        if out_path
        else src.with_name(f"{src.stem}-zoom-{rx}_{ry}_{rw}_{rh}{src.suffix}")
    )
    conv = shutil.which("magick") or shutil.which("convert")
    if not conv:
        return {
            "ok": False,
            "error": "ImageMagick (magick/convert) required for zoom crop",
        }
    try:
        r = subprocess.run(
            [conv, str(src), "-crop", f"{rw}x{rh}+{rx}+{ry}", "+repage", str(dst)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if r.returncode != 0:
            return {"ok": False, "error": f"zoom crop failed: {r.stderr[:200]}"}
    except Exception as e:
        return {"ok": False, "error": f"zoom crop failed: {e}"}
    w, h = _read_image_dimensions(dst)
    return {
        "ok": True,
        "path": str(dst),
        "x": rx,
        "y": ry,
        "width": w or rw,
        "height": h or rh,
        "scale": _screen_scale(),
        "bytes": dst.stat().st_size,
    }


def wait_for_change(timeout=3.0, poll_interval=0.25, region=None):
    """Wait for screen pixels or active window to visually change.
    Returns {ok, changed, elapsed}."""
    interval = max(0.1, min(float(poll_interval), 2.0))
    initial_win = _active_uuid()
    initial_p = TMP / f"argus-watch-base-{os.getpid()}.png"
    screenshot(initial_p, mode="fullscreen", region=region)
    base_bytes = initial_p.read_bytes() if initial_p.exists() else b""
    base_hash = hashlib.sha256(base_bytes).hexdigest() if base_bytes else None
    base_size = len(base_bytes) if base_bytes else None
    start_t = time.time()
    deadline = start_t + max(0.2, min(float(timeout), 30.0))
    while time.time() < deadline:
        time.sleep(interval)
        cur_win = _active_uuid()
        if cur_win != initial_win:
            initial_p.unlink(missing_ok=True)
            return {
                "ok": True,
                "changed": True,
                "reason": "active window changed",
                "elapsed": round(time.time() - start_t, 2),
            }
        if base_hash is not None:
            chk_p = TMP / f"argus-watch-chk-{os.getpid()}.png"
            chk_shot = screenshot(chk_p, mode="fullscreen", region=region)
            if chk_shot.get("ok") and chk_p.exists():
                cur_bytes = chk_p.read_bytes()
                cur_hash = hashlib.sha256(cur_bytes).hexdigest()
                cur_size = len(cur_bytes)
                diff = abs(cur_size - base_size)
                if cur_hash != base_hash:
                    chk_p.unlink(missing_ok=True)
                    initial_p.unlink(missing_ok=True)
                    return {
                        "ok": True,
                        "changed": True,
                        "reason": "screen pixels updated",
                        "elapsed": round(time.time() - start_t, 2),
                        "bytes_delta": diff,
                    }
                chk_p.unlink(missing_ok=True)
    initial_p.unlink(missing_ok=True)
    return {
        "ok": True,
        "changed": False,
        "reason": "timeout expired without visual change",
        "elapsed": round(time.time() - start_t, 2),
    }


def display_info():
    (
        """Retrieve attached display outputs, resolutions, logical scales, and """
        """virtual """
        """desktop geometry."""
    )
    scale = _screen_scale()
    if not shutil.which("kscreen-doctor"):
        default_out = [
            {
                "name": "default",
                "primary": True,
                "enabled": True,
                "x": 0,
                "y": 0,
                "scale": scale,
            }
        ]
        return {
            "ok": True,
            "count": 1,
            "displays": default_out,
            "outputs": default_out,
            "screen_scale": scale,
        }
    try:
        r = subprocess.run(
            ["kscreen-doctor", "-j"], capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0 or not r.stdout.strip():
            return {
                "ok": True,
                "count": 0,
                "displays": [],
                "outputs": [],
                "screen_scale": scale,
            }
        data = json.loads(r.stdout)
        outputs = []
        for out in data.get("outputs", []):
            if not out.get("enabled", True):
                continue
            pos = out.get("pos", {})
            mode = out.get("currentMode", {})
            m_size = mode.get("size", {}) if isinstance(mode, dict) else {}
            size = out.get("size") or m_size or {}
            rr = mode.get("refreshRate", 60.0) if isinstance(mode, dict) else 60.0
            if rr > 1000:
                rr = round(rr / 1000.0, 1)
            outputs.append(
                {
                    "id": out.get("id"),
                    "name": out.get("name"),
                    "primary": bool(out.get("primary", False)),
                    "x": pos.get("x", 0),
                    "y": pos.get("y", 0),
                    "width": size.get("width", 0),
                    "height": size.get("height", 0),
                    "scale": float(out.get("scale", 1.0)),
                    "rotation": out.get("rotation", 1),
                    "refresh_rate": rr,
                }
            )
        scr = data.get("screen", {}).get("currentSize") or data.get("currentSize", {})
        vw = scr.get("width")
        vh = scr.get("height")
        cur_sz = [vw, vh] if vw and vh else None
        return {
            "ok": True,
            "count": len(outputs),
            "displays": outputs,
            "outputs": outputs,
            "current_size": cur_sz,
            "virtual_width": vw,
            "virtual_height": vh,
            "screen_scale": scale,
        }
    except Exception as e:
        return {"ok": False, "error": f"failed to query displays: {e}"}


def ocr_screen(image_path=None, region=None, min_confidence=30):
    """Extract all text and bounding boxes from a screenshot using Tesseract OCR.
    Returns words and reconstructed lines with screenshot-pixel coordinates.
    """
    if not shutil.which("tesseract"):
        return {"ok": False, "error": "tesseract not installed"}
    tmp_shot = None
    crop_path = None
    if not image_path or not Path(image_path).exists():
        tmp_shot = TMP / f"argus-ocr-base-{os.getpid()}-{int(time.time() * 1000)}.png"
        shot = screenshot(tmp_shot, mode="fullscreen", region=region)
        if not shot.get("ok"):
            return shot
        target_path = tmp_shot
        # screenshot() crops the file on disk to `region` when given (and
        # reports it via region_applied) — tesseract then only ever sees
        # that cropped image, so its own (0,0) is the region's corner, not
        # the screen's. Without adding the region's offset back here, every
        # coordinate ocr_screen/find_text/click_text returns for a
        # region-scoped search would be off by (region_x, region_y): still
        # "valid" screen coordinates, just pointing at whatever happens to
        # sit that far into the top-left of the actual match — click_text
        # would then click the wrong thing while reporting success. Only
        # applied when the crop actually took (region_applied) — if it
        # didn't (e.g. no ImageMagick in this sandbox), screenshot() already
        # fell back to the uncropped full-screen image, so offset 0 is the
        # correct one for that case, not the region's.
        if region and shot.get("region_applied"):
            reg_offset_x, reg_offset_y = int(region[0]), int(region[1])
        else:
            reg_offset_x, reg_offset_y = 0, 0
    else:
        target_path = Path(image_path)
        if region:
            rx, ry, rw, rh = (int(v) for v in region)
            crop_path = (
                TMP / f"argus-ocr-crop-{os.getpid()}-{int(time.time() * 1000)}.png"
            )
            conv = shutil.which("magick") or shutil.which("convert")
            if conv:
                subprocess.run(
                    [
                        conv,
                        str(target_path),
                        "-crop",
                        f"{rw}x{rh}+{rx}+{ry}",
                        "+repage",
                        str(crop_path),
                    ],
                    capture_output=True,
                    timeout=10,
                )
                if crop_path.exists():
                    target_path = crop_path
                    reg_offset_x = rx
                    reg_offset_y = ry
                else:
                    reg_offset_x = 0
                    reg_offset_y = 0
            else:
                reg_offset_x = 0
                reg_offset_y = 0
        else:
            reg_offset_x = 0
            reg_offset_y = 0

    try:
        cmd = ["tesseract", str(target_path), "stdout", "tsv", "--dpi", "96"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0 and "--dpi" in (r.stderr or ""):
            r = subprocess.run(
                ["tesseract", str(target_path), "stdout", "tsv"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        if r.returncode != 0:
            return {"ok": False, "error": f"tesseract failed: {r.stderr[:200]}"}

        words = []
        lines_map = {}
        for row in csv.reader(r.stdout.splitlines(), delimiter="\t"):
            if len(row) >= 12 and row[0] == "5":
                txt = row[11].strip()
                try:
                    conf = float(row[10])
                except ValueError:
                    conf = 0.0
                if txt and conf >= min_confidence:
                    x = int(row[6]) + reg_offset_x
                    y = int(row[7]) + reg_offset_y
                    w = int(row[8])
                    h = int(row[9])
                    cx = x + w // 2
                    cy = y + h // 2
                    w_item = {
                        "text": txt,
                        "left": x,
                        "top": y,
                        "width": w,
                        "height": h,
                        "center_x": cx,
                        "center_y": cy,
                        "confidence": conf,
                        "box": [x, y, w, h],
                    }
                    words.append(w_item)
                    key = (row[2], row[3], row[4])
                    lines_map.setdefault(key, []).append(w_item)

        lines = []
        for key, line_words in lines_map.items():
            full_text = " ".join(w["text"] for w in line_words)
            min_x = min(w["left"] for w in line_words)
            min_y = min(w["top"] for w in line_words)
            max_x = max(w["left"] + w["width"] for w in line_words)
            max_y = max(w["top"] + w["height"] for w in line_words)
            w = max_x - min_x
            h = max_y - min_y
            avg_conf = sum(w["confidence"] for w in line_words) / len(line_words)
            lines.append(
                {
                    "text": full_text,
                    "left": min_x,
                    "top": min_y,
                    "width": w,
                    "height": h,
                    "center_x": (min_x + max_x) // 2,
                    "center_y": (min_y + max_y) // 2,
                    "confidence": round(avg_conf, 1),
                    "box": [min_x, min_y, w, h],
                }
            )

        return {
            "ok": True,
            "word_count": len(words),
            "line_count": len(lines),
            "words": words,
            "lines": lines,
        }
    finally:
        if tmp_shot:
            tmp_shot.unlink(missing_ok=True)
        if crop_path and crop_path.exists():
            crop_path.unlink(missing_ok=True)


def find_text(query, image_path=None, region=None, exact=False, min_confidence=30):
    (
        """Search for text on screen using OCR. Returns list of matches with """
        """clickable """
        """centers (x, y)."""
    )
    ocr_res = ocr_screen(
        image_path=image_path, region=region, min_confidence=min_confidence
    )
    if not ocr_res.get("ok"):
        return ocr_res

    q = str(query).strip().lower()
    matches = []

    for w in ocr_res.get("words", []):
        w_text = w["text"].lower()
        is_match = (w_text == q) if exact else (q in w_text)
        if is_match:
            matches.append(
                {
                    "text": w["text"],
                    "x": w["center_x"],
                    "y": w["center_y"],
                    "box": w["box"],
                    "confidence": round(w["confidence"], 1),
                    "exact": w_text == q,
                    "type": "word",
                }
            )

    for line in ocr_res.get("lines", []):
        l_text = line["text"].lower()
        is_match = (l_text == q) if exact else (q in l_text)
        if is_match and (" " in q or not matches):
            matches.append(
                {
                    "text": line["text"],
                    "x": line["center_x"],
                    "y": line["center_y"],
                    "box": line["box"],
                    "confidence": round(line["confidence"], 1),
                    "exact": l_text == q,
                    "type": "line",
                }
            )

    matches.sort(key=lambda m: (m["exact"], m["confidence"]), reverse=True)
    return {"ok": True, "query": query, "count": len(matches), "matches": matches}


def click_text(
    query,
    button="left",
    clicks=1,
    modifiers=None,
    region=None,
    exact=False,
    min_confidence=40.0,
    index=0,
):
    (
        """Find text on screen using OCR and click its center point. Placement is """
        """verified closed-loop."""
    )
    found = find_text(query, region=region, exact=exact, min_confidence=min_confidence)
    if not found.get("ok"):
        return found
    matches = found.get("matches", [])
    if not matches:
        return {"ok": False, "error": f"text not found on screen: {query!r}"}
    idx = int(index)
    if idx < 0 or idx >= len(matches):
        return {
            "ok": False,
            "error": f"requested match index {index} out of range ({len(matches)} "
            f"match(es) found for {query!r})",
        }
    target = matches[idx]
    c_res = click(
        target["x"], target["y"], button=button, clicks=clicks, modifiers=modifiers
    )
    return {
        "ok": bool(c_res.get("ok")),
        "query": query,
        "matched": target,
        "target": target,
        "index": idx,
        "matches_found": len(matches),
        "click": c_res,
        **({} if c_res.get("ok") else {"error": c_res.get("error")}),
    }


_LAST_ANNOTATED_ELEMENTS: dict[str, dict] = {}


def click_element(element_id, button="left", clicks=1, modifiers=None):
    (
        """Click a Set-of-Marks annotated UI element by its integer badge ID [1], """
        """[2], """
        """..."""
    )
    try:
        eid = int(element_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"invalid element id: {element_id!r}"}
    el = _LAST_ANNOTATED_ELEMENTS.get(eid)
    if not el:
        if not _LAST_ANNOTATED_ELEMENTS:
            return {
                "ok": False,
                "error": "no screen annotations available; call "
                "observe_screen(annotate=true) first",
            }
        avail = sorted(_LAST_ANNOTATED_ELEMENTS.keys())[:20]
        return {
            "ok": False,
            "error": f"element [{eid}] not found in last screen annotation (available "
            f"IDs: {avail})",
        }
    c_res = click(el["x"], el["y"], button=button, clicks=clicks, modifiers=modifiers)
    return {
        "ok": bool(c_res.get("ok")),
        "id": eid,
        "text": el.get("text", ""),
        "x": el["x"],
        "y": el["y"],
        "box": el.get("box"),
        "element": el,
        "click": c_res,
        **({} if c_res.get("ok") else {"error": c_res.get("error")}),
    }


def annotate_screen(
    image_path, region=None, output_path=None, max_elements=50, mode="auto"
):
    (
        """Annotate screenshot with Set-of-Marks (SoM) numbered badges over detected """
        """UI """
        """elements."""
    )
    global _LAST_ANNOTATED_ELEMENTS
    conv = shutil.which("magick") or shutil.which("convert")
    if not conv:
        return {
            "ok": False,
            "error": "ImageMagick (magick/convert) required for visual element "
            "annotation",
        }

    ocr = ocr_screen(image_path=image_path, region=region, min_confidence=40)
    if not ocr.get("ok"):
        return ocr

    lines = ocr.get("lines", [])
    words = ocr.get("words", [])

    if mode == "lines" and lines:
        candidates = [line for line in lines if len(line.get("text", "").strip()) > 1]
    elif mode == "words" or not lines:
        candidates = [w for w in words if len(w.get("text", "").strip()) > 1]
    else:  # mode=="auto": line blocks for short phrases/buttons, words for long blocks
        candidates = []
        for line in lines:
            t = line.get("text", "").strip()
            if 1 < len(t) <= 50:
                candidates.append(line)
        cand_boxes = [c["box"] for c in candidates if "box" in c]
        for w in words:
            if len(w.get("text", "").strip()) <= 1:
                continue
            wx, wy, ww, wh = w.get(
                "box",
                (
                    w.get("left", 0),
                    w.get("top", 0),
                    w.get("width", 0),
                    w.get("height", 0),
                ),
            )
            inside = any(
                bx <= wx
                and by <= wy
                and (bx + bw) >= (wx + ww)
                and (by + bh) >= (wy + wh)
                for bx, by, bw, bh in cand_boxes
            )
            if not inside:
                candidates.append(w)

    candidates.sort(
        key=lambda e: (e.get("top", e.get("y", 0)), e.get("left", e.get("x", 0)))
    )
    chosen = candidates[:max_elements]

    dst = str(output_path or image_path)
    if not chosen:
        _LAST_ANNOTATED_ELEMENTS = {}
        if output_path and Path(output_path) != Path(image_path):
            try:
                shutil.copyfile(str(image_path), str(output_path))
            except Exception:
                pass
        return {"ok": True, "path": dst, "count": 0, "elements": []}

    draws = []
    elements_out = []

    for idx, el in enumerate(chosen, 1):
        x1 = el.get("left", el.get("x", 0))
        y1 = el.get("top", el.get("y", 0))
        w = el.get("width", el.get("w", 0))
        h = el.get("height", el.get("h", 0))
        x2, y2 = x1 + w, y1 + h
        cx = el.get("center_x", x1 + w // 2)
        cy = el.get("center_y", y1 + h // 2)

        draws.append(
            f"stroke rgba(0,255,255,0.7) stroke-width 1 fill rgba(0,255,255,0.06) "
            f"rectangle {x1},{y1} {x2},{y2}"
        )
        by = max(0, y1 - 13)
        bx = x1
        bw = len(str(idx)) * 8 + 6
        draws.append(
            f"stroke rgba(0,255,255,0.85) stroke-width 1 fill rgba(0,0,0,0.85) "
            f"roundrectangle {bx},{by} {bx + bw},{by + 12} 2,2"
        )
        draws.append(f'stroke none fill yellow text {bx + 3},{by + 9} "[{idx}]"')

        elements_out.append(
            {
                "id": idx,
                "text": el.get("text", ""),
                "x": cx,
                "y": cy,
                "box": [x1, y1, w, h],
                "confidence": round(el.get("confidence", 80.0), 1),
            }
        )

    cmd = [
        conv,
        str(image_path),
        "-font",
        "DejaVu-Sans",
        "-pointsize",
        "9",
        "-draw",
        " ".join(draws),
        dst,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        if r.returncode != 0:
            return {"ok": False, "error": f"annotation failed: {r.stderr[:200]}"}
        _LAST_ANNOTATED_ELEMENTS = {el["id"]: el for el in elements_out}
        return {
            "ok": True,
            "path": dst,
            "count": len(elements_out),
            "elements": elements_out,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def compare_regions(before_path, after_path=None, region=None, tolerance=0.01):
    (
        """Compare a screen region across two captures using perceptual pixel error """
        """(ImageMagick compare)."""
    )
    conv = shutil.which("magick") or shutil.which("convert")
    comp = shutil.which("compare")
    if not conv or not comp:
        return {
            "ok": False,
            "error": "ImageMagick (compare/magick) required for region comparison",
        }

    if isinstance(before_path, (list, tuple)) and region is None:
        region = before_path
        before_path = after_path
        after_path = None

    tmp_after = None
    if not after_path or not Path(after_path).exists():
        tmp_after = (
            TMP / f"argus-comp-after-{os.getpid()}-{int(time.time() * 1000)}.png"
        )
        shot = screenshot(tmp_after, mode="fullscreen")
        if not shot.get("ok"):
            return shot
        p_after = tmp_after
    else:
        p_after = Path(after_path)

    if not before_path or not Path(before_path).exists():
        if tmp_after:
            tmp_after.unlink(missing_ok=True)
        return {"ok": False, "error": "before_path image required for comparison"}

    p_before = Path(before_path)

    if region:
        rx, ry, rw, rh = (int(v) for v in region)
    else:
        bw, bh = _read_image_dimensions(p_before)
        rx, ry, rw, rh = 0, 0, (bw or 1920), (bh or 1080)

    total_px = rw * rh
    c_before = TMP / f"argus-crop-b4-{os.getpid()}-{int(time.time() * 1000)}.png"
    c_after = TMP / f"argus-crop-aft-{os.getpid()}-{int(time.time() * 1000)}.png"
    diff_out = TMP / f"argus-diff-{os.getpid()}-{int(time.time() * 1000)}.png"

    try:
        if region:
            subprocess.run(
                [
                    conv,
                    str(p_before),
                    "-crop",
                    f"{rw}x{rh}+{rx}+{ry}",
                    "+repage",
                    str(c_before),
                ],
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                [
                    conv,
                    str(p_after),
                    "-crop",
                    f"{rw}x{rh}+{rx}+{ry}",
                    "+repage",
                    str(c_after),
                ],
                capture_output=True,
                timeout=10,
            )
            src_a = c_before
            src_b = c_after
        else:
            src_a = p_before
            src_b = p_after

        r = subprocess.run(
            [comp, "-metric", "AE", str(src_a), str(src_b), str(diff_out)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (r.stderr or "").strip()
        m = re.search(r"([\d\.]+)\s*\(([\d\.]+)\)", output)
        if m:
            diff_pixels = float(m.group(1))
            diff_ratio = float(m.group(2))
        else:
            try:
                diff_pixels = float(output) if output else 0.0
                diff_ratio = diff_pixels / total_px if total_px > 0 else 0.0
            except ValueError:
                diff_pixels = 0.0
                diff_ratio = 0.0

        changed = diff_ratio > float(tolerance)
        return {
            "ok": True,
            "region": [rx, ry, rw, rh],
            "diff_pixels": int(round(diff_pixels)),
            "diff_ratio": round(diff_ratio, 4),
            "diff_percent": round(diff_ratio * 100, 3),
            "total_pixels": total_px,
            "changed": changed,
            "tolerance_percent": round(float(tolerance) * 100, 3),
            "diff_image_path": str(diff_out) if diff_out.exists() else None,
        }
    finally:
        c_before.unlink(missing_ok=True)
        c_after.unlink(missing_ok=True)
        if tmp_after:
            tmp_after.unlink(missing_ok=True)


# ── pointer / keyboard ───────────────────────────────────────────────────


def _uinput_loaded():
    """uinput is a *misc* device (major 10), so it is listed in /proc/misc —
    not /proc/devices. Checking only the latter reported "module not loaded"
    even when injection worked fine."""
    for path in ("/proc/misc", "/proc/devices"):
        try:
            if "uinput" in Path(path).read_text().lower():
                return True
        except Exception:
            pass
    return False


def _ydotool_socket():
    """ydotoold's socket: $YDOTOOL_SOCKET, else $XDG_RUNTIME_DIR/.ydotool_socket
    (the packaged unit's default), else the legacy /tmp path."""
    env = os.environ.get("YDOTOOL_SOCKET")
    if env:
        return env
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    for cand in (f"{runtime}/.ydotool_socket", "/tmp/.ydotool_socket"):
        if os.path.exists(cand):
            return cand
    return f"{runtime}/.ydotool_socket"


def pointer_status():
    """(available, reason) — never claims mouse control it does not have.

    Note this only confirms the daemon is reachable, not that any single
    move lands exactly. Absolute positioning (`mousemove --absolute`) is
    uncalibrated on this host (`ydotoold --touch-on` fails outright on the
    packaged ydotool 1.0.4-2.1 — exits status 2 with no diagnostic — so the
    daemon runs without EV_ABS support), which is why move/click/drag below
    don't trust it: they read the real cursor position back through KWin
    scripting and correct with relative moves until it converges
    (see _place_pointer). Positioning is therefore verified per call, not
    assumed from the daemon being up.
    """
    if not shutil.which("ydotool"):
        return False, "ydotool not installed"
    if not _uinput_loaded():
        return False, (
            "uinput kernel module not loaded — the running kernel's "
            "modules are missing (kernel updated without reboot?)"
        )
    sock = _ydotool_socket()
    if not os.path.exists(sock):
        return False, (
            f"ydotoold not running (no socket at {sock}); "
            "start it with: systemctl --user start ydotool"
        )
    return True, "ok (closed-loop: every placement is verified via KWin cursorPos)"


def _ydotool(args, timeout=20):
    ok, why = pointer_status()
    if not ok:
        return {"ok": False, "error": why}
    env = dict(os.environ)
    env.setdefault("YDOTOOL_SOCKET", _ydotool_socket())
    try:
        r = subprocess.run(
            ["ydotool", *args], capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ydotool timed out"}
    return {"ok": r.returncode == 0, "error": (r.stderr or "")[:300]}


def move_pointer(x, y):
    """Move the pointer to (x, y), verified. See _place_pointer."""
    return _place_pointer(x, y)


# ydotool's button byte is a base (which button) OR'd with a mask (down /
# up / both) — see `ydotool click --help`: 0x00 left, 0x01 right, 0x02
# middle; 0x40 press-only, 0x80 release-only, 0xC0 (0x40|0x80) a full click.
_BTN_BASE = {"left": 0x00, "right": 0x01, "middle": 0x02}


def _click_code(button, mask):
    return f"0x{_BTN_BASE.get(button, 0x00) | mask:02X}"


# ── closed-loop pointer placement ──────────────────────────────────────
# `ydotoold --touch-on` (real EV_ABS positioning) fails on this host, so
# `mousemove --absolute` lands nowhere near the request (verified: (2000,
# 1100) on a 3840x2160 screen landed near (20, 15)). KWin scripting can
# READ workspace.cursorPos but not set it (the assignment is silently
# ignored on Wayland — verified live), so absolute placement is replaced
# with a read → relative-move → re-read loop: relative REL_X/REL_Y events
# need no calibration, and pointer acceleration only costs extra
# correction rounds, not accuracy, because every round re-reads the true
# position. Nothing here ever reports a coordinate it didn't measure.
#
# That loop alone was still not enough: it compares against
# workspace.cursorPos, which is logical pixels, while every (x, y) a caller
# actually has came from a screenshot, which is physical pixels — on this
# host's 1.7x-scaled output that mismatch alone (not pointer acceleration)
# is what "did not converge" almost always meant, because the requested
# point was often 1.7x farther from the origin than the logical screen is
# wide, so the cursor walked to the edge and stuck there. See
# to_logical_px/to_screenshot_px, applied at _place_pointer's boundary.

_JS_CURSOR = """
(function () {
    var p = workspace.cursorPos;
    console.info(
        "__MARKER__" + JSON.stringify({x: Math.round(p.x), y: Math.round(p.y)}));
})();
"""

POINTER_TOLERANCE_PX = 4
POINTER_MAX_CORRECTIONS = 6


def cursor_position(timeout=5):
    """Current pointer position as {ok, x, y}. Read-only by necessity —
    setting workspace.cursorPos from a script is ignored on Wayland."""
    try:
        raw = run_script(_JS_CURSOR, "ARGUS_CURSOR_", timeout=timeout)
    except Exception as e:
        return {"ok": False, "error": f"cursor query failed: {e}"}
    if not raw:
        return {
            "ok": False,
            "error": "cursor query returned nothing (KWin scripting unreachable?)",
        }
    try:
        pos = json.loads(raw)
        return {"ok": True, "x": int(pos["x"]), "y": int(pos["y"])}
    except Exception:
        return {"ok": False, "error": f"unparseable cursor reply: {raw[:120]}"}


def _place_pointer(x, y):
    """Move the pointer to (x, y) — screenshot-pixel coordinates, like
    observe_screen's images — verifying it actually got there.

    Returns a dict that ALWAYS carries the measured position, in
    screenshot-pixel space: {ok, x, y, requested, residual, corrections,
    verified}. ok is True only when the measured position is within
    POINTER_TOLERANCE_PX (logical px) of the request (or the cursor was
    already there). Callers must read x/y, not assume the request — a
    failed placement still reports where the pointer really is so the
    model can adjust instead of clicking blind. Internally everything is
    measured and corrected in KWin's own logical coordinate space (that's
    what cursor_position()/ydotool actually operate in); only the input and
    the fields reported back are converted, at the two boundaries — see
    to_logical_px/to_screenshot_px and the module comment above _JS_LIST.
    """
    tx, ty = to_logical_px(x, y)
    requested = [int(x), int(y)]
    cur = cursor_position()
    if not cur.get("ok"):
        # Can't see the cursor: one absolute attempt, honestly flagged.
        # This is the old behavior, kept only as a degraded fallback.
        moved = _ydotool(["mousemove", "--absolute", str(tx), str(ty)])
        return {
            "ok": bool(moved.get("ok")),
            "x": None,
            "y": None,
            "requested": requested,
            "residual": None,
            "corrections": 0,
            "verified": False,
            "error": moved.get("error") or cur.get("error"),
            "note": "cursor unreadable — placement unverified",
        }
    corrections = 0
    for _ in range(1 + POINTER_MAX_CORRECTIONS):
        dx, dy = tx - cur["x"], ty - cur["y"]
        if abs(dx) <= POINTER_TOLERANCE_PX and abs(dy) <= POINTER_TOLERANCE_PX:
            mx, my = to_screenshot_px(cur["x"], cur["y"])
            return {
                "ok": True,
                "x": mx,
                "y": my,
                "requested": requested,
                "residual": round(max(abs(dx), abs(dy)) * _screen_scale()),
                "corrections": corrections,
                "verified": True,
            }
        # Full stride on the first round (fast when unaccelerated, the
        # common case), half strides after: a proportional correction with
        # gain 1 oscillates when pointer acceleration overshoots (gain*accel
        # > 1 diverges — verified in test with a 1.6x simulated cursor),
        # while gain 0.5 converges geometrically for any accel below 4x.
        gain = 1.0 if corrections == 0 else 0.5
        sx, sy = int(round(dx * gain)), int(round(dy * gain))
        # Relative step: -x/-y flags (the "-- dx dy" form misparses
        # negative deltas on this ydotool build).
        step = _ydotool(["mousemove", "-x", str(sx), "-y", str(sy)])
        if not step.get("ok"):
            mx, my = to_screenshot_px(cur["x"], cur["y"])
            return {
                "ok": False,
                "x": mx,
                "y": my,
                "requested": requested,
                "residual": round(max(abs(dx), abs(dy)) * _screen_scale()),
                "corrections": corrections,
                "verified": True,
                "error": step.get("error") or "relative move failed",
            }
        corrections += 1
        cur = cursor_position()
        if not cur.get("ok"):
            return {
                "ok": False,
                "x": None,
                "y": None,
                "requested": requested,
                "residual": None,
                "corrections": corrections,
                "verified": False,
                "error": cur.get("error"),
            }
    dx, dy = tx - cur["x"], ty - cur["y"]
    mx, my = to_screenshot_px(cur["x"], cur["y"])
    return {
        "ok": False,
        "x": mx,
        "y": my,
        "requested": requested,
        "residual": round(max(abs(dx), abs(dy)) * _screen_scale()),
        "corrections": corrections,
        "verified": True,
        "error": f"did not converge within {POINTER_TOLERANCE_PX}px (logical) "
        f"after {corrections} corrections (pointer acceleration?)",
        "note": "pointer is at the reported x/y, not at the request",
    }


MOD_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "ctl": "ctrl",
    "alt": "alt",
    "option": "alt",
    "opt": "alt",
    "shift": "shift",
    "super": "logo",
    "win": "logo",
    "cmd": "logo",
    "command": "logo",
    "meta": "logo",
    "logo": "logo",
}

MOD_KEYCODES = {"ctrl": 29, "shift": 42, "alt": 56, "logo": 125}


def _parse_modifiers(mods):
    if not mods:
        return []
    if isinstance(mods, str):
        mods = [m.strip() for m in re.split(r"[+,\s]", mods) if m.strip()]
    out = []
    for m in mods:
        low = str(m).lower()
        if low in MOD_ALIASES:
            canon = MOD_ALIASES[low]
            if canon not in out:
                out.append(canon)
    return out


def click(x, y, button="left", clicks=1, modifiers=None):
    """Move then click, as two separate ydotool invocations.

    ydotool 1.0.4's CLI is `ydotool <cmd> <args>` — exactly one subcommand per
    process; it does not chain `mousemove ... click ...` in a single call the
    way xdotool does. Passing "click 0xC0" as trailing args to `mousemove`
    overflows its fixed-size arg buffer and aborts with "*** stack smashing
    detected ***", so every click silently failed (ok=False) while the model
    kept retrying coordinates that were never the problem. Verified fixed:
    the combined form reliably SIGABRTs (coredumpctl showed four matching
    crashes); two separate calls do not.

    `clicks=2` uses ydotool's own `-r/--repeat`+`-D/--next-delay` rather than
    two separate handler calls, so a double-click can't be split across two
    model round-trips with a stray click of something else landing between.

    `modifiers` can be a list (e.g. ['ctrl'], ['shift']) or chord string.
    Modifier keys are held down during the click and released immediately after.

    Placement is closed-loop (see _place_pointer): the result carries the
    measured click position as x/y.
    """
    placed = _place_pointer(x, y)
    if not placed.get("ok"):
        return placed
    n = max(1, min(int(clicks), 3))
    args = ["click"]
    if n > 1:
        args += ["-r", str(n), "-D", "80"]
    args.append(_click_code(button, 0xC0))
    mod_keys = _parse_modifiers(modifiers)
    for m in mod_keys:
        _ydotool(["key", f"{MOD_KEYCODES[m]}:1"])
    try:
        r = _ydotool(args)
    finally:
        for m in reversed(mod_keys):
            _ydotool(["key", f"{MOD_KEYCODES[m]}:0"])
    out = {
        "ok": bool(r.get("ok")),
        "x": placed["x"],
        "y": placed["y"],
        "requested": placed["requested"],
        "residual": placed["residual"],
        "corrections": placed["corrections"],
        "verified": placed["verified"],
    }
    if mod_keys:
        out["modifiers"] = mod_keys
    if not r.get("ok"):
        out["error"] = r.get("error") or "click failed after successful placement"
    return out


def hover(x, y, duration=0.4):
    (
        """Move the pointer to (x, y) closed-loop and pause to trigger hover """
        """effects/tooltips."""
    )
    placed = _place_pointer(x, y)
    if not placed.get("ok"):
        return placed
    d = max(0.05, min(float(duration), 10.0))
    time.sleep(d)
    out = dict(placed)
    out["hovered_seconds"] = d
    return out


def mouse_down(button="left", x=None, y=None):
    (
        """Press and hold mouse button (left/right/middle), optionally placing """
        """pointer """
        """first."""
    )
    if x is not None and y is not None:
        placed = _place_pointer(x, y)
        if not placed.get("ok"):
            return placed
    r = _ydotool(["click", _click_code(button, 0x40)])
    cur = cursor_position()
    mx, my = to_screenshot_px(cur["x"], cur["y"]) if cur.get("ok") else (x, y)
    out = {"ok": bool(r.get("ok")), "button": button, "x": mx, "y": my}
    if not r.get("ok"):
        out["error"] = r.get("error") or "mouse_down failed"
    return out


def mouse_up(button="left", x=None, y=None):
    (
        """Release a held mouse button (left/right/middle), optionally placing """
        """pointer """
        """first."""
    )
    if x is not None and y is not None:
        placed = _place_pointer(x, y)
        if not placed.get("ok"):
            return placed
    r = _ydotool(["click", _click_code(button, 0x80)])
    cur = cursor_position()
    mx, my = to_screenshot_px(cur["x"], cur["y"]) if cur.get("ok") else (x, y)
    out = {"ok": bool(r.get("ok")), "button": button, "x": mx, "y": my}
    if not r.get("ok"):
        out["error"] = r.get("error") or "mouse_up failed"
    return out


def drag(x1, y1, x2, y2, button="left", steps=1, smooth=True):
    """Press at (x1,y1), move to (x2,y2), release — real press/move/release,
    not a fabricated gesture: ydotool's click mask lets down (0x40) and up
    (0x80) fire as separate events. If steps > 1, generates intermediate relative
    motion ticks so UI widgets and drag-and-drop recognize a continuous drag.
    If smooth is True, uses cosine S-curve easing (easeInOutSine).
    Both ends are placed closed-loop; the result reports the measured start/end
    actually used.
    """
    start = _place_pointer(x1, y1)
    if not start.get("ok"):
        return start
    down = _ydotool(["click", _click_code(button, 0x40)])
    if not down.get("ok"):
        return down
    time.sleep(0.05)

    n_steps = max(1, min(int(steps), 50))
    if n_steps > 1:
        lx1, ly1 = to_logical_px(x1, y1)
        lx2, ly2 = to_logical_px(x2, y2)
        total_dx = lx2 - lx1
        total_dy = ly2 - ly1
        prev_x, prev_y = 0, 0
        for i in range(1, n_steps):
            if smooth:
                frac = 0.5 - 0.5 * math.cos(math.pi * (i / n_steps))
            else:
                frac = i / n_steps
            cur_x = round(total_dx * frac)
            cur_y = round(total_dy * frac)
            step_dx = cur_x - prev_x
            step_dy = cur_y - prev_y
            prev_x, prev_y = cur_x, cur_y
            if step_dx != 0 or step_dy != 0:
                _ydotool(["mousemove", "-x", str(step_dx), "-y", str(step_dy)])
                time.sleep(0.02)

    end = _place_pointer(x2, y2)
    if not end.get("ok"):
        # Best-effort release so a failed mid-drag move never leaves the
        # button physically stuck down for whatever runs next.
        _ydotool(["click", _click_code(button, 0x80)])
        return end
    time.sleep(0.05)
    up = _ydotool(["click", _click_code(button, 0x80)])
    return {
        "ok": bool(up.get("ok")),
        "start": [start["x"], start["y"]],
        "end": [end["x"], end["y"]],
        "verified": start["verified"] and end["verified"],
        **({} if up.get("ok") else {"error": up.get("error") or "release failed"}),
    }


def drag_path(points, button="left", duration=0.5, smooth=True):
    """Perform a continuous drag along a sequence of waypoints: [(x1,y1), (x2,y2), ...].
    Holds the button down, smoothly moves across all waypoints, and releases
    at the final point.
    Ensures the button is always released even on error.
    """
    if not points or len(points) < 2:
        return {
            "ok": False,
            "error": "drag_path requires at least 2 points: [(x1, y1), (x2, y2), ...]",
        }

    clean_pts = []
    for pt in points:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            clean_pts.append((int(pt[0]), int(pt[1])))
        else:
            return {"ok": False, "error": f"Invalid point in points: {pt}"}

    start_x, start_y = clean_pts[0]
    start = _place_pointer(start_x, start_y)
    if not start.get("ok"):
        return start

    down = _ydotool(["click", _click_code(button, 0x40)])
    if not down.get("ok"):
        return down
    time.sleep(0.05)

    button_released = False
    try:
        n_segs = len(clean_pts) - 1
        steps_per_seg = max(2, min(20, int((duration * 30) / max(1, n_segs))))
        step_delay = max(0.005, min(0.05, duration / max(1, n_segs * steps_per_seg)))

        for k in range(n_segs):
            p1 = clean_pts[k]
            p2 = clean_pts[k + 1]
            lx1, ly1 = to_logical_px(p1[0], p1[1])
            lx2, ly2 = to_logical_px(p2[0], p2[1])
            total_dx = lx2 - lx1
            total_dy = ly2 - ly1
            prev_x, prev_y = 0, 0
            for s in range(1, steps_per_seg):
                if smooth:
                    frac = 0.5 - 0.5 * math.cos(math.pi * (s / steps_per_seg))
                else:
                    frac = s / steps_per_seg
                cur_x = round(total_dx * frac)
                cur_y = round(total_dy * frac)
                step_dx = cur_x - prev_x
                step_dy = cur_y - prev_y
                prev_x, prev_y = cur_x, cur_y
                if step_dx != 0 or step_dy != 0:
                    _ydotool(["mousemove", "-x", str(step_dx), "-y", str(step_dy)])
                    time.sleep(step_delay)
            _place_pointer(p2[0], p2[1])

        time.sleep(0.05)
        up = _ydotool(["click", _click_code(button, 0x80)])
        button_released = True
        end_x, end_y = clean_pts[-1]
        cur = cursor_position()
        mx, my = (
            to_screenshot_px(cur["x"], cur["y"]) if cur.get("ok") else (end_x, end_y)
        )
        return {
            "ok": bool(up.get("ok")),
            "button": button,
            "points_count": len(clean_pts),
            "start": [start_x, start_y],
            "end": [mx, my],
            **({} if up.get("ok") else {"error": up.get("error") or "release failed"}),
        }
    finally:
        if not button_released:
            _ydotool(["click", _click_code(button, 0x80)])


def scroll(amount, x=None, y=None, direction="down"):
    """Scroll the wheel by `amount` steps in `direction`
    ('down', 'up', 'left', 'right'),
    optionally moving to (x, y) first. Wheel deltas are relative and calibrated.
    """
    if x is not None and y is not None:
        placed = _place_pointer(x, y)
        if not placed.get("ok"):
            return placed
    amt = max(1, min(abs(int(amount)), 50))
    dir_clean = str(direction).strip().lower()
    if int(amount) < 0 and dir_clean == "down":
        # Preserve direct negative-amount calls (e.g. scroll(-5))
        dx, dy = 0, max(-50, int(amount))
    elif dir_clean == "up":
        dx, dy = 0, -amt
    elif dir_clean == "down":
        dx, dy = 0, amt
    elif dir_clean == "left":
        dx, dy = -amt, 0
    elif dir_clean == "right":
        dx, dy = amt, 0
    else:
        dy = max(-50, min(int(amount), 50))
        dx = 0
    return _ydotool(["mousemove", "--wheel", str(dx), str(dy)])


def type_text(text, clear_before=False):
    """Type text using whichever backend this compositor actually supports.
    If clear_before is True, sends ctrl+a and backspace first.
    If text contains non-ASCII characters and clipboard is available, automatically
    pastes via clipboard for 100% fidelity.
    """
    if clear_before:
        key_press("ctrl+a")
        time.sleep(0.03)
        key_press("backspace")
        time.sleep(0.03)

    if not text.isascii() and shutil.which("wl-copy"):
        cb = clipboard_set(text)
        if cb.get("ok"):
            time.sleep(0.03)
            vp = key_press("ctrl+v")
            if vp.get("ok"):
                return {"ok": True, "pasted": True}

    backend, why = input_backend()
    if backend == "ydotool":
        return _ydotool(["type", "--", text])
    if backend == "wtype":
        r = subprocess.run(
            ["wtype", "--", text], capture_output=True, text=True, timeout=20
        )
        return {"ok": r.returncode == 0, "error": (r.stderr or "")[:300]}
    return {"ok": False, "error": why}


# ── key input ────────────────────────────────────────────────────────────
# Two backends, because they are not interchangeable:
#   ydotool  — uinput, works on any compositor, needs the uinput module
#   wtype    — zwp_virtual_keyboard_manager_v1, wlroots only; KWin does NOT
#              implement it, so on Plasma wtype always fails with
#              "Compositor does not support the virtual keyboard protocol"
# Models also write chords as "ctrl+t", which neither tool accepts directly.

# Linux input-event codes (ydotool) and xkb keysym names (wtype)
KEYCODES = {
    "return": 28,
    "enter": 28,
    "escape": 1,
    "esc": 1,
    "tab": 15,
    "backspace": 14,
    "space": 57,
    "delete": 111,
    "insert": 110,
    "up": 103,
    "down": 108,
    "left": 105,
    "right": 106,
    "home": 102,
    "end": 107,
    "pageup": 104,
    "pagedown": 109,
    "f1": 59,
    "f2": 60,
    "f3": 61,
    "f4": 62,
    "f5": 63,
    "f6": 64,
    "f7": 65,
    "f8": 66,
    "f9": 67,
    "f10": 68,
    "f11": 87,
    "f12": 88,
    "minus": 12,
    "equal": 13,
    "comma": 51,
    "dot": 52,
    "period": 52,
    "slash": 53,
    "semicolon": 39,
    "apostrophe": 40,
    "grave": 41,
    "backtick": 41,
    "tilde": 41,
    "backslash": 43,
    "leftbrace": 26,
    "rightbrace": 27,
    "capslock": 58,
    "caps": 58,
    "numlock": 69,
    "scrolllock": 70,
    "printscreen": 99,
    "print": 99,
    "prtscn": 99,
    "sysrq": 99,
    "super": 125,
    "meta": 125,
    "win": 125,
    "logo": 125,
    "ctrl": 29,
    "control": 29,
    "alt": 56,
    "shift": 42,
    "mute": 113,
    "audiomute": 113,
    "volumedown": 114,
    "voldown": 114,
    "volumeup": 115,
    "volup": 115,
    "menu": 139,
    "playpause": 164,
    "play": 164,
    "pause": 119,
    "nextsong": 163,
    "nexttrack": 163,
    "prevsong": 165,
    "prevtrack": 165,
    "previoussong": 165,
    "brightnessdown": 224,
    "brightnessup": 225,
}
for _n in range(13, 25):
    KEYCODES[f"f{_n}"] = 183 + (_n - 13)
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    KEYCODES[_c] = [
        30,
        48,
        46,
        32,
        18,
        33,
        34,
        35,
        23,
        36,
        37,
        38,
        50,
        49,
        24,
        25,
        16,
        19,
        31,
        20,
        22,
        47,
        17,
        45,
        21,
        44,
    ][_i]
for _i, _c in enumerate("1234567890"):
    KEYCODES[_c] = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11][_i]

# xkb keysym names for wtype (it rejects "Enter"/"Esc" spellings)
KEYSYMS = {
    "return": "Return",
    "enter": "Return",
    "escape": "Escape",
    "esc": "Escape",
    "tab": "Tab",
    "backspace": "BackSpace",
    "space": "space",
    "delete": "Delete",
    "insert": "Insert",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
    "minus": "minus",
    "equal": "equal",
    "comma": "comma",
    "dot": "period",
    "period": "period",
    "slash": "slash",
    "semicolon": "semicolon",
    "apostrophe": "apostrophe",
    "grave": "grave",
    "backslash": "backslash",
    "backtick": "grave",
    "tilde": "asciitilde",
    "leftbrace": "braceleft",
    "rightbrace": "braceright",
    "capslock": "Caps_Lock",
    "caps": "Caps_Lock",
    "numlock": "Num_Lock",
    "scrolllock": "Scroll_Lock",
    "printscreen": "Print",
    "print": "Print",
    "prtscn": "Print",
    "sysrq": "Print",
    "mute": "XF86AudioMute",
    "super": "Super_L",
    "meta": "Super_L",
    "win": "Super_L",
    "logo": "Super_L",
    "ctrl": "Control_L",
    "control": "Control_L",
    "alt": "Alt_L",
    "shift": "Shift_L",
    "audiomute": "XF86AudioMute",
    "volumedown": "XF86AudioLowerVolume",
    "voldown": "XF86AudioLowerVolume",
    "volumeup": "XF86AudioRaiseVolume",
    "volup": "XF86AudioRaiseVolume",
    "menu": "Menu",
    "playpause": "XF86AudioPlay",
    "play": "XF86AudioPlay",
    "pause": "Pause",
    "nextsong": "XF86AudioNext",
    "nexttrack": "XF86AudioNext",
    "prevsong": "XF86AudioPrev",
    "prevtrack": "XF86AudioPrev",
    "previoussong": "XF86AudioPrev",
    "brightnessdown": "XF86MonBrightnessDown",
    "brightnessup": "XF86MonBrightnessUp",
}
for _n in range(1, 25):
    KEYSYMS[f"f{_n}"] = f"F{_n}"

_WTYPE_SUPPORT: dict[str, object] = {}

# The Wayland global a virtual keyboard client binds to. Presence in the
# registry is the compositor's own statement that it implements the protocol.
_VK_GLOBAL = "zwp_virtual_keyboard_manager_v1"


def wayland_globals():
    """Compositor-advertised Wayland globals, or None if they can't be read.

    Read via `wayland-info`, which binds the registry and prints it. This is
    the only side-effect-free way to ask the compositor what it supports:
    unlike a trial keypress it changes nothing, and unlike a version check it
    reports what this compositor actually implements on this session.
    """
    if _have("wayland-info") is None:
        return None
    try:
        r = subprocess.run(
            ["wayland-info"], capture_output=True, text=True, timeout=10
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout or ""


def wtype_supported(probe=False):
    """Does the compositor implement zwp_virtual_keyboard_manager_v1?

    Returns True / False / None (None = could not determine).

    The obvious probe is to run `wtype -k F24` and see whether it complains,
    and that is what this used to do. It injects a real F24 keystroke into
    whatever window has focus, and this function is reached from
    capabilities(), which loop.py calls at the start of every task and `argus
    cli caps` calls on demand — so on any host where wtype *does* work, every
    session start threw a stray F24 into the user's focused application. A
    capability check must not change the desktop it is describing.

    So the question is asked of the compositor instead: does it advertise the
    global? That is a statement by KWin rather than an inference from a failed
    command, and it needs no keypress. The injecting probe survives as
    `probe=True` for a human who wants it confirmed by trial, which is the only
    context where perturbing the desktop is the point.

    On Plasma this answers False, and the earlier trial probe had already
    established why: KWin does not implement zwp_virtual_keyboard_manager_v1
    (wlroots-only), so `input_backend()` reduces to ydotool or nothing. The
    old heuristic also returned True on unrelated failures — its test was
    `"does not support" not in stderr`, so a missing WAYLAND_DISPLAY or a
    permission error selected a wtype backend whose every keypress then failed
    silently. Only "the compositor advertises the protocol" returns True now.
    """
    if "ok" in _WTYPE_SUPPORT and not probe:
        return _WTYPE_SUPPORT["ok"]
    if _have("wtype") is None:
        _WTYPE_SUPPORT["ok"] = False  # no client, so nothing to bind
        return False
    globals_ = wayland_globals()
    if globals_ is not None:
        _WTYPE_SUPPORT["ok"] = _VK_GLOBAL in globals_
        return _WTYPE_SUPPORT["ok"]
    if not probe:
        # Undeterminable without perturbing the desktop. Say so rather than
        # guessing: a wrong True here selects a backend that then fails on
        # every key, which is harder to diagnose than an honest unknown.
        _WTYPE_SUPPORT["ok"] = None
        return None
    try:
        r = subprocess.run(
            ["wtype", "-k", "F24"], capture_output=True, text=True, timeout=10
        )
        _WTYPE_SUPPORT["ok"] = "does not support" not in (r.stderr or "")
    except Exception:
        _WTYPE_SUPPORT["ok"] = False
    return _WTYPE_SUPPORT["ok"]


def _wtype_detail():
    state = wtype_supported()
    if state is True:
        return f"compositor advertises {_VK_GLOBAL}"
    if state is False:
        return (
            f"compositor does not advertise {_VK_GLOBAL} (wlroots-only "
            f"protocol; KWin does not implement it)"
        )
    return (
        "could not read the compositor's advertised globals, and confirming "
        "by trial would inject a real keystroke into the focused window"
    )


def input_backend():
    """(backend, reason) — 'ydotool', 'wtype', or (None, why)."""
    ok, why = pointer_status()
    if ok:
        return "ydotool", "ok"
    if wtype_supported() is True:
        return "wtype", "ok"
    undetermined = (
        " (and the compositor's advertised globals could not be read to "
        "confirm the virtual-keyboard protocol either way)"
        if wtype_supported() is None
        else ""
    )
    return None, (
        "no keyboard backend: wtype needs the virtual-keyboard protocol "
        "(wlroots only — KWin does not implement it), and ydotool needs "
        "uinput (" + why + ")" + undetermined
    )


def parse_chord(spec):
    """'ctrl+t' / 'Ctrl + T' / 'ctrl-shift+t' / 'Return' / 'shift+Page-Down'
    -> (mods, key).

    '-' is only ever consumed as a modifier separator, one recognized
    modifier at a time from the front — never by blanket-replacing every '-'
    in the string with '+' once the chord happens to start with one. That
    blanket replacement used to tear a hyphenated key name in half whenever
    it followed a modifier: 'shift+Page-Down' became tokens ['shift',
    'Page', 'Down'], of which only 'Page' (not a real key on its own) was
    kept as the key and 'Down' was silently dropped — 'Page-Down' alone
    (no modifier) was fine, only the combination broke. Walking the
    modifier chain token-by-token and treating everything from the first
    non-modifier token onward as one key string, hyphens included, fixes
    the combination without changing how a bare hyphenated key parses.
    """
    raw = str(spec).strip()
    if not raw:
        return [], ""
    parts = re.split(
        r"([+\-])", raw
    )  # keeps the separators so the key tail can be rejoined verbatim
    mods, i = [], 0
    while i + 1 < len(parts):
        low = parts[i].strip().lower()
        if low not in MOD_ALIASES:
            break
        mods.append(MOD_ALIASES[low])
        i += 2  # skip this modifier token and the separator right after it
    key = "".join(parts[i:]).strip().lower()
    return mods, key


def _norm_key(k):
    """Canonical lookup key: lowercase, separators removed."""
    return re.sub(r"[\s_-]", "", str(k).lower())


def key_press(key):
    mods, k = parse_chord(key)
    if not k and mods:
        if len(mods) == 1:
            k = mods.pop()
    if not k:
        return {"ok": False, "error": f"no key in {key!r}"}
    backend, why = input_backend()
    if backend == "ydotool":
        code = KEYCODES.get(_norm_key(k))
        if code is None:
            return {
                "ok": False,
                "error": f"unknown key {k!r}",
                "hint": "use names like Return, Escape, Tab, F5, or a single character",
            }
        seq = []
        for m in mods:
            seq.append(f"{MOD_KEYCODES[m]}:1")
        seq.append(f"{code}:1")
        seq.append(f"{code}:0")
        for m in reversed(mods):
            seq.append(f"{MOD_KEYCODES[m]}:0")
        return _ydotool(["key", *seq])
    if backend == "wtype":
        sym = KEYSYMS.get(_norm_key(k), k if len(k) == 1 else None)
        if sym is None:
            return {
                "ok": False,
                "error": f"unknown key {k!r}",
                "hint": "use names like Return, Escape, Tab, F5, or a single character",
            }
        cmd = ["wtype"]
        for m in mods:
            cmd += ["-M", m]
        cmd += ["-k", sym]
        for m in reversed(mods):
            cmd += ["-m", m]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return {"ok": r.returncode == 0, "error": (r.stderr or "")[:300]}
    return {"ok": False, "error": why}


def _lookup_keycode(k):
    """Lookup keycode for single key or modifier name."""
    raw = str(k).strip().lower()
    if raw in MOD_ALIASES:
        return MOD_KEYCODES[MOD_ALIASES[raw]]
    norm = _norm_key(raw)
    if norm in MOD_ALIASES:
        return MOD_KEYCODES[MOD_ALIASES[norm]]
    return KEYCODES.get(norm)


def key_down(key):
    """Press and hold a key down (e.g. 'ctrl', 'shift', 'alt', 'a', 'Return')."""
    backend, why = input_backend()
    if backend == "ydotool":
        code = _lookup_keycode(key)
        if code is None:
            return {"ok": False, "error": f"unknown key {key!r}"}
        return _ydotool(["key", f"{code}:1"])
    if backend == "wtype":
        raw = str(key).strip().lower()
        if raw in MOD_ALIASES:
            canon = MOD_ALIASES[raw]
            r = subprocess.run(
                ["wtype", "-M", canon], capture_output=True, text=True, timeout=10
            )
            return {"ok": r.returncode == 0, "error": (r.stderr or "")[:300]}
        return {
            "ok": False,
            "error": "holding non-modifier keys is only supported on ydotool backend",
        }
    return {"ok": False, "error": why}


def key_up(key):
    """Release a held key (e.g. 'ctrl', 'shift', 'alt', 'a', 'Return')."""
    backend, why = input_backend()
    if backend == "ydotool":
        code = _lookup_keycode(key)
        if code is None:
            return {"ok": False, "error": f"unknown key {key!r}"}
        return _ydotool(["key", f"{code}:0"])
    if backend == "wtype":
        raw = str(key).strip().lower()
        if raw in MOD_ALIASES:
            canon = MOD_ALIASES[raw]
            r = subprocess.run(
                ["wtype", "-m", canon], capture_output=True, text=True, timeout=10
            )
            return {"ok": r.returncode == 0, "error": (r.stderr or "")[:300]}
        return {
            "ok": False,
            "error": "holding non-modifier keys is only supported on ydotool backend",
        }
    return {"ok": False, "error": why}


def clipboard_set(text):
    """Copy text to the system clipboard via wl-copy. Useful for depositing
    long or special-character text into a field reliably in one shot, rather
    than fragile keystroke-by-keystroke injection through type_text.

    wl-copy forks into the background to keep serving paste requests, and
    the forked process inherits whatever file descriptors it was launched
    with. Capturing stdout/stderr via PIPE (the usual subprocess.run pattern)
    means that background process holds the pipe's write end open too, so
    Python's read-until-EOF blocks for the full timeout even though the copy
    itself completes in milliseconds — verified: the call reliably hung ~10s
    while the copy had already succeeded (a concurrent wl-paste read it back
    immediately). stdout/stderr go to DEVNULL instead so there is nothing to
    wait on; the direct child's exit code (the fork happens after argument
    validation) still reports real failures.
    """
    if not shutil.which("wl-copy"):
        return {"ok": False, "error": "wl-copy not installed (package: wl-clipboard)"}
    try:
        r = subprocess.run(
            ["wl-copy"],
            input=text,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "wl-copy timed out"}
    return {"ok": r.returncode == 0}


CLIPBOARD_MAX_CHARS = 20000


def clipboard_get():
    """Read the current system clipboard via wl-paste.

    Unlike every other tool that returns file/command content, this text
    didn't originate from a call the agent made with a bounded size in mind —
    it's whatever the user (or another app) last put on the clipboard, which
    could be an entire copied document. Capped like read_file's content, with
    the same truncation signal, instead of dumping an unbounded blob into the
    model's context on an ordinary clipboard read.
    """
    if not shutil.which("wl-paste"):
        return {"ok": False, "error": "wl-paste not installed (package: wl-clipboard)"}
    try:
        r = subprocess.run(
            ["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=10
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "wl-paste timed out"}
    if r.returncode != 0:
        return {
            "ok": False,
            "error": (r.stderr or "clipboard empty or unavailable")[:300],
        }
    text = r.stdout
    truncated = len(text) > CLIPBOARD_MAX_CHARS
    return {"ok": True, "text": text[:CLIPBOARD_MAX_CHARS], "truncated": truncated}


CAPABILITY_REQUIRES = {
    # Binary-gated capabilities, each naming *every* prerequisite its code
    # path actually shells out to. Computed, not hand-maintained per key in
    # capabilities(), so a capability can't claim to be available while the
    # function behind it returns "ImageMagick required".
    "screenshots": ("spectacle",),
    # wait_for_screen_change is implemented by re-capturing and hashing, so it
    # needs exactly what a capture needs.
    "wait_for_screen_change": ("spectacle",),

    "zoom": ("spectacle", "imagemagick"),
    "coordinate_grid": ("spectacle", "imagemagick"),
    "cursor_stamping": ("spectacle", "imagemagick"),
    "ocr": ("tesseract",),
    # annotate_screen() crops with ImageMagick and then reads the crop with
    # tesseract; either one missing fails the whole thing.
    "visual_annotations": ("spectacle", "tesseract", "imagemagick"),
    # compare_regions() needs `compare` for the metric *and* magick/convert to
    # produce the crops it compares.
    "image_compare": ("compare", "imagemagick"),
    "clipboard": ("wl-copy", "wl-paste"),
    "multi_display": ("kscreen-doctor",),
}

# What still holds even when a capability reports available. These are the
# hard-won host facts that used to exist only as prose in the comments of the
# function that discovered them: a model reading a capability table with no
# caveats will happily trust a capability right up to the moment it is wrong,
# and each entry below is a case where "available" and "works" came apart.
# Exposing them is the point of a specialist agent — this is the knowledge
# that took a live debugging session to accumulate, and it is what a
# third-party agent would otherwise have to rediscover one broken call at a
# time. Keys are capability names; a missing key means "no known caveat".
CAPABILITY_NOTES = {
    "screenshots": (
        "spectacle -b. mode=monitor means THE CURRENT monitor, not a named "
        "one; no output can be selected by name. Regions are captured "
        "fullscreen and cropped afterwards, because spectacle --region is "
        "interactive only. mode=cursor is unreliable on this host (one hang, "
        "four consecutive rc=2 with empty stderr) and falls back to mode=active. "
        "Every coordinate you read is in this capture's pixel space; the "
        "screenshot-to-logical ratio is a single scalar read from the first "
        "enabled output and cached for the lifetime of the process, so a "
        "scale or resolution change is never picked up."
    ),
    "zoom": "1:1 crop of an existing capture; a new fullscreen capture only if "
    "no path was given.",
    "cursor_stamping": (
        "returns False if the cursor position cannot be read, independently "
        "of ImageMagick being present."
    ),
    "visual_annotations": (
        "Set-of-Marks over tesseract output. Element ids come from a "
        "module-global cache that is NOT invalidated by a later screenshot, "
        "so click_element can act on coordinates from an earlier frame."
    ),
    "image_compare": (
        "whole-image pixel diff via `compare -metric AE`; a blinking cursor "
        "is enough to register as changed."
    ),
    "wait_for_screen_change": (
        "polls by re-capturing the full screen and hashing the PNG, once per "
        "poll interval, with no change-detection events. timeout=30 at the "
        "default 0.25s interval is 120 full-resolution captures and ~1GB of "
        "hashing. Prefer a short timeout, or cursor_position, to confirm a move."
    ),
    "pointer": (
        "uinput events are indistinguishable from a physical device to KWin. "
        "There is no compositor-enforced scoping, no per-session consent, and "
        "no way to tell an agent click from a user click. Placement is "
        "verified by re-reading KWin cursorPos, not reported by the compositor."
    ),
    "keyboard": (
        "wtype is dead on KWin (zwp_virtual_keyboard_manager_v1 is wlroots "
        "only), so the keyboard path is uinput or nothing — including on hosts "
        "where a virtual keyboard would otherwise be available."
    ),
    "multi_display": (
        "screen scale is a SINGLE scalar read from the first enabled output, "
        "cached for the process lifetime. Mixed-DPI multi-monitor is therefore "
        "wrong on every output but the first, and a scale/resolution/hotplug "
        "change is never picked up. Output rotation is not handled at all. "
        "Prefer window-relative coordinates to absolute ones."
    ),
    "window_inventory": (
        "via KWin scripting, whose results come back by scraping the user "
        "journal for a per-call nonce. If scripting fails the fallback is the "
        "KRunner windows runner plus org.kde.KWin.getWindowInfo, which is a "
        "KWin 5 API and may not exist on KWin 6 — and the fallback cannot be "
        "distinguished from 'no windows are open' by the caller."
    ),
    "window_control": (
        "activate_window is verified against the compositor; close, move, "
        "maximize and minimize report only that the call was issued, not that "
        "it took effect."
    ),
    "window_relative_coords": (
        "windows are resolved by exact internalId, or else by FIRST "
        "caption/class substring match in stacking order. A window whose title "
        "happens to contain the target string can be selected instead, and the "
        "ambiguity is not reported."
    ),
    "app_orchestration": (
        "focus_or_launch matches existing windows by substring, then falls "
        "back to PATH lookup, then gtk-launch. launch_app additionally execs "
        "a .desktop file's Exec= line through sh -c."
    ),
    "batch_actions": (
        "desktop_actions has no cap on the number of actions, so one call can "
        "inject unbounded input. There is no rate limit and no arbitration "
        "with the user anywhere in the input path."
    ),
}


def _missing_for(capability):
    """(bool, [missing], [present]) for a binary-gated capability."""
    missing, present = [], []
    for token in CAPABILITY_REQUIRES.get(capability, ()):
        found = _imagemagick() if token == "imagemagick" else _have(token)
        (present if found else missing).append(token)
    return not missing, missing, present


def capabilities():
    """Flat availability map, one key per capability.

    Binary-gated keys are computed from CAPABILITY_REQUIRES, so a key is True
    only when every prerequisite of the function behind it is present. The
    input/perception keys that depend on a live probe rather than a file on
    disk are still probed, because "is there a binary named ydotool" says
    nothing about whether injection works — that is the whole reason
    pointer_status() checks /proc/misc and the ydotoold socket and reports an
    actionable reason. For the detail behind each key, including the caveats
    that apply even when it is True, see capability_report().
    """
    ptr_ok, ptr_why = pointer_status()
    kb_backend, kb_detail = input_backend()
    scripting = (
        run_script(
            "(function(){ console.info('__MARKER__ok'); })();",
            "ARGUS_PROBE_",
            timeout=5,
        )
        is not None
    )
    kwin_up = available()
    caps = {
        # --- probed, not inferred from a binary name ---
        "kwin_dbus": kwin_up,
        # The KRunner/getWindowInfo fallback is KWin-5 era and unprobed, so
        # this used to report yes on the strength of KWin merely being
        # reachable. Scripting is the only path actually verified here.
        "window_inventory": scripting,
        "window_control": scripting,
        "window_relative_coords": scripting,
        "window_inventory_detail": (
            "ok (KWin scripting loaded, ran and returned a marked result)"
            if scripting
            else "KWin scripting did not return a result within 5s. The "
            "KRunner/getWindowInfo fallback is KWin-5 era and is not "
            "probed, so window inventory is reported unavailable rather "
            "than guessed."
        ),
        "keyboard": kb_backend is not None,
        "keyboard_backend": kb_backend,
        "keyboard_detail": kb_detail,
        # None means "could not determine", which is not the same as False
        # and must not be flattened into it.
        "wtype_supported": wtype_supported(),
        "wtype_supported_detail": _wtype_detail(),
        "pointer": ptr_ok,
        "pointer_detail": ptr_why,
        # --- everything below shares the pointer's uinput backend ---
        "scroll": ptr_ok,
        "directional_scroll": ptr_ok,
        "drag": ptr_ok,
        "drag_interpolation": ptr_ok,
        "smooth_drag": ptr_ok,
        "gestures": ptr_ok,
        "mouse_down_up": ptr_ok,
        "click_modifiers": ptr_ok,
        "hover": ptr_ok,
        "click_element": ptr_ok,
        "key_down_up": kb_backend is not None,
        "batch_actions": ptr_ok,
        # --- binary-gated, computed from CAPABILITY_REQUIRES ---
        "grim": _have("grim") is not None,
        "screen_scale": _screen_scale(),
    }
    for name in CAPABILITY_REQUIRES:
        caps[name] = _missing_for(name)[0]
    # kscreen-doctor being installed is not the same as there being a second
    # display, so this one is asked rather than assumed. It costs one more
    # query on top of the one _screen_scale() already made.
    md_ok, md_missing, _ = _missing_for("multi_display")
    md_count = 0
    if md_ok:
        md_count = display_info().get("count") or 0
    caps["multi_display"] = md_ok and md_count > 1
    caps["multi_display_detail"] = (
        f"ok ({md_count} enabled outputs)"
        if caps["multi_display"]
        else (
            "install: " + ", ".join(md_missing)
            if md_missing
            else f"only {md_count} enabled output(s) — nothing to switch between"
        )
    )
    # Was hardcoded True, i.e. never probed and always yes. It means "is there
    # any way to start a desktop entry": gio for tools.py's launch_app,
    # gtk-launch for this module's own focus_or_launch fallback. Either will
    # do, so it is an any-of rather than another entry in the table above.
    caps["app_orchestration"] = bool(_have("gio") or _have("gtk-launch"))
    caps["app_orchestration_detail"] = (
        "ok"
        if caps["app_orchestration"]
        else "no gio and no gtk-launch — desktop entries cannot be started"
    )
    # Not a capability, a known-bad idea on this platform, reported so the
    # model does not reach for it: wlr-screencopy is a wlroots protocol and
    # KWin does not implement it, so grim is only ever useful on a wlroots
    # compositor. observe_screen's spectacle path is the one that works here.
    caps["grim"] = caps["grim"] and not kwin_up
    caps["grim_detail"] = (
        "ok (no KWin on this display, so wlr-screencopy may be available)"
        if caps["grim"]
        else (
            "wlr-screencopy is a wlroots protocol and KWin does not implement "
            "it — grim cannot capture on this session. Use observe_screen."
            if kwin_up
            else "grim not installed"
        )
    )
    return caps


CAPS_CACHE_MAX_AGE = 120.0


def _caps_cache_path():
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, "argus", "caps.json")


def capabilities_cached(max_age=CAPS_CACHE_MAX_AGE):
    """capabilities(), reusing a live probe up to `max_age` seconds old.

    The full probe spawns ~9 subprocesses (KWin scripting round trip,
    busctl, kscreen) and cost ~120ms at the start of *every* task — each
    message runs in a fresh worker, so nothing in-process survived. The
    daemon refreshes this cache in the background (startup, after each
    task, when the panel opens), so a task normally finds it warm; a stale
    or missing cache falls back to probing live, exactly as before.
    """
    path = _caps_cache_path()
    try:
        if time.time() - os.path.getmtime(path) <= max_age:
            with open(path, encoding="utf-8") as fh:
                caps = json.load(fh)
            if isinstance(caps, dict) and caps:
                return caps
    except (OSError, ValueError):
        pass
    return refresh_capabilities_cache()


def refresh_capabilities_cache():
    """Probe live and atomically rewrite the cache; returns the fresh map."""
    caps = capabilities()
    path = _caps_cache_path()
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(caps, fh)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        pass
    return caps


def capability_report(flat=None):
    """Per-capability detail: available, what is missing, and known caveats.

    The flat map in capabilities() answers "can I do this". This answers "can
    I do this, and what will bite me if I do" — which is the half that used to
    be unavailable to anyone but the author, because it lived in the comments
    beside the code that had to discover it. It is deliberately shaped for a
    third-party agent: every unavailable capability carries the specific fix,
    and every available one carries its limitation.

    Pass `flat` to reuse an already-computed capabilities() map. Probing is
    not free — it loads a KWin script and shells out several times — so the
    caller that just called capabilities() should hand the result here rather
    than have this call it a second time.
    """
    flat = capabilities() if flat is None else flat
    report = {}
    for name, available in flat.items():
        if not isinstance(available, bool):
            continue  # keyboard_backend, pointer_detail, screen_scale, ...
        entry = {"available": available}
        ok, missing, present = _missing_for(name)
        if CAPABILITY_REQUIRES.get(name) and not ok:
            entry["missing"] = missing
            entry["fix"] = "install: " + ", ".join(missing)
        if not available and "fix" not in entry:
            detail = flat.get(name + "_detail")
            if detail:
                entry["why"] = detail
        note = CAPABILITY_NOTES.get(name)
        if note:
            entry["caveat"] = note
        report[name] = entry
    return report
