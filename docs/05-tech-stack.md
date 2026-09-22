# 05 — Tech Stack

Target base: **CachyOS / Arch**, rolling. Versions observed on the dev
machine (2026-09): Plasma **6.7.5**, Qt **6.11.2**, Quickshell **0.3.1**.

## Shell layer

| Package | Why |
|---|---|
| `quickshell` | the shell toolkit — bar, panel, overlays in QML |
| `inter-font` | UI typeface |
| `ttf-jetbrains-mono` | data/log typeface |
| `qt6-*` (via Plasma) | QML engine, `QtQuick.Effects` for shadows/blur |
| `qdbus6` / `qt6-tools` | KWin virtual-desktop + window APIs |

## Session layer

| Package | Why |
|---|---|
| `plasma-desktop` + `plasma-workspace` (6.7+) | KWin Wayland compositor, settings, app platform |
| `sddm` | display manager |
| `pipewire` + `wireplumber` | audio + **screen capture** (portal streams) |
| `xdg-desktop-portal-kde` | ScreenCast portal for agent perception |
| `xdg-utils`, `kdotool` | app launch, window ops |

## Agent runtime

| Package | Why |
|---|---|
| `ydotool` (+ `ydotoold` service) | uinput virtual mouse/keys — Wayland-safe |
| `wtype` | virtual-keyboard text input (fast path) |
| `at-spi2-core` | accessibility tree = structured perception |
| `wl-clipboard` | clipboard access under grant |
| Rust toolchain (`cargo`) | argusd implementation language |
| `curl` | LLM transport for the Phase 1 `ArgusBridge` (keys via `keys.env`) |

## OS packaging (Phase 3)

| Package | Why |
|---|---|
| `archiso` | bootable ISO profile |
| `plymouth` | branded boot splash |
| `cage` / `kwin_wayland --nested` | isolated per-agent sessions (Phase 4) |

## Install set for the current scaffold

```sh
sudo pacman -S --needed quickshell inter-font ttf-jetbrains-mono qdbus6
```

## Shell internals

| Piece | Notes |
|---|---|
| `QtQuick.Effects` (`MultiEffect`) | shadows, blur, colorization, masking — shipped with Qt 6.11 |
| `QtQuick.Shapes` | vector work |
| `Quickshell.Widgets.IconImage` | icon rendering |
| `Quickshell.Io.Process` / `SplitParser` | streaming shell pipelines |
| `Quickshell.Services.Mpris` | now-playing |
| `Quickshell.Services.Notifications` | notification server |
| `scripts/argus-sysmon.sh` | streams CPU/RAM/GPU/net/disk once per second |
| `scripts/argus-appscan.sh` | enumerates `.desktop` apps + resolves icon paths |

## LLM providers

Exactly four: **OpenAI** (`https://api.openai.com` → `/v1/chat/completions`,
Bearer), **Anthropic** (`https://api.anthropic.com` → `/v1/messages`,
`x-api-key`), **OpenRouter** (`https://openrouter.ai/api` → `/v1/chat/completions`,
Bearer + attribution headers), **OpenCode Go** (`https://opencode.ai/zen/go` →
`/v1/chat/completions`, Bearer, subscription gateway).

Two request shapes are implemented in `ArgusBridge`: `openai` (chat
completions) and `anthropic` (Messages API) — plus two subscription paths:
Claude Pro/Max OAuth bearer (`oauth-2025-04-20` + Claude Code identity
prelude) and ChatGPT Plus/Pro via the Codex Responses backend. Keys and
subscription tokens live in `~/.config/argus/keys.env` (mode `600`, managed
from the Agent Panel → gear, with masked preview + one-click `GET /v1/models`
connection test); a matching environment variable also works, saved keys win.
Secrets are sourced into the `curl` subshell — never interpolated into command
lines. The model picker is a live browser over each provider's real catalog
(curated fallback when the catalog is unreachable); UI prefs persist to
`prefs.json`.

## Runtime services (Phase 2+)

```sh
sudo pacman -S --needed ydotool wtype wl-clipboard
systemctl --user enable --now ydotoold
```

## Deliberate exclusions

- **No Hyprland** — KWin is the compositor (user requirement: Plasma).
  Quickshell's Hyprland-specific QML module stays unused; everything is
  generic-Wayland so the shell still ports if that ever changes.
- **No X11 path** — Wayland only; XWayland exists solely for legacy apps.
- **No Electron/chrome shell** — the face of the OS is QML, not a webview.
