# 02 — Design System

The bar for Argus is *film-prop quality*: every surface should feel
deliberate. This file is the contract between design intent and the QML
tokens in `shell/common/Theme.qml`.

## Color

Near-black canvas, white typography, **one** accent.

| Token | Value | Use |
|---|---|---|
| `bg` | `#0B0D12` | desktop void behind glass |
| `surfaceLow` | `white @ 4%` | inset areas, wells |
| `surface` | `white @ 7%` | panels, bar |
| `surfaceHigh` | `white @ 11%` | hovered/raised |
| `stroke` | `white @ 10%` | hairline borders |
| `strokeStrong` | `white @ 18%` | focused borders |
| `text` | `white @ 92%` | primary |
| `textDim` | `white @ 60%` | secondary |
| `textFaint` | `white @ 38%` | captions, timestamps |
| `accent` | `#8A7CFF` | iris — agent identity, primary actions |
| `accent2` | `#5EEAD4` | teal — gradient partner, "ok" states |
| `warn` | `#FFB454` | needs-attention |
| `danger` | `#FF6B6B` | destructive, panic |

Signature gradient: `accent → accent2`, used *only* for agent-presence
elements (EdgeGlow, StatusOrb ring, active workspace dot). Never on buttons
or text — restraint is what makes it feel expensive.

### Agent Panel palette (deliberate exception)

The Agent Panel is the one surface where the agent holds full authority
(computer-use, shell, destructive actions), so it carries its own palette —
a darker, single-hue crimson family defined in
`shell/agent/AgentPanel.qml` (`pAccent*` tokens). Everything else keeps the
iris/teal accents above. The temperature inversion (cool OS, warm panel) is
the point: the panel should read as a different room. The restraint rule
still applies *inside* the panel: one hue family, never a rainbow.

