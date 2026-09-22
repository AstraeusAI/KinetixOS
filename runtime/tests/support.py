"""Shared setup for the runtime tests.

Import this FIRST in every test module: argusd and lib.* resolve their data,
config and checkpoint paths at import time, so pointing the XDG dirs at a
throwaway tree has to happen before they are imported — otherwise a test run
writes into the real ~/.local/share/argus and ~/.config/argus.

Run with (pytest, if it is installed):

    python3 -m pytest runtime/tests -q

and without it:

    python3 -m unittest discover -s runtime/tests -v
"""
import os
import sys
import tempfile
import warnings
from pathlib import Path

# The runtime opens a short-lived SQLite connection per run()/approve() call and
# never closes it (the process exits), and the tests deliberately make hundreds
# of those against a throwaway database — the unclosed-connection warnings are
# noise about the test harness's own usage, not a leak worth reporting.
warnings.simplefilter("ignore", ResourceWarning)

_TMP = Path(tempfile.mkdtemp(prefix="argus-tests-"))
os.environ["XDG_DATA_HOME"] = str(_TMP / "data")
os.environ["XDG_CONFIG_HOME"] = str(_TMP / "conf")
os.environ.setdefault("ARGUS_GRANT_SHELL", "1")
os.environ.setdefault("ARGUS_GRANT_SCREEN", "1")
os.environ.setdefault("ARGUS_GRANT_INPUT", "0")
os.environ.setdefault("ARGUS_GRANT_NET", "0")

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

TMP = _TMP


def make_workspace(name="ws"):
    """An empty workspace directory (created once per name, reused after)."""
    ws = _TMP / name
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def kwin_capabilities():
    """A static capabilities() report, so the runtime's probe of the real
    desktop is not part of a unit test."""
    return {"screenshots": True, "window_inventory": True, "window_control": True,
            "keyboard": False, "pointer": False,
            "keyboard_detail": "test: no ydotool", "pointer_detail": "test: no uinput"}


def sandbox_stub(result=None):
    """A stand-in for sandbox.run() that never executes anything."""
    payload = result or {"ok": True, "code": 0, "stdout": "", "stderr": "",
                         "sandboxed": True}

    def run(command, workspace, **kwargs):
        return dict(payload, command=command)

    return run


def call(cid, name, args):
    """One OpenAI-shaped tool call."""
    import json as _json
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": _json.dumps(args)}}


def declared_and_answered(db, session):
    """Every tool_call id the journal declares, and every id it answers.

    An assistant message declaring N calls must be followed by N results — both
    OpenAI and Anthropic reject a turn with an unanswered tool_call_id, and the
    resumed request is rebuilt from the journal.
    """
    import json as _json
    declared, answered = [], []
    for kind, payload in db.execute("SELECT kind,payload FROM events WHERE session=? "
        "ORDER BY id",
                                    (session,)):
        body = _json.loads(payload)
        if kind == "assistant":
            declared += [c["id"] for c in (body.get("tool_calls") or [])]
        elif kind == "tool":
            answered.append(body.get("id"))
    return declared, answered
