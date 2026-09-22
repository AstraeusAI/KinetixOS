# 04 — Roadmap

Phases are scope-ordered, not time-estimated. Each ends in something
demonstrable.

## Phase 0 — Design playground ✅ (this repo)

- Quickshell scaffold: floating bar, Agent Panel, EdgeGlow.
- Design tokens v1 (`common/Theme.qml`).
- Iterate on look & feel until it feels inevitable.

**Exit:** the shell feels premium enough to build an OS around.

## Phase 1 — Shell hardening

- Real data plumbing: workspaces via KWin D-Bus, tray menus
  (`QsMenuAnchor`), notifications (`NotificationServer`), OSD
  (volume/brightness).
- Lock screen via `ext-session-lock`.
- Polished empty/loading/error states; font fallbacks.
- Config file for user tokens (`~/.config/argus/shell.toml` → QML
  settings bridge).

**Exit:** usable as a daily-driver shell on stock Plasma.

## Phase 2 — argusd MVP

- Daemon skeleton (Rust, tokio) + Unix-socket JSON-RPC + `QmlBridge`.
- Perception: PipeWire frame grab via ScreenCast portal; AT-SPI tree dump.
- Action: ydotool input injection; AT-SPI invoke.
- One cloud provider end-to-end: "open X, read Y, report Z" with watched
  mode approvals rendered in the panel.
- EdgeGlow driven by real input-control state.
- Panic key via KWin global shortcut → `org.argus.panic`.

**Exit:** give the agent a task in the panel and watch it do it on your
desktop, with EdgeGlow on and every step in the feed.

## Phase 3 — OS packaging

- `archiso` profile: package list, autostart units, SDDM theme,
  first-run wizard (provider keys, grant defaults, panic keybind).
- `argus-settings` panel (Plasma KCM or Quickshell surface).
- Branding pass: Plymouth, wallpapers, iconography (the Argus eye).

**Exit:** a bootable ISO that lands you in Argus.

## Phase 4 — Multi-agent isolation

- Nested compositor per worker (`kwin_wayland --nested` or `cage`),
  streamed to shell viewport tiles.
- Per-agent grants, journals, lifecycle (pause/resume/kill).
- Task queue + scheduler; run-while-screen-locked.

**Exit:** two agents working in parallel, each in its own tile.

## Phase 5 — Polish & ecosystem

- Teaching mode (record → distill → replay workflow).
- Local-model provider path + per-step model routing.
- Community shell themes; plugin API for argusd tools.
- Performance: frame-diff compression, AT-SPI delta caching.

## Parking lot

- Cross-device (watch agents from phone).
- Encrypted agent journals; enterprise audit export.
- Wayland protocol needs upstreamed (generic virtual-desktop protocol).
