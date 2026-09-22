#!/usr/bin/env python3
"""Argus execution runtime.

A real agent loop: journaled, sandboxed, policy-gated, with a coding tool
surface (files, search, exec, LSP) alongside computer use.

Architecture
------------
  journal (SQLite)      every turn, tool call, result, approval, checkpoint
  workspace             one declared project root, plus the whole user home
                        directory; all paths validated against that union
  policy                auto / prompt / deny per capability, with saved rules
  sandbox               bwrap isolation + cgroup limits for executed commands
  tool registry         tools as data (lib/tools.py) — policy, checkpoints and
                        verification are inherited, not re-implemented
  verify pipeline       after any write: syntax check, then lint if available
  providers             OpenAI / Anthropic / OpenRouter / OpenCode / Codex,
                        key or subscription auth, one neutral message format

Streaming: with --stream the runtime emits NDJSON — {"type":"event",...} as
work happens and a final {"type":"result",...} envelope — so the shell can show
progress instead of waiting for the whole task.

NOTE: the SQLite journal is plaintext at rest; `doctor` reports this.
"""
import argparse, base64, json, os, re, shutil, sqlite3, subprocess, sys, time
import urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import daemon, kwin, sandbox, lsp, mcp, errlog, tools as toolreg   # noqa: E402
from lib.workspace import Workspace                     # noqa: E402
from lib.policy import Policy                           # noqa: E402
from lib.checkpoints import Checkpoints                 # noqa: E402

HOME = Path.home()
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "argus"
CONF = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "argus"
DB = DATA / "memory.sqlite3"
def _env_int(name, default, minimum=1):
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


MAX_CONTEXT_CHARS = _env_int("ARGUS_MAX_CONTEXT_CHARS", 160_000, 20_000)
MAX_CONTEXT_EVENTS = _env_int("ARGUS_MAX_CONTEXT_EVENTS", 120, 20)
# The last 3 summaries are injected verbatim into every request, so their size
# is part of the context ceiling even though it is not part of the event window.
SUMMARY_CHARS = _env_int("ARGUS_SUMMARY_CHARS", 12_000, 2_000)
KEEP_EVENTS = _env_int("ARGUS_KEEP_EVENTS", 36, 8)
MAX_TASK_SECONDS = _env_int("ARGUS_MAX_TASK_SECONDS", 1_800, 0)
MAX_STEPS = _env_int("ARGUS_MAX_STEPS", 64, 1)
MAX_STREAM_TRUNCATIONS = _env_int("ARGUS_MAX_STREAM_TRUNCATIONS", 3, 1)
SLOW_TOOL_SECONDS = 15    # a single tool call taking longer than this gets logged
# Only the newest capture is attached. Every step used to re-attach the last two
# observe_screen images regardless of age, so a 24-step computer-use task
# re-uploaded the same screenshots on all 24 provider calls.
MAX_IMAGES = int(os.environ.get("ARGUS_MAX_IMAGES", "1"))
HTTP_TIMEOUT = 90

SYSTEM_PROMPT = (
    "You are Argus, a precise desktop execution agent with a full coding "
    "toolset. Your primary workspace is one declared project directory, but "
    "every file tool (read_file, write_file, edit_file, multi_edit, list_dir, "
    "glob, grep, move_file, make_dir) can also reach anywhere under the "
    "user's home directory — other projects, dotfiles, Downloads, anywhere "
    "under ~ — with no extra step and no approval prompt; only paths outside "
    "both the workspace and the home directory are refused. Don't assume a "
    "path outside the declared workspace is off-limits — try the tool call "
    "before telling the user something can't be done. You write "
    "production-quality code — not the smallest thing "
    "that technically satisfies the request. Work like a senior engineer "
    "producing a change they'd stand behind in review:\n"
    "- Read before you write. Use grep/glob/read_file to find the real code "
    "and its existing conventions — naming, error-handling style, how "
    "similar things are already structured nearby. A change that reads as "
    "if it was always there beats one that's correct but visibly bolted on.\n"
    "- Prefer edit_file (exact string replacement) over rewriting whole files.\n"
    "- No placeholders, stubs, or logic 'left as an exercise' — a task isn't "
    "done until the code actually does what was asked, including the edge "
    "cases the request implies (empty/missing input, the failure path, "
    "what happens if it's called twice) even when the prompt didn't spell "
    "them out. Equally, don't add abstraction, config, or handling for "
    "cases nothing asked for — match the size of the change to the size of "
    "the ask in both directions; three similar lines beat a premature "
    "helper function.\n"
    "- Resource lifecycle is part of correctness, not a nice-to-have: "
    "anything you create that outlives the call that created it — an event "
    "listener, timer/interval, subscription, observer, open handle — needs a "
    "matching teardown at the point whatever it's attached to goes away. "
    "Wiring it once and never removing it demos fine and leaks in real use, "
    "especially for anything attached to a long-lived parent (window, "
    "document, a singleton) from code that runs per-instance (per dialog, "
    "per row, per component) — closing/destroying the instance has to undo "
    "what creating it did, not just remove what's visible.\n"
    "- For visual/UI work, define shared values once — a CSS custom-property "
    "palette, a QML constants singleton (this project's own Theme.qml is the "
    "pattern), a JS/TS constants module — instead of repeating literal "
    "colors, spacing, or sizes across the file. Consistency and easy "
    "re-theming come from one source of truth, not from retyping the same "
    "magic number correctly every time.\n"
    "- When implementing a well-known pattern (retry/backoff, caching, "
    "pagination, auth, rate limiting, a queue, ...), textbook-correct isn't "
    "the same as done: the naive version of most well-known patterns is "
    "missing at least one real-world caveat that experienced engineers "
    "building the real thing hit early — retry logic that doesn't ask "
    "whether the failed operation was safe to repeat, a cache with no "
    "invalidation story, pagination that breaks when a row is inserted "
    "mid-scan. Bring what you actually know about the pattern you're "
    "building, not just the interface it exposes; handle the caveat or "
    "name the tradeoff in what you hand back, don't ship the naive version "
    "silently.\n"
    "- Releasing and reacquiring a lock is not a no-op for the values you "
    "read under it: anything you computed while holding it the first time "
    "can be stale by the second acquisition — another thread had the gap "
    "between them to run. Don't trust an earlier snapshot for a decision "
    "made after reacquiring; recompute it, or hold the lock across both "
    "the read and the decision. This matters most right before a derived "
    "value goes somewhere with its own preconditions (a sleep()/wait() "
    "call that rejects a negative duration, an index, a divisor) — a "
    "value that was clamped to a safe range under the first lock is not "
    "guaranteed to still be in that range under the second one.\n"
    "- Default to no comments. Names and structure should make the code "
    "self-explanatory; add a comment only when the WHY genuinely isn't "
    "obvious from the code itself (a non-obvious constraint, a workaround "
    "for a specific bug), never to restate what a line already says.\n"
    "- Before calling a change finished, reread the actual diff once as a "
    "reviewer would: does it handle the failure paths, is any dead code or "
    "unused import left behind, would someone who wasn't in this "
    "conversation understand it. Fix what you find rather than shipping it "
    "and moving on — the task isn't complete just because it runs once.\n"
    "- For anything with real logic (not a one-line config or copy change), "
    "write or extend a test and run it with run_tests. A change that only "
    "passed syntax_check has been shown to parse, not shown to work.\n"
    "- Benchmark discipline (the SWE-bench rule): your test suite is "
    "immutable spec. When a test fails, change the implementation — never "
    "weaken, skip, xfail, or edit the test to make it pass. Keep every "
    "previously-working behavior working (a fix that breaks another case is "
    "not a fix). Leave no scratch files, debug scripts, or stray artifacts "
    "in the deliverable, and make the README's documented commands exactly "
    "reproducible from a clean copy.\n"
    "- Robustness bar for any user-facing input or persisted state: "
    "reject non-finite and nonsensical numbers (NaN/inf) at the boundary — "
    "float() accepting a string does not make it a valid value; normalize "
    "each input once through a single function shared by validation and "
    "every downstream filter, so a spelling that passes validation behaves "
    "identically everywhere; make persistence crash-safe (write temp file "
    "plus atomic rename) so a kill mid-write cannot corrupt the live store; "
    "and make error messages name the file, record, and field at fault and "
    "say what valid looks like. Standing engineering rules, not "
    "task-specific hints — apply them to every deliverable.\n"
    "- Adversarial suite (the hidden-test rule): the suite is not done when "
    "the happy path passes. For every input the code accepts, add tests "
    "for its hostile variants — non-finite or absurd numbers wherever "
    "numbers are parsed; every alternate spelling the validation accepts; "
    "empty, whitespace-only, corrupt, and missing backing files; unicode "
    "and extreme-length strings; empty-state behavior in every output "
    "mode. A requirement covered only by happy-path tests is not covered. "
    "A red adversarial test means the implementation changes, never the "
    "test.\n"
    "- Static rigor before done: annotate every public function (params "
    "and returns), keep each function small enough to hold in your head "
    "and its branch-count low — if a function needs more than a handful "
    "of branches, split it. Add property-style tests for round-trips and "
    "invariants (parse(format(x))==x, normalization stability for every "
    "accepted spelling, output always parses), not just examples. Run "
    "lint and the type checker on the deliverable and fix what they "
    "report; an unused import or an untyped public function is a review "
    "finding you chose to ship.\n"
    "- Final report contract: end every coding task with a verification "
    "table — test command plus result (N passed), lint result, CLI demo "
    "transcript or 'covered by tests', files delivered, and anything you "
    "did NOT verify. 'It works' without the line that proves it is not a "
    "report.\n"
    "- Before that report, call verify_deliverable on the work and fix "
    "every finding it returns: strict lint (ruff E,F — including the "
    "88-column limit, so keep lines short as you write), type check, "
    "complexity budget, slop scan, test-weakening check, stray artifacts. "
    "It checks mechanically what a reviewer would flag by hand; a finding "
    "you ship anyway must be defended in the report, not silently ignored. "
    "This does not replace run_tests — correctness is proven by tests, "
    "not by lint.\n"
    "- Tier-1 test doctrine (mechanical gates verify_deliverable enforces, "
    "so write to pass them the first time): freeze time instead of "
    "tolerating datetime.now() (freezegun-style: inject the clock or the "
    "date), generate realistic test data with faker/factories instead of "
    "hand-rolled fixtures, keep branch coverage high, document every "
    "public function (interrogate ≥80%), leave no dead code (vulture) and "
    "no security-lint findings (bandit), and never hardcode a secret "
    "(gitleaks scans the deliverable).\n"
    "- UI quality bar for any web deliverable: utility-first styling with "
    "responsive prefixes (layout must adapt at 390px and 1280px with no "
    "horizontal overflow); every input has a programmatic label and every "
    "interactive element is a real button/input (never a clickable div); "
    "exactly one h1 plus lang and viewport meta; visible focus styles; "
    "design tokens over scattered magic values; data loading degrades to "
    "a designed empty state (never a blank page); zero console errors on "
    "load and on every interaction, verified by actually opening the page "
    "logic paths yourself before declaring done.\n"
    "- UI craft depth: gate every animation/transition behind "
    "prefers-reduced-motion; use real tables (caption, th scope) for "
    "tabular data; associate errors with their inputs (aria-describedby), "
    "mark required fields, use autocomplete where applicable; keep one "
    "type scale and consistent spacing tokens. Call verify_ui on the "
    "entry HTML before the final report — it checks structure, live "
    "console errors, both viewport layouts, and touch targets "
    "mechanically — and fix every finding.\n"
    "- Data-to-ink: values shown to users are human-formatted — dates as "
    "readable dates (never raw ISO timestamps), numbers with sensible "
    "precision and grouping. If it looks like a database row, it isn't "
    "done.\n"
    "- Automation contract (rubric v12 cat 27): give every primary flow "
    "control a stable data-testid and a role with a non-empty accessible "
    "name; after any submit/filter/theme action, mirror the effect into "
    "text (aria-live/status or visible status line) so an agent can read "
    "back that the action landed. Loading states use aria-busy + text, "
    "never motion alone. Personal-data inputs carry real autocomplete "
    "tokens (name/email/street-address).\n"
    "- Type rigor (cat 29): annotate every public function; run mypy "
    "--strict when you can and treat its notes as review feedback; "
    "type: ignore comments must carry an error code; never write bare "
    "except: or except Exception: pass (verify_deliverable scans for "
    "them).\n"
    "- Performance honesty (cat 22): measure, don't assert — if you claim "
    "the 10k path is fast, the report includes the command and the "
    "observed seconds; load the store once, not per row; report p95/p99 "
    "or raw samples, never a lone mean.\n"
    "- Verification contract: before declaring a coding task done, its test "
    "suite must have actually run green via run_tests in THIS session. If "
    "no test runner is available, verify behavior by executing the program "
    "with run_command over representative inputs (happy path plus failure "
    "paths) and report the transcript. Direct execution of a delivered "
    "script is not inside the auto-approved $SAFE set — it prompts for "
    "approval — so batch every demo invocation into ONE chained command "
    "(cd <ws> && VAR=value python3 script.py cmd1 && ... ) instead of "
    "calling run_command once per flag, and prefer covering behavior "
    "through the test suite, which runs without any prompt. Never attempt "
    "pip install or other "
    "environment mutation from inside the sandbox — it is blocked by "
    "design; if a dependency is genuinely missing, say so in the final "
    "summary instead of spending steps on installs.\n"
    "- Deliverable completeness: a standalone tool ships with a README (what "
    "it is, usage examples, flags/env vars, error behavior, how to run the "
    "tests); public functions carry docstrings. Before finishing, scan your "
    "own diff once for unused imports, dead code, and leftover stubs — "
    "unused imports are the single most common review finding; importing at "
    "function level is a smell, move it to the top of the file instead.\n"
    "- write_file/edit_file/multi_edit already run a syntax check (and lint, "
    "if installed) automatically after every change — read the `verify` "
    "field already in THAT SAME result instead of calling syntax_check or "
    "lint again yourself for the file you just touched: syntax_check's own "
    "internal command shape needs a fresh approval every time (it cannot be "
    "told apart from arbitrary code execution by pattern alone), so an "
    "extra call adds an avoidable approval wait and tells you nothing the "
    "automatic check didn't already report. Call syntax_check/lint "
    "yourself only for a file you did NOT just edit this turn. Use "
    "lsp_diagnostics for deeper type/reference checking, which catches real "
    "bugs syntax_check cannot: unresolved names, type mismatches, wrong "
    "argument counts. Never claim something works unless a tool result "
    "says so.\n"
    "- Use todo_write for multi-step work and keep it current.\n"
    "- Use remember_fact sparingly, only for something genuinely worth carrying into "
    "every future session (a stated preference, a recurring instruction, a project "
    "convention) — not task-specific detail, and not anything already listed under "
    "'Remembered facts' below.\n"
    "- If a tool is blocked by policy, say so plainly instead of working around it.\n"
    "- Be concise in what you report back — the engineering work above "
    "isn't optional just because the summary should be short.\n"
    "\n"
    "Desktop playbook (computer use):\n"
    "- High efficiency batch actions: whenever you need to execute multi-step GUI "
    "interactions (e.g. click a field, type text, press Tab, type another field, press Enter, "
    "or click multiple controls), use desktop_actions([actions...]). It executes the entire "
    "sequence atomically in a single turn without round-trip latency, enforces focus guard, "
    "supports window-relative targeting (relative_to='uuid_or_name'), smooth S-curve drag easing, "
    "and attaches a post-batch screenshot for verification. Supports all primitives and aliases "
    "(double_click, right_click, hotkey, mouse_down, mouse_up, key_down, key_up). Prefer desktop_actions over individual "
    "step-by-step turns.\n"
    "- Window-relative coordinates: desktop_actions and low-level kwin tools support relative_to='uuid' (or 'active', "
    "app name, caption). Relative coordinates (x, y) can be integer pixel offsets or fractional ratios (e.g. x=0.5, y=0.5 "
    "for window center), allowing robust targeting that is immune to window movement.\n"
    "- To open a URL: use open_url(url) — one call that finds-or-launches the "
    "browser, focuses it, and navigates, verifying focus is actually held "
    "before it types and before it submits. Do not hand-chain launch_app -> "
    "activate_window -> key_press('ctrl+l') -> type_text -> key_press('Return') "
    "yourself for this: each of those is a separate step with a model turn "
    "between them, which is a wide window for focus to drift on a shared "
    "desktop, and open_url already does it atomically with verification.\n"
    "- To use any other application: launch_app(name) -> list_windows(filter='app') to find "
    "its uuid -> activate_window(uuid) -> then type_text / key_press or desktop_actions. Do not "
    "skip the activate step; typing goes to whatever is focused. If a result "
    "suggests focus moved (e.g. text didn't land, or active_window shows a "
    "different uuid than expected), re-activate before continuing rather than "
    "typing again — on a shared desktop something else may have taken focus.\n"
    "- Window control: use move_window(uuid, x, y, w, h) to reposition/resize, "
    "maximize_window(uuid) to maximize (or unmaximize with state=false), "
    "minimize_window(uuid) to minimize (or restore with state=false), and "
    "close_window(uuid) to close gracefully.\n"
    "- Text entry: type_text(text) types into the focused field. Use clear_before=true "
    "to select and erase existing text before typing. Use paste=true "
    "for instant atomic insertion (via clipboard and ctrl+v), especially for "
    "multiline code, long strings, non-ASCII characters, or commands with flags.\n"
    "- Pointer & clicks: mouse_click/mouse_move/mouse_drag place the pointer "
    "closed-loop (the real cursor position is read back and corrected until it "
    "converges), and every result reports the measured x/y actually used plus the "
    "residual px off your request — read those fields rather than assuming "
    "your request landed exactly. mouse_click supports clicks=2 (double-click) "
    "and clicks=3 (triple-click to select paragraph/line), and modifiers=['ctrl'], "
    "['shift'], or ['alt'] for chord clicks (e.g. ctrl+click to open links in a new tab). "
    "mouse_down / mouse_up and key_down / key_up allow "
    "arbitrary complex drags, multi-key holds, and selections. mouse_drag supports smooth=true "
    "with cosine S-curve easing and steps (e.g. steps=5) for realistic drag interaction. "
    "Use mouse_hover(x, y) to dwell over elements to trigger tooltips, dropdowns, or hover effects. "
    "If a placement reports ok:false, the pointer is at the reported x/y, not at "
    "your request: adjust from there or switch to keyboard. Keyboard navigation "
    "is still cheaper: ctrl+l for address bar, Tab/Shift+Tab between fields, "
    "Enter/Space to activate, Escape to cancel, Super/Meta to toggle application launcher. "
    "scroll supports direction ('down', 'up', 'left', 'right') "
    "and is the cheapest pointer action (relative wheel deltas need no placement) — prefer it over clicking "
    "a scrollbar.\n"
    "- High-res inspection: full screenshots are downscaled for model context. When small text, "
    "terminal characters, tiny buttons, or subtle indicators are hard to read, call zoom_region(x, y, width, height) "
    "to get an uncompressed 1:1 physical pixel crop of the region.\n"
    "- Visual grounding & coordinate grids: observe_screen accepts grid=true (and grid_step=100) to overlay "
    "a pixel reference grid with numerical coordinates directly on the screenshot, resolving spatial ambiguity on dense displays. "
    "observe_screen also accepts stamp_cursor=true to draw a high-contrast target ring and crosshair with (x,y) pill label at the pointer position.\n"
    "- OCR text spotting & direct clicking: use find_text(query) to find buttons, links, inputs, or text on "
    "screen via local OCR. It returns bounding boxes [x, y, w, h], center coordinates, and confidence. Use click_text(text, index=0) "
    "to find and click a text label in a single atomic step without manual coordinate guessing (pass index=N to pick the N-th match). "
    "In desktop_actions, you can also use action='click_text' with optional index.\n"
    "- Set-of-Marks (SoM) visual annotations: observe_screen(annotate=true) (and desktop_actions with annotate=true) "
    "overlays high-contrast numeric badges ([1], [2], ...) over detected interactive and text elements and returns an "
    "'elements' map with their IDs, labels, bounding boxes, and center coordinates. Use click_element(id) (or action='click_element' in desktop_actions) "
    "to click directly on any annotated badge ID without extracting coordinates manually.\n"
    "- Continuous drag gestures: use mouse_gesture(points=[[x1,y1], [x2,y2], ...], duration=0.5) (or action='gesture' in "
    "desktop_actions) for multi-point paths, drawing, freehand canvas manipulation, or complex swipes. desktop_actions supports relative_to='active_window' or relative_to=uuid for window-relative gesture waypoints.\n"
    "- Batch action sequencing: desktop_actions can combine click, type, key, wait, wait_for_change, "
    "clipboard_copy, clipboard_paste, move_window, activate, maximize, minimize, close, click_text, click_element, "
    "and gesture in a single round-trip turn without per-step latency.\n"
    "- Smart application orchestration: use focus_or_launch(app_name, command) (or action='focus_or_launch' in desktop_actions) "
    "to automatically focus an app if running, or launch it and wait for its window to appear if not.\n"
    "- Display topology & multi-monitor: use list_displays() to query connected monitors, geometries, refresh rates, and scaling.\n"
    "- Quantitative visual verification: use assert_region_changed(before_path, region) to verify that an action caused "
    "the expected visual change by measuring pixel diffs.\n"
    "- Visual change detection: use wait_for_screen_change(timeout, region) to await visual updates (via SHA-256 pixel delta) after async actions.\n"
    "- To verify a desktop action worked, observe_screen or active_window "
    "afterwards rather than assuming.\n"
    "- NEVER repeat a tool call with identical arguments. If a result did not "
    "change, the action did not work: take a different action or report the "
    "blocker. Repeating wastes the step budget.\n"
    "- If a capability is reported as unavailable, say so and stop; do not "
    "retry it.\n"
    "\n"
    "External tools (MCP):\n"
    "- Any tool named mcp__<server>__<tool> comes from a user-configured MCP "
    "server, not this codebase. Call it exactly like any other tool — its "
    "schema is authoritative — and trust its own description for what it "
    "does and how to use it; you have no other documentation for it. The "
    "first call to a given server this task will pause for the user's "
    "approval, same as any other prompt-tier action; that is expected, not "
    "an error."
)
CLAUDE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."

