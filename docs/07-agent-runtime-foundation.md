# Argus runtime foundation

`runtime/argusd.py` is the execution loop: journaled, sandboxed, policy-gated,
with a coding tool surface alongside computer use. It is designed to be
upgraded into the long-running socket daemon described in
`03-agent-runtime.md` without changing its journal, tool contracts or policy
file.

## Layout

```
runtime/
├── argusd.py          loop, providers, journal, CLI (run / approve / doctor)
└── lib/
    ├── sandbox.py     bwrap isolation + cgroup limits for executed commands
    ├── workspace.py   one project root; path validation; language/tooling detection
    ├── policy.py      auto / prompt / deny per capability, with saved rules
    ├── tools.py       tool registry (tools as data) + handlers
    ├── lsp.py         minimal LSP client (real diagnostics, not regex linting)
    ├── kwin.py        KWin adapter: window inventory/control, screenshots, input
    └── checkpoints.py undo for agent file writes
```

## What is real now

- **Journal.** Every user turn, model reply, tool call, result, approval and
  checkpoint is written to `~/.local/share/argus/memory.sqlite3` (WAL). The
  active context compacts at 80k characters *or* `MAX_CONTEXT_EVENTS` (60)
  events, checked every step — not just once per `run()` call — since a
  single task can emit far more than 60 events on its own before the
  character threshold is ever reached. Originals move to `archived_events`
  and remain searchable via `search_memory`; summaries are scoped per
  session so one task's history can't bleed into another's context. Nothing
  is discarded.
- **Staying on task.** The model can't lose the goal just because raw
  history got trimmed: the task text and the live `todo_write` plan are
  pinned in `session_state` (not the rolling event window) and restated as
  system messages on every turn, independent of compaction. A new user
  instruction replaces both; the synthetic "continue" message `approve()`
  sends after a resumed approval is flagged internally so it doesn't
  overwrite them mid-task. The last 5 steps of a run additionally get an
  explicit step-budget notice telling the model to wrap up rather than start
  new exploration it won't have room to finish. If the model stops (no tool
  calls) while its own `todo_write` plan still has incomplete items, the
  runtime nudges it once — logging the premature stop, then feeding back the
  unfinished items and giving it one more turn — instead of trusting a stop
  that abandons its own plan. Only once per run, so a model that still wants
  to stop after that gets to.
- **Provider retries.** A rate limit, a 5xx, or a connect-level network blip
  no longer kills the whole task outright: `_call_stream` retries up to twice
  with backoff (honoring `Retry-After` when the provider sends one). The
  retry is only taken if nothing has been streamed to the UI yet for that
  attempt — once a delta has actually reached the panel, retrying would
  re-run the turn from scratch and duplicate what's already rendered, so
  that case still fails immediately as before.
- **Workspace.** The agent operates inside one declared root (`--workspace`,
  set from the Agent Panel). Every path is resolved and containment-checked
  *after* symlink resolution, so a link inside the workspace cannot reach out
  of it. Escapes are refused, not warned about.
- **Sandbox.** Commands run under `bwrap` with a synthetic root containing
  only `/usr`, `/etc`, `/proc`, `/dev` and a tmpfs `/tmp`, plus the workspace
  bound at its real path (read-only unless the call asks for write). The host
  filesystem, session bus, Wayland socket and the agent's own environment
  (including API keys — `--clearenv`) are absent. `systemd-run --user --scope`
  applies `MemoryMax`, `MemorySwapMax`, `TasksMax` and `CPUQuota`; POSIX
  rlimits are the fallback. Verified on this host: a fork bomb is refused at
  the process cap, a disk-fill loop is capped at 512 MiB, a 4 GiB allocation
  is killed, and the real `~/.bashrc` is untouched.
- **Timeout actually stops the process tree now — it didn't.** Every
  memory/CPU/process-count limit above is real, but until now "timed out
  after Ns" was a lie for one specific shape of command: anything that
  backgrounds a child (`long_running_thing &`) inside the sandboxed shell.
  `subprocess.run(..., timeout=...)`'s default handling only kills the one
  PID it tracks; bwrap forks internally (an outer monitor process plus an
  inner one that becomes PID 1 of the new PID namespace and execs the
  actual command), so that PID is never the whole tree. Confirmed live,
  repeatedly, with `sleep 30 &` inside a `run_command`-shaped call given a
  2s timeout: the process was still running a full second after "timed out"
  had already been returned to the caller — untracked, unbounded by
  anything but its own cgroup membership, indistinguishable from a
  legitimate result. The first fix attempted — `os.setsid()` on the direct
  child, then `os.killpg()` on timeout — did *not* work either, and that
  failure is itself informative: `bwrap`'s own `--new-session` flag (in
  `BWRAP_BASE` for a real reason — it's what stops a sandboxed process from
  using the TIOCSTI ioctl to inject input into the controlling terminal and
  escape the sandbox) puts the *inner* sandboxed process into a session and
  process group of its own, disconnected from the outer monitor's group —
  confirmed via `ps --forest`, where the two bwrap layers showed different
  `pgid`s. `os.killpg()` on the outer group physically cannot reach a
  process in a different group; needing the same anti-escape hardening the
  timeout fix has to route around is a reminder that isolation is layered,
  and each layer's own defenses can quietly defeat a fix at another layer
  that isn't checked against the process tree it produces. The actual fix
  walks `/proc/<pid>/task/*/children` recursively from the tracked root PID
  and kills every PID it finds directly, layer by layer — not relying on
  process-group or session boundaries at all, so it isn't affected by bwrap
  creating new ones internally. Re-verified clean after the fix, repeatedly
  (initial "still leaking" readings during the same investigation turned
  out to be `pgrep` pattern self-matches against the *test harness's own*
  command-line text, and a since-recognized unrelated `sleep 1` from the
  Argus Bar's own `argus-sysmon.sh` polling loop — worth naming because it's
  exactly the kind of false signal that would make someone revert a correct
  fix; a wrapped test script (so the invoking command line never itself
  contains the process name being searched for) plus an exact-match `pgrep
  -x`/argument check was what finally gave an unambiguous result).
- **Policy.** Three outcomes — `auto`, `prompt`, `deny` — decided per
  capability with path/command scoping. Reads and writes inside the workspace
  are automatic; anything outside prompts. A hard-deny list (`sudo`, `pacman`,
  `mkfs`, `rm -rf /`, `systemctl`, …) is never offered for approval. Safe
  commands may be chained (`py_compile x.py && unittest discover`); each
  segment is validated independently, so `ls && rm -rf /` still fails.
  `python3 -c`, `$(…)` and backticks are always the arbitrary-execution path
  and always prompt. "Always allow" decisions persist to
  `~/.config/argus/policy.json`.
- **Tool registry.** Tools are data (`lib/tools.py`): schema, grant, risk,
  whether they mutate, and what verification they need. The loop applies one
  pipeline — policy → checkpoint → execute → verify → journal — to every tool,
  so safety is inherited rather than re-implemented per handler.
