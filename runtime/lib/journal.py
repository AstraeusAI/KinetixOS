"""SQLite journal: events, session state, memories, compaction, context."""

import base64
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

from . import errlog
from .config import DATA, DB, _env_int
from .prompt import SYSTEM_PROMPT
from .render import tool_result_text

MAX_CONTEXT_CHARS = _env_int("ARGUS_MAX_CONTEXT_CHARS", 160_000, 20_000)
MAX_CONTEXT_EVENTS = _env_int("ARGUS_MAX_CONTEXT_EVENTS", 120, 20)
# The last 3 summaries are injected verbatim into every request, so their size
# is part of the context ceiling even though it is not part of the event window.
SUMMARY_CHARS = _env_int("ARGUS_SUMMARY_CHARS", 12_000, 2_000)
KEEP_EVENTS = _env_int("ARGUS_KEEP_EVENTS", 36, 8)
# Only the newest capture is attached. Every step used to re-attach the last two
# observe_screen images regardless of age, so a 24-step computer-use task
# re-uploaded the same screenshots on all 24 provider calls.
MAX_IMAGES = int(os.environ.get("ARGUS_MAX_IMAGES", "1"))

# ── journal ──────────────────────────────────────────────────────────────


def now():
    """Unix timestamp (float) for journal/approval ids."""
    return int(time.time() * 1000)


def connect():
    """Open (and migrate) the session SQLite journal; WAL mode."""
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(
        (
            "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts INTEGER, "
            "session TEXT, kind TEXT, payload TEXT);\n"
            "CREATE TABLE IF NOT EXISTS archived_events(id INTEGER PRIMARY KEY, ts "
            "INTEGER, session TEXT, kind TEXT, payload TEXT, archived_at INTEGER);\n"
            "CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY, ts "
            "INTEGER, text TEXT, source TEXT);\n"
            "CREATE TABLE IF NOT EXISTS summaries(id INTEGER PRIMARY KEY, ts INTEGER, "
            "session TEXT, until_id INTEGER, text TEXT);\n"
            "CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, ts "
            "INTEGER, tool TEXT, args TEXT, status TEXT);\n"
            "CREATE TABLE IF NOT EXISTS session_state(session TEXT, key TEXT, "
            "value TEXT, PRIMARY KEY(session,key));"
        )
    )
    cols = {r[1] for r in db.execute("PRAGMA table_info(approvals)").fetchall()}
    if "session" not in cols:
        db.execute("ALTER TABLE approvals ADD COLUMN session TEXT")
        db.commit()
    # Older DBs had summaries with no session column, which made every
    # summary global — one task's compacted history would bleed into an
    # unrelated session's context. Add it; pre-migration rows stay session=NULL
    # and are simply no longer surfaced (they predate per-session scoping).
    cols = {r[1] for r in db.execute("PRAGMA table_info(summaries)").fetchall()}
    if "session" not in cols:
        db.execute("ALTER TABLE summaries ADD COLUMN session TEXT")
        db.commit()
    # The id of the model's own tool_call that is waiting. The approval's id is
    # the runtime's handle on the pending decision; answering the resumed turn
    # needs the *call* id, because the assistant message in the journal declares
    # that id and a tool result keyed to anything else leaves the call
    # unanswered (see argusd.abandon_calls).
    cols = {r[1] for r in db.execute("PRAGMA table_info(approvals)").fetchall()}
    if "call_id" not in cols:
        db.execute("ALTER TABLE approvals ADD COLUMN call_id TEXT")
        db.commit()
    return db


def event(db, session, kind, payload):
    """Append one journaled event row for a session."""
    p = json.dumps(payload)
    db.execute(
        "INSERT INTO events(ts,session,kind,payload) VALUES(?,?,?,?)",
        (now(), session, kind, p),
    )
    # Keeps compact()'s per-step budget check O(1) instead of re-fetching and
    # re-joining the session's whole event history every step — see compact().
    # Same transaction as the insert above, so this costs one more indexed
    # upsert, not an extra commit/fsync.
    delta = len(kind) + 2 + len(p)  # matches compact()'s f"{k}: {p}" format
    db.execute(
        (
            "INSERT INTO session_state(session,key,value) VALUES(?, 'raw_chars', ?)\n"
            "                  ON CONFLICT(session,key) DO UPDATE SET value = "
            "CAST(value AS INTEGER) + ?"
        ),
        (session, str(delta), delta),
    )
    db.commit()


