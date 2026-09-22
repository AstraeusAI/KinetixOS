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


def vault():
    """Load keys.env into a dict of environment-style names to values."""
    out = {}
    p = CONF / "keys.env"
    if p.exists():
        for line in p.read_text(errors="ignore").splitlines():
            m = re.match(r"export ([A-Z][A-Z0-9_]*)='(.*)'$", line)
            if m:
                out[m.group(1)] = m.group(2).replace("'\\''", "'")
    return out


def prefs():
    """Load ~/.config/argus/prefs.json (provider/model/auth/reasoning)."""
    try:
        return json.loads((CONF / "prefs.json").read_text())
    except Exception:
        return {"provider": "openai", "model": "gpt-5.6-terra"}


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