| Token | Value | Use |
|---|---|---|
| `pAccent` | `#B3283A` | crimson — borders, focus, bars, hovers, identity |
| `pAccentText` | `#D6556A` | crimson lifted for text/glyphs (≥4.5:1 on both washes) |
| `pAccent2` | `#E8752E` | ember — glow, live pulses, "ok" |
| `pWarn` | `#C98F2E` | gilded amber — caution, reasoning (yellow-shifted so it can't be mistaken for ember at pip size) |
| `pDanger` | `#FF2E43` | alarm — blocked/error |
| `pGlowDeep` | `#2A070C` | deepest gradient/shadow stop |
| `pWell` | `#170A0A` | warm-dark inset fill — plan cards, idle pills |
| `pAct` | `#D9432E` | hot vermilion — "act" step in the perceive→verify feed |
| `pVerify` | `#C25A33` | rust — "verify" step (4.6:1 on panel base) |

Rules:

- `pAccent` (3.1:1 on the panel base) is for borders, bars and icons only.
  Anything textual — labels, glyphs, status text — uses `pAccentText`.
- `pWarn` and `pAccent2` sit 15° apart in hue (38° vs 23°); warn is also
  less saturated. Never move one toward the other.
- Panels of the same family may not reuse `Theme.accent` (violet) inside
  the panel — see `TerminalCard.qml`.
- Cross-surface note: the OS-level *semantic* agent states (StatusOrb,
  EdgeGlow, approval banner, `Theme.statusColor()`) still use the iris/teal/
  warn/danger mapping above — those colors carry meaning (working vs.
  watching vs. blocked) and must stay distinguishable from each other, so
  they are never swept into a single hue family. The panel's local mapping
  (ok=ember, running=crimson, blocked=alarm) is panel-scoped.

### Main bar palette

The main bar's own chrome — its glass, hairlines and pill capsules, not the
semantic content drawn on top of it — is the same deep ominous crimson
family, via dedicated `bar*` tokens in `Theme.qml` rather than reusing
`glassBase`/`surfaceHigh` directly (so every other panel — overlays,
widgets, the launcher — keeps the neutral glass above unaffected by a future
bar-only tweak):

| Token | Value | Use |
|---|---|---|
| `barBase` | near-black oxblood, 98% | the bar's own glass base |
| `barBaseHigh` | lighter oxblood, 97% | resting pill-capsule base — a shade lifted off the bar so pills still read as cut into the glass |
| `barStroke` | crimson @ 22% | inner keyline, resting pill hairline |
| `barStrokeStrong` | alarm @ 40% | hover border |
| `barHoverGlow` | crimson @ 16% | hovered (non-active) pill base wash |

This was a deliberate widening of the panel's crimson identity onto the bar
that carries it — the AGENT pill no longer has to be the bar's *only* red
element to make sense. Two things stay unchanged on purpose:

- The bottom laser rail (`FlowBand`, `mode: "bottomEdge"`) keeps its own
  four-brand rainbow sweep animation untouched — it's a deliberate contrast
  accent against the red glass, not a leftover to be retinted.
- Specular highlights (the top micro-chamfer sheen on each pill, the bar's
  overhead grazing-light bevel) stay white/bright. A real glossy surface's
  specular reflection keeps the light source's color, not the substrate's —
  tinting these red would read as flat colored plastic, not glass.

Glass: panels are translucent surfaces + 1px stroke + faint top highlight.
On KWin, enable the Blur desktop effect for true frosted glass; the tokens
are chosen so panels still read well unblurred.

## Typography

- UI: **Inter** (`inter-font`)
- Data/mono: **JetBrains Mono** (`ttf-jetbrains-mono`)

| Token | Size | Weight | Use |
|---|---|---|---|
| `tCaption` | 10 | medium | timestamps, microcopy |
| `tBody` | 12 | regular | default UI text |
| `tLabel` | 12 | semibold | section labels, buttons |
| `tTitle` | 14 | semibold | panel titles |
| `tDisplay` | 18 | medium | clock, hero numbers |

Tracking: +2% on all-caps microcopy (`ARGUS`, status labels). Never letter-
space body text.

## Shape & space

- Radii: `rS 8 · rM 14 · rL 20 · rPill 999`
- Spacing: `s1 4 · s2 8 · s3 12 · s4 16 · s5 24 · s6 32`
- Bars/panels float — `margins: 10–14` from screen edges. Nothing touches
  the bezel.
- Hairlines over shadows: depth comes from translucency + stroke, not blur
  shadows.

## Motion

| Token | ms | Feel |
|---|---|---|
| `durFast` | 130 | hover, press |
| `durMed` | 240 | toggles, small reveals |
| `durSlow` | 420 | panel slides, overlay fades |
| `durAmbient` | 1600 | breathing loops (EdgeGlow, orb) |

- Ease out for entrances: `OutQuint`. Symmetric `InOutSine` for loops.
- Panel slides use `durSlow + OutQuint` — fast enough to feel instant,
  smooth enough to feel expensive.
- Ambient motion (EdgeGlow breath, orb pulse) runs at 1.2–1.6s periods —
  slow enough to read as "alive," not "alarming."
- Nothing bounces except intentional moments. `OutBack` is a garnish, not
  a staple.

## Fidelity v2 — the glass recipe

Every surface is built from `components/GlassPanel.qml`, which layers six
things. Skipping any of them is what makes QML shells look cheap:

1. **Soft multi-layer shadow** — 2–3 stacked rounded rects, each offset
   downward with decreasing alpha and increasing outward growth
   (`Theme.shadowFor(level)`). No hard single shadow.
2. **Tinted base** — `glassBase` at ~74% alpha over whatever is behind.
3. **Depth wash** — vertical gradient, light top → dark bottom. Reads as
   thickness.
4. **Specular sheen** — diagonal horizontal gradient (white 7.5% at the
   left edge, fading by 42%). Simulates a light source at upper-left.
5. **Rim light** — 1px top edge gradient (brightest ~16% in from the left,
   fading to nothing). This is the single highest-value detail.
6. **Accent glow** — 2px outer border at 20% accent when `tinted: true`
   (active/focused states).

### Elevation

| Level | Use | Shadow reach |
|---|---|---|
| 0 | insets, chips, wells | ~2px |
| 1 | default cards, toasts | ~10px |
| 2 | the bar, widgets | ~18px |
| 3 | floating panels, launcher, palette, OSD | ~30px |

### Blur

Real backdrop blur is compositor-side on Wayland. On KWin, enable the
**Blur** desktop effect — translucent layer surfaces get frosted. The tokens
are tuned so panels still read as premium glass without it. `QtQuick.Effects`
(`MultiEffect`) is available for in-shell blur/colorization where a surface
needs to blur its own content.

### Component vocabulary

| Component | Role |
|---|---|
| `GlassPanel` | the fidelity primitive — all surfaces |
| `ArgusMark` | eye mark, breathing iris |
| `StatusOrb` | state dot + pulse ring |
| `PillButton` | labelled pill action |
| `IconButton` | compact glyph button (bar) |
| `Toggle` | switch |
| `Sparkline` | Canvas line+fill graph for live data |

## Signature elements

### EdgeGlow

Four screen-edge gradients, `accent → transparent`, ~14px deep, breathing
between 55–100% opacity. **Meaning: an agent currently holds input
control.** This is the OS's single most important piece of visual language —
it turns "is the AI typing?" into peripheral awareness.

Rules: overlay layer, click-through (`mask: Region {}`), never used for
anything except live agent control.

### StatusOrb

6px dot + expanding ring. Color encodes state:
`accent2` idle/ok · `accent` working · `warn` awaiting approval ·
`danger` error/blocked. Ring pulses only while a state is *live*.

### Agent Panel

Right-edge slide-in, 430px, overlay layer, input-on-demand. Structure:
header (orb + name + status) → computer-use grant toggle → capability chips
→ live feed → composer. The feed is the product: plain-language narration
of what the agent sees and does.

## Sound (later)

Two sounds maximum: a soft "grant" tick when computer-use is enabled, a
lower "revoke" when it's cut. Agents should be seen, not heard.

## Do / Don't

- ✅ Do: let content breathe; empty space is free.
- ✅ Do: animate state *changes*, not states.
- ❌ Don't: rainbow accents, multi-hue status soup.
- ❌ Don't: text under 10px, borders under 8% alpha, animation over 400ms
  for UI response.