TOOLS = toolreg.schemas()

# ── journal ──────────────────────────────────────────────────────────────

def now(): return int(time.time() * 1000)

def emit(obj, stream=False):
    """Emit one NDJSON line. In stream mode events are tagged so the shell can
    distinguish progress from the final result."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)

def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts INTEGER, session TEXT, kind TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS archived_events(id INTEGER PRIMARY KEY, ts INTEGER, session TEXT, kind TEXT, payload TEXT, archived_at INTEGER);
CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY, ts INTEGER, text TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS summaries(id INTEGER PRIMARY KEY, ts INTEGER, session TEXT, until_id INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, ts INTEGER, tool TEXT, args TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS session_state(session TEXT, key TEXT, value TEXT, PRIMARY KEY(session,key));""")
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
    p = json.dumps(payload)
    db.execute("INSERT INTO events(ts,session,kind,payload) VALUES(?,?,?,?)",
               (now(), session, kind, p))
    # Keeps compact()'s per-step budget check O(1) instead of re-fetching and
    # re-joining the session's whole event history every step — see compact().
    # Same transaction as the insert above, so this costs one more indexed
    # upsert, not an extra commit/fsync.
    delta = len(kind) + 2 + len(p)   # matches compact()'s f"{k}: {p}" format
    db.execute("""INSERT INTO session_state(session,key,value) VALUES(?, 'raw_chars', ?)
                  ON CONFLICT(session,key) DO UPDATE SET value = CAST(value AS INTEGER) + ?""",
               (session, str(delta), delta))
    db.commit()

def set_state(db, session, key, value):
    db.execute("INSERT OR REPLACE INTO session_state(session,key,value) VALUES(?,?,?)",
               (session, key, str(value)))
    db.commit()

def get_state(db, session, key):
    row = db.execute("SELECT value FROM session_state WHERE session=? AND key=?",
                     (session, key)).fetchone()
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
    cur = db.execute("INSERT INTO memories(ts,text,source) VALUES(?,?,?)", (now(), text, source))
    db.commit()
    return cur.lastrowid


def list_memories(db, limit=200):
    rows = db.execute("SELECT id,ts,text,source FROM memories ORDER BY id DESC LIMIT ?",
                      (limit,)).fetchall()
    return [{"id": i, "ts": t, "text": x, "source": s} for i, t, x, s in rows]


def delete_memory(db, mem_id):
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
    rows = db.execute("""
        SELECT session, MIN(ts) AS started, MAX(ts) AS last, COUNT(*) AS n
        FROM events WHERE kind IN ('user','assistant') GROUP BY session
        ORDER BY MAX(id) DESC LIMIT ?""", (limit,)).fetchall()
    out = []
    for session, started, last, n in rows:
        title = None
        first_user = db.execute(
            "SELECT payload FROM events WHERE session=? AND kind='user' ORDER BY id LIMIT 1",
            (session,)).fetchone()
        if first_user:
            try:
                title = json.loads(first_user[0]).get("text", "")
            except Exception:
                title = None
        if not title:
            title = get_state(db, session, "current_task") or "(untitled session)"
        out.append({"session": session, "title": title.strip()[:140],
                    "started": started, "last": last, "events": n})
    return out


def session_transcript(db, session):
    """Human-readable transcript for the History tab: role + text bubbles,
    the shape AgentState.messages already renders on the QML side. Tool
    calls/results are intentionally left out — this is for a human skimming
    what was discussed, not for feeding back to a model (context() does
    that, with the full tool-call/result shape providers actually need).
    """
    rows = (db.execute("SELECT ts,kind,payload FROM archived_events WHERE session=? ORDER BY id",
                       (session,)).fetchall()
            + db.execute("SELECT ts,kind,payload FROM events WHERE session=? ORDER BY id",
                        (session,)).fetchall())
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

def vault():
    out = {}
    p = CONF / "keys.env"
    if p.exists():
        for line in p.read_text(errors="ignore").splitlines():
            m = re.match(r"export ([A-Z][A-Z0-9_]*)='(.*)'$", line)
            if m: out[m.group(1)] = m.group(2).replace("'\\''", "'")
    return out

def prefs():
    try: return json.loads((CONF / "prefs.json").read_text())
    except Exception: return {"provider": "openai", "model": "gpt-5.6-terra"}

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
    return {"screen": os.getenv("ARGUS_GRANT_SCREEN", "1") == "1",
            "input": os.getenv("ARGUS_GRANT_INPUT", "0") == "1",
            "shell": os.getenv("ARGUS_GRANT_SHELL", "1") == "1",
            "net": os.getenv("ARGUS_GRANT_NET", "1") == "1"}

