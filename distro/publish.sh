#!/usr/bin/env bash
# publish.sh — build the KinetixOS packages, sign them, and push the signed
# pacman repo to GitHub Pages.
#
# Run as yourself, never root (makepkg refuses root and the signing key is
# yours, not the system's). This is the "push" half of the update system:
# everything here runs on the machine that publishes, not on a user's machine.
#
#   distro/setup-signing.sh      once, to create the key
#   distro/publish.sh            build + sign + push
#   distro/publish.sh --local    build + sign into distro/out/repo, no push
#
# What lands in the published repo (served at the URL distro/repo.conf
# describes): kinetix.pkg.tar.zst, kinetix-keyring.pkg.tar.zst, each with a
# .sig, and the signed kinetix.db database. A user's `kinetix update` fetches
# these through pacman with SigLevel = Required.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_SRC="$ROOT/distro/package"
# A user-writable build root, deliberately NOT distro/out: that
# directory holds the root-owned ISO artefacts and publish must run as
# the unprivileged user (makepkg refuses root, and the signing key is
# the user's). Override with KINETIX_PUBLISH_DIR.
OUT="${KINETIX_PUBLISH_DIR:-$ROOT/distro/.publish}"
LOCAL_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --local) LOCAL_ONLY=1 ;;
        -h|--help) printf 'usage: distro/publish.sh [--local]\n'; exit 0 ;;
        *) printf 'publish: unknown option %q\n' "$arg" >&2; exit 2 ;;
    esac
done

die() { printf 'publish: %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1;31m==>\033[0m %s\n' "$*"; }

(( EUID != 0 )) || die "run as your normal user, not root (makepkg and the signing key are per-user)"
for tool in makepkg repo-add gpg; do
    command -v "$tool" >/dev/null 2>&1 || die "$tool is required"
done

# ── version (single source of truth) ────────────────────────────────────────
# CI publishes every commit on the stable branch as <version>.r<count>.g<sha>
# (see .github/workflows/publish.yml); a local run uses distro/version as is.
pkgver="${KINETIX_PKGVER:-$(tr -d '[:space:]' < "$ROOT/distro/version")}"
[[ "$pkgver" =~ ^[0-9][0-9A-Za-z._+]*$ ]] || die "distro/version is not a valid pkgver: '$pkgver'"

# ── repo coordinates ────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "$ROOT/distro/repo.conf"
: "${KINETIX_REPO_OWNER:?}" "${KINETIX_REPO_NAME:?}" "${KINETIX_REPO_BRANCH:?}" "${KINETIX_PACMAN_REPO:?}"
repo_slug="$KINETIX_REPO_OWNER/$KINETIX_REPO_NAME"
pages_owner_lower="$(printf '%s' "$KINETIX_REPO_OWNER" | tr '[:upper:]' '[:lower:]')"
pages_url="https://${pages_owner_lower}.github.io/${KINETIX_REPO_NAME}"

# ── signing key must exist ──────────────────────────────────────────────────
[[ -d "$PKG_SRC/kinetix-keyring" ]] || die "missing $PKG_SRC/kinetix-keyring"
keyring_file="$PKG_SRC/kinetix-keyring/kinetix.gpg"
[[ -s "$keyring_file" ]] || die "no signing key — run distro/setup-signing.sh first"
# Sign with the first trusted key this machine holds the secret for: the
# maintainer's release key at a desk, the dedicated CI key in GitHub Actions
# (distro/setup-ci-signing.sh). Every key in kinetix-trusted verifies.
trusted=""
while IFS=: read -r kid _; do
    [[ -n "$kid" ]] || continue
    if gpg --list-secret-keys "$kid" >/dev/null 2>&1; then trusted="$kid"; break; fi
done < "$PKG_SRC/kinetix-keyring/kinetix-trusted"
[[ -n "$trusted" ]] || die "no key in kinetix-trusted has its secret key here — run distro/setup-signing.sh (or setup-ci-signing.sh for CI)"
printf 'Signing with key %s, version %s\n' "$trusted" "$pkgver"

# ── stage the payload tree the kinetix package installs ─────────────────────
step "Staging payload"
BUILD="$OUT/build"
TREE="$BUILD/tree"
rm -rf "$BUILD"
mkdir -p "$TREE/usr/share/kinetix"