- **Verification pipeline.** After any write, the runtime runs a syntax check
  and then the language's linter if installed, and attaches the result to the
  tool result. The model sees its own breakage immediately instead of
  reporting success.
- **LSP.** Real language servers, not regex linting: pyright (Python),
  typescript-language-server (JS/TS), qmlls (QML), clangd (C/C++). Diagnostics
  include type errors and unresolved names; `lsp_symbols` gives file structure.
  Servers are spawned per task and shut down with it.
- **Checkpoints.** Every mutating tool snapshots the file first;
  `checkpoint_restore` undoes it. Created files are removed on restore.
- **Streaming.** With `--stream` the runtime emits NDJSON: `{"type":"event"}`
  lines as work happens and a final `{"type":"result"}` envelope. The Agent
  Panel consumes this with `SplitParser`, so progress appears live.
- **Providers.** OpenAI, Anthropic, OpenRouter, OpenCode Go, plus subscription
  auth (Claude Pro/Max OAuth, ChatGPT via the Codex backend). One neutral
  message format is adapted per provider, so the tool loop is identical
  everywhere.

## Computer use on KWin (Plasma/Wayland)

KWin is not wlroots, so the wlroots-shaped tools do not apply: `grim` cannot
capture (no `wlr-screencopy`) and there is no `zwlr_foreign_toplevel`
inventory. `runtime/lib/kwin.py` uses what KWin actually provides:

| Capability | Mechanism | Status |
|---|---|---|
| Window inventory | KWin scripting (`workspace.windowList()`) via `org.kde.kwin.Scripting`; results returned through `console.info` → user journal (KWin 6 removed `writeConfig`). Fallback: KRunner windows runner + `org.kde.KWin.getWindowInfo` | working |
| Active window | same scripting call (`w.active`) | working |
| Window control | scripting: activate, close, move/resize | working |
| Screenshots | `spectacle -b -n` (fullscreen / monitor / active window / window under cursor); regions are captured fullscreen and cropped, since spectacle's `--region` is interactive only; cursor mode auto-retries as active on failure (it hangs/fails in background use) | working |
| Keyboard + text | `ydotool` (uinput) preferred; `wtype` only on wlroots | **needs `uinput` loaded** |
| Pointer (click/move/drag) | closed-loop over uinput: KWin `cursorPos` read → relative `mousemove` steps → re-read and correct until within 4px; results report the measured landing position, never the blind request | **needs `uinput` loaded** |
| Cursor readout | `cursor_position` tool (same KWin read, no input grant needed) | working |
| Scroll | `ydotool mousemove --wheel` — a relative delta, not an absolute position, so it never needed calibration | **needs `uinput` loaded** |
| Clipboard | `wl-copy` / `wl-paste` — copy/paste as one reliable deposit instead of keystroke-by-keystroke `type_text` for long or special-character text | working |

Screenshots feed the model real pixels: `observe_screen` captures, downscales
and attaches the image, so the agent can describe what is on screen rather
than guessing from window titles.

### Keyboard prerequisite (same root cause)

`wtype` uses `zwp_virtual_keyboard_manager_v1`, which **KWin does not
implement** — on Plasma it always fails with "Compositor does not support the
virtual keyboard protocol". Keyboard and text injection therefore also go
through `ydotool`/uinput, so the same `uinput` fix below enables both.

The runtime probes the compositor once and picks the backend that actually
works (`input_backend()`), rather than assuming. Chords are parsed for the
model: `ctrl+t`, `ctrl-shift+t`, `alt+F4`, `super+d` and spellings like
`Enter`/`Esc`/`Page-Down` are normalised to the backend's own key names.

### Pointer prerequisite

`ydotool` needs the `uinput` kernel module and a running `ydotoold`. The
packaged user unit (`ydotool.service`, shipped by the ydotool package) is
enabled; it starts `ydotoold` with the default socket
`$XDG_RUNTIME_DIR/.ydotool_socket`, which the runtime resolves automatically
(`YDOTOOL_SOCKET` → `$XDG_RUNTIME_DIR` → legacy `/tmp`).

Access to `/dev/uinput` comes from the udev rule `80-uinput.rules` plus
`TAG+="uaccess"`, so the logged-in user gets an ACL and no root is needed to
*run* the daemon. The module itself must be loaded by root:

```sh
sudo modprobe uinput
echo uinput | sudo tee /etc/modules-load.d/uinput.conf   # persist across boots
systemctl --user restart ydotool
python3 runtime/argusd.py doctor | grep -A3 pointer
```

**If `modprobe` reports "Module uinput not found in directory
/lib/modules/<running-kernel>"**, the kernel was updated without rebooting and
the running kernel's modules are no longer on disk. Verify the new kernel has
it (`find /lib/modules/$(ls /lib/modules | tail -1) -name 'uinput*'`) and
reboot — the `modules-load.d` entry then loads it automatically.

`pointer_status()` reports the exact reason when mouse control is unavailable
(missing module, missing socket, missing binary) instead of failing silently —
the agent is told it cannot click rather than pretending a click happened.

**Found while chasing absolute-positioning accuracy: three real upstream bugs
in `ydotool` 1.0.4.** `Daemon/ydotoold.c`'s `--touch-on` argument handler has
`case 'A':` where it should be `case 'T':` — a plain typo that sends every
`--touch-on` invocation straight to `default: exit(2);` with no message
(confirmed via `gdb`+`coredumpctl`, not a crash — a deliberate silent exit).
Even patched, the daemon never calls `UI_ABS_SETUP` before `UI_DEV_CREATE`,
so the kernel creates `ABS_X`/`ABS_Y` with `minimum=maximum=0` (confirmed via
`EVIOCGABS`) — a degenerate range no compositor can scale from. And
`Client/tool_mousemove.c`'s `--absolute` flag never emits a real `EV_ABS`
event at all: it fakes absolute positioning by emitting a relative jump of
`INT32_MIN` (to slam the cursor into a corner) and then moving *relatively*
by the requested amount from there — which is exactly what pointer
acceleration curves distort on large jumps, matching ydotool's own "disable
mouse acceleration" warning. A source-level patch for all three is at
`/tmp/ydotool-build` (not installed as of this writing — the daemon fix
alone was verified to make `EV_ABS` events flow, but full pixel-accurate
click positioning needs one more layer: libinput doesn't appear to treat the
resulting device as a proper absolute pointer, most likely needing a
`resolution` value and/or a udev hwdb entry classifying it — not yet solved).
Until that's resolved, computer-use stays keyboard-first (see the system
prompt) and `mouse_click`/`mouse_move` remain best-effort.

**Practical lesson from the same investigation: don't leave the real
`ydotool.service` stopped while testing a replacement.** Freeing
`/dev/uinput` for a test daemon (only one process can hold it) means
stopping the production service, and forgetting to restart it afterward
silently breaks every keyboard/mouse tool call — with no error at the Argus
layer, since `pointer_status()`/`key_press` correctly reports "ydotoold not
running," but that's easy to miss/lose track of when the same task never
happens to call them. This was, in fact, the immediate cause the one time it
was diagnosed live: `ydotool.service` had been stopped for 50 minutes.

