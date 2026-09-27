#!/usr/bin/env bash
# setup-signing.sh — create the KinetixOS package-signing key, once.
#
# Run this as yourself (never root) on the machine that will publish. It
# creates a dedicated GPG key used only to sign the Kinetix package repo, then
# writes the three files the kinetix-keyring package needs:
#
#   distro/package/kinetix-keyring/kinetix.gpg       public keyring (binary)
#   distro/package/kinetix-keyring/kinetix-trusted   <keyid>:4
#   distro/package/kinetix-keyring/kinetix-revoked   (empty)
#
# The private key stays in your GPG keyring and is never written to the repo.
# Back it up: losing it means users can no longer verify future packages
# against a key they already trust, and would have to re-trust a new one out
# of band.
#
# All GPG calls use --pinentry-mode loopback so this behaves the same whether
# or not a pinentry is available (over ssh, in CI), instead of depending on the
# ambient gpg-agent configuration.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KEYRING_DIR="$ROOT/distro/package/kinetix-keyring"

NO_PASSPHRASE=0
for arg in "$@"; do
    case "$arg" in
        --no-passphrase) NO_PASSPHRASE=1 ;;
        -h|--help)
            printf 'usage: distro/setup-signing.sh [--no-passphrase]\n'
            printf '  KINETIX_SIGNING_NAME / KINETIX_SIGNING_EMAIL to skip prompts\n'
            printf '  KINETIX_SIGNING_PASSPHRASE=... to avoid the passphrase prompt\n'
            exit 0 ;;
        *) printf 'setup-signing: unknown option %q\n' "$arg" >&2; exit 2 ;;
    esac
done

command -v gpg >/dev/null 2>&1 || { printf 'setup-signing: gpg is required\n' >&2; exit 1; }

# ── identity ────────────────────────────────────────────────────────────────
name="${KINETIX_SIGNING_NAME:-}"
email="${KINETIX_SIGNING_EMAIL:-}"
if [[ -z "$name" ]]; then
    read -r -p "Signing key name  [KinetixOS Package Signing]: " name || true
    name="${name:-KinetixOS Package Signing}"
fi
if [[ -z "$email" ]]; then
    read -r -p "Signing key email [pkgs@kinetixos.invalid]: " email || true
    email="${email:-pkgs@kinetixos.invalid}"
fi
printf 'Using identity: %s <%s>\n' "$name" "$email"

if gpg --list-secret-keys --with-colons "$email" 2>/dev/null | grep -q '^sec:'; then
    printf 'setup-signing: a secret key for %s already exists; use it or remove it first\n' "$email" >&2
    printf '  existing: %s\n' "$(gpg --list-secret-keys --with-colons "$email" | awk -F: '/^sec:/{print $5; exit}')" >&2
    exit 1
fi

# ── passphrase ──────────────────────────────────────────────────────────────
passphrase="${KINETIX_SIGNING_PASSPHRASE:-}"
if (( ! NO_PASSPHRASE )) && [[ -z "$passphrase" ]]; then
    read -r -s -p "Passphrase for the signing key (empty for none): " passphrase; printf '\n'
fi
if [[ -z "$passphrase" ]]; then
    printf 'warning: no passphrase — anyone who reads this key file can sign as Kinetix.\n' >&2
fi

# ── generate ────────────────────────────────────────────────────────────────
batch="$(mktemp)"
trap 'rm -f -- "$batch"' EXIT
{
    printf 'Key-Type: eddsa\n'
    printf 'Key-Curve: ed25519\n'
    printf 'Key-Usage: sign\n'
    printf 'Name-Real: %s\n' "$name"
    printf 'Name-Email: %s\n' "$email"
    printf 'Expire-Date: 0\n'
    # %no-protection is required when there is no passphrase; when there is
    # one, loopback supplies it and no protection line is needed.
    [[ -z "$passphrase" ]] && printf '%%no-protection\n'
    printf '%%commit\n'
} > "$batch"

gpg --batch --pinentry-mode loopback --passphrase "$passphrase" \
    --generate-key "$batch"

# ── locate the key we just made, by the email we chose ──────────────────────
keyid="$(gpg --list-secret-keys --with-colons "$email" 2>/dev/null \
    | awk -F: '/^sec:/ {print $5; exit}')"
if [[ -z "$keyid" ]]; then
    printf 'setup-signing: generated key not found for %s\n' "$email" >&2
    exit 1
fi
fingerprint="$(gpg --list-secret-keys --with-colons "$keyid" 2>/dev/null \
    | awk -F: '/^fpr:/ {print $10; exit}')"
printf 'Key generated: %s\n' "$fingerprint"

# ── write the keyring package files ─────────────────────────────────────────
mkdir -p -- "$KEYRING_DIR"
# Binary export, not armored: /usr/share/pacman/keyrings/*.gpg is read by
# pacman-key as an actual GnuPG keyring, and an armored file would not import.
gpg --export "$keyid" > "$KEYRING_DIR/kinetix.gpg"
# Trusted file format: one "<keyid>:<trust>" per line, trust 4 = full.
printf '%s:4\n' "$keyid" > "$KEYRING_DIR/kinetix-trusted"
: > "$KEYRING_DIR/kinetix-revoked"

cat <<EOF

Wrote distro/package/kinetix-keyring/{kinetix.gpg,kinetix-trusted,kinetix-revoked}
Fingerprint: $fingerprint

Back up the private key somewhere you will not lose it:
  gpg --export-secret-keys --armor $keyid > kinetix-signing-key.asc

Then publish: distro/publish.sh
EOF
