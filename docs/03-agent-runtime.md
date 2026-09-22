# 03 — Agent Runtime (`argusd`)

The daemon that makes "computer use" an OS service. Cloud-first cognition,
optional local models, hard permission boundaries.

## The loop

```
┌─────────┐    ┌────────┐    ┌────────┐    ┌────────┐
│ PERCEIVE │───▶│  PLAN  │───▶│  ACT   │───▶│ VERIFY │──┐
└─────────┘    └────────┘    └────────┘    └────────┘  │
     ▲                                                 │
     └─────────────────────────────────────────────────┘
```

1. **Perceive** — build a `ScreenState`:
   - Frame capture via `org.freedesktop.portal.ScreenCast` (PipeWire
     stream; KWin-native `zkde_screencast` as fast path).
   - **AT-SPI2 accessibility tree** — structured UI: role, name, bounds,
     states of every widget. Cheaper and more reliable than pixels alone;
     the tree is the agent's DOM.
   - Window inventory via `zwlr-foreign-toplevel-management`.
   - Diffing: only send the model what changed (tree deltas, cropped
     regions around focus).

2. **Plan** — provider call with the task + ScreenState + tool list.
   Returns one of: `action`, `ask_human`, `done`, `blocked`.

3. **Act** — dispatch to the action layer (below).

4. **Verify** — re-perceive; compare expected vs actual. Failed actions
   retry once, then escalate to `ask_human`.

## Action layer (Wayland-safe)

| Capability | Mechanism | Notes |
|---|---|---|
| Mouse move/click/scroll | `ydotool` → uinput | compositor-agnostic, needs `ydotoold` |
| Key/text input | `ydotool` / `wtype` | wtype for pure text (virtual-keyboard) |
| Widget invoke | AT-SPI `Action` interface | press a real button by role — no guessing coords |
| Window ops | KWin D-Bus + `kdotool` | activate, move, resize, virtual-desktop |
| Clipboard | `wl-clipboard` / portal | read+write with grant |
| Files/shell | sandboxed exec | scoped to grant envelope |
| Apps | `gtk4-launch`/`kioclient`/`systemd-run` | launch by desktop file id |

## Cognition — providers

```toml
# ~/.config/argus/providers.toml (planned)
[default]
provider = "anthropic"
model = "claude-sonnet-..."
api_key_env = "ANTHROPIC_API_KEY"

[gateway]                     # optional, user-configured
provider = "openai-compatible"
base_url = "https://opencode.ai/zen/go/v1"
model = "kimi-k2.6"
```

- Four providers behind one trait/interface: OpenAI, Anthropic, OpenRouter,
  OpenCode Go (gateway). Keys live in the `keys.env` vault, never in configs.
- Per-step routing is a later optimization (cheap model for "did the
  dialog open?", frontier model for planning).

## Permission model — the human is root

Capability grants, checked per action class:

| Grant | Covers | Default |
|---|---|---|
| `screen.read` | capture frames, read AT-SPI | on (required to function) |
| `input.inject` | uinput mouse/keys | **off** until user flips the switch |
| `clipboard` | read/write | prompt first time |
| `fs.<scope>` | file access outside home | prompt |
| `net` | outbound from agent tools | on |
| `shell.exec` | spawn processes | prompt for unlisted binaries |

Risk tiers on individual actions:
- **read** (observe) — silent
- **soft** (click, type, navigate) — allowed while `input.inject` granted;
  logged
- **commit** (send message, purchase, delete, irreversible) — always
  surfaces an approval in the Agent Panel unless the user pre-authorized
  the pattern

**Panic key** (global shortcut, e.g. `Ctrl+Alt+Backspace`-adjacent):
revokes `input.inject` for all agents, kills in-flight actions, EdgeGlow
snaps off. Implement as an argusd D-Bus method bound in KWin.

## Modes

- **Watched** — agent narrates and proposes each action; user approves in
  the panel. Trust-building default.
- **Autonomous** — runs inside the grant envelope; commits still prompt.
- **Teaching** (Warmwind-style, later) — record human demo (input events +
  narration), distill to a repeatable workflow recipe.

## Observability

Every loop emits an event: `{ts, agent, kind, summary, screenshot_ref?}` →
the feed in Agent Panel + `~/.local/share/argus/journal.jsonl`. Sessions
are replayable; screenshots are reference-counted and pruned.

## Shell contract (what QML needs from argusd)

Implemented today as per-task process invocation, not a socket: the QML
bridge (`shell/common/ArgusBridge.qml`) spawns `argusd.py run --stream`
(one process per task) and reads NDJSON from stdout:

```
state:    AgentState.status: idle|watching|working|blocked (QML-side)
          agentActive (bool) drives EdgeGlow
events:   NDJSON on stdout — {"type":"event"|"delta"|"reasoning_delta"|
          "tool_call_start"|"tool_call_delta"|"tool_call_ready"|"todos"|
          "metrics"|"usage", ...} and one final {"type":"result",...}
approval: {"id", "action_summary", "risk"} inside result → resolved by
          re-spawning `argusd.py approve <id> --allow|--deny`
cmd:      task.new(text) = spawn run --stream; grants via ARGUS_GRANT_*
          env vars; panic() = QML-side revoke + process kill
```

The planned D-Bus socket + resident `QmlBridge` daemon remains future
work (see `runtime/argusd.service`, currently used for `doctor` runs).