**`open_url(url)`** was added after diagnosing *why* browser navigation
specifically kept failing intermittently even with the keyboard-first
approach working: `launch_app` → `activate_window` → `key_press('ctrl+l')`
→ `type_text` → `key_press('Return')` as five separate tool calls means four
full model round-trips between them — seconds apart, not milliseconds — on
a desktop that, in this deployment, is routinely shared with other
concurrent agents also taking input focus. `open_url` does the whole
sequence in one handler call: it verifies focus is actually held (not just
requested) before typing and again before submitting, and fails closed with
a precise reason — "focus moved away right after ctrl+l," "focus moved away
while typing" — instead of typing or pressing Return into whatever now has
focus. The system prompt directs the model to prefer it over hand-chaining
the individual tools for exactly this reason.

**Known issue: absolute coordinates are uncalibrated.** `kwin.click()`
previously issued `ydotool mousemove --absolute X Y click 0xC0` as one
invocation; ydotool's CLI is one subcommand per process, so the trailing
`click` tokens overflowed `mousemove`'s arg parsing and aborted with `***
stack smashing detected ***` (confirmed via `coredumpctl` — four matching
crashes). Every `mouse_click` was silently failing while the model retried
different coordinates, assuming *those* were the problem. Fixed: `click()`
now issues `mousemove` and `click` as two separate calls.

That fix makes clicks stop crashing, but a second, deeper issue remains:
`mousemove --absolute` is not actually calibrated to the screen on this host.
Real absolute positioning needs `ydotoold --touch-on` (EV_ABS), but that flag
fails outright on the installed `ydotool` 1.0.4-2.1 package — exit status 2,
no diagnostic, reproducible however it's invoked (verified directly, not just
under systemd). Without it, `--absolute` falls back to an uncalibrated mode:
requesting (2000, 1100) on this 3840x2160 screen landed the cursor near
(20, 15), nowhere close.

Fixed in software with closed-loop placement (`kwin._place_pointer()`):
KWin scripting can read `workspace.cursorPos` (setting it is silently
ignored on Wayland — verified live), so move/click/drag no longer trust
`--absolute` at all. They read the true position, step with relative
`mousemove -x/-y` deltas that need no calibration, re-read, and correct —
full stride first, half strides after (gain 0.5 converges for any pointer
acceleration below 4x; gain 1 was verified to oscillate at 1.6x). Every
result carries the *measured* landing position (`x`/`y`), the residual off
the request, and a `verified` flag; a placement that doesn't converge
within 4px fails closed with the real position attached instead of
clicking blind. A new `cursor_position` tool exposes the same read to the
model. Verified live: an 80px move landed residual 2px after 2 corrections
and restored exactly. The system prompt still prefers keyboard (cheaper —
no correction rounds), but the mouse is trustworthy now, not a last resort.

**`wl-copy` hung for the full 10s timeout on every call despite succeeding
instantly.** `clipboard_set()`'s first implementation used
`subprocess.run(["wl-copy"], input=text, capture_output=True, ...)` —
standard for a one-shot command, but `wl-copy` forks into the background to
keep serving paste requests, and that forked process inherits whatever file
descriptors it was launched with. With `capture_output=True`, those are pipes
to the Python parent; the daemon never writes to or closes them, so Python's
read-until-EOF blocked for the full timeout even though a concurrent
`wl-paste` could read the copied text back immediately — confirmed live: the
copy round-tripped correctly while `clipboard_copy` still reported failure.
Fixed by sending stdout/stderr to `DEVNULL` instead of `PIPE` — nothing left
to wait on, and the *direct* child (before the fork) still exits with a real
return code for genuine failures.

**Further computer-use hardening, same pass as the tool-surface polish
below:** `clipboard_get()` now caps returned text at 20,000 characters (with
a `truncated` flag) — unlike every other tool's output, clipboard content
never went through a call the agent made with a bounded size in mind, so an
ordinary paste of a large document used to dump an unbounded blob straight
into the model's context. `scroll()`'s `amount` is clamped to ±50 steps per
call for the same reason `mouse_click`'s `clicks` was already clamped to 3 —
one call is one deliberate step, not a substitute for calling it repeatedly.
`launch_app`'s raw `sh -c` fallback (used when neither `gio` nor
`gtk-launch` is available) now checks a desktop entry's `Terminal=true` and
wraps the command in `konsole`/`alacritty`/`xterm`, or reports plainly that
no terminal emulator is installed — previously it silently ran a console
app with no terminal attached, which for a TUI-only tool means it launches
with no visible output at all rather than failing. `capabilities()` also
stopped calling `input_backend()` three separate times for one report.

## Unbounded disk growth: captures and checkpoints were never cleaned up

Two directories under `~/.local/share/argus/` grow forever with nothing to
cap them, and both were caught live rather than by inspection alone:

- **`captures/`.** `observe_screen` writes a new, uniquely-timestamped PNG
  on every call, and `argusd.image_payload()` adds a downscaled `-small.jpg`
  alongside each one — and the system prompt explicitly tells the model to
  call `observe_screen` after desktop actions to verify them, so a single
  computer-use-heavy task can produce dozens. Nothing ever deleted them.
  Confirmed live: this host's `captures/` directory had already accumulated
  41 files (21MB) from ordinary use with zero cleanup anywhere in the
  codebase. `observe_screen` now prunes to the newest `CAPTURES_KEEP=40`
  files (by mtime) before writing the new one — verified against a
  synthetic 60-file backlog (correctly pruned to 40, keeping the newest)
  and end-to-end through a real agent run.
- **`checkpoints/<session>/`.** Every mutating file write saves a full
  backup for `checkpoint_restore`, and nothing ever removed old session
  directories either. Confirmed live: 73 files (304KB) had accumulated
  across roughly 15 one-off session directories, several clearly from a
  single finished task that will never be resumed. `Checkpoints.__init__`
  now prunes whole session directories whose *newest* file is more than
  `MAX_AGE_DAYS=7` old — age-based, not count-based, specifically so a
  session still in active use (which by definition keeps producing new
  checkpoints) is never at risk of eviction no matter how long ago it
  started or how many old, unrelated sessions exist. Verified: a
  synthetic 10-day-old session was removed while a same-run fresh session
  was untouched, and the added `Checkpoints()` construction overhead is
  ~0.2ms at these file counts.

## Computer-use honesty pass: three more "silently pretends" gaps

Same principle as the pointer-calibration and clipboard fixes above — a
tool that can't do what was asked should say so, not quietly do something
else and report success:

- **`screenshot()`'s region crop.** If `region` was requested but ImageMagick
  (`magick`/`convert`) wasn't installed, or the crop subprocess itself
  failed, the old code silently returned the *full, uncropped* capture with
  `ok: true` — a caller reading pixels at the requested coordinates would
  get the wrong part of the screen with no signal anything was off.
  Verified live (monkeypatched to simulate no ImageMagick): the byte size
  alone gives it away — 1.97MB (full screen) vs. 9KB (an actual 100×100
  crop) — but nothing in the result said so. Now returns `region_applied:
  false` plus an explanatory note whenever the crop didn't actually happen,
  and `region_applied: true` when it did.
- **`observe_screen`'s `grim` fallback (wlroots compositors) ignored `mode`
  and `region` entirely** — always a bare `grim <path>`, a full-screen
  capture regardless of what was asked for, with no signal that the request
  wasn't honored. `region` is now passed through via grim's own `-g "<x>,<y>
  <w>x<h>"` geometry syntax (verified: `region=[10,20,300,400]` on this host
  now produces `grim -g "10,20 300x400" <path>`, confirmed by dry-running
  with subprocess mocked out, since this host is KWin/Plasma and grim can't
  actually capture here — no wlr-screencopy support, as already documented
  above). A non-fullscreen `mode` with no `region` — `active`/`monitor`/
  `cursor` — has no grim equivalent without an output name or foreign-
  toplevel id this fallback doesn't look up, so it captures fullscreen and
  attaches a `note` saying so, instead of silently substituting one thing
  for another.
