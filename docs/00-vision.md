# 00 — Vision

## One-liner

**Argus OS is a desktop Linux where AI agents are first-class citizens** —
they can see the screen, move the mouse, type, open apps, and do real work,
while the human watches a shell designed to make that visible and beautiful.

## The reference: Warmwind OS

Warmwind (Jena, Germany — public launch Aug 2026) proved the category:

- Custom Linux image on the server, Wayland + VNC streamed to a browser.
- AI "workers" operate ordinary software with a virtual mouse/keyboard —
  no API integrations needed.
- Teaching mode: demonstrate a workflow once, worker repeats it.
- Workers run in parallel on isolated cloud computers; they keep working
  while you're offline.

## What Argus does differently

| Warmwind | Argus OS |
|---|---|
| Cloud-hosted, streamed to browser | **Local** — your hardware, your session |
| Utilitarian streamed UI | **Premium native shell** (Quickshell on Plasma 6) |
| Business workflow automation | Personal + pro agent computing |
| Opaque remote workers | **Legible agency** — watch agents work live |
| Closed platform | Open Arch base, hackable everything |

Argus keeps the core insight — *the agent uses the computer the way a human
does* — and makes the experience of living alongside it the product.

## Product pillars

### 1. Computer use is the primitive

Agents don't need app integrations. Perception (screen capture + the
accessibility tree) and action (virtual input) are OS services, available to
any authorized agent — like sockets are to networking apps.

### 2. Legibility of agency

The signature question Argus answers at a glance: *"is the agent driving
right now?"*

- **EdgeGlow** — screen edges breathe in the accent color while an agent
  has input control. Impossible to miss, impossible to resent.
- **Agent Panel** — live feed of what the agent sees, intends, and does.
- **Activity timeline** — every action logged and replayable.

### 3. The human is root

- Computer use is a **grant**, not a default — per-agent, per-action-class
  permissions, revocable in one keystroke.
- "Watched mode": agent proposes, you approve each step.
- "Autonomous mode": agent runs within a policy envelope.
- Panic key: instantly revokes input control and freezes agents.

### 4. Restraint reads as premium

Near-black glass surfaces, a single accent gradient (iris → teal), springy
motion, real typography (Inter / JetBrains Mono). The UI should feel like a
sci-fi film prop that respects your attention.

### 5. Boring where it should be

Arch Linux underneath. Pacman, systemd, Plasma 6 for the human-facing DE
chrome (KWin handles window management — Quickshell owns the *agentic*
surfaces). No custom kernel, no bespoke init. The magic is in the runtime
and the shell, not in reinventing plumbing.

## Non-goals (for now)

- Not a mobile OS, not a cloud platform, not a browser-only product.
- Not a new desktop environment — Plasma stays for app compat and KWin.
- Not an LLM — Argus orchestrates models; it doesn't train them.

## First-principles bets

- Models keep getting better at operating GUIs; the OS that treats that as
  a native capability wins over OSes that bolt on a sidebar chatbot.
- Structured perception (AT-SPI accessibility tree) + vision beats
  vision-only — faster, cheaper, more reliable.
- The hardest part is **trust UX**, not model quality. The shell exists to
  solve it.
