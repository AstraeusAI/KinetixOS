"""Shared runtime constants plus prefs/vault/auth loading (stdlib only)."""

import json
import os
import re
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parent.parent.parent
DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "argus"
CONF = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "argus"
DB = DATA / "memory.sqlite3"


def _env_int(name, default, minimum=1):
    """Read an integer env var with default and floor."""
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


MAX_TASK_SECONDS = _env_int("ARGUS_MAX_TASK_SECONDS", 1_800, 0)
MAX_STEPS = _env_int("ARGUS_MAX_STEPS", 64, 1)
MAX_STREAM_TRUNCATIONS = _env_int("ARGUS_MAX_STREAM_TRUNCATIONS", 3, 1)
SLOW_TOOL_SECONDS = 15  # a single tool call taking longer than this gets logged
HTTP_TIMEOUT = 90

# Reasoning/extended-thinking effort → Anthropic's thinking budget in
# tokens. Anthropic requires max_tokens to exceed budget_tokens (the
# response budget covers both thinking and the actual output), so
# provider_call bumps max_tokens alongside this rather than leaving the
# fixed 4096 in place — a budget_tokens of 8000 against a 4096 max_tokens
# would be rejected outright.
_REASONING_BUDGET = {"low": 2000, "medium": 8000, "high": 16000}


_DEFAULT_PREFS = {"provider": "openai", "model": "gpt-5.6-terra"}
_vault_cache = {"mtime": None, "value": {}}
_prefs_cache = {"mtime": None, "value": _DEFAULT_PREFS}


def vault():
    """Load keys.env into a dict of environment-style names to values.

    Cached by the file's mtime: provider_call() (providers/service.py)
    calls this once per agent step, and a multi-step task can run this
    dozens of times against a keys.env that never changes mid-run —
    re-reading and regex-parsing every line on every step was pure
    repeated I/O for the common case where nothing changed. A stat() to
    check mtime is far cheaper than the read+parse it lets us skip, and an
    actual edit (rotating a key) is still picked up on the very next call
    — the long-lived daemon's "edit config, no restart needed" behavior
    is unaffected. Returns a copy so a caller mutating its dict can't
    corrupt the cache for the next call.
    """
    p = CONF / "keys.env"
    try:
        mtime = p.stat().st_mtime
    except OSError:
        _vault_cache["mtime"], _vault_cache["value"] = None, {}
        return {}
    if mtime != _vault_cache["mtime"]:
        out = {}
        for line in p.read_text(errors="ignore").splitlines():
            m = re.match(r"export ([A-Z][A-Z0-9_]*)='(.*)'$", line)
            if m:
                out[m.group(1)] = m.group(2).replace("'\\''", "'")
        _vault_cache["mtime"], _vault_cache["value"] = mtime, out
    return dict(_vault_cache["value"])


def prefs():
    """Load ~/.config/argus/prefs.json (provider/model/auth/reasoning).

    Same mtime-gated cache as vault(), for the same reason — see its
    docstring.
    """
    p = CONF / "prefs.json"
    try:
        mtime = p.stat().st_mtime
    except OSError:
        _prefs_cache["mtime"], _prefs_cache["value"] = None, _DEFAULT_PREFS
        return dict(_DEFAULT_PREFS)
    if mtime != _prefs_cache["mtime"]:
        try:
            value = json.loads(p.read_text())
        except Exception:
            value = _DEFAULT_PREFS
        _prefs_cache["mtime"], _prefs_cache["value"] = mtime, value
    return dict(_prefs_cache["value"])


def auth_mode(prefs_doc, provider, v, keyname, subname):
    """Resolve a provider credential: ('key'|'sub', secret) or raise."""
    declared = (prefs_doc.get("auth") or {}).get(provider)
    key = v.get(keyname, "")
    sub = v.get(subname, "") if subname else ""
    if declared == "sub" and sub:
        return ("sub", sub)
    if declared == "key" and key:
        return ("key", key)
    if key:
        return ("key", key)
    if sub:
        return ("sub", sub)
    return (declared or "key", "")