def auth_mode(prefs_doc, provider, v, keyname, subname):
    declared = (prefs_doc.get("auth") or {}).get(provider)
    key = v.get(keyname, "")
    sub = v.get(subname, "") if subname else ""
    if declared == "sub" and sub: return ("sub", sub)
    if declared == "key" and key: return ("key", key)
    if key: return ("key", key)
    if sub: return ("sub", sub)
    return (declared or "key", "")

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
        return (f"tool {p.get('name', '')} {'ok' if res.get('ok') else 'FAILED'}"
                + (f" — {detail}" if detail else ""))
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
    # What has to fit is the request context() builds, not just the events
    # table: the last 3 summaries are injected verbatim on every turn and were
    # never counted here, so the real ceiling was MAX_CONTEXT_CHARS plus up to
    # 3 x SUMMARY_CHARS of summary text that no trigger could see.
    carried = sum(len(t) for (t,) in db.execute(
        "SELECT text FROM summaries WHERE session=? ORDER BY id DESC LIMIT 3", (session,)).fetchall())
    # Cheap path first: this runs every step of run()'s loop, and on most
    # steps nothing needs archiving. `raw_chars` is a running count kept in
    # session_state by event() (updated in the same transaction as each
    # insert, no extra commit) instead of re-fetching and re-joining every
    # event payload in the session just to measure it — with a long task's
    # history growing every step, redoing that full join on every single step
    # made each step a little slower than the last. COUNT(*) is index-only,
    # not a payload scan, so it stays cheap even on the fast path.
    event_count = db.execute("SELECT COUNT(*) FROM events WHERE session=?", (session,)).fetchone()[0]
    raw_chars = int(get_state(db, session, "raw_chars") or 0)
    if raw_chars + carried <= MAX_CONTEXT_CHARS and event_count <= MAX_CONTEXT_EVENTS: return None
    # Past the cheap threshold (or it's drifted — raw_chars undercounts by the
    # join's newlines, see event()): fetch for real and archive.
    rows = db.execute("SELECT id,kind,payload FROM events WHERE session=? ORDER BY id", (session,)).fetchall()
    raw = "\n".join(f"{k}: {p}" for _, k, p in rows)
    boundary = _safe_window_start([k for _, k, _ in rows], len(rows) - KEEP_EVENTS)
    old = rows[:boundary]
    if not old:
        set_state(db, session, "raw_chars", str(len(raw)))  # resync the drift
        return None
    summary = "Permanent session record: " + " | ".join(
        _summarize_event(k, p) for _, k, p in old[-120:])
    db.execute("INSERT INTO summaries(ts,session,until_id,text) VALUES(?,?,?,?)",
               (now(), session, old[-1][0], summary[:SUMMARY_CHARS]))
    db.execute("INSERT OR IGNORE INTO archived_events SELECT id,ts,session,kind,payload,? FROM events WHERE id <= ? AND session=?",
               (now(), old[-1][0], session))
    db.execute("DELETE FROM events WHERE id <= ? AND session=?", (old[-1][0], session))
    kept = rows[boundary:]
    set_state(db, session, "raw_chars", str(sum(len(f"{k}: {p}") for _, k, p in kept)))
    db.commit()
    return {"compacted": True, "before": len(raw), "after": len(summary), "archivedEvents": len(old)}

# ── images ───────────────────────────────────────────────────────────────

_IMAGE_CACHE = {}

def image_payload(path, preserve_raw=False):
    key = f"{path}:raw" if preserve_raw else str(path)
    if not path or key in _IMAGE_CACHE: return _IMAGE_CACHE.get(key)
    src = Path(path)
    if not src.exists(): return None
    is_zoom = preserve_raw or src.name.startswith("zoom-")
    if is_zoom:
        use = src
    else:
        small = src.with_name(src.stem + "-small.jpg")
        conv = shutil.which("magick") or shutil.which("convert")
        if conv and not small.exists():
            try:
                subprocess.run([conv, str(src), "-resize", "1280x>", "-quality", "70", str(small)],
                               capture_output=True, timeout=25)
            except Exception:
                pass
        use = small if small.exists() else src
    try:
        data = base64.b64encode(use.read_bytes()).decode()
    except Exception:
        return None
    payload = {"mime": "image/jpeg" if use.suffix in (".jpg", ".jpeg") else "image/png", "b64": data}
    _IMAGE_CACHE[key] = payload
    return payload

def _clip_strings(value, cap):
    """Truncate long strings in a tool result, wherever they sit."""
    if isinstance(value, str):
        if len(value) <= cap:
            return value
        return value[:cap] + f"\n… [truncated: {len(value) - cap} more characters]"
    if isinstance(value, list):
        return [_clip_strings(v, cap) for v in value]
    if isinstance(value, dict):
        return {k: _clip_strings(v, cap) for k, v in value.items()}
    return value


_RESULT_KEEP_KEYS = ("ok", "path", "error", "name", "id", "count", "truncated",
                     "lines", "shown", "language", "code")


def _summarize_args(args, cap=300):
    """Tool arguments, bounded for the incident log — a write_file call's
    `content` can be megabytes; the log needs enough to identify the call,
    not the payload itself."""
    return _clip_strings(args, cap)


def tool_result_text(result, limit=20_000):
    """The tool result as the model receives it: valid JSON, always.

    This used to be `json.dumps(res)[:limit]` — a slice of serialized JSON cuts
    whatever field is long enough to reach the boundary, so the model was handed
    a broken object (verified: `json.loads` on a truncated read_file result
    raises "Unterminated string", with the cut landing in the middle of the file
    content). Truncating has to happen at field level, before serializing, so
    what arrives is parseable and says what was dropped.
    """
    text = json.dumps(result)
    if len(text) <= limit:
        return text
    slim = _clip_strings(result, max(600, limit // 4))
    if len(json.dumps(slim)) <= limit:
        return json.dumps(slim)
    if not isinstance(slim, dict):
        return json.dumps({"ok": False, "truncated": True,
                           "note": "tool result exceeded the size limit and was dropped; "
                                   "re-run the call with a narrower scope"})
    # Still too large: drop the payload fields, biggest first, keeping the
    # identity/metadata keys the model needs to understand what happened.
    for key in sorted(slim, key=lambda k: -len(json.dumps(slim.get(k, "")))):
        if len(json.dumps(slim)) <= limit:
            break
        if key in _RESULT_KEEP_KEYS:
            continue
        slim[key] = "[omitted — this result exceeded the size limit; re-run the call " \
                    "with a narrower range (offset/limit, a smaller path, fewer results)]"
    if len(json.dumps(slim)) <= limit:
        return json.dumps(slim)
    return json.dumps({"ok": False, "truncated": True,
                       "note": "tool result exceeded the size limit and was dropped; "
                               "re-run the call with a narrower scope"})


# Some provider/model combinations reject any request that carries image
# content outright rather than just performing worse on it — confirmed live
# running a computer-use task against OpenRouter's free Nemotron Ultra:
# the very first observe_screen call's result was attached to context() as
# an image block, and the next provider_call died with HTTP 404 "No
# endpoints found that support image input". That is a request-shape
# rejection, not a transient failure (it is not in _RETRYABLE_HTTP and
# will reproduce identically on retry), so before the check below existed
# it killed the entire task on the very next screenshot of any computer-use
# session run against a text-only model — the model had already spent
# several tool calls making real progress (launch_app, list_windows) and
# lost all of it over a single image attachment.
_IMAGE_UNSUPPORTED_HINTS = ("support image", "image input", "images are not supported",
                            "does not support images", "no endpoints found")


def _image_unsupported_error(exc):
    msg = str(exc).lower()
    return "image" in msg and any(h in msg for h in _IMAGE_UNSUPPORTED_HINTS)


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
                    errlog.warning("orphan_tool_result_dropped", session=session,
                                   call_id=tid)
                except Exception:
                    pass
                continue
        kept.append((kind, payload))
    return kept


def _clean_workspace_caches(root):
    """Remove tooling cache dirs (__pycache__, .pytest_cache, .ruff_cache,
    .mypy_cache) and coverage data (.coverage*) under the workspace root.
    Verification runs leave them behind and agents reliably forget to remove
    them; the runtime does it on task finish instead. Only these known
    regenerable names, best-effort."""
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            for d in list(dirnames):
                if d in ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"):
                    shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                    dirnames.remove(d)
            for fn in filenames:
                if fn == ".coverage" or fn.startswith(".coverage."):
                    try:
                        os.unlink(os.path.join(dirpath, fn))
                    except Exception:
                        pass
    except Exception:
        pass


def context(db, session, ws_info=None, step_info=None):
    s = db.execute("SELECT text FROM summaries WHERE session=? ORDER BY id DESC LIMIT 3", (session,)).fetchall()
    fetched = db.execute("SELECT kind,payload FROM events WHERE session=? ORDER BY id DESC LIMIT ?",
                         (session, MAX_CONTEXT_EVENTS + _WINDOW_SAFETY_MARGIN)).fetchall()[::-1]
    start = _safe_window_start([k for k, _ in fetched], len(fetched) - MAX_CONTEXT_EVENTS)
    e = fetched[start:]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if ws_info:
        messages.append({"role": "system", "content": ws_info})
    # Genuinely cross-session (the `memories` table has no session column) —
    # unlike the per-session summaries block right below, this is visible
    # from every future session too, which is the entire point of
    # remember_fact. Capped at 30: this is meant to carry durable facts
    # (preferences, conventions), not grow without bound.
    mems = list_memories(db, limit=30)
    if mems:
        messages.append({"role": "system", "content": "Remembered facts (from past sessions, "
                         "via remember_fact or automatic extraction):\n"
                         + "\n".join(f"- {m['text']}" for m in mems)})
    if s: messages.append({"role": "system", "content": "This conversation so far "
                           "(condensed, this session only):\n" + "\n".join(x[0] for x in s)})
    # Pinned anchors: sourced from session_state, not the rolling event
    # window, so they survive compaction/trimming and are restated every
    # turn — the model cannot lose track of what it was actually asked to
    # do, or the plan it committed to, just because the raw history scrolled.
    current_task = get_state(db, session, "current_task")
    if current_task:
        messages.append({"role": "system", "content": "Current task — stay on this, do not "
                         "drift into unrelated work: " + current_task})
    todos_raw = get_state(db, session, "todos")
    if todos_raw:
        try: todos = json.loads(todos_raw)
        except Exception: todos = []
        if todos:
            lines = "\n".join(f"- [{t.get('status', 'pending')}] {t.get('content', '')}" for t in todos)
            messages.append({"role": "system", "content": "Current plan (update with todo_write "
                             "as steps complete; do not silently abandon pending items):\n" + lines})
    no_images = get_state(db, session, "no_image_support") == "1"
    if no_images:
        messages.append({"role": "system", "content": "This model/provider does not accept "
                         "image input — observe_screen still captures a screenshot to disk, "
                         "but it is not shown to you. Verify desktop actions with "
                         "list_windows/active_window (window titles, geometry, focus) and tool "
                         "results instead of visual inspection."})
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
            if p.get("tool_calls"): m["tool_calls"] = p["tool_calls"]
            messages.append(m)
        elif kind == "tool":
            res = p.get("result", {})
            messages.append({"role": "tool", "tool_call_id": p.get("id", "history"),
                             "name": p.get("name", ""), "content": tool_result_text(res)})
            if not no_images and res.get("ok"):
                tool_name = p.get("name")
                img_path = res.get("path") or res.get("screenshot_path")
                if img_path and tool_name in ("observe_screen", "zoom_region", "desktop_actions"):
                    img = image_payload(img_path, preserve_raw=(tool_name == "zoom_region"))
                    if img: images.append((img, res, tool_name))
    for img, res, tool_name in images[-MAX_IMAGES:]:
        w, h = res.get("width"), res.get("height")
        scale = res.get("scale")
        if tool_name == "zoom_region":
            caption = "High-resolution 1:1 inspection crop from zoom_region (native uncompressed pixel detail)."
            if w and h:
                caption += f" Dimensions: {w}x{h} px (scale: {scale or 1.0})."
        elif tool_name == "desktop_actions":
            caption = "Screenshot captured after desktop_actions batch execution."
            if w and h:
                caption += f" Screen coordinate space: {w}x{h} px (scale: {scale or 1.0}). Input coordinates for desktop_actions must be in this coordinate space."
        else:
            caption = "Screenshot from observe_screen (most recent capture)."
            if w and h:
                caption += f" Screen coordinate space: {w}x{h} px (scale: {scale or 1.0}). Input coordinates for mouse_click/mouse_move/mouse_drag/desktop_actions must be in this {w}x{h} coordinate space."
        if res.get("grid"):
            step = res.get("grid_step", 100)
            caption += f" A coordinate reference grid is overlaid with pixel markers every {step} px."
        if res.get("annotated") and res.get("elements"):
            num_elem = len(res["elements"])
            caption += f" Set-of-Marks (SoM) visual labels [1]..[{num_elem}] are overlaid on detected elements."
        messages.append({"role": "user", "content": [
            {"type": "text", "text": caption},
            {"type": "image", "mime": img["mime"], "b64": img["b64"]}]})
    return messages

# ── provider adapters ────────────────────────────────────────────────────

def to_anthropic(messages):
    systems, out = [], []
    for m in messages:
        role = m["role"]
        if role == "system":
            systems.append(m["content"]); continue
        if role == "user":
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
            else:
                blocks = []
                for b in content:
                    if b.get("type") == "text": blocks.append({"type": "text", "text": b["text"]})
                    elif b.get("type") == "image":
                        blocks.append({"type": "image", "source": {"type": "base64",
                                      "media_type": b["mime"], "data": b["b64"]}})
                out.append({"role": "user", "content": blocks or ""})
        elif role == "assistant":
            blocks = []
            if m.get("content"): blocks.append({"type": "text", "text": m["content"]})
            for c in m.get("tool_calls", []) or []:
                fn = c.get("function", {})
                try: inp = json.loads(fn.get("arguments") or "{}")
                except Exception: inp = {}
                blocks.append({"type": "tool_use", "id": c.get("id", "call"),
                               "name": fn.get("name", ""), "input": inp})
            out.append({"role": "assistant", "content": blocks or m.get("content", "")})
        elif role == "tool":
            out.append({"role": "user", "content": [{"type": "tool_result",
                        "tool_use_id": m.get("tool_call_id", "history"),
                        "content": m.get("content", "")}]})
    return "\n\n".join(x for x in systems if x), out

def to_openai(messages):
    out = []
    for m in messages:
        if m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id", ""),
                        "content": m.get("content", "")})
        elif m["role"] == "user" and not isinstance(m["content"], str):
            blocks = []
            for b in m["content"]:
                if b.get("type") == "text": blocks.append({"type": "text", "text": b["text"]})
                elif b.get("type") == "image":
                    blocks.append({"type": "image_url", "image_url": {
                        "url": "data:" + b["mime"] + ";base64," + b["b64"]}})
            out.append({"role": "user", "content": blocks})
        else:
            out.append(m)
    return out

def to_codex(messages):
    instructions, items = "", []
    for m in messages:
        role = m["role"]
        if role == "system":
            instructions = (instructions + "\n\n" + m["content"]).strip(); continue
        if role == "tool":
            items.append({"type": "function_call_output", "call_id": m.get("tool_call_id", ""),
                          "output": m.get("content", "")})
        elif role == "assistant":
            if m.get("content"):
                items.append({"role": "assistant", "content": [{"type": "output_text", "text": m["content"]}]})
            for c in m.get("tool_calls", []) or []:
                fn = c.get("function", {})
                items.append({"type": "function_call", "call_id": c.get("id", "call"),
                              "name": fn.get("name", ""), "arguments": fn.get("arguments") or "{}"})
        else:
            content = m["content"]
            if isinstance(content, str):
                items.append({"role": "user", "content": [{"type": "input_text", "text": content}]})
            else:
                blocks = []
                for b in content:
                    if b.get("type") == "text": blocks.append({"type": "input_text", "text": b["text"]})
                    elif b.get("type") == "image":
                        blocks.append({"type": "input_image", "image_url": "data:" + b["mime"] + ";base64," + b["b64"]})
                items.append({"role": "user", "content": blocks})
    return instructions, items

