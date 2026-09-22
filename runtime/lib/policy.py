"""Policy engine: decides auto / prompt / deny for every tool call.

Replaces the old binary commit-tier gate. Coding work needs hundreds of
in-workspace reads and edits to flow without prompting, while anything that
leaves the workspace, touches the network, or can damage the system still
stops for a human. Decisions are:

  auto   — run it, journal it
  prompt — raise an approval in the Agent Panel (with a diff preview for writes)
  deny   — refuse outright, no approval offered

Approval memory lives in ~/.config/argus/policy.json so "always allow
`ruff format`" is a one-time decision, not a per-call interruption.
"""
import fnmatch
import json
import os
import re
from pathlib import Path

CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "argus"
POLICY_FILE = CONF / "policy.json"

# Commands that are never offered for approval — the agent must not be able to
# talk a user into these, and they are not needed for software work.
HARD_DENY = [
    r"\bsudo\b", r"\bsu\b", r"\bdoas\b",
    r"\brm\s+-rf?\s+/(\s|$)", r"\bmkfs\b", r"\bdd\b.*of=/dev/",
    r"\bshutdown\b", r"\breboot\b", r"\bpoweroff\b", r"\bhalt\b",
    r"\bsystemctl\b", r"\bjournalctl\b",
    r"\bpacman\b", r"\bapt\b", r"\bdnf\b", r"\byay\b", r"\bparu\b",
    r"\bchmod\s+777\s+/", r"\bchown\b.*\s/(\s|$)",
    r":\(\)\s*\{", r"\bmkfs\.", r"\bwipefs\b", r"\bfdisk\b", r"\bparted\b",
    r"\bmodprobe\b", r"\binsmod\b", r"\bsysctl\b",
    r">\s*/dev/sd", r"\bkillall5\b", r"\bkill\s+-9\s+-1\b",
]

# Read-only commands that may run unattended inside the workspace.
# Redirection is permitted because the sandbox confines writes to the
# workspace; command substitution and backticks are not, because they are the
# arbitrary-execution path.
# The trailing character class excludes newlines as well as the other chaining
# and substitution characters: a negated class matches a newline, and `$`
# matches at the end of the whole string, so `cat a.py\nrm -rf /tmp/x` used to
# satisfy this pattern in one piece and auto-approve the second line on the
# strength of the first one's safety (verified: segments_safe() returned True
# and classify() said "auto: exec within $SAFE", while the `&&` spelling of the
# same chain correctly prompted). Newlines are chaining, not whitespace.
SAFE_SHELL = re.compile(
    r"^\s*(ls|cat|echo|printf|stat|file|df|du|free|uname|uptime|whoami|id|date|"
    r"wc|head|tail|nl|sort|uniq|cut|tr|find|fd|rg|grep|which|type|env|pwd|pgrep|ps|"
    r"true|false|test|cd|git\s+(status|diff|log|show|branch|remote|describe)|"
    r"python3?\s+--version|node\s+--version|npm\s+--version)\b[^&|`$(){}\n\r]*$"
)

# Build/test/format commands that are safe to auto-run in a sandboxed,
# workspace-scoped context (they only write inside the workspace).
#
# The scaffolding commands (git/npm/cargo/uv/venv/go mod init) are here for
# the same reason as the rest of this list: none of them touch the network
# or write outside the workspace — `cargo init`/`uv init`/`npm init -y`/
# `go mod init` just template a manifest file locally, `python3 -m venv`
# only creates a local virtualenv directory. Without these, starting a new
# project from scratch meant a prompt for every single bootstrap step before
# any real work could begin.
SAFE_BUILD = re.compile(
    r"^\s*(pytest|python3?\s+-m\s+(pytest|unittest|py_compile|ruff|black|venv)|"
    r"ruff\s+(check|format)|black|prettier|eslint|tsc|"
    r"cargo\s+(test|build|check|clippy|fmt|init|new)|rustfmt|"
    r"npm\s+(test|run\s+\w+|ci|init\s+-y)|node\s+--check|"
    r"qmllint|qmlformat|shellcheck|shfmt|bash\s+-n|"
    r"make(\s+\w+)?|cmake\s+--build|gcc|g\+\+|clang|clang-format|"
    r"git\s+init|uv\s+init|go\s+mod\s+init)\b[^&|`$(){}\n\r]*$"
)

