#!/bin/sh
# argus-appscan.sh — enumerate installed applications.
# Emits one TSV line per app:  name \t exec \t iconPath \t comment \t categories \t desktopFile

DIR="$(dirname "$0")"
if command -v python3 >/dev/null 2>&1 && [ -f "$DIR/argus-appscan.py" ]; then
    exec python3 "$DIR/argus-appscan.py" "$@"
fi

ICON_DIRS="$HOME/.local/share/icons $HOME/.icons /usr/share/icons/hicolor /usr/share/pixmaps /usr/share/icons/Adwaita /usr/share/icons/breeze /usr/share/icons/breeze-dark /usr/share/icons/Papirus /usr/share/icons/Papirus-Dark"

INDEX=$(mktemp)
trap 'rm -f "$INDEX"' EXIT

# ── build icon index: basename(no ext) → best path ──
for d in $ICON_DIRS; do
    [ -d "$d" ] || continue
    find "$d" -type f \( -iname '*.png' -o -iname '*.svg' -o -iname '*.xpm' \) 2>/dev/null
done | awk -F/ '
{
    base = $NF; sub(/\.(png|svg|xpm)$/, "", base);
    score = 4;
    if ($0 ~ /scalable/) score = 12;
    else if ($0 ~ /256x256/) score = 10;
    else if ($0 ~ /128x128/) score = 9;
    else if ($0 ~ /96x96/) score = 8;
    else if ($0 ~ /64x64/) score = 7;
    else if ($0 ~ /48x48/) score = 6;
    else if ($0 ~ /32x32/) score = 5;
    if ($0 ~ /\/hicolor\//) score += 3;
    if (!(base in best) || score > best[base]) { best[base] = $0 }
}
END { for (b in best) print b "\t" best[b] }' > "$INDEX"

resolve() {
    [ -z "$1" ] && return
    case "$1" in
        /*) [ -f "$1" ] && printf '%s' "$1"; return ;;
    esac
    awk -F'\t' -v k="$1" '$1 == k { print $2; exit }' "$INDEX"
}

for f in "$HOME"/.local/share/applications/*.desktop /usr/share/applications/*.desktop; do
    [ -f "$f" ] || continue
    grep -q '^NoDisplay=true' "$f" 2>/dev/null && continue
    grep -q '^Type=Application' "$f" 2>/dev/null || continue
    name=$(grep -m1 '^Name=' "$f" | cut -d= -f2-)
    [ -n "$name" ] || continue
    exec=$(grep -m1 '^Exec=' "$f" | cut -d= -f2- | sed 's/ *%[a-zA-Z]//g')
    icon=$(grep -m1 '^Icon=' "$f" | cut -d= -f2-)
    comment=$(grep -m1 '^Comment=' "$f" | cut -d= -f2-)
    cats=$(grep -m1 '^Categories=' "$f" | cut -d= -f2-)
    ipath=$(resolve "$icon")
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$exec" "$ipath" "$comment" "$cats" "$f"
done