def parse_codex(reply):
    calls, text = [], []
    for item in reply.get("output", []) or []:
        if item.get("type") == "function_call":
            calls.append({"id": item.get("call_id") or item.get("id", "call"), "type": "function",
                          "function": {"name": item.get("name", ""), "arguments": item.get("arguments") or "{}"}})
        elif item.get("type") == "message":
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text") and c.get("text"): text.append(c["text"])
    return {"choices": [{"message": {"content": "".join(text), "tool_calls": calls}}]}

# ── streaming (SSE) ──────────────────────────────────────────────────────
# Every provider is called with stream=True and parsed incrementally, so the
# panel can show the model's prose and tool-call arguments as they're
# generated instead of only after the whole turn completes. `on_event` is
# always a callable (a no-op when the CLI wasn't invoked with --stream) so the
# parsers below never need to know whether anyone is listening; the final
# return value has the exact `{"choices": [{"message": {...}}]}` shape the
# non-streaming code used to produce, so the tool-execution loop in `run()`
# needed no changes.

class ProviderError(RuntimeError):
    """A failure the provider itself reported inside the stream — an
    `{"error": ...}` body delivered with HTTP 200 (how OpenRouter and DeepSeek
    report upstream rate limits and provider failures), an `error`/`failed`
    event, or a stream that ended without a completed response.

    Distinct from RuntimeError generally so _call_stream can retry it when
    nothing has been shown to the user yet: a rate limit in the body of a 200
    response is exactly as transient as a 429 status, but used to fail the whole
    task on the first attempt because the retry branch only caught HTTPError and
    URLError (verified: a stubbed in-band error raised after 1 attempt while a
    URLError recovered on the 2nd).
    """

def _sse_iter(resp):
    """Yield (event, data) pairs from a text/event-stream response body following WHATWG SSE spec."""
    event = "message"
    data_lines = []
    first_line = True
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if first_line:
            line = line.lstrip("\ufeff")
            first_line = False
        if not line:
            if data_lines:
                yield event, "\n".join(data_lines)
            event, data_lines = "message", []
            continue
        if line.startswith(":"):
            continue  # comment / heartbeat / ping
        if ":" in line:
            field, val = line.split(":", 1)
            if val.startswith(" "):
                val = val[1:]
        else:
            field, val = line, ""
        field = field.strip()
        if field == "event":
            event = val.strip()
        elif field == "data":
            data_lines.append(val)
    if data_lines:
        yield event, "\n".join(data_lines)

def _post_stream(url, headers, body):
    payload = dict(body)
    payload["stream"] = True
    if ("api.openai.com" in url or "openrouter.ai" in url) and "messages" in payload and "stream_options" not in payload:
        payload["stream_options"] = {"include_usage": True}
    req_headers = {
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    req_headers.update(headers)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=req_headers, method="POST")
    return urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)