# The kinetix command set, systemd units, migrations README.
cp -a "$ROOT/distro/payload/." "$TREE/"
# The desktop itself.
cp -a "$ROOT/shell" "$TREE/usr/share/kinetix/shell"
cp -a "$ROOT/runtime" "$TREE/usr/share/kinetix/runtime"
cp -a "$ROOT/scripts" "$TREE/usr/share/kinetix/scripts"
install -Dm644 "$ROOT/distro/version" "$TREE/usr/share/kinetix/version"
# Repo mirrorlist: owned by the package so `kinetix update` keeps the URL
# current without the installer having to rewrite it.
install -Dm644 "$ROOT/distro/repo/kinetix-mirrorlist" "$TREE/etc/pacman.d/kinetix-mirrorlist"

# Desktop config carried from the live ISO, at identical paths.
copy_cfg() {
    local rel="$1"
    local src="$ROOT/distro/archiso/airootfs/$rel"
    [[ -f "$src" ]] || return 0
    install -Dm644 "$src" "$TREE/$rel"
}
copy_cfg etc/sysctl.d/99-kinetix-performance.conf
copy_cfg etc/udev/rules.d/60-kinetix-ioscheduler.rules
copy_cfg etc/systemd/zram-generator.conf
copy_cfg etc/systemd/system.conf.d/00-timeout.conf
copy_cfg etc/systemd/system.conf.d/10-limits.conf
copy_cfg etc/systemd/user.conf.d/00-timeout.conf
copy_cfg etc/systemd/user.conf.d/10-limits.conf
copy_cfg etc/tmpfiles.d/thp.conf
install -Dm644 "$ROOT/distro/assets/kinetix-wallpaper.png" \
    "$TREE/usr/share/backgrounds/kinetixos/wallpaper.png"
install -Dm644 "$ROOT/distro/archiso/airootfs/usr/share/wayland-sessions/kinetix.desktop" \
    "$TREE/usr/share/wayland-sessions/kinetix.desktop"

# Scripts the package ships must be executable inside the tree.
find "$TREE/usr/bin" -type f -exec chmod 0755 {} +
find "$TREE/usr/share/kinetix/migrations" -type f -name '*.sh' -exec chmod 0755 {} + 2>/dev/null || true

# ── build both packages ─────────────────────────────────────────────────────
build_package() {
    local name="$1"
    local dir="$BUILD/pkgbuild-$name"
    mkdir -p "$dir"
    cp "$PKG_SRC/$name/PKGBUILD" "$PKG_SRC/$name/$name.install" "$dir/" 2>/dev/null || true
    # Single source of truth for the version: rewrite the PKGBUILD's pkgver
    # from distro/version at build time rather than keeping two numbers.
    sed -i "s/^pkgver=.*/pkgver=$pkgver/" "$dir/PKGBUILD"
    if [[ "$name" == "kinetix" ]]; then
        cp -a "$TREE" "$dir/tree"
    else
        cp "$PKG_SRC/kinetix-keyring/kinetix.gpg" \
           "$PKG_SRC/kinetix-keyring/kinetix-trusted" \
           "$PKG_SRC/kinetix-keyring/kinetix-revoked" "$dir/"
    fi
    ( cd "$dir" && makepkg --noconfirm -f --nodeps --sign --key "$trusted" >/dev/null )
    printf '%s' "$dir"
}

step "Building kinetix-$pkgver"
kinetix_dir="$(build_package kinetix)"
step "Building kinetix-keyring-$pkgver"
keyring_dir="$(build_package kinetix-keyring)"