- **`open_url` checked focus at every step but not command success.** Each
  focus-dependent step (`ctrl+t`, `ctrl+l`, typing the url, `Return`)
  re-verified the browser window was still focused before continuing, but
  never checked whether the `key_press`/`type_text` call that was supposed
  to *cause* that state actually succeeded. A transient ydotool failure
  (e.g. the daemon hiccups) with focus untouched would sail straight past
  the focus check, since focus genuinely hadn't moved — the keystroke just
  never reached the compositor — and the next step would fire anyway; for
  `ctrl+l` specifically, that means the url gets typed into whatever was
  already focused instead of the address bar. Verified live with a mocked
  `key_press` that fails on `ctrl+l` while focus stays put: previously this
  would have proceeded to type the url blind; now every step checks its own
  call's `ok` first and fails closed with the real reason, the same way a
  focus-loss was already handled.

## Building software: the rest of the coding tool surface

Beyond edit/verify, the tool registry now covers the rest of what building a
project actually needs:

- **`move_file` / `delete_file` / `make_dir`.** Filesystem tools stopped at
  content edits — restructuring a project (renaming a module, deleting
  scaffolding, moving a file into a new directory) had no first-class tool
  and fell back to `run_command`'s `mv`/`rm`, ungated by the checkpoint
  system. `move_file`/`delete_file` are checkpointed the same way
  `write_file`/`edit_file` are: `move_file` saves *two* ordinary single-file
  checkpoints (source and destination), which composes correctly with the
  existing restore semantics — restoring both undoes the move — without
  teaching `Checkpoints` a second, move-specific representation. Both are
  deliberately scoped to single files, not directories: the checkpoint
  mechanism backs up one file's content, not a subtree, so a directory
  delete/move can't be made reversible the same way; `run_command` (still
  approval-gated) covers that case. `make_dir` isn't checkpointed at all —
  restoring a "didn't exist" checkpoint means `unlink()`, which raises on a
  directory, so treating an empty directory like a file would make
  `checkpoint_restore` crash instead of undo.
- **`run_tests`.** `lint`/`format_file`/`syntax_check` already existed as a
  verification-stage tool per stage but running the test suite itself only
  ever went through generic `run_command`. `run_tests` rounds out that
  family using the same auto-detected `tooling()["commands"]["test"]` the
  rest of the runtime already computes. Path-scoping was harder than it
  looked: different runners scope to a path differently, and getting this
  wrong doesn't error, it silently does the wrong thing — confirmed live,
  appending a bare directory to `python3 -m unittest discover` doesn't fail,
  it just discovers zero tests and reports a plain, misleading failure. So
  `run_tests` scopes per runner shape instead of blindly appending a path:
  pytest gets a positional path (it supports that natively); `unittest
  discover` gets `-s <dir>` for a directory or is rewritten to `python3 -m
  unittest <dotted.module>` for a single file (discover has no single-file
  mode); cargo/npm — whose positionals mean a test-name filter or vary by
  project rather than a path — get a clear "scoping not supported" error
  instead of a silent mis-scope. Separately: `unittest discover` is known to
  miss tests under a subdirectory with no `__init__.py` even when correctly
  invoked (confirmed live — identical files run correctly from inside the
  test directory but are invisible to discovery from the project root; a
  real Python stdlib limitation, not a sandboxing artifact). `run_tests`
  detects that specific "Ran 0 tests" shape and attaches an explanatory
  `note` instead of leaving it looking like an empty or broken test suite.
- **Scaffolding commands stopped needing a prompt each.** `policy.py`'s
  `SAFE_BUILD` allowlist covers non-networked project-init commands (`git
  init`, `npm init -y`, `cargo init`/`new`, `uv init`, `python3 -m venv`,
  `go mod init`) the same way it already covered build/lint/format/test
  commands — starting a new project from scratch used to mean an approval
  prompt for every single bootstrap step before any real work could begin.
  `npm init` (without `-y`, which is interactive) was deliberately left out.
- **Closed a shell-grant bypass.** `syntax_check`/`lint`/`format_file` all
  execute real binaries inside the sandbox (`python3 -c`, `node`, linters,
  formatters) but never required the `shell` grant the way `run_command`
  does — with the default configuration (`shell` off), a user who believed
  "the agent can't execute shell commands" could still have it run
  arbitrary compiler/linter/formatter invocations through these three tools.
  All three (and the new `run_tests`) now declare `needs_grant="shell"`.
  This only gates the *model's* direct tool calls — the runtime's own
  automatic post-write verification (`argusd.verify()`, called after every
  successful `write_file`/`edit_file`/`multi_edit`) calls the same handlers
  directly rather than through the gated dispatch path, so syntax/lint
  feedback after an edit still works regardless of the shell grant.

## `shell` now defaults on, and the system prompt stopped double-verifying

Reported directly: tasks were quietly stalling partway through — not
crashing, not erroring, just stopping — and shell access needed to be on by
default. Both turned out to be the same root cause, compounded by a second
issue found while fixing it.

- **`shell` defaulted off** (`ARGUS_GRANT_SHELL`/`ProviderConfig.qml`'s
  `grantShell`), which — after the shell-grant-consistency fix directly
  above this section — meant every `syntax_check`/`lint`/`format_file`/
  `run_tests` call the model made came back "shell grant disabled" by
  default, with no path to actually verify or run anything it wrote. Now
  defaults on in both `argusd.grants()` and `ProviderConfig.qml` (neither
  persists it to `prefs.json`, so this is a clean default flip with no
  migration needed). `input` — desktop mouse/keyboard control — stays
  opt-in; a meaningfully more invasive default than running code.
