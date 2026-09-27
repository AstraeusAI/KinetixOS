---
name: kinetix-release
description: 'Use when cutting, publishing, or verifying a KinetixOS release, or when asked how to push updates. Triggers: publish, release, kinetix update, kinetix check, distro/version, publish.sh, build-iso.sh, setup-signing.sh, signing key, kinetix-pkgs, migrations.'
---

# KinetixOS release and publish workflow

KinetixOS ships in two independent layers. Confusing them is the usual mistake:

| Layer | What | How it reaches users |
|---|---|---|
| OS packages | Arch + CachyOS + the `[kinetix]` repo | `pacman -Syu`, via `kinetix update` |
| Kinetix payload | shell, agent runtime, `scripts/`, configs, the `kinetix` command — packaged as `kinetix` + `kinetix-keyring` | the same `kinetix update`, because it is a pacman package |

The payload is a **signed pacman package** published to `AstraeusAI/kinetix-pkgs` on GitHub Pages (mirror URL in `distro/repo.conf`, enforced by `SigLevel = Required`). Packaging is what makes updates possible: package ownership lets pacman replace files cleanly, which a loose copy cannot.

**Rebuilding the ISO does not update anyone. Publishing a package does.** They are separate operations.

## Push an update (the common task)

```sh
cd ~/Desktop/argus-os

# 1. Bump the version. This is mandatory — same version = no upgrade on the
#    other end, even though the files changed, because pacman compares pkgver.
echo 0.1.1 > distro/version

# 2. Build, sign and publish. Run as your NORMAL USER, never root.
./distro/publish.sh
```

`publish.sh` reads `distro/version`, rewrites both PKGBUILDs' `pkgver` from it, stages the payload tree, builds `kinetix` and `kinetix-keyring` with `makepkg`, signs every package and the `kinetix.db`, and pushes `x86_64/` to the repo. GitHub Pages serves it ~15–30s later.

- **Version rules:** valid pkgver, no dashes (`0.1.1`, `2026.09.27`).
- **Pre-flight instead of committing to a push:** `./distro/publish.sh --local` builds and signs into `distro/.publish/` and stops before pushing.
- Edit `shell/`, `runtime/`, `distro/` etc. **before** step 2 — the working tree is packaged as-is.

Users then run `kinetix check` (the bar badge does this automatically) and `kinetix update`.

## Migrations (only when a release changes state outside `/usr`)

A package cannot move `~/.config/argus/*` or the runtime's `~/.local/share/argus` journal. When a release changes the *shape* of any of that, add a migration instead:

- File: `distro/payload/usr/share/kinetix/migrations/NNNN-short-name.sh`
- Runs as root, once, in numeric order, on each machine's next `kinetix update`
- Must be idempotent (a failure is retried, not marked) and `set -Eeuo pipefail`
- Contract: `distro/payload/usr/share/kinetix/migrations/README.md`

## Rebuild the ISO (only for a new installer/live image)

```sh
sudo ./distro/build-iso.sh
```

- **Root** (it checks and refuses otherwise). Needs `archiso`, `cachyos-keyring`, baseline `cachyos-mirrorlist`.
- Output: `distro/out/` — **root-owned**, which is why publish builds in `distro/.publish/` instead.
- Bakes in the `[kinetix]` stanza, mirrorlist and the public signing key (`setup-signing.sh` must have run at least once, else it warns and skips the key).
- Env overrides: `ARCHISO_PROFILE_SOURCE`, `KINETIX_OUT_DIR`, `KINETIX_VERSION`.

## The signing key

One-time setup on the publish machine (already done for `AstraeusAI/kinetix-pkgs`):

```sh
./distro/setup-signing.sh            # not root; creates the GPG key
```

- Private key stays in `~/.gnupg`; only the public keyring enters `distro/package/kinetix-keyring/` (which is gitignored, by design — it rotates).
- **Back it up** (`gpg --export-secret-keys --armor <id>`); losing it means existing installs cannot verify future packages.
- Never regenerate the key casually, and never add the private key to the repo.

## Verifying a release actually works

Do not trust "Pushed kinetix X". Check the served artifact and the trust chain:

```sh
gh api repos/AstraeusAI/kinetix-pkgs/pages            # expect status: building -> built
gh api repos/AstraeusAI/kinetix-pkgs/contents/x86_64  # expect both packages + kinetix.db(.sig)

# Fetch and verify as a client would (public key from the keyring package):
URL=https://astraeusai.github.io/kinetix-pkgs/x86_64
curl -sfO --output-dir /tmp "$URL/kinetix.db" "$URL/kinetix.db.sig"
gpg --no-default-keyring \
    --keyring distro/package/kinetix-keyring/kinetix.gpg \
    --verify /tmp/kinetix.db.sig /tmp/kinetix.db     # expect "Good signature"
```

For a full client-side proof, sync the repo with pacman under an isolated
`--config`/`--dbpath`/`--root`/`GPGDir` in a temp dir (run through `fakeroot`,
since pacman and pacman-key require uid 0) and confirm `pacman -Sl kinetix`
lists both packages. This is how the endpoint was validated when it was built.

## Hard rules

- `publish.sh` and `build-iso.sh` have different privileges: publish as **user**, ISO as **root**. Never swap them.
- Never publish without bumping `distro/version`.
- Never `sudo ./distro/publish.sh` — makepkg refuses root and the key is the user's.
- A `libfakeroot internal error: payload not recognized!` line during the keyring build is a known host glibc/fakeroot mismatch; the package still builds and verifies. Investigate only if a package is missing or corrupt.
- The repo is public; the private key is not. Do not put secrets in `distro/payload/`.
- `distro/out/`, `distro/.publish/`, the staged tree and the generated keyring files are gitignored. Nothing here commits on your behalf.

## File map

```
distro/version                     single source of truth for the version
distro/repo.conf                   repo owner/name/branch (drives the mirror URL)
distro/repo/kinetix-mirrorlist     the pacman `Server =` line
distro/repo/kinetix.conf           canonical [kinetix] stanza
distro/setup-signing.sh            one-time key creation
distro/publish.sh                  build + sign + repo-add + push
distro/build-iso.sh                ISO build (root)
distro/package/kinetix/            PKGBUILD + .install for the payload package
distro/package/kinetix-keyring/    PKGBUILD + generated keyring files
distro/payload/usr/bin/kinetix*    the kinetix command set
distro/payload/usr/share/kinetix/migrations/   release migrations
```