# ── assemble the repo ───────────────────────────────────────────────────────
step "Assembling signed repo"
REPO_DIR="$OUT/repo/$([ "$(uname -m)" = x86_64 ] && echo x86_64 || uname -m)"
rm -rf "$OUT/repo"
mkdir -p "$REPO_DIR"
shopt -s nullglob
for pkg in "$kinetix_dir"/*.pkg.tar.zst "$keyring_dir"/*.pkg.tar.zst; do
    cp -f "$pkg" "$pkg.sig" "$REPO_DIR/"
done
shopt -u nullglob
compgen -G "$REPO_DIR/*.pkg.tar.zst" >/dev/null || die "no packages were built"

# repo-add wants the db basename to match the pacman repo name.
( cd "$REPO_DIR" && repo-add "${KINETIX_PACMAN_REPO}.db.tar.zst" ./*.pkg.tar.zst >/dev/null )

# repo-add makes the db a symlink; GitHub Pages serving a symlink over HTTP is
# not something to rely on, so make them real files before signing/publishing.
for db in "$REPO_DIR/${KINETIX_PACMAN_REPO}.db" "$REPO_DIR/${KINETIX_PACMAN_REPO}.files"; do
    if [[ -L "$db" ]]; then
        cp -fL "$db" "$db.real"
        mv -f "$db.real" "$db"
    fi
    if [[ -f "$db" ]]; then
        gpg --batch --yes --use-agent -u "$trusted" --detach-sign "$db"
    fi
done

printf '\nRepo built at %s\n' "$REPO_DIR"
ls -1 "$REPO_DIR"

if (( LOCAL_ONLY )); then
    printf '\n--local: not pushing. To serve it, copy %s/ to %s and enable Pages.\n' "$REPO_DIR" "$pages_url"
    exit 0
fi

# ── publish to GitHub Pages ─────────────────────────────────────────────────
# Push route: KINETIX_PKGS_REMOTE (a git URL — CI uses an SSH deploy key) or,
# for a maintainer at a desk, the gh CLI's logged-in account.
PKGS_REMOTE="${KINETIX_PKGS_REMOTE:-}"
[[ -n "$PKGS_REMOTE" ]] || command -v gh >/dev/null 2>&1 \
    || die "gh is required to publish (or set KINETIX_PKGS_REMOTE, or re-run with --local)"
step "Publishing to $repo_slug ($KINETIX_REPO_BRANCH)"

WORK="$OUT/publish"
if [[ ! -d "$WORK/.git" ]]; then
    rm -rf "$WORK"
    if [[ -n "$PKGS_REMOTE" ]]; then
        git clone --quiet "$PKGS_REMOTE" "$WORK"
    else
        gh repo view "$repo_slug" >/dev/null 2>&1 \
            || gh repo create "$repo_slug" --public \
                --description "KinetixOS signed pacman package repository" >/dev/null
        gh repo clone "$repo_slug" "$WORK"
    fi
    git -C "$WORK" checkout --quiet "$KINETIX_REPO_BRANCH" 2>/dev/null \
        || git -C "$WORK" checkout --quiet -b "$KINETIX_REPO_BRANCH"
else
    git -C "$WORK" fetch --quiet origin
    git -C "$WORK" checkout --quiet "$KINETIX_REPO_BRANCH" 2>/dev/null || true
    git -C "$WORK" pull --quiet --ff-only 2>/dev/null || true
fi

mkdir -p "$WORK/${REPO_DIR##*/}"
# Replace the arch dir wholesale: a stale package left in place would keep
# being served and, worse, keep being listed in an old db.
rm -f "$WORK/${REPO_DIR##*/}"/*.pkg.tar.zst "$WORK/${REPO_DIR##*/}"/*.sig \
      "$WORK/${REPO_DIR##*/}/${KINETIX_PACMAN_REPO}".* 2>/dev/null || true
cp -f "$REPO_DIR"/* "$WORK/${REPO_DIR##*/}/"
touch "$WORK/.nojekyll"   # stop Jekyll from swallowing files it does not like

git -C "$WORK" add -A
if git -C "$WORK" diff --cached --quiet; then
    printf 'Repo already up to date; nothing to push.\n'
else
    git -C "$WORK" -c user.name="${GIT_AUTHOR_NAME:-KinetixOS Packages}" \
        -c user.email="${GIT_AUTHOR_EMAIL:-pkgs@kinetixos.invalid}" \
        commit --quiet -m "kinetix ${pkgver}"
    git -C "$WORK" push --quiet origin "$KINETIX_REPO_BRANCH"
    printf 'Pushed kinetix %s.\n' "$pkgver"
fi

# Pages must actually be switched on for the push to be served.
if [[ -z "$PKGS_REMOTE" ]]; then
    gh api --method POST "repos/$repo_slug/pages" \
        -f "source[branch]=$KINETIX_REPO_BRANCH" -f "source[path]=/" >/dev/null 2>&1 || true
fi

printf '\nPublished. Users pull from: %s/$arch\n' "$pages_url"
printf 'Verify with:  kinetix check   (on any installed KinetixOS)\n'