def _stream_anthropic(url, headers, body, on_event):
    """https://docs.anthropic.com/en/api/messages-streaming — tool_use input
    arrives as `input_json_delta.partial_json` fragments that concatenate
    into the full arguments JSON string once the block closes."""
    resp = _post_stream(url, headers, body)
    text_parts, tools, order = [], {}, []
    start_time = time.time()
    first_token_time = None
    token_count = 0
    last_metrics_emit = 0.0
    prompt_tokens = 0
    completion_tokens = 0

    def maybe_emit_metrics(force=False):
        nonlocal last_metrics_emit
        now_t = time.time()
        if first_token_time is None:
            return
        if force or (now_t - last_metrics_emit >= 0.15 and token_count > 0):
            elapsed = max(now_t - first_token_time, 0.001)
            tps = round(token_count / elapsed, 1)
            ttft_ms = int((first_token_time - start_time) * 1000)
            on_event({"type": "metrics", "ttft": ttft_ms, "tokens": token_count, "tps": tps, "elapsed": round(elapsed, 2)})
            last_metrics_emit = now_t

    truncated_reason = None
    try:
        for _event, data in _sse_iter(resp):
            if not data:
                continue
            try: obj = json.loads(data)
            except Exception: continue
            et = obj.get("type")
            if et == "message_start":
                msg = obj.get("message", {}) or {}
                usage = msg.get("usage", {}) or {}
                if usage:
                    prompt_tokens = usage.get("input_tokens", 0)
                    on_event({"type": "usage", "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens})
            elif et == "content_block_start":
                idx = obj.get("index", 0)
                block = obj.get("content_block", {}) or {}
                if block.get("type") == "tool_use":
                    tools[idx] = {"id": block.get("id") or f"call_{idx}",
                                  "name": block.get("name", ""), "json": ""}
                    order.append(idx)
                    on_event({"type": "tool_call_start", "id": tools[idx]["id"], "name": tools[idx]["name"]})
            elif et == "content_block_delta":
                idx = obj.get("index", 0)
                delta = obj.get("delta", {}) or {}
                dt = delta.get("type")
                if dt == "text_delta":
                    t = delta.get("text", "")
                    if t:
                        if first_token_time is None:
                            first_token_time = time.time()
                        token_count += 1
                        text_parts.append(t)
                        on_event({"type": "delta", "text": t})
                        maybe_emit_metrics()
                elif dt == "input_json_delta" and idx in tools:
                    frag = delta.get("partial_json", "")
                    if frag:
                        if first_token_time is None:
                            first_token_time = time.time()
                        token_count += max(1, len(frag) // 4)
                        tools[idx]["json"] += frag
                        on_event({"type": "tool_call_delta", "id": tools[idx]["id"], "arguments": frag})
                        maybe_emit_metrics()
                elif dt == "thinking_delta":
                    # Extended thinking. `signature_delta` (the block's
                    # crypto signature, not user-facing text) is otherwise
                    # ignored on purpose.
                    t = delta.get("thinking", "")
                    if t:
                        if first_token_time is None:
                            first_token_time = time.time()
                        token_count += 1
                        on_event({"type": "reasoning_delta", "text": t})
                        maybe_emit_metrics()
            elif et == "content_block_stop":
                idx = obj.get("index", 0)
                if idx in tools:
                    try: parsed = json.loads(tools[idx]["json"] or "{}")
                    except Exception: parsed = {}
                    on_event({"type": "tool_call_ready", "id": tools[idx]["id"],
                              "name": tools[idx]["name"], "arguments": parsed})
            elif et == "message_delta":
                usage = obj.get("usage", {}) or {}
                if usage:
                    completion_tokens = usage.get("output_tokens", completion_tokens)
                    on_event({"type": "usage", "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens})
            elif et == "error":
                err = obj.get("error") or {}
                msg = err.get("message", "stream error") if isinstance(err, dict) else str(err)
                raise ProviderError(f"Anthropic stream error: {msg}")
    except Exception as e:
        # See the matching comment in _stream_openai_chat: nothing arrived
        # yet -> let the caller's normal retry-from-scratch handle it;
        # something DID arrive -> salvage the text and let run() ask the
        # model to continue rather than discarding it.
        if not text_parts and not tools:
            raise
        truncated_reason = str(e)
    finally:
        resp.close()
    maybe_emit_metrics(force=True)
    if truncated_reason is not None:
        # Discard any tool_use block, complete or not — see the matching
        # comment in _stream_openai_chat for why this stays uniform across
        # providers even though Anthropic's content_block_stop could in
        # principle distinguish a finished block from a cut-off one.
        return {"choices": [{"message": {"content": "".join(text_parts), "tool_calls": []}}],
                "_stream_truncated": True, "_truncation_reason": truncated_reason}
    calls = [{"id": tools[i]["id"], "type": "function",
              "function": {"name": tools[i]["name"], "arguments": tools[i]["json"] or "{}"}} for i in order]
    return {"choices": [{"message": {"content": "".join(text_parts), "tool_calls": calls}}]}

def _stream_openai_chat(url, headers, body, on_event):
    """OpenAI-compatible chat.completions SSE (OpenAI, OpenRouter, OpenCode
    Go): each tool_call delta carries an `index`; `function.arguments`
    fragments concatenate in order into the full JSON string per index."""
    resp = _post_stream(url, headers, body)
    text_parts, tools, order, started = [], {}, [], set()
    start_time = time.time()
    first_token_time = None
    token_count = 0
    last_metrics_emit = 0.0

    def maybe_emit_metrics(force=False):
        nonlocal last_metrics_emit
        now_t = time.time()
        if first_token_time is None:
            return
        if force or (now_t - last_metrics_emit >= 0.15 and token_count > 0):
            elapsed = max(now_t - first_token_time, 0.001)
            tps = round(token_count / elapsed, 1)
            ttft_ms = int((first_token_time - start_time) * 1000)
            on_event({"type": "metrics", "ttft": ttft_ms, "tokens": token_count, "tps": tps, "elapsed": round(elapsed, 2)})
            last_metrics_emit = now_t

    truncated_reason = None
    try:
        for _event, data in _sse_iter(resp):
            data = data.strip()
            if not data or data == "[DONE]":
                continue
            try: obj = json.loads(data)
            except Exception: continue

            # Detect provider error mid-stream
            if "error" in obj:
                err = obj["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                raise ProviderError(f"Provider stream error: {msg}")

            # Capture usage if present (e.g. OpenAI / OpenRouter stream_options)
            usage = obj.get("usage")
            if usage and isinstance(usage, dict):
                p_tok = usage.get("prompt_tokens", 0)
                c_tok = usage.get("completion_tokens", 0)
                t_tok = usage.get("total_tokens", p_tok + c_tok)
                on_event({"type": "usage", "prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": t_tok})

            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta", {}) or {}
            if delta.get("content"):
                t = delta["content"]
                if first_token_time is None:
                    first_token_time = time.time()
                token_count += 1
                text_parts.append(t)
                on_event({"type": "delta", "text": t})
                maybe_emit_metrics()
            # Not OpenAI's own field — OpenRouter's unified format (`reasoning`)
            # and some direct reasoning-model APIs, e.g. DeepSeek
            # (`reasoning_content`), stream chain-of-thought this way ahead
            # of `content`. Neither is part of the returned message; it's
            # shown live and then dropped, same as other providers' "thinking".
            reasoning = delta.get("reasoning") or delta.get("reasoning_content")
            if reasoning:
                if first_token_time is None:
                    first_token_time = time.time()
                token_count += 1
                on_event({"type": "reasoning_delta", "text": reasoning})
                maybe_emit_metrics()
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                if idx not in tools:
                    tools[idx] = {"id": tc.get("id") or f"call_{idx}", "name": "", "arguments": ""}
                    order.append(idx)
                fn = tc.get("function") or {}
                if fn.get("name"):
                    # OpenAI sends the name once, in the first delta for that
                    # index, so fragments are normally concatenated. Some
                    # OpenAI-compatible servers resend the whole name in every
                    # chunk instead; appending there produced a name like
                    # "read_fileread_file…" and the call came back as an unknown
                    # tool, so an exact resend of what is already accumulated is
                    # ignored rather than doubled.
                    if not tools[idx]["name"]:
                        tools[idx]["name"] = fn["name"]
                    elif fn["name"] != tools[idx]["name"]:
                        tools[idx]["name"] += fn["name"]
                if idx not in started and tools[idx]["name"]:
                    started.add(idx)
                    on_event({"type": "tool_call_start", "id": tools[idx]["id"], "name": tools[idx]["name"]})
                if fn.get("arguments"):
                    if first_token_time is None:
                        first_token_time = time.time()
                    token_count += max(1, len(fn["arguments"]) // 4)
                    tools[idx]["arguments"] += fn["arguments"]
                    on_event({"type": "tool_call_delta", "id": tools[idx]["id"], "arguments": fn["arguments"]})
                    maybe_emit_metrics()
    except Exception as e:
        # A connection-level failure partway through (dropped socket, idle
        # timeout, truncated chunk, an in-band ProviderError, ...). Nothing
        # arrived yet: there is nothing to salvage, so let the caller's
        # normal retry-from-scratch handle it (see _call_stream) exactly as
        # before this existed. Something DID arrive: salvaging it and
        # letting run() ask the model to continue from there is strictly
        # better than discarding it — confirmed live (twice, same failure,
        # "Upstream idle timeout exceeded" against a slow free model) that a
        # mid-generation drop killed the whole task and threw away
        # everything the model had already written, even though the panel
        # had already shown it to the user.
        if not text_parts and not tools:
            raise
        truncated_reason = str(e)
    finally:
        resp.close()
    maybe_emit_metrics(force=True)
    if truncated_reason is not None:
        # Discard any tool call, complete or not: this streaming shape gives
        # no signal that a call finished independent of the whole response
        # ending, so there's no safe way to tell a genuinely complete call
        # apart from one truncated mid-arguments. Resending a maybe-broken
        # tool_calls array risks a hard provider-side rejection or the model
        # acting on truncated arguments; continuing from the text alone and
        # letting the model re-decide its next tool call is the safe,
        # simple recovery — see run()'s handling of _stream_truncated.
        return {"choices": [{"message": {"content": "".join(text_parts), "tool_calls": []}}],
                "_stream_truncated": True, "_truncation_reason": truncated_reason}
    calls = []
    for i in order:
        t = tools[i]
        try: parsed = json.loads(t["arguments"] or "{}")
        except Exception: parsed = {}
        on_event({"type": "tool_call_ready", "id": t["id"], "name": t["name"], "arguments": parsed})
        calls.append({"id": t["id"], "type": "function",
                      "function": {"name": t["name"], "arguments": t["arguments"] or "{}"}})
    return {"choices": [{"message": {"content": "".join(text_parts), "tool_calls": calls}}]}

def _stream_codex(url, headers, body, on_event):
    """OpenAI Responses API SSE (ChatGPT Codex backend). The incremental
    events drive live UI feedback only; `response.completed` carries the
    full, authoritative output (same shape parse_codex already handled for
    the non-streaming call), so execution correctness never depends on this
    module's read of the less-documented delta event names."""
    resp = _post_stream(url, headers, body)
    tool_started, final = set(), None
    start_time = time.time()
    first_token_time = None
    token_count = 0
    last_metrics_emit = 0.0

    def maybe_emit_metrics(force=False):
        nonlocal last_metrics_emit
        now_t = time.time()
        if first_token_time is None:
            return
        if force or (now_t - last_metrics_emit >= 0.15 and token_count > 0):
            elapsed = max(now_t - first_token_time, 0.001)
            tps = round(token_count / elapsed, 1)
            ttft_ms = int((first_token_time - start_time) * 1000)
            on_event({"type": "metrics", "ttft": ttft_ms, "tokens": token_count, "tps": tps, "elapsed": round(elapsed, 2)})
            last_metrics_emit = now_t

    try:
        for _event, data in _sse_iter(resp):
            if not data:
                continue
            try: obj = json.loads(data)
            except Exception: continue
            et = obj.get("type", "")
            if et == "response.output_text.delta":
                t = obj.get("delta", "")
                if t:
                    if first_token_time is None:
                        first_token_time = time.time()
                    token_count += 1
                    on_event({"type": "delta", "text": t})
                    maybe_emit_metrics()
            elif et == "response.output_item.added":
                item = obj.get("item", {}) or {}
                if item.get("type") == "function_call":
                    cid = item.get("call_id") or item.get("id", "call")
                    if cid not in tool_started:
                        tool_started.add(cid)
                        on_event({"type": "tool_call_start", "id": cid, "name": item.get("name", "")})
            elif et == "response.function_call_arguments.delta":
                cid = obj.get("call_id") or obj.get("item_id", "")
                frag = obj.get("delta", "")
                if frag:
                    if first_token_time is None:
                        first_token_time = time.time()
                    token_count += max(1, len(frag) // 4)
                    on_event({"type": "tool_call_delta", "id": cid, "arguments": frag})
                    maybe_emit_metrics()
            elif et == "response.function_call_arguments.done":
                cid = obj.get("call_id") or obj.get("item_id", "")
                try: parsed = json.loads(obj.get("arguments") or "{}")
                except Exception: parsed = {}
                on_event({"type": "tool_call_ready", "id": cid, "name": "", "arguments": parsed})
            elif et == "response.reasoning_summary_text.delta":
                t = obj.get("delta", "")
                if t:
                    if first_token_time is None:
                        first_token_time = time.time()
                    token_count += 1
                    on_event({"type": "reasoning_delta", "text": t})
                    maybe_emit_metrics()
            elif et == "response.completed":
                final = obj.get("response", obj)
                usage = final.get("usage") if isinstance(final, dict) else None
                if usage and isinstance(usage, dict):
                    p_tok = usage.get("input_tokens", usage.get("prompt_tokens", 0))
                    c_tok = usage.get("output_tokens", usage.get("completion_tokens", 0))
                    t_tok = usage.get("total_tokens", p_tok + c_tok)
                    on_event({"type": "usage", "prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": t_tok})
            elif et in ("response.failed", "error"):
                err = obj.get("response", {}).get("error") if "response" in obj else obj.get("error")
                raise ProviderError(str((err or {}).get("message", err) if isinstance(err, dict) else err))
    finally:
        resp.close()
    maybe_emit_metrics(force=True)
    if final is None:
        raise ProviderError("stream ended without response.completed")
    return parse_codex(final)

_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
_MAX_PROVIDER_RETRIES = 2


def _clean_http_detail(exc, cap=300):
    """The body of an HTTPError, cleaned up for a human/model to read.

    Confirmed live: a 403 from an intermediate proxy (not the provider
    itself — a WAF/CDN block page) came back as a full raw
    "<!doctype html>...<!--[if lt IE 7]>..." document, which _call_stream
    used to dump verbatim into the task's error message. That is technically
    "the response body" but tells whoever reads it nothing about what
    actually went wrong, and drowns out the one thing that matters (the
    status code) in markup. A provider's own error responses are JSON; an
    HTML body means something other than the provider produced this one.
    """
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:
        return ""
    stripped = raw.strip()
    if stripped[:1] == "<" or "<html" in stripped[:400].lower():
        return ("non-JSON (HTML) error page, not a provider-reported API error — "
                "likely an intermediate proxy/CDN block page, rate-limit challenge, "
                "or gateway error")
    return stripped[:cap]


def _retry_delay(attempt, http_error=None):
    if http_error is not None and http_error.headers:
        ra = http_error.headers.get("Retry-After")
        if ra:
            try: return min(float(ra), 20)
            except ValueError: pass
    return min(2 ** attempt, 8)


# Events that represent durable, visible conversation content — retrying
# after one of these has streamed would re-run the model turn from scratch
# and duplicate whatever the panel already rendered. reasoning_delta and
# metrics are deliberately excluded: reasoning/thinking text is never sent
# back to the model as conversation history (see AgentState.qml's
# appendReasoning — it's ephemeral, shown once and discarded) and metrics
# are pure telemetry, so neither leaves anything behind to duplicate.
# Confirmed live against a free/slower model (OpenRouter's Nemotron Ultra):
# it streamed several reasoning_delta chunks, then the upstream itself cut
# the connection with "Upstream idle timeout exceeded" before a single real
# token of the actual reply — before this distinction, that counted as
# "already emitted" and killed the whole task on one slow thinking phase,
# exactly the blip this function exists to absorb.
_DURABLE_STREAM_EVENT_TYPES = {"delta", "tool_call_start", "tool_call_delta", "tool_call_ready"}


def _call_stream(fn, *args):
    """Retry a transient provider failure (rate limit / 5xx / connect-level
    network error) with backoff — a single flaky request used to kill the
    whole task, which looked to the user like the agent had given up rather
    than hit a blip. Retries stop the moment durable content has actually
    been streamed to the UI for this attempt (see _DURABLE_STREAM_EVENT_TYPES):
    retrying past that point would re-run the model turn from scratch and
    duplicate whatever the panel already rendered, which is worse than
    surfacing the error — so that case still raises immediately, same as
    before this existed.
    """
    on_event = args[-1]
    rest = args[:-1]
    emitted = False

    def guarded(evt):
        nonlocal emitted
        if evt.get("type") in _DURABLE_STREAM_EVENT_TYPES:
            emitted = True
        on_event(evt)

    for attempt in range(_MAX_PROVIDER_RETRIES + 1):
        emitted = False
        try:
            return fn(*rest, guarded)
        except urllib.error.HTTPError as e:
            detail = _clean_http_detail(e)
            if attempt < _MAX_PROVIDER_RETRIES and e.code in _RETRYABLE_HTTP and not emitted:
                time.sleep(_retry_delay(attempt + 1, e))
                continue
            raise RuntimeError(f"Provider request failed: HTTP {e.code} {detail}")
        except ProviderError as e:
            # In-band failure reported inside a 200 response, or a stream that
            # ended early. Same reasoning as the HTTPError branch above: retry
            # only while nothing has been streamed, since a retry re-runs the
            # whole model turn. ProviderError is deliberately not a bare
            # RuntimeError so this branch cannot also swallow credential and
            # configuration errors, which retrying would never fix.
            if attempt < _MAX_PROVIDER_RETRIES and not emitted:
                time.sleep(_retry_delay(attempt + 1))
                continue
            raise
        except RuntimeError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < _MAX_PROVIDER_RETRIES and not emitted:
                time.sleep(_retry_delay(attempt + 1))
                continue
            raise RuntimeError("Provider request failed: " + str(e))
        except Exception as e:
            raise RuntimeError("Provider request failed: " + str(e))

# Reasoning/extended-thinking effort → Anthropic's thinking budget in
# tokens. Anthropic requires max_tokens to exceed budget_tokens (the
# response budget covers both thinking and the actual output), so
# provider_call bumps max_tokens alongside this rather than leaving the
# fixed 4096 in place — a budget_tokens of 8000 against a 4096 max_tokens
# would be rejected outright.
_REASONING_BUDGET = {"low": 2000, "medium": 8000, "high": 16000}


def provider_call(messages, on_event):
    p = prefs(); v = vault()
    provider = p.get("provider", "openai"); model = p.get("model", "")
    if not model: raise RuntimeError("No model selected")
    # "off" by default and whenever the saved value isn't recognized, so a
    # model that doesn't support reasoning sees an unmodified request body —
    # the parameter is only ever added, never sent as an explicit "off"/
    # zero-budget value the API would have to interpret.
    reasoning = p.get("reasoning", "off")
    if reasoning not in _REASONING_BUDGET:
        reasoning = "off"

    if provider == "anthropic":
        mode, key = auth_mode(p, "anthropic", v, "ANTHROPIC_API_KEY", "ANTHROPIC_SUB_TOKEN")
        if not key: raise RuntimeError("No credential configured for anthropic")
        system, msgs = to_anthropic(messages)
        if mode == "sub":
            system = (CLAUDE_IDENTITY + "\n\n" + system).strip()
            headers = {"Authorization": "Bearer " + key, "anthropic-version": "2023-06-01",
                       "anthropic-beta": "oauth-2025-04-20,claude-code-20250219",
                       "content-type": "application/json"}
        else:
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
                       "content-type": "application/json"}
        body = {"model": model, "max_tokens": 4096, "system": system, "messages": msgs,
                "tools": [{"name": x["function"]["name"], "description": x["function"]["description"],
                           "input_schema": x["function"]["parameters"]} for x in TOOLS]}
        if reasoning != "off":
            budget = _REASONING_BUDGET[reasoning]
            body["max_tokens"] = budget + 4096
            body["thinking"] = {"type": "enabled", "budget_tokens": budget}
            # Known limitation, not silently pretended: thinking blocks are
            # streamed live via reasoning_delta (see _stream_anthropic) and
            # then dropped — context() never journals them, so a later turn
            # that replays this conversation does not resend the prior
            # thinking block/signature the way strict interleaved-thinking
            # continuity wants. Anthropic's API tolerates this (it does not
            # reject the turn), but the model's own reasoning does not
            # carry forward across turns the way its final text/tool calls do.
        return _call_stream(_stream_anthropic, "https://api.anthropic.com/v1/messages", headers, body, on_event)

    elif provider == "openai":
        mode, key = auth_mode(p, "openai", v, "OPENAI_API_KEY", "OPENAI_CODEX_TOKEN")
        if not key: raise RuntimeError("No credential configured for openai")
        if mode == "sub":
            instructions, items = to_codex(messages)
            body = {"model": model, "store": False,
                    "instructions": instructions or SYSTEM_PROMPT, "input": items,
                    "tools": [{"type": "function", "name": x["function"]["name"],
                               "description": x["function"]["description"],
                               "parameters": x["function"]["parameters"]} for x in TOOLS],
                    "tool_choice": "auto"}
            if reasoning != "off":
                body["reasoning"] = {"effort": reasoning}
            headers = {"Authorization": "Bearer " + key, "content-type": "application/json"}
            acct = v.get("OPENAI_CODEX_ACCOUNT", "")
            if acct: headers["ChatGPT-Account-Id"] = acct
            return _call_stream(_stream_codex, "https://chatgpt.com/backend-api/codex/responses",
                                 headers, body, on_event)
        else:
            url = "https://api.openai.com/v1/chat/completions"
            body = {"model": model, "messages": to_openai(messages), "tools": TOOLS, "tool_choice": "auto"}
            if reasoning != "off":
                body["reasoning_effort"] = reasoning
            headers = {"Authorization": "Bearer " + key, "content-type": "application/json"}
            return _call_stream(_stream_openai_chat, url, headers, body, on_event)
    else:
        conf = {"openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
                "opencode": ("https://opencode.ai/zen/go/v1/chat/completions", "OPENCODE_API_KEY")}
        url, keyname = conf.get(provider, conf["openrouter"])
        key = v.get(keyname, "")
        if not key: raise RuntimeError("No credential configured for " + provider)
        body = {"model": model, "messages": to_openai(messages), "tools": TOOLS, "tool_choice": "auto"}
        if reasoning != "off":
            # OpenRouter's own unified format — it translates or drops this
            # per the backing model rather than erroring on an unsupported
            # model, which is what makes it safe to send unconditionally
            # here (unlike the direct-provider paths above, where an
            # unsupported field can be rejected outright).
            body["reasoning"] = {"effort": reasoning}
        headers = {"Authorization": "Bearer " + key, "content-type": "application/json"}
        if provider == "openrouter":
            headers.update({"HTTP-Referer": "https://argus.os", "X-Title": "Argus OS"})
        return _call_stream(_stream_openai_chat, url, headers, body, on_event)

# ── execution context ────────────────────────────────────────────────────

class Context:
    def __init__(self, db, session, workspace, policy, checkpoints, g):
        self.db = db; self.session = session; self.workspace = workspace
        self.policy = policy; self.checkpoints = checkpoints; self.grants = g
        self.data_dir = DATA; self.todos = []
        # First-written (test-count, assert-count) per test file, recorded by
        # lib/tools._record_test_baseline on every successful write/edit —
        # verify_deliverable compares against it to catch test-weakening.
        self.test_baseline = {}
        # MCP servers a tool call spawns are cached here for the rest of
        # this Context's lifetime (one task in run(), one call in approve())
        # rather than restarted on every call — see lib/tools.py's
        # _make_mcp_handler. Always stopped via lib/mcp.stop_all before this
        # Context goes out of scope (run()'s finish(), approve()'s finally).
        self.mcp_clients = {}

def verify(ctx, path):
    """Enforced post-write verification: syntax, then lint when available."""
    out = {}
    try:
        syn = toolreg.REGISTRY["syntax_check"]["handler"](ctx, {"path": path})
        out["syntax"] = {"ok": syn.get("ok"), "error": (syn.get("stderr") or syn.get("error") or "")[:600]}
    except Exception as e:
        out["syntax"] = {"ok": False, "error": str(e)}
    try:
        spec = ctx.workspace.tooling(ctx.workspace.resolve(path))["commands"].get("lint")
        if spec:
            lin = toolreg.REGISTRY["lint"]["handler"](ctx, {"path": path})
            out["lint"] = {"ok": lin.get("ok"), "output": (lin.get("stdout") or lin.get("error") or "")[:800]}
    except Exception as e:
        out["lint"] = {"ok": False, "error": str(e)}
    return out

# ANSI red for stderr/errors so the panel's terminal card (TerminalCard.qml,
# which renders SGR color codes as QML rich text — deliberately not xterm.js,
# see docs/07) shows failures in-place rather than needing a separate status line.
_ANSI_RED, _ANSI_RESET = "\x1b[31m", "\x1b[0m"

def tool_detail(name, result):
    """Pull the part of a tool result worth showing in a terminal-style card.
    Returns None when there is nothing more useful than the one-line summary
    already in the event (e.g. a window activation)."""
    if not isinstance(result, dict):
        return None
    if name == "run_command":
        parts = []
        if result.get("stdout"): parts.append(result["stdout"])
        if result.get("stderr"): parts.append(_ANSI_RED + result["stderr"] + _ANSI_RESET)
        text = "\n".join(parts).strip()
        return {"kind": "shell", "text": text[-4000:]} if text else None
    if name in ("edit_file", "write_file", "multi_edit") and result.get("diff"):
        return {"kind": "diff", "text": result["diff"][:4000]}
    if name in ("syntax_check", "lint", "format_file"):
        text = (result.get("stdout") or "") + (("\n" + result["stderr"]) if result.get("stderr") else "")
        text = text.strip()
        return {"kind": "shell", "text": text[:4000]} if text else None
    if name == "read_file" and result.get("content"):
        return {"kind": "code", "text": result["content"][:4000]}
    if name == "grep" and result.get("matches"):
        text = "\n".join(f"{m['file']}:{m['line']}: {m['text']}" for m in result["matches"][:60])
        return {"kind": "code", "text": text} if text else None
    if name == "desktop_actions":
        lines = []
        if result.get("results"):
            for i, r in enumerate(result["results"], 1):
                act = r.get("action", "step")
                ok_marker = "✓" if r.get("ok", True) else (_ANSI_RED + "✗" + _ANSI_RESET)
                line = f"[{i}] {ok_marker} {act}"
                # Ordered most-specific first: click_element/click_text both
                # also carry a top-level x/y (the point actually clicked), so
                # checking those generic fields first would always win and
                # this branch would never fire — badge id or matched text is
                # the more useful label for those two actions specifically.
                if act == "click_element" and "id" in r:
                    line += f" badge [{r.get('id')}]"
                    if r.get("text"):
                        line += f" '{r['text']}'"
                elif act == "click_text" and isinstance(r.get("target"), dict):
                    t = r["target"]
                    line += f" '{t.get('text', '')}' -> ({t.get('x')}, {t.get('y')})"
                elif "start" in r and "end" in r:
                    line += f" {r['start']} -> {r['end']}"
                elif "x" in r and "y" in r:
                    line += f" -> ({r['x']}, {r['y']})"
                elif r.get("key"):
                    line += f" '{r['key']}'"
                elif "text_preview" in r:
                    line += f" '{r['text_preview']}'"
                elif "direction" in r and "amount" in r:
                    line += f" {r['direction']} x{r['amount']}"
                elif act == "clipboard_paste" and "text" in r:
                    line += f" '{(r['text'] or '')[:60]}'"
                elif isinstance(r.get("window"), dict):
                    w = r["window"]
                    line += f" -> {w.get('caption') or w.get('cls') or w.get('uuid', '')}"[:80]
                elif isinstance(r.get("result"), str):
                    line += f" -> {r['result']}"
                elif "changed" in r:
                    line += f" -> changed={r.get('changed')}"
                elif act == "wait" and "duration" in r:
                    line += f" {r['duration']}s"
                if r.get("error"):
                    line += f" - {_ANSI_RED}{r['error']}{_ANSI_RESET}"
                lines.append(line)
        if result.get("screenshot_path"):
            lines.append(f"screenshot: {result['screenshot_path']}")
        elif result.get("screenshot_error"):
            lines.append(_ANSI_RED + f"screenshot failed: {result['screenshot_error']}" + _ANSI_RESET)
        if result.get("error"):
            lines.append(_ANSI_RED + f"error: {result['error']}" + _ANSI_RESET)
        text = "\n".join(lines).strip()
        return {"kind": "desktop", "text": text[:4000]} if text else None
    if name == "find_text":
        matches = result.get("matches") or []
        lines = [f"Found {len(matches)} match(es) for '{result.get('query', '')}':"]
        for i, m in enumerate(matches[:15], 1):
            box = m.get("box", [])
            lines.append(f" [{i}] \"{m.get('text', '')}\" @ center=({m.get('x')}, {m.get('y')}) box={box} conf={m.get('confidence', 0)}%")
        return {"kind": "desktop", "text": "\n".join(lines)[:4000]}
    if name == "click_text":
        target = result.get("target") or {}
        if target:
            idx = result.get("index", 0)
            total = result.get("matches_found", 1)
            text = f"Clicked '{target.get('text', '')}' at ({target.get('x')}, {target.get('y')}) [match {idx + 1}/{total}]"
            return {"kind": "desktop", "text": text}
    if name == "click_element":
        el = result.get("element") or {}
        if el:
            text = f"Clicked mark [{result.get('id')}] '{el.get('text', '')}' at ({result.get('x')}, {result.get('y')})"
            return {"kind": "desktop", "text": text}
    if name == "list_displays":
        displays = result.get("displays") or []
        lines = [f"Displays ({len(displays)}):"]
        for d in displays:
            lines.append(f" - {d.get('name', 'Display')}: {d.get('width')}x{d.get('height')} @ ({d.get('x', 0)},{d.get('y', 0)}) scale={d.get('scale', 1.0)} ({d.get('refresh_rate', 0)}Hz)")
        return {"kind": "desktop", "text": "\n".join(lines)[:4000]}
    if name == "assert_region_changed":
        changed = result.get("changed")
        pct = result.get("diff_percent", 0.0)
        status = "CHANGED" if changed else "UNCHANGED"
        text = f"Region diff: {status} ({pct:.2f}% pixels changed, threshold={result.get('threshold_percent', 0.1)}%)"
        return {"kind": "desktop", "text": text}
    if name == "wait_for_screen_change":
        status = "CHANGED" if result.get("changed") else "TIMEOUT"
        reason = result.get("reason", "no details")
        return {"kind": "desktop", "text": f"Screen change: {status} ({reason})"}
    if name in ("clipboard_paste", "clipboard_get"):
        txt = result.get("text", "")
        if txt:
            return {"kind": "shell", "text": f"Clipboard ({len(txt)} chars):\n{txt[:1000]}"}
    if not result.get("ok") and result.get("error"):
        return {"kind": "error", "text": _ANSI_RED + str(result["error"])[:2000] + _ANSI_RESET}
    return None

def _failure_detail(result):
    """Best available diagnostic text for a failed tool result. An
    explicit "error" key means an infra-level failure (timeout, missing
    binary); a command that ran and simply exited non-zero (run_tests,
    run_command) has no "error" key at all — its failure lives in stderr/
    stdout. Falling straight to a bare "unknown" for that second, very
    common case (confirmed live: an approved run_tests failure surfaced to
    the user as just "Approved action failed closed: unknown", discarding
    the actual ModuleNotFoundError traceback that explained it) makes a
    diagnosable failure look opaque."""
    if result.get("error"):
        return str(result["error"])
    for key in ("stderr", "stdout"):
        text = (result.get(key) or "").strip()
        if text:
            return text[:500]
    return "unknown"

_RANK = {"auto": 0, "prompt": 1, "deny": 2}


def _policy_subjects(spec, ctx, args):
    """Every path-like value the policy should judge for this call.

    Which argument holds the subject is declared by the tool itself
    (`subject=` in lib/tools.py) rather than assumed to be `path`, because
    assuming it meant move_file (src/dst) and checkpoint_restore (id) were
    classified with no subject at all.
    """
    declared = spec.get("subject")
    if callable(declared):
        return [s for s in (declared(ctx, args) or []) if s]
    names = declared if isinstance(declared, (list, tuple)) else ("path",)
    return [args.get(n) for n in names if args.get(n)]


def policy_decision(policy, spec, ctx, args):
    """The policy verdict for one tool call.

    Every path-like subject the tool declares is judged, and the strictest
    verdict wins (deny > prompt > auto) — a move has two, src and dst, and
    approving the source says nothing about the destination. run_command's
    `net` flag is a capability request the base "exec" classification never
    sees ($SAFE/$WORKSPACE patterns only look at the command text), so it can
    only escalate, never downgrade: a command already denied or already
    prompting stays that way.
    """
    decision, reason = "auto", ""
    for subject in _policy_subjects(spec, ctx, args) or [None]:
        d, r = policy.classify(spec["grant"], path=subject, command=args.get("command"),
                               tool=spec["name"], risk=spec["risk"])
        if _RANK[d] > _RANK[decision]:
            decision, reason = d, r
    if spec["name"] == "run_command" and args.get("net") and decision == "auto":
        decision, reason = policy.classify("net", command=args.get("command"))
    # Every exec-grant tool that takes no free-text `command` argument
    # (syntax_check, lint, format_file, run_tests — only run_command takes
    # one) dispatches to a fixed command it assembles itself from trusted
    # Python logic (see Workspace.tooling()/_python_test_cmd() and the
    # per-language branches in syntax_check/format_file), never from
    # model-supplied shell text. There is no injection surface for $SAFE to
    # be guarding here in the first place — but classify()'s exec-grant path
    # only ever auto-approves via a $SAFE match against `command`, so with
    # none to check these tools fell through to "exec outside the
    # auto-approved scope" on every single call, prompting exactly like a
    # risk="commit" action regardless of their own declared risk tier.
    # Confirmed live twice: a run_tests call stopped a real eval task dead at
    # "run the tests and confirm they pass", and — after that first instance
    # was fixed as a run_tests-only special case — the *same* mismatch showed
    # up again on syntax_check in a second, unrelated eval, which is why this
    # is now general rather than one more name check. Each of these tools'
    # own handler already calls Workspace.resolve(path, must_exist=True),
    # which refuses any path outside the workspace before this is reached, so
    # nothing left unauto'd here is still actually undecided — downgrade only
    # the specific "exec outside the auto-approved scope"/"exec requires
    # approval" prompts this mismatch produces, never a real deny from a
    # hard-deny rule or saved policy memory.
    if (spec["grant"] == "exec" and "command" not in spec["parameters"].get("properties", {})
            and decision == "prompt" and reason.startswith("exec ")):
        decision, reason = "auto", f"auto: {spec['name']} is a fixed, sandboxed, workspace-scoped action"
    return decision, reason


def journal_approval_outcome(db, session, answer_id, tool, result):
    """Record the outcome of a call that was waiting for approval.

    The pause journaled a placeholder result for this call id (see run()), so the
    outcome is written over that row rather than appended: the providers reject
    two tool results for one call id exactly as they reject none, and keeping the
    row's position is what makes the resumed turn read as the assistant message
    declaring the calls, immediately followed by one result per call.
    """
    for eid, payload in db.execute(
            "SELECT id,payload FROM events WHERE session=? AND kind='tool' ORDER BY id DESC",
            (session,)).fetchall():
        body = json.loads(payload)
        if body.get("id") == answer_id and (body.get("result") or {}).get("pending_approval"):
            body["result"] = result
            db.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(body), eid))
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
        event(db, session, "tool", {"id": cid, "name": fn.get("name", ""),
                                    "result": {"ok": False, "error": reason}})
        if progress:
            progress("act", f"{fn.get('name', '')} (not run — {reason})", "blocked", id=cid)


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
    db = connect()
    transcript = session_transcript(db, session)
    if not transcript:
        return {"ok": True, "added": 0, "note": "empty session, nothing to extract"}
    known_text = "\n".join(f"- {m['text']}" for m in list_memories(db, limit=200)) or "(nothing yet)"
    convo = "\n".join(f"{t['role']}: {t['text']}" for t in transcript)[:20_000]
    messages = [
        {"role": "system", "content": _MEMORY_EXTRACTION_PROMPT + "\n\nAlready known:\n" + known_text},
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


def run(task, session, workspace_root, stream=False, is_continuation=False):
    db = connect()
    event(db, session, "user", {"text": task})
    # `is_continuation` is only true for the synthetic "Continue the previous
    # task..." message approve() sends after a resumed approval — the same
    # task still in flight, not a new instruction. A real new task replaces
    # the pinned anchors so a stale plan from a previous, unrelated request
    # can't leak forward and get mistaken for the current one; a continuation
    # leaves them alone so the task and plan survive the resume.
    if is_continuation:
        saved_todos = get_state(db, session, "todos") or "[]"
        task_started = float(get_state(db, session, "task_started") or time.time())
        steps_used = int(get_state(db, session, "task_steps") or 0)
    else:
        task_started = time.time()
        steps_used = 0
        set_state(db, session, "current_task", task)
        set_state(db, session, "todos", "[]")
        set_state(db, session, "task_started", task_started)
        set_state(db, session, "task_steps", steps_used)
        saved_todos = "[]"
    try:
        ws = Workspace(workspace_root)
    except Exception as e:
        return {"ok": False, "text": f"⚠️ Invalid workspace: {e}"}
    policy = Policy(ws.root)
    cps = Checkpoints(session)
    g = grants()
    ctx = Context(db, session, ws, policy, cps, g)
    try:
        ctx.todos = json.loads(saved_todos)
    except Exception:
        ctx.todos = []
    if stream and ctx.todos:
        emit({"type": "todos", "todos": ctx.todos})
    comp = compact(db, session)
    events = []
    started = time.time()

    def progress(kind, summary, status="ok", id=None, detail=None):
        e = {"kind": kind, "summary": summary, "status": status}
        if id is not None: e["id"] = id
        if detail is not None: e["detail"] = detail
        events.append(e)
        if stream: emit({"type": "event", **e})

    # Fired for every streamed provider delta (prose tokens, tool-call name/
    # arguments as the model generates them). A no-op when not streaming, so
    # the SSE parsers never need to know whether anyone is listening.
    def stream_cb(evt):
        if stream: emit(evt)

    def finish(text, ok=True, **extra):
        """Every exit path goes through here, so the journal always ends with
        the assistant's final words — a truncated journal made the panel look
        like it had silently died."""
        mcp.stop_all(ctx.mcp_clients)
        _clean_workspace_caches(ws.root)
        event(db, session, "assistant", {"text": text})
        res = {"ok": ok, "text": text, "events": events,
               "compaction": comp, "todos": ctx.todos}
        res.update(extra)
        return res

    # A model that repeats the exact same call *back to back* is flailing,
    # not making progress. This used to count cumulatively over the whole
    # task instead of consecutively — so a zero/fixed-argument tool that's
    # legitimately called more than once over a longer task (observe_screen,
    # active_window, list_windows: exactly what the system prompt itself
    # tells the model to do for verification — "observe_screen or
    # active_window afterwards") got falsely flagged as a stuck duplicate on
    # its second use, no matter how much unrelated, useful work happened in
    # between. Confirmed live: a task calling list_windows, then list_apps,
    # then list_windows again (a completely ordinary before/after check) had
    # the second list_windows blocked as "duplicate — redirected" purely
    # because its signature matched the first call from steps earlier.
    # Tracking only the single most recent signature (reset the moment a
    # different call happens) still catches the actual flailing pattern —
    # the same call with nothing else in between — without penalizing
    # ordinary spaced-out reuse.
    last_sig = None
    consecutive = 0
    last_results = {}
    REPEAT_ABORT = 5      # hard stop; below this the model is redirected instead

    # Tell the model what it is working with before it starts guessing:
    # the root, the project kind, and which verify commands actually exist.
    proj = ws.project()
    probe = None
    for f in ws.walk(".", limit=200):
        if f.suffix in (".py", ".qml", ".ts", ".js", ".rs", ".c", ".cpp", ".sh", ".lua"):
            probe = f
            break
    tooling = ws.tooling(probe)["commands"] if probe else {}
    available = {k: " ".join(v) for k, v in tooling.items() if v}
    missing = [k for k, v in tooling.items() if not v]
    # Tell the model what the desktop can actually do, so it reports a missing
    # capability instead of burning steps retrying something that cannot work.
    caps = kwin.capabilities()
    desktop = (f"screen capture={'yes' if caps['screenshots'] else 'NO'}, "
               f"window inventory={'yes' if caps['window_inventory'] else 'NO'}, "
               f"window control={'yes' if caps['window_control'] else 'NO'}, "
               f"keyboard input={'yes' if caps['keyboard'] else 'NO'}, "
               f"pointer input={'yes' if caps['pointer'] else 'NO'}")
    if not caps["keyboard"]:
        desktop += f" — keyboard unavailable: {caps['keyboard_detail']}"
    if not caps["pointer"]:
        desktop += f" — pointer unavailable: {caps['pointer_detail']}"
    # Unlike node's npm test / cargo's cargo test, Python's test runner
    # can't be inferred from a project marker file — pytest vs. plain
    # unittest.discover depends only on what's actually importable, and
    # Python needs no marker at all to be a valid choice, so a brand-new/
    # empty workspace gives the probe-file-based `available` detection
    # above nothing to go on for it specifically. Reported unconditionally,
    # not gated behind finding a .py file first, so the model knows which
    # style to write *before* writing its first test — confirmed live:
    # without this, in an empty workspace with pytest not installed, the
    # model defaulted to writing pytest-style tests (the idiomatic default)
    # and they failed to even import when run_tests actually ran them.
    py_test_cmd = Workspace._python_test_cmd()
    py_test_line = ("Python test runner: " +
                     (" ".join(py_test_cmd) if py_test_cmd
                      else "none installed — do NOT `import pytest`; write plain unittest.TestCase tests") + "\n")
    ws_info = (f"Workspace root: {ws.root}\nProject kind: {proj['kind']}\n"
               f"Available verification commands: {available or 'none'}\n"
               + (f"Not installed (do not try these): {', '.join(missing)}\n" if missing else "")
               + py_test_line
               + f"Desktop capabilities: {desktop}\n"
               + "If a capability is NO, say so plainly instead of retrying it.\n"
               + f"Sandbox: {'bwrap + cgroup limits' if sandbox.available() else 'UNAVAILABLE — commands run unsandboxed'}")
    progress("perceive", f"Workspace {ws.root} · {proj['kind']} · sandbox={sandbox.available()}"
             + (f" · verify: {', '.join(available)}" if available else ""))

    # Nudge (at most once per run) rather than trust a stop that leaves the
    # model's own plan half-done: a model that quietly abandons pending
    # todo_write items and starts chatting is drifting off task just as much
    # as one that wanders into unrelated work mid-stream.
    nudged_incomplete_todos = False

    # Same idea for verification. The system prompt already says "for
    # anything with real logic, write or extend a test and run it with
    # run_tests" — but that's a text instruction a model can simply forget
    # under step-budget pressure, especially a faster/cheaper one, and
    # nothing before this caught it: a task could mutate a file in a project
    # with a perfectly good test command available and still finish having
    # never run it. This is advisory, not a hard gate — the model can answer
    # the nudge with "this was a one-line config change, no test needed" and
    # finish anyway, same as the todo nudge doesn't force todo completion.
    mutated_testable_file = False
    ran_tests = False
    nudged_missing_verification = False

    # A mid-stream connection drop after real content already arrived (see
    # _DURABLE_STREAM_EVENT_TYPES) used to kill the whole task outright —
    # confirmed live twice ("Upstream idle timeout exceeded" against a slow
    # free model), discarding whatever the model had already written.
    # provider_call now salvages that partial text instead of raising (see
    # _stream_openai_chat/_stream_anthropic), and this just bounds how many
    # times in a row this task will accept "keep going from a drop" before
    # giving up for real — a persistently flaky connection should still end
    # the task rather than silently eat the whole step budget retrying.
    stream_truncations = 0

    # Per-tool timing, kept only to explain *why* a task ran out of budget —
    # "stopped after 600s" alone doesn't say whether that was one slow
    # run_command or twenty ordinary steps. Logged (never shown to the model)
    # whenever the task is stopped by a limit rather than finishing cleanly.
    tool_durations = {}
    provider_seconds = 0.0

    def _log_budget_incident(event_name, **extra):
        errlog.warning(event_name, session=session, step=step_idx,
                       elapsed=round(time.time() - started, 2),
                       provider_seconds=round(provider_seconds, 2),
                       tool_durations={k: {"count": v["count"], "seconds": round(v["seconds"], 2)}
                                       for k, v in tool_durations.items()},
                       last_tool=last_sig, **extra)

    for step_idx in range(steps_used, MAX_STEPS):
        set_state(db, session, "task_steps", step_idx + 1)
        task_elapsed = time.time() - task_started
        if task_elapsed > MAX_TASK_SECONDS:
            _log_budget_incident("task_budget_exceeded", budget_seconds=MAX_TASK_SECONDS,
                                 task_elapsed=round(task_elapsed, 2))
            return finish(f"Stopped after the {MAX_TASK_SECONDS}s cumulative task budget. "
                          "Partial progress is in the action feed.", ok=False)
        # A single run() can itself emit far more than MAX_CONTEXT_EVENTS
        # (an assistant + tool event per step, up to MAX_STEPS steps), so
        # compaction must be re-checked every step, not just once at entry —
        # otherwise the original task can scroll out of context() mid-task.
        c = compact(db, session)
        if c: comp = c
        remaining = MAX_STEPS - step_idx
        step_info = None
        if remaining <= 5:
            step_info = (f"Step budget: {step_idx + 1} of {MAX_STEPS} used this task, "
                         f"{remaining} left. If the work is close to done, stop exploring "
                         "and wrap up now: verify what you changed and report the outcome "
                         "before the budget runs out mid-action.")
        provider_t0 = time.time()
        try:
            reply = provider_call(context(db, session, ws_info, step_info), stream_cb)
        except Exception as e:
            if _image_unsupported_error(e) and get_state(db, session, "no_image_support") != "1":
                # One-shot self-heal: strip images and retry this same step
                # rather than aborting the whole task over one screenshot —
                # see the comment on _image_unsupported_error. Guarded by the
                # state flag so a *different*, genuinely fatal request error
                # still fails the task instead of looping.
                set_state(db, session, "no_image_support", "1")
                errlog.warning("model_lacks_image_support", session=session, step=step_idx,
                               detail=str(e)[:300])
                progress("act", "current model can't accept image input — continuing "
                                "without screenshots", "ok")
                continue
            errlog.exception("provider_call_failed", e, session=session, step=step_idx,
                             elapsed=round(time.time() - started, 2))
            return finish("⚠️ " + str(e), ok=False)
        provider_seconds += time.time() - provider_t0
        if reply.get("_stream_truncated"):
            stream_truncations += 1
            text = (reply.get("choices", [{}])[0].get("message", {}) or {}).get("content") or ""
            if text:
                event(db, session, "assistant", {"text": text})
            reason = str(reply.get("_truncation_reason", "connection interrupted"))[:200]
            errlog.warning("stream_truncated_recovered", session=session, step=step_idx,
                           reason=reason, recovered_chars=len(text),
                           attempt=stream_truncations)
            if stream_truncations > MAX_STREAM_TRUNCATIONS:
                return finish(f"⚠️ The connection to the model kept dropping mid-reply "
                              f"({stream_truncations} times this task) — stopping instead "
                              "of retrying indefinitely. Partial progress is in the "
                              "action feed.", ok=False)
            progress("act", "connection dropped mid-reply — continuing from what was "
                            "received", "ok", detail=reason)
            event(db, session, "user", {"text": "Your last reply was cut off mid-stream by "
                                        "a connection drop. Continue exactly where you left "
                                        "off — do not restart or repeat what you already said."})
            continue
        choice = reply.get("choices", [{}])[0].get("message", {})
        calls = choice.get("tool_calls", [])
        if not calls:
            pending = [t for t in ctx.todos if t.get("status") != "completed"]
            if pending and not nudged_incomplete_todos and step_idx < MAX_STEPS - 1:
                nudged_incomplete_todos = True
                items = "; ".join(t.get("content", "") for t in pending[:5])
                event(db, session, "assistant", {"text": choice.get("content") or ""})
                event(db, session, "user", {"text": "Your own plan (todo_write) still has "
                                            f"unfinished items: {items}. Continue and finish "
                                            "them, or call todo_write to update the plan if "
                                            "they are no longer needed, before stopping."})
                progress("act", "unfinished todo items — continuing instead of stopping", "ok")
                continue
            if (mutated_testable_file and not ran_tests
                    and not nudged_missing_verification and step_idx < MAX_STEPS - 1):
                nudged_missing_verification = True
                event(db, session, "assistant", {"text": choice.get("content") or ""})
                event(db, session, "user", {"text": "You edited code in a project that has a "
                                            "test command available, but never ran run_tests. "
                                            "If this change has real logic behind it, verify it "
                                            "now before finishing; if it was genuinely a trivial "
                                            "change (config, comments, a rename) say so and "
                                            "finish."})
                progress("act", "no test run yet — continuing instead of stopping", "ok")
                continue
            return finish(choice.get("content") or "(The model returned no text.)")
        event(db, session, "assistant", {"text": "", "tool_calls": calls})

        for c_idx, c in enumerate(calls):
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except Exception:
                args = {}
            cid = c.get("id", str(now()))
            spec = toolreg.REGISTRY.get(name)
            if not spec:
                result = {"ok": False, "error": "unknown tool: " + name}
                event(db, session, "tool", {"id": cid, "name": name, "result": result})
                progress("act", f"{name} (unknown tool)", "blocked", id=cid)
                continue

            sig = name + ":" + json.dumps(args, sort_keys=True)
            consecutive = consecutive + 1 if sig == last_sig else 1
            last_sig = sig
            if consecutive >= REPEAT_ABORT:
                last = last_results.get(sig, {})
                errlog.warning("task_stuck_repeat", session=session, step=step_idx,
                               tool=name, args=_summarize_args(args), repeats=consecutive,
                               last_result=_clip_strings(last, 300))
                abandon_calls(db, session, calls, c_idx,
                              "not executed — the runtime stopped this task as stuck",
                              progress)
                return finish(
                    f"Stopped: {name} was called {consecutive} times in a row with "
                    f"identical arguments and is not making progress. Last result: "
                    f"{json.dumps(last)[:300]}", ok=False)
            if consecutive >= 2:
                # Correct rather than abort: hand the model the previous result
                # plus explicit guidance, and let it choose a different action.
                result = {"ok": False,
                          "error": f"duplicate call: {name} was already called with "
                                   f"these exact arguments. The result is unchanged.",
                          "previous_result": last_results.get(sig, {}),
                          "guidance": "Do not repeat this call. Take a different "
                                      "action, or report the blocker if none is possible."}
                event(db, session, "tool", {"id": cid, "name": name, "result": result})
                progress("act", f"{name} (duplicate — redirected)", "blocked", id=cid)
                continue

            ng = spec.get("needs_grant")
            if ng and not g.get(ng):
                result = {"ok": False, "error": ng + " grant disabled"}
                event(db, session, "tool", {"id": cid, "name": name, "result": result})
                progress("act", f"{name} (blocked: no {ng} grant)", "blocked", id=cid)
                continue

            decision, reason = policy_decision(policy, spec, ctx, args)
            if decision == "deny":
                result = {"ok": False, "error": "policy: " + reason}
                event(db, session, "tool", {"id": cid, "name": name, "result": result})
                progress("act", f"{name} denied — {reason}", "blocked", id=cid)
                continue
            if decision == "prompt":
                aid = f"a-{now()}"
                # call_id is the model's own tool_call id: the resumed turn's
                # history declares that id, so the result approve() journals has
                # to answer *that* call, not the approval handle.
                db.execute("INSERT INTO approvals(id,ts,tool,args,status,session,call_id) "
                           "VALUES(?,?,?,?,?,?,?)",
                           (aid, now(), name, json.dumps(args), "pending", session, cid)); db.commit()
                progress("act", f"{name} awaiting approval", "blocked", id=cid)
                # Answer this call right away with a placeholder that approve()
                # later overwrites. Both halves matter: a turn whose declared
                # calls are not all answered is rejected by the provider, and so
                # is a call answered twice — and the resume cannot happen until
                # the user decides, so the placeholder is what keeps the journal
                # consistent in between.
                event(db, session, "tool", {"id": cid, "name": name,
                                            "result": {"ok": False, "pending_approval": True,
                                                       "error": f"awaiting user approval ({aid})"}})
                # A sibling call in the same turn will not run while this one
                # waits; it still has to be answered in the journal.
                abandon_calls(db, session, calls, c_idx + 1,
                              "not executed — a sibling call in the same turn is awaiting "
                              "approval; re-issue it after the approval if it is still needed",
                              progress)
                return finish(f"Approval required: {name}",
                              approval={"id": aid,
                                        "summary": name + " " + json.dumps(args)[:200],
                                        "risk": spec["risk"], "reason": reason})

            # Marks the live tool-call card "running" between the streamed
            # arguments finishing and the handler actually returning — the gap
            # can be seconds for run_command, and without this the card just
            # sits there with no sign the runtime picked it up.
            progress("act", f"{name} running…", "ok", id=cid)

            tool_t0 = time.time()
            crashed = False
            try:
                result = spec["handler"](ctx, args)
            except PermissionError as e:
                # Expected, model-facing failures (bad path, missing file) —
                # not a runtime bug, so no traceback, just a plain record.
                result = {"ok": False, "error": str(e)}
            except FileNotFoundError as e:
                result = {"ok": False, "error": "not found: " + str(e)}
            except Exception as e:
                # traceback.format_exc() only sees anything while the except
                # block that caught it is still on the stack, so the log call
                # has to happen here — not after the try/except returns, by
                # which point sys.exc_info() has already been cleared and
                # every traceback comes back empty.
                result = {"ok": False, "error": "tool crashed: " + str(e)}
                crashed = True
                errlog.exception("tool_crashed", e, tool=name, session=session,
                                 step=step_idx, args=_summarize_args(args),
                                 seconds=round(time.time() - tool_t0, 2))
            tool_dur = time.time() - tool_t0
            td = tool_durations.setdefault(name, {"count": 0, "seconds": 0.0})
            td["count"] += 1; td["seconds"] += tool_dur

            if not crashed and not result.get("ok"):
                # Not every ok:false result is a bug (a lint failure or a bad
                # regex is the model's mistake, not the runtime's), but logging
                # all of them costs nothing and means a *systemic* one — a
                # sandbox timeout, a policy the model keeps tripping, a tool
                # that's silently broken — shows up as a repeated `event` in
                # the log instead of only ever being visible in the one
                # journal entry that gets compacted away.
                # _failure_detail(), not str(result.get("error")): run_tests/
                # run_command have no "error" key at all on a normal non-zero
                # exit (see _failure_detail's own docstring) — their failure
                # lives in stdout/stderr. The naive version logged the
                # literal string "None" for every one of those, which is
                # exactly the case this log exists to make diagnosable
                # (confirmed live: chased a run_tests loop through this log
                # during an eval and got nothing but "error: None" for it).
                errlog.warning("tool_failed", tool=name, session=session, step=step_idx,
                               error=_failure_detail(result)[:500],
                               args=_summarize_args(args), seconds=round(tool_dur, 2))
            if tool_dur > SLOW_TOOL_SECONDS:
                errlog.warning("slow_tool_call", tool=name, session=session, step=step_idx,
                               seconds=round(tool_dur, 2), args=_summarize_args(args))

            if name == "todo_write" and result.get("ok") and stream:
                emit({"type": "todos", "todos": ctx.todos})

            if spec["mutates"] and result.get("ok") and args.get("path"):
                v = verify(ctx, args["path"])
                result["verify"] = v
                ok = v.get("syntax", {}).get("ok")
                progress("verify", f"{name} → syntax {'ok' if ok else 'FAILED'}"
                         + (" · lint ok" if v.get("lint", {}).get("ok") else ""),
                         "ok" if ok else "blocked", id=cid)
                if not mutated_testable_file:
                    try:
                        p = ctx.workspace.resolve(args["path"])
                        if ctx.workspace.tooling(p)["commands"].get("test"):
                            mutated_testable_file = True
                    except Exception:
                        pass
            if name == "run_tests":
                ran_tests = True

            last_results[sig] = result
            event(db, session, "tool", {"id": cid, "name": name, "result": result})
            summary = name
            if name in ("edit_file", "write_file", "multi_edit"):
                summary = f"{name} {result.get('path','')}"
            elif name == "run_command":
                summary = f"run_command: {str(args.get('command',''))[:60]}"
            progress("act", summary, "ok" if result.get("ok") else "blocked",
                     id=cid, detail=tool_detail(name, result))

    step_idx = max(steps_used - 1, MAX_STEPS - 1)
    _log_budget_incident("task_step_limit_exceeded", step_budget=MAX_STEPS)
    return finish(f"Stopped after {MAX_STEPS} tool steps without finishing. "
                  "The action feed shows what was attempted.", ok=False)

def approve(approval_id, allow, workspace_root, resume=True, stream=False, always=False):
    db = connect()
    row = db.execute("SELECT tool,args,status,session,call_id FROM approvals WHERE id=?",
                     (approval_id,)).fetchone()
    if not row: return {"ok": False, "text": "Approval no longer exists."}
    tool, raw, status, session, call_id = row; session = session or "default"
    # Answer the model's own tool_call when it is known — see run()'s INSERT.
    # Older pending approvals (and any row from before this column existed) fall
    # back to the approval id, which is what the journal used before.
    answer_id = call_id or approval_id
    if status != "pending": return {"ok": False, "text": "Approval was already resolved."}
    args = json.loads(raw)
    if not allow:
        db.execute("UPDATE approvals SET status='denied' WHERE id=?", (approval_id,)); db.commit()
        journal_approval_outcome(db, session, answer_id, tool,
                                 {"ok": False, "error": "denied by user"})
        e = {"kind": "commit", "summary": tool + " denied", "status": "blocked", "id": approval_id}
        if stream: emit({"type": "event", **e})
        return {"ok": True, "text": "Action denied and retained in the audit journal.", "events": [e]}
    if stream: emit({"type": "event", "kind": "commit", "summary": f"{tool} running…",
                     "status": "ok", "id": approval_id})
    ctx = None
    try:
        ws = Workspace(workspace_root)
        policy = Policy(ws.root)
        ctx = Context(db, session, ws, policy, Checkpoints(session), grants())
        spec = toolreg.REGISTRY.get(tool)
        result = spec["handler"](ctx, args) if spec else {"ok": False, "error": "unknown tool"}
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    finally:
        # A resumed approval executes exactly one tool call, so there is no
        # reason to keep whatever MCP server it spawned alive after —
        # unlike run()'s finish(), which amortizes a server across a whole
        # task's worth of calls.
        if ctx is not None:
            mcp.stop_all(ctx.mcp_clients)
    if tool == "todo_write" and result.get("ok") and stream:
        emit({"type": "todos", "todos": ctx.todos})
    db.execute("UPDATE approvals SET status=? WHERE id=?",
               ("executed" if result.get("ok") else "blocked", approval_id)); db.commit()
    journal_approval_outcome(db, session, answer_id, tool, result)

    # "Always allow" persists a rule keyed on the exact subject that was
    # approved (never a wildcard) — see policy.py's `_matches`. This must use
    # the tool's own declared `subject=` (via _policy_subjects, the same
    # derivation policy_decision() itself judges the call against), not just
    # args["command"]/args["path"]: confirmed live, approving an MCP tool
    # call with --always executed it but silently left no rule behind — its
    # subject is a callable producing "server.tool" (lib/tools.py's
    # _register_mcp_tools), which neither literal argument name matches, so
    # the very next identical call prompted again as if `always` had done
    # nothing. run_command has no declared subject at all (classify() reads
    # its command text directly instead), so the literal-argument fallback
    # stays for it and for any other tool in the same position. A
    # computer-use commit action (type_text, key_press, ...) has neither a
    # declared subject nor a command/path argument, so `always` still
    # behaves like a one-time approval for those, same as before.
    if always and result.get("ok"):
        subjects = list(_policy_subjects(spec, ctx, args)) if spec else []
        if not subjects:
            legacy = args.get("command") or args.get("path")
            if legacy:
                subjects = [legacy]
        for subject in subjects:
            policy.remember(subject, True)

    ev = {"kind": "commit", "summary": tool, "status": "ok" if result.get("ok") else "blocked",
          "id": approval_id, "detail": tool_detail(tool, result)}
    if stream: emit({"type": "event", **ev})
    out = {"ok": bool(result.get("ok")),
           "text": "Approved action completed." if result.get("ok")
                   else "Approved action failed closed: " + _failure_detail(result),
           "events": [ev]}

    # Resume the conversation. Without this the task simply stops at the
    # approval and the user has to re-send it — which makes multi-step
    # computer use (ctrl+l, then type) unusable.
    if resume and result.get("ok"):
        try:
            cont = run(f"Continue the previous task. The approved action "
                       f"({tool}) executed successfully. Take the next step, or "
                       f"report the outcome if the task is complete.",
                       session, workspace_root, stream=stream, is_continuation=True)
            out["events"] = out["events"] + (cont.get("events") or [])
            out["text"] = cont.get("text") or out["text"]
            out["ok"] = cont.get("ok", out["ok"])
            if cont.get("approval"):
                out["approval"] = cont["approval"]
            if cont.get("todos"):
                out["todos"] = cont["todos"]
        except Exception as e:
            out["text"] = out["text"] + f" (could not resume: {e})"
    return out

def doctor(workspace_root):
    p = prefs(); v = vault()
    try:
        ws = Workspace(workspace_root)
        ws_info = {"root": str(ws.root), **ws.project()}
    except Exception as e:
        ws_info = {"error": str(e)}
    recent_errors = [e for e in errlog.tail(200) if e.get("level") in ("WARNING", "ERROR")][-10:]
    emit({"python": sys.version.split()[0], "database": str(DB), "encrypted": False,
          "sandbox": sandbox.describe(),
          "kwin": kwin.capabilities(),
          "adapters": {x: bool(shutil.which(x)) for x in ["grim", "ydotool", "wtype", "gdbus", "rg", "fd"]},
          "lsp": {k: bool(v2) for k, v2 in lsp.available_servers().items()},
          "formatters": {x: bool(shutil.which(x)) for x in
                         ["ruff", "black", "prettier", "eslint", "rustfmt", "clang-format",
                          "shellcheck", "shfmt", "qmllint", "qmlformat"]},
          "provider": p.get("provider"), "model": p.get("model"),
          "limits": {"task_seconds": MAX_TASK_SECONDS, "steps": MAX_STEPS,
                     "context_chars": MAX_CONTEXT_CHARS, "context_events": MAX_CONTEXT_EVENTS,
                     "keep_events": KEEP_EVENTS, "summary_chars": SUMMARY_CHARS},
          "credentials": sorted(k for k in v if v[k]),
          "workspace": ws_info, "tools": sorted(toolreg.REGISTRY.keys()),
          "log_file": str(errlog.LOG_FILE), "recent_errors": recent_errors})

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--task", required=True)
    r.add_argument("--session", default="default")
    r.add_argument("--workspace", default=str(Path.cwd()))
    r.add_argument("--stream", action="store_true")
    x = sub.add_parser("approve")
    x.add_argument("id"); x.add_argument("--allow", action="store_true")
    x.add_argument("--always", action="store_true",
                    help="remember this exact command/path so it auto-approves next time")
    x.add_argument("--workspace", default=str(Path.cwd()))
    x.add_argument("--stream", action="store_true")
    d = sub.add_parser("doctor"); d.add_argument("--workspace", default=str(Path.cwd()))
    s = sub.add_parser("serve", help="run the persistent Unix-socket daemon")
    s.add_argument("--socket", default=str(daemon.socket_path()))
    c = sub.add_parser("client", help="send one JSON request to the daemon")
    c.add_argument("--socket", default=str(daemon.socket_path()))
    c.add_argument("--request", required=True)
    e = sub.add_parser("errors", help="tail the incident log (argus.log) — "
                        "crashes, tool failures, budget/step-limit stops, with tracebacks")
    e.add_argument("-n", "--count", type=int, default=20)
    m = sub.add_parser("mcp-probe", help="spawn one configured MCP server, list its tools, "
                        "and write the result back into mcp.json — used by the Agent Panel's "
                        "MCP tab \"Test\" action")
    m.add_argument("--name", required=True)
    sub.add_parser("list-sessions", help="past conversations, newest first — "
                    "used by the Agent Panel's History tab")
    st = sub.add_parser("session-transcript", help="a past session's messages, as text bubbles")
    st.add_argument("--session", required=True)
    sub.add_parser("list-memories", help="everything remembered via remember_fact or "
                    "automatic extraction")
    dm = sub.add_parser("delete-memory")
    dm.add_argument("--id", required=True, type=int)
    em = sub.add_parser("extract-memory", help="one small provider call over a finished "
                        "session's transcript, pulling out durable cross-session facts — "
                        "used when the Agent Panel starts a new session")
    em.add_argument("--session", required=True)
    a = ap.parse_args()

    if a.cmd == "doctor":
        doctor(a.workspace); return
    if a.cmd == "serve":
        daemon.serve(Path(__file__), a.socket); return
    if a.cmd == "client":
        daemon.client(json.loads(a.request), a.socket); return
    if a.cmd == "errors":
        for rec in errlog.tail(a.count):
            emit(rec)
        return
    if a.cmd == "mcp-probe":
        emit(mcp.probe_server(a.name)); return
    if a.cmd == "list-sessions":
        emit({"ok": True, "sessions": list_sessions(connect())}); return
    if a.cmd == "session-transcript":
        emit({"ok": True, "messages": session_transcript(connect(), a.session)}); return
    if a.cmd == "list-memories":
        emit({"ok": True, "memories": list_memories(connect())}); return
    if a.cmd == "delete-memory":
        delete_memory(connect(), a.id); emit({"ok": True}); return
    if a.cmd == "extract-memory":
        emit(extract_memory(a.session)); return
    if a.cmd == "approve":
        res = approve(a.id, a.allow, a.workspace, stream=a.stream, always=a.always)
        emit({"type": "result", **res} if a.stream else res)
        return
    try:
        res = run(a.task, a.session, a.workspace, stream=a.stream)
    except Exception as e:
        errlog.exception("uncaught_run_exception", e, task=str(a.task)[:200],
                         session=a.session, workspace=a.workspace)
        res = {"ok": False, "text": "⚠️ " + str(e)}
    if a.stream:
        emit({"type": "result", **res})
    else:
        emit(res)

if __name__ == "__main__":
    main()