# A command may chain safe commands with these separators. Each segment is
# validated independently, so `ls && rm -rf /` still fails (the second segment
# is not safe) while `py_compile x.py && unittest discover` passes. Newlines
# (and CRLF) are separators too — a shell reads them as end-of-command exactly
# like `;`, so leaving them out of this list was a hole in "each segment is
# validated independently", not a whitespace nicety.
SEPARATORS = re.compile(r"\s*(?:&&|\|\||;|\||\n|\r)\s*")

# File-descriptor duplication (`2>&1`, `1>&2`) is not command chaining and is
# extremely common in test invocations — strip it before matching so it does
# not look like an unsafe `&`.
FD_DUP = re.compile(r"\d*>&\d+")

# Leading environment-variable assignments (FOO=bar python3 ...) are a plain,
# ubiquitous way to run a program against a temp data file. The command itself
# must still independently pass $SAFE — only assignment prefixes are stripped,
# and only when each value is metacharacter-free: a value containing $, a
# backtick, a quote or any chaining separator could smuggle command
# substitution or chaining into what looks like a bare word (FOO=$(cmd),
# FOO="a; rm -rf /" would be exactly the newline-chaining hole this file
# already documented once).
ENV_ASSIGN = re.compile(
    r"\s*[A-Za-z_][A-Za-z0-9_]*=[^\s`$;&|<>\"']+")


def _strip_env_prefix(segment):
    while True:
        stripped = ENV_ASSIGN.sub("", segment, count=1).lstrip()
        if stripped == segment:
            return segment
        segment = stripped


def segments_safe(command):
    parts = [p for p in SEPARATORS.split(command) if p.strip()]
    if not parts:
        return False
    return all(SAFE_SHELL.match(_strip_env_prefix(FD_DUP.sub("", p))) or
               SAFE_BUILD.match(_strip_env_prefix(FD_DUP.sub("", p)))
               for p in parts)

DEFAULTS = {
    # $HOME/** alongside $WORKSPACE/**: the file tools reach anywhere under
    # the user's home directory now (see workspace.py's resolve(), the real
    # enforcement point this mirrors), so the auto-approve set has to cover
    # that too or every file outside the one declared workspace would newly
    # start prompting instead of being refused outright — the opposite of
    # what was asked for.
    "fs.read":  {"auto": ["$WORKSPACE/**", "$HOME/**"], "prompt": ["**"]},
    "fs.write": {"auto": ["$WORKSPACE/**", "$HOME/**"], "prompt": ["**"]},
    "exec":     {"auto": ["$SAFE"], "prompt": ["**"], "deny": HARD_DENY},
    "net":      {"auto": [], "prompt": ["**"]},
    # Computer use follows the risk tiers in docs/03: the capability grant is
    # the user's consent, so reads and soft actions flow while it is on, and
    # commit-tier actions (typing, key chords, closing windows) always surface.
    "screen":   {"auto": ["**"], "prompt": []},
    "input":    {"auto": ["**"], "prompt": []},
    "apps":     {"auto": ["**"], "prompt": []},
    # MCP tools are opaque, user-added third-party code — same posture as
    # "net": always prompt until the user explicitly saves an allow rule
    # for that exact server.tool subject (see lib/tools.py's
    # _register_mcp_tools, which derives the subject the model's tool call
    # is judged against).
    "mcp":      {"auto": [], "prompt": ["**"]},
    # Tools that name no filesystem path and no command — the plan (todo_write)
    # and the undo log (checkpoint_list) — are not workspace paths and must not
    # be judged as if they were. They used to be granted fs.read, which only
    # worked because an empty subject was (wrongly) treated as "inside the
    # workspace"; see classify()'s fail-closed branch.
    "internal": {"auto": ["**"], "prompt": []},
}


