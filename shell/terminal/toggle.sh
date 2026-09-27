#!/bin/sh
# Toggles the KinetixOS quick terminal — Ghostty's own native drop-down
# terminal (a real wlr-layer-shell surface, not a QML reimplementation; see
# ghostty.conf's header comment for why).
#
# Prints the resulting state, exactly "open" or "closed", as the only line
# on stdout. The shell (Bar.qml) reads this to keep the bar button's active
# indicator — and therefore "minimize vs restore" on the next click — in
# sync with what's actually on screen. This works because
# quick-terminal-autohide is off and the surface has no titlebar or close
# button of its own (ghostty.conf), so this script is the *only* thing that
# ever changes its visibility: a small state file here can't drift from
# reality the way it could if the user had some other way to dismiss it.
#
# A custom `class` (ghostty.conf: com.kinetixos.quick-terminal) keeps this
# instance from ever being confused with, or toggled by, a normal ghostty
# window the user opened some other way — but it also means D-Bus auto-
# activation (the trick that normally lets `ghostty +toggle-quick-terminal`
# launch Ghostty from nothing) doesn't apply: that only fires for the
# default `com.mitchellh.ghostty` bus name, which has a system-installed
# .service file this custom class does not. So the checks below do that
# job by hand: if no instance owns our bus name yet, launch one directly
# with our config; every later toggle just messages the instance already
# running.
DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="$DIR/ghostty.conf"
CLASS="com.kinetixos.quick-terminal"
STATE="${XDG_RUNTIME_DIR:-/tmp}/argus-quickterm.state"

if [ "${1:-}" = "--status" ]; then
    if busctl --user status "$CLASS" >/dev/null 2>&1; then
        current="closed"
        [ -f "$STATE" ] && current="$(cat "$STATE" 2>/dev/null)"
        [ "$current" = "open" ] && echo "open" || echo "closed"
    else
        echo "closed"
    fi
    exit 0
fi

if ! command -v ghostty >/dev/null 2>&1; then
    notify-send "KinetixOS" "ghostty is not installed — the quick terminal needs it (pacman -S ghostty)" 2>/dev/null
    echo "closed"
    exit 1
fi

if busctl --user status "$CLASS" >/dev/null 2>&1; then
    ghostty --class="$CLASS" +toggle-quick-terminal
    prev="closed"
    [ -f "$STATE" ] && prev="$(cat "$STATE" 2>/dev/null)"
    if [ "$prev" = "open" ]; then next="closed"; else next="open"; fi
    echo "$next" > "$STATE"
    echo "$next"
    exit 0
fi

# First call in this session (or the instance died/was killed outside our
# control): launch our own instance directly rather than depending on
# D-Bus activation. Detached (setsid) so this script — and in turn the QML
# Process that ran it — returns immediately instead of blocking on
# Ghostty's whole lifetime. A freshly launched quick terminal is always
# shown, so the state is unconditionally "open" here.
setsid -f ghostty \
    --config-default-files=false \
    --config-file="$CONF" \
    --class="$CLASS" \
    +toggle-quick-terminal >/dev/null 2>&1 < /dev/null
echo "open" > "$STATE"
echo "open"
