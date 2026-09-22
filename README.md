# Argus OS

An agent-native operating system concept: a Linux desktop designed from the
ground up for AI agents with **full computer-use ability** — and a shell built
to make watching agents work feel premium.

> **Argus** — the all-seeing. The OS is the body, the shell is the face,
> the agent is the resident.

Inspired by [Warmwind OS](https://about.warmwind.com) (cloud-streamed AI
workers that click and type like a human), but reimagined as a **local,
beautiful, user-facing desktop** you actually sit in front of — not a browser
window into a remote VM.

## What this repo is right now

Phase 1 — a Quickshell shell plus a durable desktop-agent runtime. `runtime/`
owns the agent journal, context compaction, provider tool loop, approvals, and
the first Wayland execution adapters; `shell/` remains its control surface.

## Quickstart (CachyOS / Arch, Plasma 6 + Wayland)

```sh
sudo pacman -S quickshell inter-font ttf-jetbrains-mono
~/Desktop/argus-os/run.sh
```

For real desktop input and capture (the runtime fails closed until these are
available):

```sh
sudo pacman -S --needed ydotool wtype grim wl-clipboard at-spi2-core
systemctl --user enable --now ydotoold
python3 ~/Desktop/argus-os/runtime/argusd.py doctor
mkdir -p ~/.config/systemd/user
ln -sf ~/Desktop/argus-os/runtime/argusd.service ~/.config/systemd/user/argusd.service
systemctl --user daemon-reload
systemctl --user enable --now argusd.service
```

The shell talks to the persistent runtime over `$XDG_RUNTIME_DIR/argus/argusd.sock`
and falls back to direct execution if the service is unavailable.

See [`docs/07-agent-runtime-foundation.md`](docs/07-agent-runtime-foundation.md)
for the memory, compaction, execution, and safety contract. Long-task limits can
be tuned with `ARGUS_MAX_STEPS`, `ARGUS_MAX_TASK_SECONDS`,
`ARGUS_MAX_CONTEXT_CHARS`, and `ARGUS_MAX_CONTEXT_EVENTS`; `argusd.py doctor`
reports the active values.

### API keys (OpenAI · Anthropic · OpenRouter · OpenCode Go)

Open the Agent Panel → gear icon → pick a provider, paste the key, hit
**Save**, then **Test**. Keys are stored in `~/.config/argus/keys.env`
(mode `600`) and exported into requests — they never appear in logs or
process lists. A matching environment variable also works (saved keys win):

```sh
export OPENAI_API_KEY=...      # https://platform.openai.com/api-keys
export ANTHROPIC_API_KEY=...   # https://console.anthropic.com/
export OPENROUTER_API_KEY=...  # https://openrouter.ai/keys (100s of models, one key)
export OPENCODE_API_KEY=...    # https://opencode.ai/auth (Go gateway subscription)
```

### Subscription login (no API key)

OpenAI and Anthropic cards offer a **Subscription** mode alongside API keys:

- **Claude Pro/Max** — run `claude setup-token` in a terminal, switch the
  Anthropic card to Subscription, paste the token, hit **Test**. Calls reuse
  the Claude Code scope (`oauth-2025-04-20` bearer); API keys remain the more
  stable path.
- **ChatGPT Plus/Pro** — run `codex login` (Codex CLI), switch the OpenAI
  card to Subscription, hit **Import Codex login** (reads `~/.codex/auth.json`)
  or paste a token manually, then **Test**. Requests ride the Codex backend,
  billed to your plan, not API credits.

The model picker is a **live browser**: it fetches the provider's real
`/v1/models` catalog (refresh on select/save/test, or the ↻ button), with
search and a curated fallback. UI prefs (provider, model, auth modes) persist
to `~/.config/argus/prefs.json`.

Hot-reload is built in — edit any `.qml` file and the shell updates live.

What you get:

- **Argus Bar** — floating pill bar at 2× elevation: mark, workspaces, launcher
  / palette / widget buttons, active window, clock, **live resource monitor**
  (CPU/RAM/GPU sparklines + network), now-playing (MPRIS), tray, audio/battery,
  agent pill.
- **App Launcher** — full-screen glass launcher (`▦` in the bar): 60+ apps with
  real icons, search, category filters, favourites (right-click to pin),
  full keyboard navigation.