class Policy:
    def __init__(self, workspace=None):
        self.workspace = str(workspace) if workspace else None
        self.memory = {"allow": [], "deny": []}
        self.load()

    # ── persistence ──────────────────────────────────────────────────────
    def load(self):
        try:
            doc = json.loads(POLICY_FILE.read_text())
            self.memory["allow"] = list(doc.get("allow", []))
            self.memory["deny"] = list(doc.get("deny", []))
        except Exception:
            pass

    def save(self):
        CONF.mkdir(parents=True, exist_ok=True)
        POLICY_FILE.write_text(json.dumps(self.memory, indent=2))
        try:
            POLICY_FILE.chmod(0o600)
        except OSError:
            pass

    def remember(self, pattern, allow=True):
        key = "allow" if allow else "deny"
        if pattern not in self.memory[key]:
            self.memory[key].append(pattern)
            self.save()

    # ── classification ───────────────────────────────────────────────────
    def _within_workspace(self, value):
        p = Path(value)
        if not p.is_absolute():
            p = Path(self.workspace) / p
        try:
            return p.resolve().is_relative_to(Path(self.workspace).resolve())
        except Exception:
            return False

    def _within_home(self, value):
        p = Path(value)
        if not p.is_absolute():
            # A relative path is always relative to the workspace (there is
            # no other base to resolve it against here) — if there is no
            # workspace configured, it cannot be resolved at all.
            if not self.workspace:
                return False
            p = Path(self.workspace) / p
        try:
            return p.resolve().is_relative_to(Path.home())
        except Exception:
            return False

    def _matches(self, pattern, value):
        if pattern == "$SAFE":
            return segments_safe(value)
        if pattern.startswith("$WORKSPACE"):
            # Only ever reached for fs.read/fs.write, and paths there are
            # backstopped by Workspace.resolve()'s own unconditional
            # containment check (see workspace.py) — this can't itself be
            # the difference between an escape being allowed or refused.
            # It used to return True for any `value` once a workspace was
            # configured at all (never actually testing containment), which
            # made the "outside the workspace prompts" half of
            # DEFAULTS["fs.write"]/["fs.read"] unreachable. Fixed for
            # correctness — harmless before, but silently wrong.
            if not self.workspace or not self._within_workspace(value):
                return False
            suffix = pattern[len("$WORKSPACE"):].lstrip("/")
            if not suffix or suffix == "**":
                return True
            return fnmatch.fnmatch(value, suffix)
        if pattern.startswith("$HOME"):
            # Same backstop reasoning as $WORKSPACE above — the real
            # enforcement is workspace.py's resolve(), this just decides
            # auto vs. prompt for whatever it already let through.
            if not self._within_home(value):
                return False
            suffix = pattern[len("$HOME"):].lstrip("/")
            if not suffix or suffix == "**":
                return True
            return fnmatch.fnmatch(value, suffix)
        return fnmatch.fnmatch(value, pattern)

    def classify(self, grant, *, path=None, command=None, tool=None, risk=None):
        """Return (decision, reason). `grant` is the capability class.

        A path-scoped grant with no subject at all fails closed rather than
        falling through to a pattern match it cannot mean anything for. The
        registry declares which argument(s) hold a path (`subject=` in
        tools.py), so a tool that names its arguments something other than
        `path` — move_file's src/dst, checkpoint_restore's id — no longer
        arrives here with an empty subject and gets auto-approved by
        `$WORKSPACE/**` matching "" (verified: that was the actual behavior,
        which made "outside the workspace prompts" unreachable for those two
        tools). Tools with genuinely no path use the `internal` grant.
        """
        subject = command if command is not None else (path or "")
        if command is None and not str(subject).strip() and grant in ("fs.read", "fs.write"):
            return ("prompt", f"{grant} call supplied no path to check — "
                              "an unchecked subject is never auto-approved")
        # explicit memory wins
        for pat in self.memory["deny"]:
            if self._matches(pat, subject):
                return ("deny", f"denied by saved rule: {pat}")
        for pat in self.memory["allow"]:
            if self._matches(pat, subject):
                return ("auto", f"allowed by saved rule: {pat}")

        rules = DEFAULTS.get(grant, {})
        for pat in rules.get("deny", []):
            if re.search(pat, subject):
                return ("deny", f"refused: matches hard-deny rule {pat}")
        # commit-tier actions are irreversible or externally visible: they
        # always surface unless the user saved a rule for them above.
        if risk == "commit":
            return ("prompt", f"{grant} commit-tier action requires approval")
        for pat in rules.get("auto", []):
            if self._matches(pat, subject):
                return ("auto", f"auto: {grant} within {pat}")
        for pat in rules.get("prompt", []):
            if self._matches(pat, subject):
                return ("prompt", f"{grant} outside the auto-approved scope")
        return ("prompt", f"{grant} requires approval")

    def describe(self):
        return {"workspace": self.workspace, "allow": self.memory["allow"],
                "deny": self.memory["deny"], "file": str(POLICY_FILE)}