def set_state(db, session, key, value):
    """Upsert one session_state key."""
    db.execute(
        "INSERT OR REPLACE INTO session_state(session,key,value) VALUES(?,?,?)",
        (session, key, str(value)),
    )
    db.commit()


def get_state(db, session, key):
    """Read one session_state key, or None."""
    row = db.execute(
        "SELECT value FROM session_state WHERE session=? AND key=?", (session, key)
    ).fetchone()
    return row[0] if row else None


# ── cross-session memory ────────────────────────────────────────────────
# Unlike session_state/summaries (both keyed by `session`), `memories` is
# global — a fact stored here is visible from every future session, not
# just the one it was learned in. See context()'s "Remembered facts" block.


def add_memory(db, text, source):
    """Persist a durable, cross-session fact. Skips an exact-text duplicate
    so re-running extraction (or the model re-noticing the same fact) does
    not pile up repeats of what is already known."""
    text = text.strip()
    if not text:
        return None
    existing = db.execute("SELECT id FROM memories WHERE text=?", (text,)).fetchone()
    if existing:
        return existing[0]
    cur = db.execute(
        "INSERT INTO memories(ts,text,source) VALUES(?,?,?)", (now(), text, source)
    )
    db.commit()
    return cur.lastrowid


def list_memories(db, limit=200):
    """All durable cross-session facts as dicts."""
    rows = db.execute(
        "SELECT id,ts,text,source FROM memories ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [{"id": i, "ts": t, "text": x, "source": s} for i, t, x, s in rows]


def delete_memory(db, mem_id):
    """Remove one remembered fact by id."""
    db.execute("DELETE FROM memories WHERE id=?", (mem_id,))
    db.commit()


# ── session history ──────────────────────────────────────────────────────


def list_sessions(db, limit=50):
    """One row per session that has ever had a real turn, newest first.
    Every session keeps at least its most recent events (compact() always
    keeps a KEEP_EVENTS tail — see compact()), so this never has to fall
    back to summaries just to find a session at all; current_task is only a
    fallback for the *title* if a session's very first user event is
    somehow missing/malformed.
    """
    # Ordered by MAX(id), not MAX(ts): two sessions can legitimately get their
    # last event in the same millisecond (seen in tests, and plausible for
    # real fast turns too) — id is monotonically increasing with insertion
    # order regardless of clock resolution, so it is the more robust "most
    # recently active" signal. ts is still selected for display.
    rows = db.execute(
        """
        SELECT session, MIN(ts) AS started, MAX(ts) AS last, COUNT(*) AS n
        FROM events WHERE kind IN ('user','assistant') GROUP BY session
        ORDER BY MAX(id) DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    out = []
    for session, started, last, n in rows:
        title = None
        first_user = db.execute(
            "SELECT payload FROM events WHERE session=? AND kind='user' ORDER BY id "
            "LIMIT 1",
            (session,),
        ).fetchone()
        if first_user:
            try:
                title = json.loads(first_user[0]).get("text", "")
            except Exception:
                title = None
        if not title:
            title = get_state(db, session, "current_task") or "(untitled session)"
        out.append(
            {
                "session": session,
                "title": title.strip()[:140],
                "started": started,
                "last": last,
                "events": n,
            }
        )
    return out


def session_transcript(db, session):
    """Human-readable transcript for the History tab: role + text bubbles,
    the shape AgentState.messages already renders on the QML side. Tool
    calls/results are intentionally left out — this is for a human skimming
    what was discussed, not for feeding back to a model (context() does
    that, with the full tool-call/result shape providers actually need).
    """
    rows = (
        db.execute(
            "SELECT ts,kind,payload FROM archived_events WHERE session=? ORDER BY id",
            (session,),
        ).fetchall()
        + db.execute(
            "SELECT ts,kind,payload FROM events WHERE session=? ORDER BY id", (session,)
        ).fetchall()
    )
    out = []
    for ts, kind, payload in rows:
        if kind not in ("user", "assistant"):
            continue
        try:
            text = (json.loads(payload).get("text") or "").strip()
        except Exception:
            continue
        if text:
            out.append({"role": kind, "text": text, "ts": ts})
    return out


def grants():
    # shell defaults on, alongside screen/net: code execution (run_command,
    # and — since the shell-grant-consistency fix — syntax_check/lint/
    # format_file/run_tests too) is core to what a coding agent does, not
    # an opt-in extra. The system prompt tells the model to call
    # syntax_check/lint/tests after every change; with this off by default,
    # every one of those calls came back "shell grant disabled" and the
    # model had no path to actually verify its own work — input (mouse/
    # keyboard control of the shared desktop) stays opt-in, that's a
    # meaningfully different blast radius.
    """Current capability grants (shell/desktop) from journal state."""
    return {
        "screen": os.getenv("ARGUS_GRANT_SCREEN", "1") == "1",
        "input": os.getenv("ARGUS_GRANT_INPUT", "0") == "1",
        "shell": os.getenv("ARGUS_GRANT_SHELL", "1") == "1",
        "net": os.getenv("ARGUS_GRANT_NET", "1") == "1",
    }


def _summarize_event(kind, payload):
    """One line of archived history, as the model will read it after compaction.

    This used to keep the event kind plus the text (or the tool's name), so a
    compacted session remembered that `edit_file` had been called but not
    whether it succeeded, what it wrote, or why it failed — the model could no
    longer tell a completed edit from a broken one. Outcomes are kept, clipped.
    """
    try:
        p = json.loads(payload)
    except Exception:
        return f"{kind} …"
    if kind == "tool":
        res = p.get("result") or {}
        detail = res.get("error") or res.get("path") or res.get("command") or ""
        if not isinstance(detail, str):
            detail = json.dumps(detail)
        detail = " ".join(detail.split())[:140]
        return f"tool {p.get('name', '')} {'ok' if res.get('ok') else 'FAILED'}" + (
            f" — {detail}" if detail else ""
        )
    text = " ".join(str(p.get("text", "")).split())
    return f"{kind} {text[:200]}"


def _safe_window_start(kinds, start):
    """A trailing window of `kinds` (chronological, oldest first) beginning
    at `start` must never open with a "tool" event — that is a tool
    *result*, and every OpenAI-shape provider rejects a request whose tool
    result has no matching tool_calls declaration in the same request. This
    codebase's own journal always writes an assistant message's tool_calls
    immediately followed by that many "tool" events, so walking `start`
    backward past a leading run of "tool" kinds always lands on the
    assistant message that declared them — keeping the pair together.

    Confirmed live as a real, production-breaking bug, not a theoretical
    one: compact()'s old KEEP_EVENTS-sized tail did exactly this once — an
    assistant's two tool_calls got archived while both of their "tool"
    results stayed in the kept tail — and every subsequent turn of that
    session failed identically with "No function call found for function
    call output with call_id ...", forever, because the orphaned pair had
    nowhere to go: it just kept sliding forward as the permanent head of
    the window. context()'s own independent LIMIT-based window has the
    identical vulnerability and uses this same helper.
    """
    idx = max(0, min(start, len(kinds)))
    while idx > 0 and idx < len(kinds) and kinds[idx] == "tool":
        idx -= 1
    return idx


def compact(db, session):
    """Archive old events into a summary so nothing falls out of the model's
    view ungoverned. Two independent triggers: total character volume
    (MAX_CONTEXT_CHARS) and event count (MAX_CONTEXT_EVENTS). The event-count
    trigger matters even when the text is small — context() only ever shows
    the newest MAX_CONTEXT_EVENTS rows, and a single long task can emit far
    more than that in one run() (an assistant + several tool events per step,
    up to MAX_STEPS steps). Without this trigger, events beyond the window —
    including the original task statement — were silently invisible to the
    model with no summary ever written to replace them: the agent would lose
    track of what it was asked to do partway through its own task, not just
    across separate turns.
    """
    import argusd as _facade

    KEEP_EVENTS = _facade.KEEP_EVENTS
    MAX_CONTEXT_EVENTS = _facade.MAX_CONTEXT_EVENTS
    # What has to fit is the request context() builds, not just the events
    # table: the last 3 summaries are injected verbatim on every turn and were
    # never counted here, so the real ceiling was MAX_CONTEXT_CHARS plus up to
    # 3 x SUMMARY_CHARS of summary text that no trigger could see.
    carried = sum(
        len(t)
        for (t,) in db.execute(
            "SELECT text FROM summaries WHERE session=? ORDER BY id DESC LIMIT 3",
            (session,),
        ).fetchall()
    )
    # Cheap path first: this runs every step of run()'s loop, and on most
    # steps nothing needs archiving. `raw_chars` is a running count kept in
    # session_state by event() (updated in the same transaction as each
    # insert, no extra commit) instead of re-fetching and re-joining every
    # event payload in the session just to measure it — with a long task's
    # history growing every step, redoing that full join on every single step
    # made each step a little slower than the last. COUNT(*) is index-only,
    # not a payload scan, so it stays cheap even on the fast path.
    event_count = db.execute(
        "SELECT COUNT(*) FROM events WHERE session=?", (session,)
    ).fetchone()[0]
    raw_chars = int(get_state(db, session, "raw_chars") or 0)
    if raw_chars + carried <= MAX_CONTEXT_CHARS and event_count <= MAX_CONTEXT_EVENTS:
        return None
    # Past the cheap threshold (or it's drifted — raw_chars undercounts by the
    # join's newlines, see event()): fetch for real and archive.
    rows = db.execute(
        "SELECT id,kind,payload FROM events WHERE session=? ORDER BY id", (session,)
    ).fetchall()
    raw = "\n".join(f"{k}: {p}" for _, k, p in rows)
    boundary = _safe_window_start([k for _, k, _ in rows], len(rows) - KEEP_EVENTS)
    old = rows[:boundary]
    if not old:
        set_state(db, session, "raw_chars", str(len(raw)))  # resync the drift
        return None
    summary = "Permanent session record: " + " | ".join(
        _summarize_event(k, p) for _, k, p in old[-120:]
    )
    db.execute(
        "INSERT INTO summaries(ts,session,until_id,text) VALUES(?,?,?,?)",
        (now(), session, old[-1][0], summary[:SUMMARY_CHARS]),
    )
    db.execute(
        "INSERT OR IGNORE INTO archived_events SELECT id,ts,session,kind,payload,? "
        "FROM events WHERE id <= ? AND session=?",
        (now(), old[-1][0], session),
    )
    db.execute("DELETE FROM events WHERE id <= ? AND session=?", (old[-1][0], session))
    kept = rows[boundary:]
    set_state(db, session, "raw_chars", str(sum(len(f"{k}: {p}") for _, k, p in kept)))
    db.commit()
    return {
        "compacted": True,
        "before": len(raw),
        "after": len(summary),
        "archivedEvents": len(old),
    }


# ── images ───────────────────────────────────────────────────────────────

_IMAGE_CACHE: dict[str, str] = {}


def image_payload(path, preserve_raw=False):
    """Attach a screenshot as an image content block if the model takes images."""
    key = f"{path}:raw" if preserve_raw else str(path)
    if not path or key in _IMAGE_CACHE:
        return _IMAGE_CACHE.get(key)
    src = Path(path)
    if not src.exists():
        return None
    is_zoom = preserve_raw or src.name.startswith("zoom-")
    if is_zoom:
        use = src
    else:
        small = src.with_name(src.stem + "-small.jpg")
        conv = shutil.which("magick") or shutil.which("convert")
        if conv and not small.exists():
            try:
                subprocess.run(
                    [conv, str(src), "-resize", "1280x>", "-quality", "70", str(small)],
                    capture_output=True,
                    timeout=25,
                )
            except Exception:
                pass
        use = small if small.exists() else src
    try:
        data = base64.b64encode(use.read_bytes()).decode()
    except Exception:
        return None
    payload = {
        "mime": "image/jpeg" if use.suffix in (".jpg", ".jpeg") else "image/png",
        "b64": data,
    }
    _IMAGE_CACHE[key] = payload
    return payload


# Generous vs. any realistic single-turn tool-call burst: exists purely so
# _safe_window_start has rows to walk backward into when the naive
# MAX_CONTEXT_EVENTS cut lands inside one. Only changes how much is
# over-fetched from SQLite, never the safety guarantee itself.
_WINDOW_SAFETY_MARGIN = 20


def _drop_orphan_tool_results(events, session):
    """Scrub orphaned tool results before assembling history: a "tool" event
    whose call id was never declared by an assistant message in this same
    request is a hard provider-side rejection ("No function call found for
    function call output with call_id ..."). Confirmed live: a blocked
    multi_edit left exactly such an orphan in a session journal, and every
    later turn of that session 400'd identically until a fresh session was
    started. Declarations without results are left alone (the approval flow
    legitimately has in-flight declarations); only results without
    declarations are fatal, so only those are dropped — and logged."""
    declared = set()
    for kind, payload in events:
        if kind != "assistant":
            continue
        try:
            ap = json.loads(payload)
        except Exception:
            continue
        for c in ap.get("tool_calls", []) or []:
            if isinstance(c, dict) and c.get("id"):
                declared.add(c["id"])
    if not declared:
        return events
    kept = []
    for kind, payload in events:
        if kind == "tool":
            try:
                tid = json.loads(payload).get("id", "history")
            except Exception:
                tid = "history"
            if tid != "history" and tid not in declared:
                try:
                    errlog.warning(
                        "orphan_tool_result_dropped", session=session, call_id=tid
                    )
                except Exception:
                    pass
                continue
        kept.append((kind, payload))
    return kept


def context(db, session, ws_info=None, step_info=None):
    """Build the provider message list for the next model turn."""
    import argusd as _facade

    list_memories = _facade.list_memories
    MAX_CONTEXT_EVENTS = _facade.MAX_CONTEXT_EVENTS
    s = db.execute(
        "SELECT text FROM summaries WHERE session=? ORDER BY id DESC LIMIT 3",
        (session,),
    ).fetchall()
    fetched = db.execute(
        "SELECT kind,payload FROM events WHERE session=? ORDER BY id DESC LIMIT ?",
        (session, MAX_CONTEXT_EVENTS + _WINDOW_SAFETY_MARGIN),
    ).fetchall()[::-1]
    start = _safe_window_start(
        [k for k, _ in fetched], len(fetched) - MAX_CONTEXT_EVENTS
    )
    e = fetched[start:]
    # The `cache` tier on each system message is what lets the Anthropic
    # adapter place prompt-cache breakpoints where the content stops changing
    # (see adapters.anthropic_system_blocks). It is metadata only — every
    # other adapter ignores it, and OpenAI/OpenRouter cache the prefix
    # automatically without being told.
    #
    # "stable" = cannot change for the life of a task; "semi" = changes
    # rarely, so a second breakpoint over this band pays for itself across
    # the steps between changes. Anything past the last breakpoint is outside
    # both cache units, which is why the step-budget notice below can change
    # every step without invalidating either.
    messages = [{"role": "system", "content": SYSTEM_PROMPT, "cache": "stable"}]
    if ws_info:
        messages.append({"role": "system", "content": ws_info, "cache": "stable"})
    # Genuinely cross-session (the `memories` table has no session column) —
    # unlike the per-session summaries block right below, this is visible
    # from every future session too, which is the entire point of
    # remember_fact. Capped at 30: this is meant to carry durable facts
    # (preferences, conventions), not grow without bound.
    mems = list_memories(db, limit=30)
    if mems:
        messages.append(
            {
                "role": "system",
                "content": "Remembered facts (from past sessions, "
                "via remember_fact or automatic extraction):\n"
                + "\n".join(f"- {m['text']}" for m in mems),
                "cache": "semi",
            }
        )
    if s:
        messages.append(
            {
                "role": "system",
                "content": "This conversation so far "
                "(condensed, this session only):\n" + "\n".join(x[0] for x in s),
                "cache": "semi",
            }
        )
    # Pinned anchors: sourced from session_state, not the rolling event
    # window, so they survive compaction/trimming and are restated every
    # turn — the model cannot lose track of what it was actually asked to
    # do, or the plan it committed to, just because the raw history scrolled.
    current_task = get_state(db, session, "current_task")
    if current_task:
        messages.append(
            {
                "role": "system",
                "content": "Current task — stay on this, do not "
                "drift into unrelated work: " + current_task,
                "cache": "semi",
            }
        )
    todos_raw = get_state(db, session, "todos")
    if todos_raw:
        try:
            todos = json.loads(todos_raw)
        except Exception:
            todos = []
        if todos:
            lines = "\n".join(
                f"- [{t.get('status', 'pending')}] {t.get('content', '')}"
                for t in todos
            )
            messages.append(
                {
                    "role": "system",
                    "content": "Current plan (update with todo_write "
                    "as steps complete; do not silently abandon pending items):\n"
                    + lines,
                    "cache": "semi",
                }
            )
    no_images = get_state(db, session, "no_image_support") == "1"
    if no_images:
        messages.append(
            {
                "role": "system",
                "content": "This model/provider does not accept "
                "image input — observe_screen still captures a screenshot to disk, "
                "but it is not shown to you. Verify desktop actions with "
                "list_windows/active_window (window titles, geometry, focus) and tool "
                "results instead of visual inspection.",
            }
        )
    if step_info:
        messages.append({"role": "system", "content": step_info})
    images = []
    e = _drop_orphan_tool_results(e, session)
    for kind, payload in e:
        p = json.loads(payload)
        if kind == "user":
            messages.append({"role": "user", "content": p["text"]})
        elif kind == "assistant":
            text = p.get("text", "")
            if text.startswith("⚠️") and not p.get("tool_calls"):
                # finish()'s own error/status text, journaled so the panel's
                # feed never looks like it silently died (see finish()'s
                # docstring) — but it is diagnostic text about what went
                # wrong, not something the model actually said. Feeding it
                # back as history is actively harmful, not just pointless:
                # confirmed live, a session whose provider call failed once
                # kept restating that exact error to itself as its own
                # "previous reply" on every later turn, forever, instead of
                # ever getting a clean look at the actual task again.
                continue
            m = {"role": "assistant", "content": text}
            if p.get("tool_calls"):
                m["tool_calls"] = p["tool_calls"]
            messages.append(m)
        elif kind == "tool":
            res = p.get("result", {})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": p.get("id", "history"),
                    "name": p.get("name", ""),
                    "content": tool_result_text(res),
                }
            )
            if not no_images and res.get("ok"):
                tool_name = p.get("name")
                img_path = res.get("path") or res.get("screenshot_path")
                if img_path and tool_name in (
                    "observe_screen",
                    "zoom_region",
                    "desktop_actions",
                ):
                    img = image_payload(
                        img_path, preserve_raw=(tool_name == "zoom_region")
                    )
                    if img:
                        images.append((img, res, tool_name))
    for img, res, tool_name in images[-MAX_IMAGES:]:
        w, h = res.get("width"), res.get("height")
        scale = res.get("scale")
        if tool_name == "zoom_region":
            caption = (
                "High-resolution 1:1 inspection crop from zoom_region (native "
                "uncompressed pixel detail)."
            )
            if w and h:
                caption += f" Dimensions: {w}x{h} px (scale: {scale or 1.0})."
        elif tool_name == "desktop_actions":
            caption = "Screenshot captured after desktop_actions batch execution."
            if w and h:
                caption += (
                    f" Screen coordinate space: {w}x{h} px (scale: "
                    f"{scale or 1.0}). Input coordinates for desktop_actions must be "
                    f"in this coordinate space."
                )
        else:
            caption = "Screenshot from observe_screen (most recent capture)."
            if w and h:
                caption += (
                    f" Screen coordinate space: {w}x{h} px (scale: "
                    f"{scale or 1.0}). Input coordinates for "
                    f"mouse_click/mouse_move/mouse_drag/desktop_actions must be in "
                    f"this {w}x{h} coordinate space."
                )
        if res.get("grid"):
            step = res.get("grid_step", 100)
            caption += (
                f" A coordinate reference grid is overlaid with pixel markers "
                f"every {step} px."
            )
        if res.get("annotated") and res.get("elements"):
            num_elem = len(res["elements"])
            caption += (
                f" Set-of-Marks (SoM) visual labels [1]..[{num_elem}] are "
                f"overlaid on detected elements."
            )
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": caption},
                    {"type": "image", "mime": img["mime"], "b64": img["b64"]},
                ],
            }
        )
    return messages


def journal_approval_outcome(db, session, answer_id, tool, result):
    """Record the outcome of a call that was waiting for approval.

    The pause journaled a placeholder result for this call id (see run()), so the
    outcome is written over that row rather than appended: the providers reject
    two tool results for one call id exactly as they reject none, and keeping the
    row's position is what makes the resumed turn read as the assistant message
    declaring the calls, immediately followed by one result per call.
    """
    for eid, payload in db.execute(
        "SELECT id,payload FROM events WHERE session=? AND kind='tool' ORDER BY id "
        "DESC",
        (session,),
    ).fetchall():
        body = json.loads(payload)
        if body.get("id") == answer_id and (body.get("result") or {}).get(
            "pending_approval"
        ):
            body["result"] = result
            db.execute(
                "UPDATE events SET payload=? WHERE id=?", (json.dumps(body), eid)
            )
            db.commit()
            return
    event(db, session, "tool", {"id": answer_id, "name": tool, "result": result})


def abandon_calls(db, session, calls, from_index, reason, progress=None):
    """Journal a result for every tool call in this turn that will never run.

    An assistant message that declares N tool calls has to be followed by N tool
    results — OpenAI rejects a turn with an unanswered tool_call_id, and
    Anthropic the same for a tool_use without a tool_result. When the loop
    returns early (a sibling call is awaiting approval, or the task was stopped
    as stuck) the remaining calls used to be dropped silently while still
    journaled as declared, so the *resumed* turn's request was built from a
    history that declared 3 calls and answered 1 (verified) and came back as a
    provider error instead of continuing the task.
    """
    for call in calls[from_index:]:
        fn = call.get("function") or {}
        cid = call.get("id", str(now()))
        event(
            db,
            session,
            "tool",
            {
                "id": cid,
                "name": fn.get("name", ""),
                "result": {"ok": False, "error": reason},
            },
        )
        if progress:
            progress(
                "act", f"{fn.get('name', '')} (not run — {reason})", "blocked", id=cid
            )


_MEMORY_EXTRACTION_PROMPT = (
    "Read this conversation transcript. List any durable facts worth remembering for "
    "every future conversation with this user — a stated preference, a recurring "
    "instruction, a project convention. Do not list anything already known below, "
    "anything specific only to this one task, or anything trivial. One fact per "
    "line, plain self-contained statements, no numbering or bullets. If there is "
    "nothing new worth keeping, reply with exactly: NONE"
)


def extract_memory(session):
    """Fire-and-forget, called once a conversation is actually left behind (see
    SessionHistory.qml's extractMemory, triggered from AgentState.clearMessages)
    — not per task, to avoid doubling provider-call cost/latency on every single
    message for a feature that only matters at a conversation's natural end.
    One small call, seeded with what is already remembered so a session ending
    does not re-propose the same facts every time.
    """
    import argusd as _facade

    provider_call = _facade.provider_call
    db = connect()
    transcript = session_transcript(db, session)
    if not transcript:
        return {"ok": True, "added": 0, "note": "empty session, nothing to extract"}
    known_text = (
        "\n".join(f"- {m['text']}" for m in list_memories(db, limit=200))
        or "(nothing yet)"
    )
    convo = "\n".join(f"{t['role']}: {t['text']}" for t in transcript)[:20_000]
    messages = [
        {
            "role": "system",
            "content": _MEMORY_EXTRACTION_PROMPT + "\n\nAlready known:\n" + known_text,
        },
        {"role": "user", "content": convo},
    ]
    try:
        reply = provider_call(messages, lambda evt: None)
    except Exception as e:
        errlog.warning("extract_memory_failed", session=session, error=str(e)[:300])
        return {"ok": False, "error": str(e)}
    text = (reply.get("choices", [{}])[0].get("message", {}) or {}).get("content") or ""
    added = 0
    for line in text.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if not line or line.upper() == "NONE":
            continue
        if add_memory(db, line, source="auto") is not None:
            added += 1
    return {"ok": True, "added": added}
