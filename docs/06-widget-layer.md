# 06 — Desktop Widget Layer

Vista-Aero-style gadgets: glass widgets that float **over applications**,
user-creatable, draggable, resizable, and persisted.

## Concept

Windows Vista's Sidebar/Gadgets proved the idea — small, glanceable,
always-available surfaces living on the desktop — but they were desktop-bound
(behind windows) and closed to user authoring. Argus widgets are:

- **Above applications** — a `WlrLayer.Top` layer surface, so a system monitor
  or agent panel stays visible while you work.
- **User-authored** — add any number, pick a type, configure it, move it.
- **Glass, not chrome** — same fidelity primitive as the shell (`GlassPanel`).

## Architecture

```
WidgetStore (singleton, common/WidgetStore.qml)
  ├─ widgets: [ {id, type, x, y, w, h, config} ]
  ├─ types:   catalog (clock, sysmon, notes, command, agent, image, weather)
  └─ persistence: ~/.config/argus/widgets.json  (debounced writes)

overlay/WidgetLayer.qml
  └─ Variants { model: WidgetStore.widgets }
       └─ widgets/WidgetWindow.qml      ← one layer-shell window per widget
            └─ widgets/WidgetFrame.qml  ← glass chrome: drag, settings, close, resize
                 └─ widgets/WidgetHost.qml
                      └─ widgets/content/<Type>Widget.qml
```

### Why one window per widget

A single full-screen overlay would need a union input mask over every widget
rect (and would intercept clicks in the gaps). One window per widget means the
window *is* the widget: clicks anywhere else pass straight through to
applications, with no mask bookkeeping. Widget z-order is array order —
`bringToFront()` reorders the model on release.

### Dragging under layer-shell

Layer surfaces have no global cursor coordinates, so dragging uses the
self-correcting incremental form:

```
widget.x += (mouse.x - pressLocalX)
```

The window origin follows the cursor, which resets the local mouse coordinate,
so each subsequent event contributes exactly the incremental movement.

## Widget types

| Type | Content | Config |
|---|---|---|
| `clock` | Hero time, weekday, date, seconds | — |
| `sysmon` | CPU / RAM / GPU sparklines, network, disk | — |
| `notes` | Editable scratchpad, autosaved | — |
| `command` | Live output of any shell command | `cmd`, `interval` |
| `agent` | Agent status orb, last message, quick task box | — |
| `image` | Local image, aspect-cropped | `path` |
| `weather` | Live weather via wttr.in (no key) | `location` |

**"Widgets of any kind"** is served by `command`: point it at any shell command
and set a refresh interval. That covers API polls, build status, git state,
sensor readouts, log tails — without shipping a plugin per use case.

## Managing widgets

- **Add** — bar `◫` button → catalog → click a type. New widgets land offset
  from the last one so they don't stack.
- **Move** — drag the header.
- **Resize** — drag the bottom-right grip (min 180×110).
- **Configure** — gear icon (only shown for types with fields); `↵` applies.
- **Remove** — `✕` in the header.
- **Reset / clear** — catalog footer.

Layout is written to `~/.config/argus/widgets.json` 600 ms after the last
change (debounced). Delete the file to reseed the default layout
(clock + system monitor).

## Roadmap for the layer

- **Phase 1 (now)** — built-in types, manual layout, JSON persistence.
- **Phase 2** — snap-to-grid + alignment guides; per-widget opacity/blur;
  widget groups; import/export layout files.
- **Phase 3** — authoring: user-defined widgets from a declarative spec
  (bindings to `argusd` data sources), and a marketplace of layouts.
- **Phase 4** — agent-authored widgets: ask Argus for a widget and it writes
  the spec, registers it, and places it.
