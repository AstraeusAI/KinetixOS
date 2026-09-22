# 01 — Architecture

## Layer cake

```
┌─────────────────────────────────────────────────────────────┐
│  ARGUS SHELL (Quickshell / QML)                             │
│  Bar · Agent Panel · EdgeGlow · OSD · lock-in UI            │
│  "the face" — renders agent state, takes human commands      │
├─────────────────────────────────────────────────────────────┤
│  IPC — Unix socket JSON-RPC  (org.argus)                    │
│  shell ⇄ argusd : state stream, commands, approvals         │
├─────────────────────────────────────────────────────────────┤
│  ARGUSD — agent runtime daemon (Rust or Go)                 │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌───────────┐ │
│  │ Perception │ │ Cognition  │ │  Action    │ │  Policy   │ │
│  │ screencast │ │ providers  │ │ uinput     │ │ grants,   │ │
│  │ AT-SPI     │ │ cloud+local│ │ AT-SPI act │ │ audit log │ │
│  │ win list   │ │ planner    │ │ kdotool    │ │ panic key │ │
│  └────────────┘ └────────────┘ └────────────┘ └───────────┘ │
├─────────────────────────────────────────────────────────────┤
│  SESSION — Plasma 6.7 / KWin (Wayland) · SDDM · PipeWire    │
│  portals (screencast) · AT-SPI2 · ydotoold (uinput)         │
├─────────────────────────────────────────────────────────────┤
│  BASE — Arch / CachyOS kernel · systemd · pacman            │
└─────────────────────────────────────────────────────────────┘
```

## Why Quickshell on Plasma/KWin

- KWin implements `zwlr-layer-shell-v1` → Quickshell `PanelWindow`
  surfaces (bar, panels, overlays) work natively.
- `ext-session-lock-v1` is supported by KWin → Quickshell can also draw the
  lock screen later.
- Plasma stays for what it's good at: window management, settings, app
  ecosystem. Quickshell owns the agentic chrome.

### Known gaps on KWin (vs. Hyprland/niri)

| Feature | Status on KWin |
|---|---|
| Layer surfaces (bar/panels/overlays) | ✅ works |
| Session lock (`ext-session-lock`) | ✅ works (Plasma 6) |
| Foreign toplevel (active window title) | ✅ `zwlr-foreign-toplevel-management` |
| Virtual desktops | ⚠ no standard protocol → use KWin D-Bus (`org.kde.KWin /VirtualDesktops`) |
| Screen capture | ⚠ no `wlr-screencopy` → use `org.freedesktop.portal.ScreenCast` (PipeWire) or `zkde_screencast_unstable_v1` |
| Blur-behind | ⚠ not automatic → KWin Blur effect applies to translucent windows; tune opacity so panels look good either way |
| Virtual input | via `ydotool` (uinput) — compositor-agnostic ✅ |

## argusd — the brain

A user-session systemd service. Owns the agent loop:

```
perceive → plan → act → verify → repeat
```

- **Perception**: periodic PipeWire screen frames (on change/on demand),
  AT-SPI tree snapshots, window inventory via foreign-toplevel.
- **Cognition**: provider abstraction → OpenAI / Anthropic / OpenRouter /
  OpenCode Go, keys from the `keys.env` vault. Planner decides next action
  or asks for approval.
- **Action**: uinput (`ydotool`) for mouse/keys, AT-SPI for direct widget
  invocation, KWin D-Bus for window ops, shell for processes.
- **Policy**: capability grants (screen-read, input-inject, net, fs),
  per-action risk tiers, human-in-the-loop approvals streamed to the shell.

## Shell ↔ daemon IPC

- Transport: Unix domain socket `$XDG_RUNTIME_DIR/argusd.sock`,
  newline-delimited JSON-RPC.
- Channels: `state` (agent status, current task, glow on/off), `events`
  (action log for the timeline), `approvals` (shell must render +
  resolve), `commands` (send task, toggle computer-use, panic).
- The scaffold fakes this with the `AgentState` singleton; Phase 2 swaps in
  a real `Process`/`Socket` binding.

## Isolation model (later phases)

- **v1**: agents share the user session (simplest, matches "watch it work").
- **v2**: per-agent sandboxed nested sessions — `cage`/`kwin_wayland
  --nested` per worker, streamed into a shell viewport tile. This is the
  Warmwind-style "parallel workers" story, local edition.
- **v3**: disposable containers/VMs for untrusted tasks.

## Boot flow (future ISO)

`archiso` profile → SDDM → Plasma session → autostart `quickshell -p
/usr/share/argus/shell` + `systemctl --user start argusd` → first-run
wizard (provider keys, permission defaults, panic key).
