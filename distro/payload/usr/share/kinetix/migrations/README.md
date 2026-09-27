# KinetixOS migrations

Each file here is a one-shot system change that a package upgrade cannot make
on its own — usually because it touches state outside `/usr`, like the user's
`~/.config/argus` or `~/.local/share/argus`.

Run by `kinetix update` (and `kinetix-migrations run`) after `pacman -Syu`,
once each, in numeric order. `kinetix migrations` lists what is applied and
what is pending.

## Writing one

- Name it `NNNN-short-description.sh`, zero-padded, so `LC_ALL=C sort` orders
  it correctly. **Never reuse or reorder a number** — the applied marker is
  keyed on the filename, so a reused number would either double-apply or skip.
- Runs as **root**. Read the invoking user from `$SUDO_USER` or `$HOME` if you
  need to touch their files; do not assume `$HOME` is the target home.
- **Idempotent.** A failure does not write the marker, so a fixed script is
  re-run on the next update. It must therefore be safe to run against a system
  that is already half-migrated.
- Failure is a real failure: exit non-zero and let `kinetix update` stop. Do
  not swallow errors with `|| true` unless the operation is genuinely optional.
- Use `set -Eeuo pipefail` like the rest of the distro.
