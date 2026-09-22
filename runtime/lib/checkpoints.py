"""Checkpoints: undo for agent file writes.

Before any mutating tool touches a file, the previous contents are copied
here. `checkpoint_restore` puts them back. Without this, nobody should let an
agent near a repository — and "the model will be careful" is not a safety
mechanism.
"""
import itertools
import json
import os
import shutil
import time
from pathlib import Path

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "argus"
ROOT = DATA / "checkpoints"
MAX_AGE_DAYS = 7

# Module-level: two checkpoints in the same millisecond (e.g. a model turn
# with several edit_file/multi_edit calls back to back, no network latency
# between them) used to get the same id from int(time.time()*1000) alone —
# the second save's backup silently overwrote the first's, so restoring the
# *first* checkpoint actually restored the *second* snapshot's content. The
# counter alone only protects one process: the shell's ArgusBridge gates on
# a `busy` flag so it never runs two argusd.py processes for the same panel
# concurrently, but the CLI is also documented as directly runnable by hand
# (see README), and nothing stops two manually-launched processes sharing a
# --session. Folding in the pid closes that gap too, for free.
_counter = itertools.count()


def _prune_stale_sessions(max_age_days=MAX_AGE_DAYS):
    """Delete whole checkpoint session directories that haven't had a new
    checkpoint written in `max_age_days` — undo is only useful for recent
    work, and nothing here was ever cleaning these up. Confirmed live: 73
    files (304KB) had already accumulated across ~15 one-off session
    directories on this host, several clearly from a single finished task
    that will never be resumed (session ids like "code-1789583908"). Only
    a directory whose *newest* file is old gets removed, so a session still
    in active use — which by definition keeps getting new checkpoints — is
    never touched, regardless of how long ago it started.
    """
    if not ROOT.is_dir():
        return
    cutoff = time.time() - max_age_days * 86400
    for d in ROOT.iterdir():
        if not d.is_dir():
            continue
        try:
            newest = max((f.stat().st_mtime for f in d.rglob("*") if f.is_file()), default=0)
        except OSError:
            continue
        if newest and newest < cutoff:
            shutil.rmtree(d, ignore_errors=True)


class Checkpoints:
    def __init__(self, session):
        self.session = session
        self.dir = ROOT / session
        # Once per instantiation (once per run()/approve() call, not per
        # checkpoint) — cheap at the file counts this produces in practice,
        # and self-limiting since pruning keeps that count small.
        _prune_stale_sessions()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.dir / "manifest.jsonl"

    def _seq(self):
        return f"{int(time.time() * 1000)}-{os.getpid()}-{next(_counter)}"

    def save(self, path, workspace, reason=""):
        """Snapshot `path` before it is modified. Returns a checkpoint id."""
        p = Path(path)
        cid = f"c{self._seq()}"
        entry = {"id": cid, "ts": int(time.time()), "path": str(p),
                 "rel": str(p.relative_to(workspace)) if workspace and str(p).startswith(str(workspace)) else str(p),
                 "existed": p.exists(), "reason": reason}
        if p.exists():
            dest = self.dir / cid
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest / p.name)
            entry["backup"] = str(dest / p.name)
        with self.manifest.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return cid

    def list(self, limit=40):
        if not self.manifest.exists():
            return []
        out = []
        for line in self.manifest.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out[-limit:]

    def restore(self, cid, workspace=None):
        """Put a checkpointed file back. `workspace` is the root the restore is
        allowed to write inside; the target path comes out of the manifest, not
        from the caller, so it has to be re-checked here rather than trusted —
        a stale or foreign manifest entry naming a path outside the workspace
        used to be written to unconditionally."""
        root = Path(workspace).resolve() if workspace else None
        for e in self.list(limit=10000):
            if e["id"] != cid:
                continue
            target = Path(e["path"])
            if root is not None:
                resolved = (target.resolve() if target.exists()
                            else target.parent.resolve() / target.name)
                if resolved != root and root not in resolved.parents:
                    return {"ok": False, "error": f"checkpoint {cid} points outside the "
                            f"workspace ({e.get('rel', e['path'])}) — refusing to write there"}
            if not e.get("existed"):
                # file was created by the agent — restoring means removing it
                if target.exists():
                    target.unlink()
                return {"ok": True, "action": "removed", "path": str(target)}
            backup = Path(e.get("backup", ""))
            if not backup.exists():
                return {"ok": False, "error": "backup missing for " + cid}
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            return {"ok": True, "action": "restored", "path": str(target)}
        return {"ok": False, "error": "unknown checkpoint " + cid}
