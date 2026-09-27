#!/usr/bin/env bash
# setup-ci-signing.sh — give GitHub Actions its own KinetixOS signing key.
#
# Instead of exporting your passphrase-protected release key into CI, this
# creates a separate key used only by the publish workflow:
#
#   1. generates an ed25519 signing key in a throwaway GnuPG home
#      (never touches your own ~/.gnupg)
#   2. stores its private half as the KINETIX_SIGNING_KEY secret on the source
#      repo (encrypted by GitHub; readable only by workflows)
#   3. adds its public half to the kinetix-keyring files, next to your
#      existing key, so KinetixOS systems trust packages signed by either
#   4. destroys the throwaway GnuPG home
#
# Trade-off, knowingly accepted by running this: anyone who can change this
# repository's workflows can sign packages that every KinetixOS system
# trusts. Revoke by removing the key's line from kinetix-trusted (and adding
# it to kinetix-revoked), then publishing a new keyring.
#
# Systems installed before this change only know your original key: they
# accept the first CI-signed release once they have the updated keyring
# (a new ISO, or `sudo pacman-key --add` + `--lsign-key` of the CI key).
#
# Usage: distro/setup-ci-signing.sh [owner/repo]   (default: this repo's origin)
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KEYRING_DIR="$ROOT/distro/package/kinetix-keyring"
REPO="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

die() { printf 'setup-ci-signing: %s\n' "$*" >&2; exit 1; }
for tool in gpg gh shred; do command -v "$tool" >/dev/null || die "$tool is required"; done
[[ -f "$KEYRING_DIR/kinetix-trusted" ]] || die "missing $KEYRING_DIR/kinetix-trusted"

G="$(mktemp -d)"
cleanup() {
    gpgconf --homedir "$G" --kill gpg-agent 2>/dev/null || true
    find "$G" -type f -exec shred -u {} + 2>/dev/null || true
    rm -rf -- "$G"
}
trap cleanup EXIT
chmod 700 "$G"

# The key lives only in GitHub's secret store; a passphrase stored next to it
# there would add nothing, so the key is unprotected by design.
cat > "$G/batch" <<'EOF'
Key-Type: eddsa
Key-Curve: ed25519
Key-Usage: sign
Name-Real: KinetixOS CI Signing
Name-Email: ci-signing@kinetixos.invalid
Expire-Date: 0
%no-protection
%commit
EOF
GNUPGHOME="$G" gpg --batch --quiet --generate-key "$G/batch"
keyid="$(GNUPGHOME="$G" gpg --list-secret-keys --with-colons | awk -F: '/^sec:/{print $5; exit}')"
[[ -n "$keyid" ]] || die "key generation failed"
printf 'CI signing key: %s\n' "$keyid"

GNUPGHOME="$G" gpg --armor --export-secret-keys "$keyid" \
    | gh secret set KINETIX_SIGNING_KEY -R "$REPO"
printf 'Stored KINETIX_SIGNING_KEY on %s\n' "$REPO"

GNUPGHOME="$G" gpg --export "$keyid" >> "$KEYRING_DIR/kinetix.gpg"
grep -q "^$keyid:" "$KEYRING_DIR/kinetix-trusted" \
    || printf '%s:4\n' "$keyid" >> "$KEYRING_DIR/kinetix-trusted"
printf 'Added %s to the kinetix-keyring (trusted keys now:)\n' "$keyid"
sed 's/^/  /' "$KEYRING_DIR/kinetix-trusted"

printf '\nDone. Commit distro/package/kinetix-keyring/ so the next keyring ships it.\n'