- **The system prompt was telling the model to double-verify.**
  `write_file`/`edit_file`/`multi_edit` already run an automatic syntax
  check (and lint, if installed) after every change, via `argusd.verify()`
  calling the handler directly — the result lands right in that same tool
  call's own response. But the system prompt separately told the model to
  call `syntax_check` again itself after every change, and `syntax_check`'s
  internal implementation is a `python3 -c "..."` invocation, which
  `policy.py` deliberately treats as indistinguishable from arbitrary code
  execution and always routes through approval (see `policy.py`'s own
  comment on this). So a normal edit-and-verify loop was generating an
  approval prompt *for information the model already had* — and if nothing
  was watching to approve it, the task just sat there, which is exactly
  what "randomly stopped" looks like from the outside. Verified live,
  before/after: the same write-then-verify task went from `write_file` →
  `verify ok` → an unnecessary `syntax_check` approval prompt, to just
  `write_file` → `verify ok`, reaching the one genuinely new action
  (`run_tests`, which really does execute code and rightly still asks for
  approval) directly. The system prompt now tells the model to read the
  `verify` field already in write_file/edit_file/multi_edit's own result
  instead of re-checking a file it just touched, and reserves explicit
  syntax_check/lint calls for files it did *not* just edit this turn.
- **What's still expected to pause, by design:** anything that actually
  *executes* code — `run_command`, `run_tests`, and a first-time
  `syntax_check`/`lint`/`format_file` on a file the model didn't just
  write — still goes through approval, because none of those match the
  policy's narrow `$SAFE` allowlist. That's the intended trust boundary
  ("the human is root" — `ProviderConfig.qml`'s own words), not a bug; a
  task that needs one of those will still show a pending approval in the
  panel and wait for it.

## Bug/bottleneck sweep

- **The duplicate-call guard counted cumulatively over the whole task
  instead of consecutively.** Its purpose is to catch a model flailing —
  calling the exact same thing over and over with nothing changing — but
  the counter (`repeats[sig]`, keyed by tool+args) never reset, so a
  zero/fixed-argument tool called more than once anywhere in a longer task
  tripped it on the *second* use no matter how much unrelated, useful work
  happened in between. That's a real, common pattern: `observe_screen`/
  `active_window`/`list_windows` are exactly what the system prompt itself
  tells the model to call for before/after verification. Confirmed live: a
  task doing `list_windows` → `list_apps` → `list_windows` (an entirely
  ordinary before/after check) had the second `list_windows` blocked as
  "duplicate — redirected" purely because its signature matched the first
  call from steps earlier. Fixed by tracking only the single most recent
  signature, reset the moment a different call happens, rather than a
  cumulative per-signature count — re-verified live that the same
  before/after pattern now runs clean, while a genuinely back-to-back
  repeat (confirmed in the same test session, the model called
  `list_windows` twice in a row with nothing in between) is still caught
  exactly as before.
- **`Workspace.tooling()` recomputed Python test-runner availability on
  every call, unconditionally** — including from `argusd.verify()`, which
  runs after *every* `write_file`/`edit_file`/`multi_edit` and only ever
  reads the `lint` key, paying for a `test` probe (up to two subprocess
  spawns checking `pytest`/`unittest` importability) it never uses.
  Measured live: ~83ms per call. A task doing a dozen small Python edits
  was burning roughly a second of pure waste on a result that cannot
  change mid-process. Cached with `functools.lru_cache` on the underlying
  probe — measured after the fix: ~20ms average across repeated calls (the
  first pays the real cost, the rest are next to free).

## Reasoning/thinking effort selection

`ProviderConfig.qml` gained a global "REASONING EFFORT" control (Off/Low/
Medium/High, persisted to `prefs.json`, validated against a whitelist on
load) and `argusd.provider_call()` maps it to each provider's own shape:
Anthropic's `thinking: {type: "enabled", budget_tokens}` (with `max_tokens`
bumped accordingly — Anthropic requires it exceed `budget_tokens`), OpenAI's
`reasoning: {effort}` (Codex/subscription) or `reasoning_effort` (API key),
and OpenRouter/OpenCode's unified `reasoning: {effort}`. At "Off" — the
default — the request body is byte-for-byte identical to before this
existed, verified directly; all four provider shapes and the "invalid saved
value falls back to off rather than crashing" case were verified the same
way, plus one live end-to-end run. Known limitation, documented in code:
Anthropic thinking blocks stream live via `reasoning_delta` and are then
discarded — `context()` never journals them — so extended reasoning does
not carry across conversation turns the way final text/tool calls do; the
API tolerates this, it just means the model's reasoning is not visible to
itself in later turns.

## Code quality: the system prompt set a low bar, and two bugs undermined it

Reported directly: the agent completed tasks, but what it produced was
"simple and low quality." The prior `SYSTEM_PROMPT` had five thin,
mostly mechanical bullets under "work like a careful engineer" — which
tool to call when, not one line about matching existing conventions,
avoiding placeholders, handling edge cases, self-reviewing before calling
something done, or writing tests. Rewritten with concrete, specific
standards instead of vague "write good code" (which models tend to treat
as filler): match the surrounding code's own conventions before writing;
no placeholders/stubs/"left as an exercise", but also no speculative
abstraction for cases nothing asked for; default to no comments explaining
*what*, only the non-obvious *why*; reread the actual diff once as a
reviewer would before calling a change finished; write or extend a test
for anything with real logic, since a change that only passed
`syntax_check` has been shown to parse, not shown to work.

That last line exposed two real bugs while verifying it live:

- **The Python test-runner probe only ran when an existing `.py` file was
  found to detect the language from** — so a brand-new/empty workspace (a
  very ordinary starting point: "write a function that...") told the model
  "Available verification commands: none," with zero signal about whether
  `pytest` is actually installed. Confirmed live: in an empty workspace
  with pytest not installed, the model defaulted to the idiomatic
  `import pytest` / `@pytest.mark.parametrize` style, and those tests
  failed to even import once `run_tests` actually ran them —
  `ModuleNotFoundError: No module named 'pytest'`. Unlike node's
  `package.json` or Rust's `Cargo.toml`, Python needs no marker file to be
  a valid choice, so the probe-file gate doesn't apply to it the way it
  reasonably does for other languages. Fixed by reporting Python's actual
  test runner in `ws_info` unconditionally, not gated behind finding a
  `.py` file first — re-verified live: the same task, same empty
  workspace, now correctly writes `unittest.TestCase`-style tests instead,
  and they pass.
- **A command that ran and simply failed (non-zero exit, no "error" key —
  `run_tests`, `run_command`) surfaced through the approval path as a bare
  "Approved action failed closed: unknown"**, discarding the actual
  stderr/traceback that explained *why*. `result.get("error", "unknown")`
  only accounts for infra-level failures (timeout, missing binary); a
  completed-but-failed command's real diagnostic lives in stdout/stderr,
  which that line never looked at. Confirmed live: the exact
  `ModuleNotFoundError` above surfaced as just "unknown" until fixed.
  `_failure_detail()` now falls back to stderr, then stdout, before giving
  up and saying "unknown."

Re-verified the whole path end to end after both fixes: same task, same
empty starting workspace — the model wrote `duration.py`, wrote
`unittest`-style tests unprompted, caught and fixed its own syntax error
via the automatic post-write verify signal without being told to, and
`run_tests` (once approved) reported a genuine pass.