- **Agent Panel** — right-edge command surface with two tabs:
  - **Chat** — talk to a real LLM across 4 providers, computer-use toggle,
    capability chips, retry/clear, stop-while-working, typing indicator,
    approval banner for commit-tier actions.
  - **Actions** — live perceive → plan → act → verify log.
  - **Settings sheet** — provider cards with live key/link status, per-provider
    API key vault (show/hide, save/clear, masked preview) **or** subscription
    linking (Claude Pro/Max token, Codex login import), one-click connection
    test, **live model browser** (real provider catalogs + search), capability
    grants.
- **Desktop Widgets** (Vista-Aero style) — glass gadgets that float **over
  applications**: clock, system monitor, notes, command output, agent, image,
  weather. Add from the `◫` catalog, drag to move, resize from the corner,
  configure via the gear. Persisted to `~/.config/argus/widgets.json`.
- **Command Palette** — `⌘` in the bar: apps + agent commands (new task,
  toggle computer-use, add widget, edit mode, panic).
- **EdgeGlow** — screen edges breathe while an agent holds input control.
- **Notifications** — glass toast stack; **OSD** — volume popups.

## Controls

| Where | Action |
|---|---|
| Bar `▦` | app launcher |
| Bar `⌘` | command palette |
| Bar `◫` | widget catalog |
| Bar `AGENT` | agent panel |
| Widget header | drag to move |
| Widget corner | drag to resize |
| Widget gear | configure |
| Widget right-click (launcher) | pin/unpin favourite |

## Repo map

```
argus-os/
├── docs/
│   ├── 00-vision.md          # what Argus is, pillars, vs. Warmwind
│   ├── 01-architecture.md    # system layers, shell ↔ argusd IPC, isolation
│   ├── 02-design-system.md   # tokens, glass recipe, motion, signature elements
│   ├── 03-agent-runtime.md   # computer-use pipeline, safety, providers
│   ├── 04-roadmap.md         # phased build plan
│   ├── 05-tech-stack.md      # exact packages & versions
│   └── 06-widget-layer.md    # desktop widget system
├── runtime/                  # the agent runtime (argusd)
│   ├── argusd.py             # loop, providers, journal, CLI
│   ├── lib/                  # sandbox · workspace · policy · tools · lsp · checkpoints
│   └── tests/                # unittest suite (no pytest required)
│       ├── test_policy.py    # command chaining, hard denies, subject scoping
│       ├── test_workspace_and_checkpoints.py
│       ├── test_context.py   # tool-result shape, compaction, what the model sees
│       ├── test_approvals.py # the approval round trip end to end
│       ├── test_providers.py # SSE parsing, tool-call assembly, retry policy
│       ├── test_lsp.py       # the LSP client against a fake language server
│       ├── fake_lsp_server.py
│       └── test_sandbox.py   # real bwrap runs (skipped without bwrap)
├── scripts/
│   ├── argus-sysmon.sh       # streams CPU/RAM/GPU/net/disk (1 Hz)
│   └── argus-appscan.sh      # enumerates apps + resolves icon paths
└── shell/                    # Quickshell config (point `quickshell -p` here)
    ├── shell.qml             # entry point
    ├── common/               # Theme, AgentState, ArgusBridge (LLM calls),
    │                         # ProviderConfig, AppIndex, SysInfo, WidgetStore,
    │                         # OsdState, Notif singletons
    ├── components/           # GlassPanel, ArgusMark, StatusOrb, PillButton,
    │                         # IconButton, Toggle, Sparkline
    ├── bar/                  # top bar + widgets (SysMonitor, NowPlaying, …)
    ├── agent/                # AgentPanel (chat + actions + settings)
    │                         # + tests/markdown.test.js (node, no Qt needed)
    ├── widgets/              # widget layer: window, frame, host, content/*
    └── overlay/              # EdgeGlow, Osd, SysPopup, AppLauncher,
                              # CommandPalette, Notifications, WidgetCatalog,
                              # WidgetLayer
```

## Design pillars

1. **Agent-first, human-always-welcome** — every surface works for both.
2. **Legibility of agency** — you can always tell when the agent is watching,
   working, or idle (EdgeGlow, StatusOrb, activity feed).
3. **Restraint = premium** — near-black glass, one accent, generous space,
   springy motion. No clutter, no neon soup.
4. **Local by default** — your machine, your data; cloud models for brains,
   optional local models for privacy.

See `docs/00-vision.md` for the full story.