## Agent Panel: live streaming and rich tool-call rendering

The panel no longer waits for a whole model turn to finish before showing
anything. `provider_call()` in `argusd.py` calls every provider (Anthropic,
OpenAI, OpenRouter, OpenCode Go, and the Codex/ChatGPT Responses API backend)
with `stream: true` and parses each provider's SSE shape as it arrives,
emitting normalized NDJSON events over the same `--stream` channel the panel
already consumed: `delta` (prose tokens), `tool_call_start` /
`tool_call_delta` / `tool_call_ready` (a function call's name and arguments
as the model generates them), and the existing `event` (perceive/plan/act/
verify/commit) now carrying an `id` — matching a tool call — plus an optional
`detail` (stdout/stderr/diff/file content, ANSI-colored for errors) built by
`tool_detail()`. The tool-execution loop's own logic and its final
`{"choices":[{"message":{...}}]}` return shape are unchanged; streaming only
adds live narration of the same turn.

`AgentState.messages` is a real `ListModel`, not a plain JS array —
`ListModel.setProperty()` updates exactly the one row being streamed into,
where reassigning a `property var` array (the original design) would rebuild
every delegate in the whole chat history on every token. The `segments` role
is stored JSON-encoded: assigning a raw JS array-of-objects to a `ListModel`
role silently gets converted into a nested `QQmlListModel` on read-back
(no `.slice()`/`.push()`), which is easy to hit and non-obvious — storing it
as text and `JSON.parse`/`JSON.stringify` at the two access points sidesteps
it entirely. `AgentPanel.qml`'s chat delegate renders each message's
`segments` as an ordered mix of prose bubbles and tool-call cards (name,
streamed arguments, status glyph, and — when there's output worth showing —
a `TerminalCard`.

**`TerminalCard.qml` is not xterm.js.** The original design embedded real
xterm.js in a `WebEngineView` (QtWebEngine is installed on this host). It
looked right in isolation but reliably `qFatal()`-aborted the *entire shell*
the first time a card with output actually rendered — confirmed via the
crash reporter's stacktrace (`QQuickWebEngineView::QQuickWebEngineView` →
`QMessageLogger::fatal`). QtWebEngine requires `QtWebEngineQuick::initialize()`
before the application starts; a generic `quickshell -p` process never calls
it, and there's no hook to add it without patching Quickshell itself.
`TerminalCard.qml` instead renders the same ANSI SGR color codes (the
runtime only ever emits `\x1b[31m`/`\x1b[0m` for stderr/errors) as QML rich
text — monospace, dark, scrollable, no extra process, no crash risk. It is a
close visual match, not a real terminal emulator (no PTY, no true
column-exact layout on wrapped lines).

**Reasoning/thinking tokens.** Several of the wired-up providers stream
chain-of-thought ahead of the real answer, in three different shapes:
Anthropic extended thinking (`content_block_delta` with
`delta.type: "thinking_delta"`, field `thinking`), OpenRouter's unified
format and DeepSeek's own API (`delta.reasoning` /
`delta.reasoning_content` on an otherwise ordinary chat.completions chunk —
confirmed live against the configured `deepseek/deepseek-v4.1-flash`
model, which reasons on non-trivial prompts by default), and Codex/Responses
reasoning summaries (`response.reasoning_summary_text.delta`). All three
normalize to the same `{"type": "reasoning_delta", "text": ...}` NDJSON
event. It is never sent back to the model as conversation history — same
treatment as Claude's and ChatGPT's own UIs — so it's a display-only stream:
`AgentState.appendReasoning()` accumulates it into a `"reasoning"` segment,
rendered by `AgentPanel.qml`'s `reasoningComp` as a small "Thinking…" card
with a spinner. `AgentState._closeTrailingReasoning()` marks it done (glyph
stops spinning, card auto-collapses) the moment anything else starts on the
same turn — prose or a tool call — since no provider sends an explicit
"done thinking" event to key off of.

**Message formatting.** Chat bubbles used to render literal `**bold**` and
`- bullets` as-is — the model's markdown was never interpreted. `Markdown.js`
(`.pragma library`) is a scoped-not-spec-complete converter to
`Text.RichText`'s HTML4 subset: fenced code blocks, bold/italic, inline
code, bullet/numbered lists, links (opened via `Qt.openUrlExternally`), and
paragraph breaks. Headings, tables and blockquotes are out of scope — model
replies in practice don't lean on them. Applied to every prose segment
(`textBubbleComp`), including the user's own messages, since running it on
plain text with no markdown syntax is a no-op (nothing matches, so it falls
through to escaped-and-line-joined text, identical to the old rendering).

## Tool surface

| Group | Tools |
|---|---|
| Read | `read_file` (offset/limit) · `list_dir` · `glob` · `grep` (ripgrep) · `file_info` |
| Write | `write_file` · `edit_file` (exact-string, uniqueness-checked) · `multi_edit` |
| Exec | `run_command` (sandboxed) · `syntax_check` · `format_file` · `lint` |
| LSP | `lsp_diagnostics` · `lsp_symbols` |
| Undo | `checkpoint_list` · `checkpoint_restore` |
| Plan | `todo_write` |
| Apps | `list_apps` · `launch_app` (desktop-file aware, via `gio launch`) |
| Computer use | `observe_screen` (fullscreen/monitor/active/cursor + region) · `list_windows` · `active_window` · `activate_window` · `close_window` · `move_window` · `mouse_click` · `mouse_move` · `type_text` · `key_press` · `open_url` (atomic, verified browser navigation) |

## Review pass: approval history, command chaining, provider retries, context size

Six defects found by executing the runtime's own modules rather than reading
them, each now covered by `runtime/tests/` (no pytest needed — stdlib unittest,
since Python's test runner here is `unittest`):

```sh
python3 -m unittest discover -s runtime/tests        # 81 tests
python3 -m pytest runtime/tests -q                   # same suite, if installed
node shell/agent/tests/markdown.test.js              # panel markdown (11 tests)
```

(The suite is stdlib `unittest` on purpose: `unittest` is this host's detected
Python test runner, so it runs with no extra install. `-W ignore::ResourceWarning`
silences the runtime's unclosed per-call SQLite handles, which are harmless in a
process that exits.)

- **A turn that paused for approval left an invalid history behind.** Real
  evidence from this host's journal (session `smu5p5umb`): 14 tool calls
  declared, 13 results journalled — 5 declared calls with no result at all, and
  4 results keyed to `a-<timestamp>` approval ids that no declared call
  matched. `run()` journals the assistant message with *every* call of the turn,
  then returns as soon as one of them needs approval: the calls after it were
  dropped silently, and the approved call's result was journalled under the
  approval's own id instead of the model's `tool_call_id`. Both providers reject
  that turn (OpenAI: every `tool_call_id` must be answered; Anthropic: every
  `tool_use` needs a `tool_result`), so the resume — the panel's main path —
  came back as a provider error instead of continuing. Now: the approvals table
  carries `call_id` (migrated on connect, legacy rows fall back to the old id),
  the pause journals a `pending_approval` placeholder that `approve()` writes
  the real outcome over (one result per call id, in the declaring turn's own
  order — appending a second answer would be rejected just as a missing one is),
  and `abandon_calls()` answers every sibling that will not run, including on the
  stuck-task abort path, with the reason recorded rather than silence.
- **A newline bypassed the per-segment command validation.** `SAFE_SHELL`'s
  trailing `[^&|`$(){}]*$` matched newlines (a negated class does) and `$`
  matches at the end of the whole string, so `cat a.py\nrm -rf /tmp/x` satisfied
  the pattern in one piece and was auto-approved on the strength of its first
  line — while the `&&` spelling of the same chain correctly prompted. Newlines
  and CR are now separators and are excluded from the pattern, so a multi-line
  command is validated line by line like any other chain.
- **In-band provider errors were never retried.** `_call_stream` retried
  `HTTPError` and `URLError`, but the parsers raise for an `{"error": ...}` body
  delivered with HTTP 200 — which is exactly how OpenRouter and DeepSeek report
  an upstream rate limit — and `except RuntimeError: raise` sat above the retry
  branches, so that failure killed the task on the first attempt. The stream
  parsers now raise `ProviderError`, which is retried under the same
  "only while nothing has been streamed" rule as a 429; credential and
  configuration errors still fail immediately.
- **Tool results reached the model as invalid JSON.** `json.dumps(res)[:20000]`
  slices mid-string: a `read_file` on an 81KB file produced a result whose
  `json.loads` raises "Unterminated string", with the cut landing inside the file
  content. Truncation now happens at field level (`tool_result_text`), so the
  model gets parseable JSON that says what was clipped, and a result that cannot
  be shrunk is replaced by an explicit marker rather than a broken object.
- **Path-scoped tools were judged without a subject.** `classify()` took
  `path or ""`, and `""` resolves to the workspace root, so `$WORKSPACE/**`
  matched it: `move_file` (src/dst), `checkpoint_restore` (id) and anything else
  naming its arguments something other than `path` were auto-approved against a
  subject the policy never saw. The registry now declares its subject
  (`subject=` in `lib/tools.py`: argument names or a resolver), every subject is
  judged and the strictest verdict wins (a move has two), a path-scoped grant
  with no subject at all fails closed, `todo_write`/`checkpoint_list` moved to
  their own `internal` grant instead of pretending to be file reads, and
  `Checkpoints.restore()` re-checks the manifest's path against the workspace
  rather than trusting state it wrote earlier.
- **Compaction measured less than the request it bounds.** `compact()` summed
  only the events table while `context()` also injects the last three summaries
  on every turn, so the ceiling was `MAX_CONTEXT_CHARS` plus up to 3×20000 chars
  of summary text no trigger could see. Summaries are now counted, capped at
  `SUMMARY_CHARS`, and their lines keep each tool's outcome (`edit_file FAILED —
  syntax error`) instead of only its name, so a compacted session still
  remembers what worked. Only the newest capture is attached (was: the last two,
  re-uploaded on every step of a 24-step task).

Two smaller ones: a provider that resends the whole tool name in every stream
chunk no longer produces `read_fileread_file…`, and the stale "real xterm.js"
comment in `argusd.py` now matches what `TerminalCard.qml` actually is.

Not changed, and worth knowing: the step/time budget (`MAX_STEPS`,
`MAX_TASK_SECONDS`) is per `run()` call, and an approval resumes through a fresh
`run()`, so a task's total budget does not include the turns before it.

## Review pass 2: the desktop adapter, the LSP client, and the panel's markdown

Same method as above — run it and watch, don't read it and assume. Everything
here is covered by `runtime/tests/` (81 tests) and
`node shell/agent/tests/markdown.test.js` (11 tests).

- **`kwin` scripting results could come from a previous call.** `run_script()`
  put its per-call nonce in the temp *filename* and nowhere else, while the
  string it waited for in the journal was the caller's constant prefix
  (`ARGUS_WINDOWS_`, `ARGUS_ACTION_`) inside a rolling 25-second window. Any
  line an earlier call had logged in that window satisfied the match, so
  `list_windows` could return an older inventory and `activate_window` /
  `move_window` could return a previous call's `activated` / `notfound` without
  doing anything. Confirmed live on this host: a stale `ARGUS_WINDOWS_` line was
  still sitting in the 25s window when the check ran, i.e. the *next* call would
  have matched it. The marker is now unique per call (`prefix + timestamp-pid + <`)
  and the journal scan prefers the scope that actually contains it, instead of
  the first scope that happens to log anything — the latter also made a healthy
  compositor look like "scripting unavailable" and burned the full timeout.
- **`activate_window` reported success without checking.** The JS logs
  `activated` unconditionally after `target.activate()`, and the KRunner fallback
  returned `ok: True` off a *void* D-Bus call. Wayland activation is
  asynchronous and the caller's next action is injecting input, so a false
  success there is a keystroke or URL delivered to whatever was already focused —
  the exact hazard `lib/tools.py`'s focus guard exists to prevent. Activation is
  now confirmed by reading the compositor's active window back (bounded poll) and
  fails closed naming the window that *is* focused. Measured live: 0.30s when the
  activation sticks (the already-focused window), 2.1s and a precise error for a
  uuid that cannot take focus.
- **The LSP client reported an unanswered file as a clean one.** When
  `publishDiagnostics` never arrived, `diagnostics()` returned `ok: True` with
  `diagnostics: []` — identical in shape to "the server checked and found
  nothing" — while its own sibling `symbols()` returned `ok: False` for the same
  condition. Worse, server-initiated requests were being dropped: the reader
  thread only enqueued messages and `wait_for()` discards anything that does not
  match its predicate, so nothing ever replied to `workspace/configuration` or
  `client/registerCapability` — requests pyright and typescript-language-server
  send during startup and wait on before they will analyse anything. A timeout,
  a hung startup and a crashed server all collapsed into "clean". Now: the
  `initialize` response is checked (missing or `error` → `ok: False` with the
  reason), server requests are answered from the reader thread, a timeout is
  `ok: False` saying the file was not checked, a `documentSymbol` error is
  surfaced instead of becoming "no symbol response", and a killed server is
  reaped instead of left as a zombie child. Verified against a fake server that
  refuses to publish until its configuration request is answered (test would hang
  before) *and* end-to-end against the real pyright on this host, which still
  reports `"undefined_name" is not defined` at 5:12 and nothing for a clean file.
- **Every fenced code block in a model reply rendered as the word `undefined`.**
  `Markdown.js` pulled fenced blocks out under a space-delimited index
  placeholder (" 0 ") but substituted `\u0001…\u0001`, so the placeholders were
  never replaced; and because the *inline-code* substitution matched a bare digit
  surrounded by spaces (`/ (\d+) /`), the leftover placeholder — and any
  ordinary number in prose — was replaced by `codeSlots[i]`, i.e. `undefined`
  (with the surrounding spaces eaten: "there are 3 files" → "there
  are<font>undefined</font>files"). Confirmed by loading the file under node and
  printing `toRich()` output. There are now two distinct non-printable
  placeholder characters, no digit matching anywhere, and a test file so this
  cannot come back. The link rule also no longer builds `href` from an
  unescaped URL, and only `http`/`https`/`mailto` become clickable at all —
  `file://` and `javascript:` now render as plain text instead of being handed to
  `Qt.openUrlExternally` on click.
- **Two panel bugs found while reviewing the same path.** `ArgusBridge`'s
  `parseTest()` calls `codexText()`, which existed nowhere in the repo (a
  duplicate, shadowed `buildTest` was the intended function) — the
  `ReferenceError` was swallowed by `parseTest`'s own `catch`, so a working
  ChatGPT/Codex subscription was always reported as "Unparseable"; the function
  is named correctly now. And the runtime was launched as `sh -c "… python3 -u …"`
  with no `exec`, so Stop / panic / the stall watchdog SIGTERM'd the `sh` wrapper
  and left the python runtime (and any computer-use it was doing) alive behind a
  UI that said "stopped" — both launch sites now `exec`, and the approve path
  passes `ARGUS_GRANT_NET` like the run path does.

Deliberately not changed, in both cases because they are the author's documented
decisions rather than oversights:

- `screenshot()`'s region path still returns `ok: True, region_applied: false`
  with a note when ImageMagick is missing. That is what `docs/07` documents as
  the fix; a caller that only checks `ok` still maps crop coordinates onto a full
  frame, so returning `ok: False` for a requested-but-unapplied crop would be the
  stricter contract — worth doing, but it changes behaviour the docs promise.
- The panel's per-token work (a `ListModel` role rewritten with `JSON.stringify`
  on every delta, a `Repeater` over a JS array rebuilt from it, the raw-array
  `actions` model, and a feed that force-scrolls to the end on every `rev` bump)
  is a real performance/UX issue — quadratic CPU on long replies, delegates
  destroyed per token, and no way to read history while a task streams. Fixing it
  means restructuring `AgentPanel.qml`'s streaming path, not a patch, and it
  needs eyes on the actual UI.

## Setup

```sh
# sandbox + language tooling (root)
sudo pacman -S --needed bubblewrap ruff prettier shellcheck shfmt \
  rust-analyzer lua-language-server gopls

# LSP servers that need no root (already installed here)
npm install --prefix ~/.local/share/argus/lsp pyright typescript-language-server

python3 runtime/argusd.py doctor --workspace /path/to/project
```

`doctor` reports the sandbox, adapters, LSP servers, formatters, credentials,
workspace and the full tool list. It also reports `"encrypted": false` — the
journal is plaintext at rest and encryption is a roadmap item, not a claim.

## Incident logging: a task that stops has a reason, on disk

The SQLite journal (`event()` in argusd.py) is a conversation trail, not a
debugging aid: it gets compacted, it mixes normal turns with failures, and a
caught exception was previously reduced to `str(e)` with the traceback thrown
away the moment the `except` block returned. A task that hit the 600s budget
or the 24-step limit said only "Stopped after the Ns budget" — no sign of
which tool call actually burned the time, or whether it was one slow
`run_command` versus twenty ordinary steps.

`runtime/lib/errlog.py` adds a small, append-only, rotated (5MB × 3) JSON-line
log at `$XDG_DATA_HOME/argus/argus.log`, separate from the journal so it is
never compacted away. `run()` in argusd.py now writes to it at every point a
task can go wrong:

- **`tool_crashed`** — a tool handler raised something other than
  `PermissionError`/`FileNotFoundError` (those two are expected, model-facing
  mistakes and are logged as `tool_failed` instead, no traceback). Captured
  with `traceback.format_exc()` from *inside* the `except` block — calling it
  after the `try/except` exits returns `"NoneType: None"`, since
  `sys.exc_info()` is already cleared by then. (Caught live by the test for
  this: the first version of this logging called it one line too late.)
- **`tool_failed`** — a handler returned `{"ok": false, ...}` normally
  (sandbox timeout, bad path, a policy the model keeps tripping). No
  traceback needed; the point is a *pattern* of these becomes visible as
  repeated log lines instead of one journal entry each, alone.
- **`provider_call_failed`** / **`uncaught_run_exception`** — a provider
  request or anything else in the loop raised, with its traceback.
- **`task_stuck_repeat`**, **`task_budget_exceeded`**,
  **`task_step_limit_exceeded`** — every stop-the-task path now logs a
  diagnostic breakdown alongside the user-facing message: elapsed time, time
  spent in provider calls vs. tools, and a per-tool `{count, seconds}` table
  built up over the run. This is the direct answer to "why did it stop" —
  the breakdown was previously nowhere, not even in the journal.
- **`slow_tool_call`** — any single tool call over `SLOW_TOOL_SECONDS` (15s),
  logged the moment it returns rather than only inferable after the fact from
  a budget breakdown.

`argusd.py errors [-n N]` tails the log (defaults to the last 20 records);
`doctor` now also reports the log file's path and its last 10
warning/error records, so a stuck task is diagnosable from the same command
that already reports sandbox/kwin/provider health.

## Explicit limitations

- **Loop convergence.** The runtime stops early when the same tool is called
  three times with identical arguments, and every exit path journals the
  assistant's final words — a truncated journal previously made the panel look
  like it had silently died.
- **The shell now uses a persistent socket daemon.** `argusd.py serve` owns a
  mode-`0600` Unix socket at `$XDG_RUNTIME_DIR/argus/argusd.sock`; each QML
  request gets its own streamed NDJSON connection and cancellable process group.
  The service accepts concurrent sessions, while duplicate live request IDs are
  refused. If the socket is unavailable, the shell retries once and then uses
  the previous direct CLI path so the panel remains usable during service
  upgrades or failures.
- **No MCP, no subagents.** External tool servers and isolated-context
  delegation are the next capability step.
- **No sandbox for the LSP servers themselves.** They are trusted, installed
  binaries run against the workspace; the sandbox covers agent-executed
  commands.
- **Budgets now survive approval resumes.** A task's start time and consumed
  steps are stored in `session_state`, so repeatedly pausing for approval cannot
  reset either limit. Defaults are 64 model steps, 30 minutes, 160,000 context
  characters and 120 retained events; deployments can tune them with
  `ARGUS_MAX_STEPS`, `ARGUS_MAX_TASK_SECONDS`, `ARGUS_MAX_CONTEXT_CHARS`,
  `ARGUS_MAX_CONTEXT_EVENTS`, `ARGUS_KEEP_EVENTS`, and `ARGUS_SUMMARY_CHARS`.
  The active values are included in `argusd.py doctor` output.
- **`rust-analyzer`, `lua-language-server`, `gopls`, `ruff`, `prettier`,
  `shellcheck`, `shfmt` are not installed here** — the pacman line above fixes
  that. Until then the runtime reports them missing rather than silently
  degrading.
