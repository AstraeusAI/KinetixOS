"""Tool registry: tools as data, so policy/checkpoint/verify are inherited.

Each tool declares its schema (handed to the model), the capability grant it
needs, its risk tier, and whether it mutates files. The loop then applies the
same policy → checkpoint → execute → verify → journal pipeline to every tool
instead of each handler re-implementing safety (which is how the old
`risky()` precedence bug happened).

Handlers receive a `ctx` with the workspace, policy, checkpoints and grants.
"""

import difflib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from . import kwin, lsp, mcp, sandbox
from .workspace import IGNORE_DIRS, _qt6_qml_tool

REGISTRY: dict[str, dict] = {}


def tool(
    name,
    description,
    parameters,
    *,
    grant,
    risk="read",
    mutates=False,
    verify=None,
    needs_grant=None,
    sandboxed=False,
    spawn_arg=None,
    subject=None,
    undo=None,
):
    """Register one tool.

    `subject` tells the policy layer which argument(s) carry the thing being
    judged: a tuple of argument names, or a callable `(ctx, args) -> list` when
    the subject has to be looked up. Without it a tool whose schema names its
    paths something else (move_file's src/dst) is classified with no subject at
    all — which policy.py now fails closed on rather than treating as inside
    the workspace.

    Left unset, the subject is derived from the schema: a tool judges a path
    only if it actually has a `path` argument, so the ~30 computer-use tools
    that take no filesystem path no longer advertise a subject they don't have.
    An explicitly declared tuple is checked against the schema at import time.
    That check exists because the alternative is silent: assert_region_changed
    declared the default `("path",)` while its path argument is `before_path`,
    so it was classified with an *empty* subject, the empty-subject fail-closed
    branch in policy.py only covers fs.read/fs.write, and the `screen` grant's
    `**` auto rule matched "" — a caller-supplied absolute path went straight
    into ImageMagick with no prompt and no workspace check. A misdeclaration
    that produces a weaker verdict than intended is exactly the kind of bug a
    silent default invites, so it is now a loud import-time error.

    `verify` names which post-write checks the loop runs on the file the call
    touched, and it is the *only* thing that decides that — it used to be
    declared on three tools and read by nobody, while the loop independently
    hardcoded "syntax, then lint if available" for anything flagged
    `mutates`. A declared-but-unread field is the same failure mode as the
    `sandboxed` flag below, and it had already produced one real divergence:
    delete_file wrote to disk and snapshot undo state without declaring
    `mutates`, so it was outside the pipeline entirely, while
    checkpoint_restore declared `mutates` and pointed at a `path` argument it
    does not have. Left unset, a mutating tool defaults to `("syntax", "lint")`
    — the behaviour the hardcoded version had — and passing `verify=()` is the
    explicit, visible way to say "this mutation has nothing to check", which is
    what delete_file (the file is gone) and move_file (its arguments are src
    and dst, not path) mean.

    `undo` declares that the call is undoable, which the loop enforces: a tool
    that claims it and returns no checkpoint id is logged as
    `undo_not_checkpointed`. It defaults to `mutates`, and declaring it on a
    non-mutating tool is an import-time error, because "I mutate the world
    but not the files" and "I snapshot undo state but declare nothing" are
    both ways for the declaration to stop describing the handler.

    The checkpoint itself stays in the handler rather than moving into the
    loop, deliberately. Saving before the call would burn a snapshot for every
    *failed* edit — edit_file rejects a non-unique needle, a stale old_string
    and a no-op replacement before it ever writes, and a loop-driven save
    would record all of those as restorable states — whereas the handler knows
    the write is genuinely about to happen. The declaration is what makes that
    per-handler call auditable instead of a convention.

    `sandboxed=True` is a claim the loop relies on: loop.py auto-approves an
    `exec`-grant tool that takes no free-text command on the strength of being
    "a fixed, sandboxed, workspace-scoped action". Set it only when the handler
    actually confines execution through sandbox.run. It used to be declared but
    never read, so syntax_check / format_file / lint all confined their
    subprocesses and still said False while the downgrade applied to them
    anyway, on the strength of a claim nobody checked. verify_ui was the one
    tool where the claim was genuinely false — it starts a `--no-sandbox`
    Chromium with working network and no approval — and it is now the one that
    prompts.

    `spawn_arg` names the argument that carries free-text process input, which
    is only sometimes present in a given call. When it is supplied the call is
    never auto-approved, whatever the grant: the grant answers "may this agent
    use the mouse" and says nothing about "may this agent run this string".
    It is an argument name rather than a flag because the same tool has a
    bounded path and an unbounded one — focus_or_launch resolves an app name
    against the installed .desktop table (routine, unattended) but also
    accepts a literal `command` it shlex.splits into an unsandboxed Popen (not
    routine). A blanket flag would have prompted on every app launch; a blanket
    omission would have left `sudo rm -rf /` auto-approved through it.
    """

    def deco(fn):
        props = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
        declared = subject
        if declared is None:
            declared = ("path",) if "path" in props else None
        elif not callable(declared):
            names = declared if isinstance(declared, (list, tuple)) else (declared,)
            missing = [n for n in names if n not in props]
            if missing:
                raise ValueError(
                    f"tool {name!r} declares subject {list(names)!r} but its schema "
                    f"has no such argument (properties: {sorted(props)}). Either "
                    f"name the argument that carries the subject or pass "
                    f"subject=callable when it has to be looked up."
                )
        # Resolve both defaults here rather than in the loop, so the registry
        # entry is the single place the answer lives: after this, `verify` and
        # `undo` are concrete values and no consumer has to re-derive a default
        # from `mutates` and hope it matches this one.
        if verify is not None:
            kinds = tuple(verify)
        else:
            kinds = ("syntax", "lint") if mutates else ()
        unknown = [k for k in kinds if k not in ("syntax", "lint")]
        if unknown:
            raise ValueError(
                f"tool {name!r} declares unknown verify kind(s) {unknown!r}; "
                f"loop.verify() implements ('syntax', 'lint')."
            )
        wants_undo = mutates if undo is None else bool(undo)
        if wants_undo and not mutates:
            raise ValueError(
                f"tool {name!r} declares undo=True but mutates=False. Undo is "
                f"about snapshotting a file the call changes, so it cannot hold "
                f"for a call that declares it changes nothing — pick one."
            )
        REGISTRY[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "grant": grant,
            "risk": risk,
            "mutates": mutates,
            "verify": list(kinds),
            "undo": wants_undo,
            "needs_grant": needs_grant,
            "sandboxed": sandboxed,
            "spawn_arg": spawn_arg,
            "subject": declared,
            "handler": fn,
        }
        return fn

    return deco


def schemas():
    """Tool list in OpenAI function-calling shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["parameters"],
            },
        }
        for s in REGISTRY.values()
    ]


def _diff(old, new, path):
    d = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile="a/" + path,
            tofile="b/" + path,
            lineterm="",
        )
    )
    return "\n".join(d[:400])


_TEST_PATH = re.compile(
    r"(^|[/_.~-])tests?([/_.~-]|$)|(^|[/_.-])test_.*\.py$|.*_test\.py$"
)


def _test_counts(text):
    """(test-function count, assert count) — the two numbers whose *decrease*
    between writes signals test-weakening (see _record_test_baseline)."""
    tests = len(re.findall(r"(?m)^\s*(?:async\s+)?def\s+test_", text))
    asserts = len(re.findall(r"(?<![\w.])assert\b", text))
    return (tests, asserts)


def _record_test_baseline(ctx, path):
    """Remember the first-written shape of every test file in this task.

    Called after every successful write/edit of a test-like path; only the
    FIRST write per path is recorded, so the baseline is what the agent
    itself originally asserted — verify_deliverable then flags any later
    write that reduces test or assert counts (the SWE-bench anti-cheat:
    a failing test must be fixed by changing the implementation, never by
    weakening the test). Counts, not hashes: adding tests is always fine,
    only shrinking is suspect.
    """
    try:
        rel = ctx.workspace.rel(path)
    except Exception:
        return
    if not _TEST_PATH.search(rel.replace(os.sep, "/")):
        return
    base = getattr(ctx, "test_baseline", None)
    if base is None:
        ctx.test_baseline = base = {}
    if rel in base:
        return
    try:
        base[rel] = _test_counts(path.read_text(errors="replace"))
    except Exception:
        pass


def _read_text(p):
    try:
        return p.read_text(errors="replace")
    except Exception:
        return ""


def _atomic_write(path, content):
    """Write via a temp file + os.replace instead of a direct write_text, so
    a crash or power loss mid-write can never leave a truncated file where
    the original was: the replace is a single atomic rename, so the file on
    disk is always either the old content or the fully-written new content,
    never a partial mix of both."""
    tmp = path.with_name(
        f"{path.name}.argus-tmp-{os.getpid()}-{int(time.time() * 1000)}"
    )
    try:
        tmp.write_text(content)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ── filesystem: read ─────────────────────────────────────────────────────


@tool(
    "read_file",
    "Read a file with line numbers. Use offset/limit for large files.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "1-based first line"},
            "limit": {"type": "integer", "description": "max lines (default 400)"},
        },
        "required": ["path"],
    },
    grant="fs.read",
)
def read_file(ctx, args):
    p = ctx.workspace.resolve(args["path"], must_exist=True)
    if p.is_dir():
        return {"ok": False, "error": "is a directory — use list_dir"}
    lines = _read_text(p).splitlines()
    off = max(1, int(args.get("offset", 1)))
    lim = min(int(args.get("limit", 400)), 2000)
    chunk = lines[off - 1 : off - 1 + lim]
    body = "\n".join(f"{off + i:>5}\t{line}" for i, line in enumerate(chunk))
    truncated = len(lines) > off - 1 + lim
    return {
        "ok": True,
        "path": ctx.workspace.rel(p),
        "lines": len(lines),
        "shown": f"{off}-{off + len(chunk) - 1}",
        "truncated": truncated,
        "content": body[:60000]
        + ("\n… (truncated; use offset to continue)" if truncated else ""),
    }


def _workspace_relative_subject(*names):
    """Subject resolver for tools whose path argument is optional and defaults
    to the workspace root (glob/grep/list_dir). The policy has to be given the
    root explicitly rather than no subject at all, because "no subject supplied"
    now means "refuse to auto-approve" for the path-scoped grants."""

    def resolve(ctx, args):
        for n in names:
            if args.get(n):
                return [args[n]]
        return ["."]

    return resolve


@tool(
    "list_dir",
    "List a directory tree (skips .git/node_modules/build dirs).",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}, "depth": {"type": "integer"}},
        "required": [],
    },
    grant="fs.read",
    subject=_workspace_relative_subject("path"),
)
def list_dir(ctx, args):
    base = ctx.workspace.resolve(args.get("path", "."))
    depth = min(int(args.get("depth", 2)), 5)
    out = []
    root_len = len(str(base))
    cap = 600
    truncated = False
    for dirpath, dirnames, filenames in os.walk(base):
        rel = dirpath[root_len:].count(os.sep)
        if rel >= depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for f in sorted(filenames)[:200]:
            if len(out) >= cap:
                truncated = True
                break
            out.append(str(Path(dirpath, f))[root_len + 1 :])
        if truncated:
            break
    return {
        "ok": True,
        "path": ctx.workspace.rel(base),
        "count": len(out),
        "truncated": truncated,
        "entries": out,
    }


@tool(
    "glob",
    "Find files by glob pattern (e.g. '**/*.py').",
    {
        "type": "object",
        "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
        "required": ["pattern"],
    },
    grant="fs.read",
    subject=_workspace_relative_subject("path"),
)
def glob_files(ctx, args):
    base = ctx.workspace.resolve(args.get("path", "."))
    pat = args["pattern"]
    if shutil.which("fd"):
        # fd's --glob matches basenames unless --full-path is given, so a
        # pattern containing a separator (e.g. '**/*.qml') needs it.
        cmd = ["fd", "--type", "f", "--hidden", "--exclude", ".git"]
        if "/" in pat:
            cmd += ["--full-path"]
        cmd += ["--glob", pat, str(base)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        # fd exits 1 for "no matches" (fine) as well as a genuinely bad
        # invocation; only stderr output distinguishes them, so surface it
        # instead of reporting an empty match list either way.
        if r.returncode not in (0, 1) or (r.returncode == 1 and r.stderr.strip()):
            return {"ok": False, "error": (r.stderr or "fd failed").strip()[:400]}
        files = [line for line in r.stdout.splitlines() if line.strip()]
    else:
        files = [str(p) for p in ctx.workspace.walk(base) if Path(p).match(pat)]
    # Count reflects what's actually returned, not the pre-truncation total —
    # matching read_file's truncation flag rather than silently capping the
    # count itself, which previously made "count": 400 look like the whole
    # answer even when there were far more matches.
    cap = 400
    rel = [ctx.workspace.rel(f) for f in files[:cap]]
    return {"ok": True, "count": len(rel), "truncated": len(files) > cap, "files": rel}


@tool(
    "grep",
    "Search file contents with ripgrep. Returns matches with line numbers.",
    {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "glob": {"type": "string", "description": "e.g. '*.py'"},
            "context": {"type": "integer"},
            "max_results": {"type": "integer"},
        },
        "required": ["pattern"],
    },
    grant="fs.read",
    subject=_workspace_relative_subject("path"),
)
def grep(ctx, args):
    base = ctx.workspace.resolve(args.get("path", "."))
    cmd = ["rg", "--json", "-n", "--max-count", "200"]
    if args.get("glob"):
        cmd += ["--glob", args["glob"]]
    if args.get("context"):
        cmd += ["-C", str(min(int(args["context"]), 6))]
    cmd += ["--", args["pattern"], str(base)]
    if not shutil.which("rg"):
        return {"ok": False, "error": "ripgrep not installed"}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    # rg exits 1 for "no matches" (a normal, successful search) and 2 for a
    # real problem (bad regex, unreadable path, ...) — previously neither
    # returncode nor stderr was checked, so an invalid pattern silently came
    # back as "count: 0, matches: []", indistinguishable from a clean search
    # that just found nothing.
    if r.returncode == 2:
        return {"ok": False, "error": (r.stderr or "ripgrep failed").strip()[:400]}
    hits, limit = [], min(int(args.get("max_results", 60)), 200)
    truncated = False
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") != "match":
            continue
        if len(hits) >= limit:
            truncated = True
            break
        d = ev["data"]
        hits.append(
            {
                "file": ctx.workspace.rel(d["path"]["text"]),
                "line": d["line_number"],
                "text": (d["lines"]["text"] or "").rstrip()[:300],
            }
        )
    return {"ok": True, "count": len(hits), "truncated": truncated, "matches": hits}


@tool(
    "file_info",
    "Size, line count, language and available tooling for a file.",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    grant="fs.read",
)
def file_info(ctx, args):
    p = ctx.workspace.resolve(args["path"], must_exist=True)
    st = p.stat()
    return {
        "ok": True,
        "path": ctx.workspace.rel(p),
        "bytes": st.st_size,
        "lines": len(_read_text(p).splitlines()) if p.is_file() else 0,
        "language": ctx.workspace.language(p),
        "tooling": ctx.workspace.tooling(p),
    }


# ── filesystem: write ────────────────────────────────────────────────────


@tool(
    "write_file",
    "Create or overwrite a file. Returns a diff of the change.",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
    grant="fs.write",
    risk="soft",
    mutates=True,
)
def write_file(ctx, args):
    p = ctx.workspace.resolve(args["path"])
    existed = p.exists()
    old = _read_text(p) if existed else ""
    new = args["content"]
    cid = ctx.checkpoints.save(p, ctx.workspace.root, "write_file")
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, new)
    _record_test_baseline(ctx, p)
    return {
        "ok": True,
        "path": ctx.workspace.rel(p),
        "created": not existed,
        "checkpoint": cid,
        "diff": _diff(old, new, ctx.workspace.rel(p))[:8000],
    }


@tool(
    "edit_file",
    "Replace an exact string in a file. old_string must be unique "
    "unless replace_all is set. Preferred over write_file for edits.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        "required": ["path", "old_string", "new_string"],
    },
    grant="fs.write",
    risk="soft",
    mutates=True,
)
def edit_file(ctx, args):
    p = ctx.workspace.resolve(args["path"], must_exist=True)
    old = _read_text(p)
    needle, repl = args["old_string"], args["new_string"]
    # An empty needle isn't "not found" — .count("") matches between every
    # character, so it used to fall into "old_string appears {N} times" with
    # a large, confusing N instead of the real problem. A no-op edit (needle
    # == repl) would otherwise "succeed" while changing nothing, still
    # burning a checkpoint and a verify pass on a file that never moved.
    if not needle:
        return {"ok": False, "error": "old_string cannot be empty"}
    if needle == repl:
        return {
            "ok": False,
            "error": "old_string and new_string are identical — nothing to change",
        }
    n = old.count(needle)
    if n == 0:
        return {
            "ok": False,
            "error": "old_string not found — read the file and match exactly",
        }
    if n > 1 and not args.get("replace_all"):
        return {
            "ok": False,
            "error": f"old_string appears {n} times; add surrounding context or set "
            f"replace_all",
        }
    new = (
        old.replace(needle, repl)
        if args.get("replace_all")
        else old.replace(needle, repl, 1)
    )
    cid = ctx.checkpoints.save(p, ctx.workspace.root, "edit_file")
    _atomic_write(p, new)
    _record_test_baseline(ctx, p)
    return {
        "ok": True,
        "path": ctx.workspace.rel(p),
        "replacements": n if args.get("replace_all") else 1,
        "checkpoint": cid,
        "diff": _diff(old, new, ctx.workspace.rel(p))[:8000],
    }


@tool(
    "multi_edit",
    "Apply several exact-string edits to one file, all or nothing.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                    },
                    "required": ["old_string", "new_string"],
                },
            },
        },
        "required": ["path", "edits"],
    },
    grant="fs.write",
    risk="soft",
    mutates=True,
)
def multi_edit(ctx, args):
    edits = args.get("edits")
    # Models occasionally send `edits` as a JSON string instead of an array
    # (observed live: tool_crashed `'str' object has no attribute 'get'` on a
    # compare-run strict-01 trial). Coerce the string form and reject any
    # other shape with a plain tool error — the handler must never crash.
    if isinstance(edits, str):
        try:
            edits = json.loads(edits)
        except Exception:
            return {
                "ok": False,
                "error": "edits must be a JSON array of "
                "{old_string, new_string} objects (got an unparseable string)",
            }
    if not isinstance(edits, list):
        return {
            "ok": False,
            "error": "edits must be an array of {old_string, new_string} objects",
        }
    p = ctx.workspace.resolve(args["path"], must_exist=True)
    old = _read_text(p)
    cur = old
    for i, e in enumerate(edits):
        if not isinstance(e, dict):
            return {
                "ok": False,
                "error": f"edit {i}: expected an object with old_string/"
                f"new_string, got {type(e).__name__}",
            }
        needle = e.get("old_string", "")
        repl = e.get("new_string", "")
        if not needle:
            return {"ok": False, "error": f"edit {i}: old_string cannot be empty"}
        if needle == repl:
            return {
                "ok": False,
                "error": f"edit {i}: old_string and new_string are identical — nothing "
                f"to change",
            }
        if cur.count(needle) != 1:
            return {
                "ok": False,
                "error": f"edit {i}: old_string matched {cur.count(needle)} times",
            }
        cur = cur.replace(needle, repl, 1)
    cid = ctx.checkpoints.save(p, ctx.workspace.root, "multi_edit")
    _atomic_write(p, cur)
    _record_test_baseline(ctx, p)
    return {
        "ok": True,
        "path": ctx.workspace.rel(p),
        "edits": len(edits),
        "checkpoint": cid,
        "diff": _diff(old, cur, ctx.workspace.rel(p))[:8000],
    }


@tool(
    "make_dir",
    "Create a directory (and any missing parent directories).",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    # mutates=False: nothing to syntax-check about an empty directory — see
    # delete_file's comment for why this matters given the "path" key.
    grant="fs.write",
    risk="soft",
    mutates=False,
)
def make_dir(ctx, args):
    p = ctx.workspace.resolve(args["path"])
    if p.exists() and not p.is_dir():
        return {"ok": False, "error": "path exists and is not a directory"}
    existed = p.is_dir()
    p.mkdir(parents=True, exist_ok=True)
    # Not checkpointed: Checkpoints.save()/restore() are file-shaped (they
    # snapshot content and, for a path that "didn't exist", restore by
    # unlink()ing it) — calling unlink() on a directory raises, so treating
    # this like write_file would make checkpoint_restore crash rather than
    # undo. An empty directory holds nothing to lose; remove it directly
    # (or via run_command) if it turns out to be unwanted.
    return {"ok": True, "path": ctx.workspace.rel(p), "created": not existed}


@tool(
    "move_file",
    "Move or rename a file within the workspace (checkpointed — both the "
    "source and destination are recorded, so checkpoint_restore fully undoes the "
    "move).",
    {
        "type": "object",
        "properties": {"src": {"type": "string"}, "dst": {"type": "string"}},
        "required": ["src", "dst"],
    },
    grant="fs.write",
    risk="soft",
    mutates=True,
    # No syntax target: this tool's schema has src/dst and no `path`, and a
    # renamed file is not a file the loop could check. Declared explicitly so
    # the absence is a decision on the tool rather than a side effect of the
    # loop's old `args.get("path")` test silently finding nothing here.
    verify=(),
    subject=("src", "dst"),
)
def move_file(ctx, args):
    src = ctx.workspace.resolve(args["src"], must_exist=True)
    dst = ctx.workspace.resolve(args["dst"])
    if src.is_dir():
        return {
            "ok": False,
            "error": "src is a directory — move files individually, or use "
            "run_command for directory moves (will prompt for approval)",
        }
    if dst.is_dir():
        dst = dst / src.name
    overwrote = dst.exists()
    # Two ordinary file checkpoints, not a special "move" checkpoint type:
    # save() on the source (which exists) backs up its content so restoring
    # recreates it there; save() on the destination (which usually doesn't
    # exist yet) records that absence so restoring removes whatever the move
    # placed there. Restoring both, in either order, is a complete undo —
    # reusing the existing single-file checkpoint semantics rather than
    # teaching Checkpoints a second, move-specific representation.
    cid_src = ctx.checkpoints.save(src, ctx.workspace.root, "move_file:src")
    cid_dst = ctx.checkpoints.save(dst, ctx.workspace.root, "move_file:dst")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {
        "ok": True,
        "src": ctx.workspace.rel(src),
        "dst": ctx.workspace.rel(dst),
        "overwrote": overwrote,
        "checkpoints": [cid_src, cid_dst],
    }


@tool(
    "delete_file",
    "Delete a single file within the workspace (checkpointed — "
    "checkpoint_restore brings it back).",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    # `mutates` is the declaration that this call changes the world, and this
    # one deletes a file — it used to say mutates=False, which kept it out of
    # the pipeline entirely and therefore out of undo accounting too, even
    # though the handler had been snapshotting the file all along. The old
    # reason for False was the automatic post-write verify pass, which is now
    # the separate `verify` field: a file that no longer exists has no syntax
    # to check, so that is what is switched off here, not the mutation.
    grant="fs.write",
    risk="soft",
    mutates=True,
    verify=(),
)
def delete_file(ctx, args):
    p = ctx.workspace.resolve(args["path"], must_exist=True)
    if p.is_dir():
        # Scoped to single files on purpose: the checkpoint mechanism backs
        # up one file's content, not a whole subtree, so a directory delete
        # here couldn't be made reversible the same way. run_command's `rm`
        # covers it and still goes through approval.
        return {
            "ok": False,
            "error": "is a directory — delete files individually, or use "
            "run_command for directory removal (will prompt for approval)",
        }
    cid = ctx.checkpoints.save(p, ctx.workspace.root, "delete_file")
    p.unlink()
    return {"ok": True, "path": ctx.workspace.rel(p), "checkpoint": cid}


# ── execution ────────────────────────────────────────────────────────────


@tool(
    "run_command",
    "Run a shell command inside the sandboxed workspace. "
    "The workspace is writable by default; pass write=false to run something "
    "read-only/inspection-only on purpose. Network is off unless net=true.",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer"},
            "write": {
                "type": "boolean",
                "description": "defaults to true (the workspace is "
                "writable); set false to deliberately run this one command read-only",
            },
            "net": {"type": "boolean", "description": "allow network access"},
        },
        "required": ["command"],
    },
    grant="exec",
    risk="soft",
    sandboxed=True,
    needs_grant="shell",
)
def run_command(ctx, args):
    net = bool(args.get("net"))
    if net and not ctx.grants.get("net", True):
        return {"ok": False, "error": "network grant disabled"}
    # Defaults to writable. This used to default to read-only, requiring the
    # model to remember write=true on every command that so much as touched
    # a file — including pure incidental side effects (a test run's own
    # __pycache__, a formatter's temp file) — and confirmed live to
    # misfire on the most mundane case imaginable: a plain `rm -rf
    # __pycache__` cleanup failed with a raw "Read-only file system" error
    # and nothing else. This gate never added real security of its own —
    # policy_decision() never even looks at `write`; a destructive command
    # still goes through the exact same $SAFE/approval gate either way (see
    # policy.py) — so it was pure friction with no matching safety benefit.
    # `write=false` still exists for a command deliberately run read-only.
    write = bool(args.get("write", True))
    r = sandbox.run(
        args["command"],
        ctx.workspace.root,
        write_workspace=write,
        net=net,
        timeout=min(int(args.get("timeout", 60)), 300),
    )
    if (
        not write
        and not r.get("ok")
        and "read-only file system" in (r.get("stderr") or "").lower()
    ):
        # Only reachable now when write=false was passed explicitly (the
        # default is writable) — so the note's job is just to say that
        # plainly, not to explain an easy-to-forget opt-in anymore.
        r["note"] = (
            "This command tried to modify the workspace, but write=false "
            "was set on this call, deliberately making it read-only. If the "
            "modification is intended, retry without write=false."
        )
    return r


@tool(
    "syntax_check",
    "Parse/compile a file without executing it (no bytecode written).",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    grant="exec",
    risk="read",
    needs_grant="shell",
    sandboxed=True,
)
def syntax_check(ctx, args):
    p = ctx.workspace.resolve(args["path"], must_exist=True)
    lang = ctx.workspace.language(p)
    # These commands are assembled as shell strings and run via `/bin/sh -c`
    # (see sandbox.run), so an unquoted path is both a correctness bug (a
    # space in the filename silently splits it into two arguments) and,
    # since a model could in principle be pointed at an attacker-chosen
    # filename, a shell-injection surface if that name contains metacharacters.
    rel = shlex.quote(ctx.workspace.rel(p))
    if lang == "python":
        cmd = (
            f'python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read(), '
            f'sys.argv[1])" {rel}'
        )
    elif lang in ("javascript", "typescript"):
        cmd = f"node --check {rel}"
    elif lang == "qml":
        # Not bare "qmllint": this host also has Qt5 installed, whose
        # same-named binary shadows Qt6's on PATH and can't parse
        # Quickshell-only syntax — see _qt6_qml_tool's docstring.
        cmd = f"{_qt6_qml_tool('qmllint')} -I /usr/lib/qt6/qml {rel}"
    elif lang == "shellscript":
        cmd = f"bash -n {rel}"
    elif lang in ("c", "cpp"):
        cc = "gcc" if lang == "c" else "g++"
        cmd = f"{cc} -fsyntax-only {rel}"
    elif lang == "rust":
        cmd = (
            f"rustc --edition 2021 --emit=metadata --crate-type=lib -o "
            f"/tmp/out.rmeta {rel}"
        )
    else:
        return {"ok": True, "skipped": f"no syntax checker for {lang}"}
    r = sandbox.run(cmd, ctx.workspace.root, write_workspace=True, timeout=60)
    r["language"] = lang
    if (
        lang == "qml"
        and not r.get("ok")
        and not (r.get("stdout") or "").strip()
        and not (r.get("stderr") or "").strip()
    ):
        # Backstop, not the primary fix (see _qt6_qml_tool): the real Qt6
        # qmllint reliably prints `file:line:col: message` text for an
        # actual problem, so a non-zero exit with *no* output at all is
        # never a real finding — it's the tool itself failing to run
        # (missing binary/import path/etc). Reporting that as a syntax
        # failure would make the agent doubt or revert valid QML.
        r["ok"] = True
        r["inconclusive"] = True
        r["note"] = (
            "qmllint exited non-zero with no diagnostic output — a known defect "
            "in this qmllint build, not evidence the file is invalid. Treat this "
            "check as inconclusive."
        )
    return r


@tool(
    "format_file",
    "Run the language's formatter on a file (checkpointed).",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    grant="exec",
    risk="soft",
    mutates=True,
    needs_grant="shell",
    sandboxed=True,
)
def format_file(ctx, args):
    p = ctx.workspace.resolve(args["path"], must_exist=True)
    spec = ctx.workspace.tooling(p)["commands"].get("format")
    if not spec:
        return {
            "ok": False,
            "error": "no formatter installed for " + ctx.workspace.language(p),
        }
    before = _read_text(p)
    cid = ctx.checkpoints.save(p, ctx.workspace.root, "format_file")
    rel = ctx.workspace.rel(p)
    r = sandbox.run(
        " ".join(spec) + " " + shlex.quote(rel),
        ctx.workspace.root,
        write_workspace=True,
        timeout=60,
    )
    after = _read_text(p)
    r["changed"] = before != after
    r["checkpoint"] = cid
    r["diff"] = _diff(before, after, rel)[:6000]
    return r


@tool(
    "lint",
    "Run the language's linter and return its findings.",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    grant="exec",
    risk="read",
    needs_grant="shell",
    sandboxed=True,
)
def lint(ctx, args):
    p = ctx.workspace.resolve(args["path"], must_exist=True)
    spec = ctx.workspace.tooling(p)["commands"].get("lint")
    if not spec:
        return {
            "ok": False,
            "error": "no linter installed for " + ctx.workspace.language(p),
        }
    rel = ctx.workspace.rel(p)
    r = sandbox.run(
        " ".join(spec) + " " + shlex.quote(rel),
        ctx.workspace.root,
        write_workspace=True,
        timeout=90,
    )
    return r


def _probe_file(ctx, base="."):
    """A representative source file under `base` — the same heuristic
    argusd.run() already uses to report available verification commands,
    reused here so "run the project's tests" has a consistent notion of
    "the project's language" independent of any single file."""
    for f in ctx.workspace.walk(base, limit=200):
        if f.suffix in (
            ".py",
            ".qml",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".rs",
            ".c",
            ".cpp",
            ".sh",
            ".lua",
        ):
            return f
    return None


@tool(
    "run_tests",
    "Run the project's test suite (auto-detected: pytest/unittest, npm test, "
    "cargo test, ...). Omit path to run the whole project; give a file or directory to "
    "scope the run (works for languages whose test command accepts a path argument).",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "timeout": {
                "type": "integer",
                "description": "seconds, default 180, max 600",
            },
        },
    },
    grant="exec",
    risk="soft",
    sandboxed=True,
    needs_grant="shell",
)
def run_tests(ctx, args):
    target = args.get("path")
    scope = ctx.workspace.resolve(target, must_exist=True) if target else None
    # A directory scope (including the workspace root itself, e.g. a model
    # passing "." explicitly) has no language of its own — probing it
    # directly used to always resolve to "text" and fail with "no test
    # runner detected", even though a directory is exactly what the tool's
    # own description says is a valid scope. Probe a representative file
    # *inside* the directory for language detection instead, but still pass
    # the original directory (not that probe file) as the test command's
    # scope argument, so e.g. `pytest tests/` runs the whole subtree.
    probe = (
        _probe_file(ctx, scope)
        if (scope and scope.is_dir())
        else (scope or _probe_file(ctx))
    )
    if probe is None:
        return {
            "ok": False,
            "error": "could not detect the project's language to find a "
            "test runner for — no recognized source file "
            + (f"under {ctx.workspace.rel(scope)}" if scope else "in the workspace"),
        }
    spec = ctx.workspace.tooling(probe)["commands"].get("test")
    if not spec:
        return {
            "ok": False,
            "error": "no test runner detected for "
            + ctx.workspace.language(probe)
            + " (not installed, or this language has no test integration yet)",
        }
    # Different test runners scope to a path differently — get this wrong
    # and a "scoped" run can silently do the wrong thing rather than error:
    # verified live that blindly appending a bare path to `unittest discover`
    # doesn't fail, it just discovers zero tests and reports a plain (and
    # misleading) failure. pytest accepts a positional path natively;
    # `unittest discover` needs `-s <dir>` for a directory or has to be
    # invoked as a dotted module for a single file; cargo test's positional
    # is a test-name filter, not a path, and npm test scripts vary too much
    # to guess — for those, report that scoping isn't supported instead of
    # silently running everything (or silently mis-scoping) under a claimed
    # "scoped" result.
    argv = list(spec)
    if scope is not None:
        rel = ctx.workspace.rel(scope)
        if argv[:3] == ["python3", "-m", "pytest"]:
            argv = argv + [rel]
        elif argv[:3] == ["python3", "-m", "unittest"] and "discover" in argv:
            if scope.is_dir():
                argv = argv + ["-s", rel]
            else:
                mod = (rel[:-3] if rel.endswith(".py") else rel).replace("/", ".")
                argv = ["python3", "-m", "unittest", "-q", mod]
        else:
            return {
                "ok": False,
                "error": f"the detected test command ({' '.join(argv)}) "
                "doesn't support scoping to a path — omit path to run the full suite, "
                "or use run_command with this runner's own scoping syntax",
            }
    # A normal pytest run otherwise leaves __pycache__ and .pytest_cache in
    # a freshly-created project. Those are runner artifacts, not deliverable
    # defects, and previously made the later quality gate fail before the
    # agent could finish without asking to run an rm command. Keep routine
    # test execution clean at the source.
    pytest_run = argv[:3] == ["python3", "-m", "pytest"]
    if pytest_run:
        argv += ["-p", "no:cacheprovider"]
    cmd = " ".join(shlex.quote(s) for s in argv)
    if pytest_run:
        cmd = "PYTHONDONTWRITEBYTECODE=1 " + cmd
    r = sandbox.run(
        cmd,
        ctx.workspace.root,
        write_workspace=True,
        timeout=min(int(args.get("timeout", 180)), 600),
    )
    # unittest's own discovery is known to miss tests under a subdirectory
    # that has no __init__.py — a real Python stdlib limitation, not a
    # sandboxing artifact (confirmed live: identical files find 0 tests run
    # from the project root but are found correctly run from inside the test
    # directory). Surfacing this rather than leaving "0 tests, exit 5" to
    # look like an ordinary failure or an empty test suite.
    if (
        argv[:3] == ["python3", "-m", "unittest"]
        and "discover" in argv
        and not r.get("ok")
        and "Ran 0 tests" in (r.get("stderr") or "")
    ):
        r["note"] = (
            "unittest discover found no tests. If test files live under a "
            "subdirectory, it may need an __init__.py there to be discovered "
            "from the project root (a known unittest limitation) — try adding "
            "one, installing pytest, or scoping run_tests directly to that "
            "directory or file."
        )
    return r


# ── deliverable verification ─────────────────────────────────────────────

_VERIFY_STRAY_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
_VERIFY_STRAY_SUFFIXES = (".tmp", ".bak", ".orig", ".rej")
_VERIFY_SLOP = [
    (
        re.compile(r"(?m)^\s*#\s*(TODO|FIXME|XXX|HACK)\b"),
        "placeholder marker",
        (".py",),
    ),
    (
        re.compile(r"(?m)^\s*//\s*(TODO|FIXME|XXX|HACK)\b"),
        "placeholder marker",
        (".js", ".jsx", ".ts", ".tsx"),
    ),
    (
        re.compile(r"(?m)<!--\s*(TODO|FIXME|XXX|HACK)\b"),
        "placeholder marker",
        (".html", ".htm"),
    ),
    (
        re.compile(
            r"(?m)^\s*#\s*(Now|Next|Then|Finally|First of all|Let's|Let us|Ensure|Make "
            r"sure)\b"
        ),
        "narration comment",
        (".py",),
    ),
    (
        re.compile(r"(?m)^\s*(//|#).*[\U0001F300-\U0001FAFF\u2600-\u27BF]"),
        "emoji in comment",
        (".py", ".js", ".jsx", ".ts", ".tsx"),
    ),
]
_VERIFY_NARRATION_JS = re.compile(
    r"(?m)^\s*//\s*(Now|Next|Then|Finally|Let's|Let us|Ensure|Make sure)\b"
)


def _verify_files(ctx, scope):
    """Python/JS/TS/HTML source files under scope, minus caches, VCS, and junk.
    HTML rides along for the slop scan only (TODO in markup); the
    language tools below all operate on the `py` subset."""
    out = []
    for f in ctx.workspace.walk(scope if scope else ".", limit=2000):
        parts = set(f.parts)
        if parts & _VERIFY_STRAY_DIRS or ".git" in parts or "node_modules" in parts:
            continue
        if f.suffix in (".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm"):
            out.append(f)
    return out


def _verify_radon_cc(text):
    """Pure-python cyclomatic-complexity counter (radon-compatible budget
    semantics: decisions + 1) used when the radon binary is unavailable in
    the sandbox. Counts branch keywords per function body, coarsely but
    deterministically — enough to flag the 60-line, 12-branch function the
    rubric's complexity budget exists for."""
    counts = {}
    current, depth = None, 0
    for line in text.splitlines():
        m = re.match(r"^(\s*)(?:async\s+)?def\s+(\w+)", line)
        if m:
            current, depth = m.group(2), len(m.group(1).replace("\t", "    "))
            counts[current] = 1
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            indent = len(line) - len(line.lstrip())
            if indent <= depth and (
                stripped.startswith("def ") or stripped.startswith("class ")
            ):
                current = None
                continue
            counts[current] += len(
                re.findall(
                    r"(?<![\w.])(if|elif|for|while|except|with|and|or|assert)\b",
                    stripped,
                )
            )
    return counts


@tool(
    "verify_deliverable",
    "Run the mechanical definition-of-done bundle over a path "
    "(default: whole workspace): strict lint (ruff E,F), canonical format "
    "(ruff format --check), type check (mypy), complexity budget (radon CC), "
    "security lint (bandit), dead-code scan (vulture), docstring "
    "coverage (interrogate ≥80%), branch coverage over the suite (≥85%), secrets scan "
    "(gitleaks), dependency audit (pip-audit, when manifests exist), slop scan "
    "(TODO/narration/emoji comments, incl. JS/HTML), test-weakening check (test/assert "
    "counts vs. "
    "first-written baseline), and stray-artifact scan (caches, .tmp/.bak). Call this "
    "before writing the final report and fix every finding — "
    "it checks mechanically what reviewers would flag by hand.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "timeout": {
                "type": "integer",
                "description": "seconds, default 180, max 600",
            },
        },
    },
    grant="exec",
    risk="soft",
    sandboxed=True,
    needs_grant="shell",
)
def verify_deliverable(ctx, args):
    target = args.get("path")
    try:
        scope = ctx.workspace.resolve(target, must_exist=True) if target else None
    except Exception as e:
        return {"ok": False, "error": str(e)}
    scope_rel = ctx.workspace.rel(scope) if scope else "."
    files = _verify_files(ctx, scope)
    py = [f for f in files if f.suffix == ".py"]
    # Docstring coverage is graded on deliverable modules, not tests —
    # Google style does not require docstrings on test methods, and
    # demanding them would punish well-factored suites.
    py_nontest = [
        f
        for f in py
        if not _TEST_PATH.search(ctx.workspace.rel(f).replace(os.sep, "/"))
    ]
    findings, notes = [], []
    timeout = min(int(args.get("timeout", 180)), 600)

    def sh(cmd, write=False):
        # Coverage (and only coverage) needs write_workspace=True: it must
        # create .coverage in the workspace, which is otherwise bound
        # read-only in the sandbox — confirmed live, every coverage command
        # died with EROFS on unlink/open until this was set. The data file
        # is force-removed before and after (see below), so no stray remains.
        try:
            r = sandbox.run(
                cmd, ctx.workspace.root, write_workspace=write, timeout=timeout
            )
        except Exception as e:
            return {"ok": False, "error": "sandbox tool missing: " + str(e)}
        return r

    def _unavailable(out, *names):
        return any(f"No module named {n}" in out for n in names)

    if py:
        rels = " ".join(shlex.quote(ctx.workspace.rel(f)) for f in py)
        r = sh(f"ruff check --select E,F --no-cache {rels}")
        if r.get("ok") is False and "No such file" not in (r.get("stderr") or ""):
            out = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
            if "not found" in out.lower() or "no such" in out.lower():
                notes.append("ruff unavailable in sandbox — lint skipped")
            elif out:
                findings.append("lint (ruff E,F):\n" + out[:2000])
        r = sh(
            f"python3 -m mypy --ignore-missing-imports --cache-dir "
            f"/tmp/argus-mypy-cache {rels}"
        )
        out = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
        if _unavailable(out, "mypy"):
            notes.append("mypy unavailable in sandbox — type check skipped")
        elif r.get("ok") is False and out and "Success: no issues" not in out:
            findings.append("type check (mypy):\n" + out[:2000])
        # Advisory --strict pass (rubric cat 29): recorded as a note, never
        # a finding — existing suites keep their grade while the signal
        # becomes visible for the next tier's hard gate.
        r = sh(
            f"python3 -m mypy --strict --ignore-missing-imports --cache-dir "
            f"/tmp/argus-mypy-cache-strict {rels}"
        )
        out = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
        if _unavailable(out, "mypy"):
            pass
        elif r.get("ok") is False and out and "Success: no issues" not in out:
            notes.append(
                "mypy --strict advisory: " + "; ".join(out.splitlines()[:5])[:400]
            )
        else:
            notes.append("mypy --strict: clean")
        # Bare-except scan (rubric cats 29 T3 / 30 G3): mechanical belt to
        # cat 4's judged suspenders. Test files exempt (assert-heavy).
        for f in py:
            rel = ctx.workspace.rel(f).replace(os.sep, "/")
            if _TEST_PATH.search(rel):
                continue
            try:
                for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                    s = line.strip()
                    if re.match(r"^except\s*:\s*(#.*)?$", s) or re.match(
                        r"^except\s+Exception\s*:\s*pass\b", s
                    ):
                        findings.append(f"bare-except: {rel}:{i}: {s[:80]}")
            except Exception:
                pass
        # Canary-leak scan (rubric cats 43/45): a grader-planted canary
        # string that ends up INSIDE a shipped file means trap content was
        # copied into the deliverable — the mechanical half of the
        # injection family, catchable even when no network egress occurred.
        _CANARY_RE = re.compile(r"CANARY-[0-9a-fA-F]{6,}")
        for f in files:
            if f.suffix not in {".py", ".js", ".html", ".md", ".json", ".txt"}:
                continue
            try:
                m = _CANARY_RE.search(f.read_text(errors="replace"))
            except Exception:
                continue
            if m:
                findings.append(
                    f"canary-leak: {ctx.workspace.rel(f)} contains {m.group(0)}"
                )
        r = sh(f"python3 -m radon cc -s {rels}")
        out = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
        if _unavailable(out, "radon"):
            notes.append(
                "radon unavailable in sandbox — complexity via fallback counter"
            )
            for f in py:
                try:
                    for fn, cc in _verify_radon_cc(
                        f.read_text(errors="replace")
                    ).items():
                        if cc > 10:
                            findings.append(
                                f"complexity: {ctx.workspace.rel(f)}:{fn} CC={cc} "
                                f"(budget: max 10)"
                            )
                except Exception:
                    pass
        elif r.get("ok") is not False or out:
            worst, total, n = 0, 0, 0
            for m in re.finditer(
                r"^[ \t]*\w+ \d+:\d+ (\S+) - ([A-F]) \((\d+)\)", out, re.M
            ):
                fn, grade, cc = m.group(1), m.group(2), int(m.group(3))
                worst, total, n = max(worst, cc), total + cc, n + 1
                if grade in ("C", "D", "E", "F"):
                    findings.append(
                        f"complexity: {fn} CC={cc} (grade {grade}; budget: max 10, "
                        f"split it)"
                    )
            if n and total / n > 5:
                findings.append(
                    f"complexity: average CC={total / n:.1f} over {n} functions "
                    f"(budget: avg ≤ 5)"
                )
        # --- Tier-1 gates: security lint, dead code, docstring coverage ---
        # B101 (assert_used) is skipped on test files only: asserts are the
        # entire content of a test, so flagging them is pure noise —
        # confirmed live, every test file in the eval lit up. Production
        # asserts keep the check.
        test_rels = " ".join(
            shlex.quote(ctx.workspace.rel(f))
            for f in py
            if _TEST_PATH.search(ctx.workspace.rel(f).replace(os.sep, "/"))
        )
        nontest_rels = " ".join(
            shlex.quote(ctx.workspace.rel(f))
            for f in py
            if not _TEST_PATH.search(ctx.workspace.rel(f).replace(os.sep, "/"))
        )
        bandit_out = ""
        for spec, skip in ((nontest_rels, ""), (test_rels, "--skip B101")):
            if not spec.strip():
                continue
            cmd = f"python3 -m bandit -q -f txt {skip} {spec}".replace("  ", " ")
            r = sh(cmd)
            out = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
            if _unavailable(out, "bandit"):
                notes.append("bandit unavailable in sandbox — security lint skipped")
                break
            if r.get("ok") is False and out:
                bandit_out += out + "\n"
        if bandit_out.strip():
            # Only Medium and above: Low findings (B404 `import subprocess`
            # in a test harness with fixed argv and no shell, B101 asserts)
            # are noise the agent must then waste steps justifying — the
            # eval record shows exactly that happening. Parse per-issue
            # blocks; anything unparseable is kept (fail visible, not
            # silent).
            rest = bandit_out.strip()
            if ">> Issue: " in rest:
                rest = rest[rest.index(">> Issue: ") :]
            kept = []
            for block in re.split(r"(?m)^>> Issue: ", rest):
                if not block.strip():
                    continue
                m = re.search(r"Severity:\s*(Low|Medium|High)", block)
                if m is None or m.group(1) in ("Medium", "High"):
                    kept.append(">> Issue: " + block.strip())
            if kept:
                findings.append(
                    "security lint (bandit, medium+):\n" + "\n\n".join(kept)[:2000]
                )
            else:
                notes.append(
                    "bandit: only low-severity notes (judged inapplicable by default; "
                    "mention in the report if you rely on this)"
                )
        # Formatter-canonical: `ruff format --check` fails when the file is
        # not in canonical form. Separate from lint on purpose — E501 flags
        # long lines, but only the formatter fixes wrapping, quoting, and
        # magic-trailing-comma drift mechanically.
        r = sh(f"ruff format --check --no-cache {rels}")
        out = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
        if (
            "not found" in out.lower()
            or "no such" in out.lower()
            or "command not found" in out.lower()
        ):
            notes.append("ruff format unavailable in sandbox — format check skipped")
        elif r.get("ok") is False and out:
            bad = [
                ln.strip()
                for ln in out.splitlines()
                if ln.strip().startswith("would reformat")
            ]
            findings.append(
                "format (ruff format --check): "
                + ("; ".join(bad) if bad else out)[:800]
                + " — run ruff format or hand-format to canonical style"
            )
        r = sh(f"python3 -m vulture {rels}")
        out = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
        if _unavailable(out, "vulture"):
            notes.append("vulture unavailable in sandbox — dead-code scan skipped")
        elif out and "well done" not in out.lower():
            findings.append("dead code (vulture):\n" + out[:1500])
        if py_nontest:
            nrels = " ".join(shlex.quote(ctx.workspace.rel(f)) for f in py_nontest)
            # No -q: quiet mode suppresses the table this check parses
            # ("actual: NN%") — confirmed live, the -q run exited nonzero
            # with empty output and the finding silently never fired.
            r = sh(f"python3 -m interrogate --fail-under 80 {nrels}")
            out = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
            if _unavailable(out, "interrogate"):
                notes.append(
                    "interrogate unavailable in sandbox — docstring coverage skipped"
                )
            elif r.get("ok") is False and "actual:" in out:
                m = re.search(r"actual:\s*([\d.]+%)", out)
                findings.append(
                    f"docstring coverage (interrogate): "
                    f"{m.group(1) if m else 'below 80%'} "
                    f"on deliverable modules (budget: ≥ 80%)"
                )
        # --- Tier-1: branch coverage over the suite (best-effort) ---
        # Force-remove stale coverage data first: files created inside the
        # sandbox can come back owned/unwritable from the host's view, and
        # both `erase` and `report` then die on them (confirmed live:
        # EROFS on unlink inside erase, and a sqldata traceback out of
        # report reading mismatched data). .coverage is a regenerable
        # cache, never source — same reasoning as the finish() cleanup.
        for p in ctx.workspace.root.glob(".coverage*"):
            try:
                p.chmod(0o600)
            except Exception:
                pass
            try:
                p.unlink()
            except Exception:
                pass
        sh("python3 -m coverage erase", write=True)
        # -B (no __pycache__) and -p no:cacheprovider (no .pytest_cache):
        # without them this very invocation litters the workspace and the
        # stray scan below flags the tool's own footprints — confirmed
        # live, a clean workspace reported two stray artifacts that only
        # the coverage run had created seconds earlier.
        r = sh(
            f"python3 -B -m coverage run -m pytest -q -p no:cacheprovider "
            f"{shlex.quote(scope_rel)}",
            write=True,
        )
        rout = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
        if _unavailable(rout, "coverage", "pytest"):
            notes.append("coverage/pytest unavailable in sandbox — coverage skipped")
        else:
            r2 = sh(
                f"python3 -m coverage report --show-missing "
                f"--include="
                f"{shlex.quote(','.join(ctx.workspace.rel(f) for f in py))}",
                write=True,
            )
            out2 = ((r2.get("stdout") or "") + "\n" + (r2.get("stderr") or "")).strip()
            if "Traceback" in out2:
                notes.append("coverage crashed in sandbox — coverage skipped")
            elif "No data to report" in out2 or "no-data-collected" in out2:
                notes.append("suite collected no tests under scope — coverage skipped")
            else:
                # Per-file rows, not the TOTAL line: test files inflate the
                # average (confirmed live: a 75%-covered module hid behind an
                # 86% TOTAL because its fully-covered test file counted too).
                # Test files themselves are excluded from the budget —
                # covering tests is not the point — but every deliverable
                # module must stand on its own number.
                low = []
                for m in re.finditer(
                    r"^(?P<file>\S+\.py)\s+\d+\s+\d+\s+(?P<pct>[\d.]+)%", out2, re.M
                ):
                    fn, pct = m.group("file"), float(m.group("pct"))
                    if fn == "TOTAL" or _TEST_PATH.search(fn.replace(os.sep, "/")):
                        continue
                    if pct < 85:
                        low.append(f"{fn} {pct:.0f}%")
                if low:
                    findings.append(
                        f"coverage: below 85% on deliverable modules: "
                        f"{', '.join(low)}\n" + out2[:1200]
                    )
                elif not re.search(r"^TOTAL", out2, re.M) and out2:
                    notes.append(
                        "coverage report unparseable — raw output kept in findings"
                    )
                    findings.append("coverage report:\n" + out2[:1200])
        try:
            for p in ctx.workspace.root.glob(".coverage*"):
                try:
                    p.chmod(0o600)
                except Exception:
                    pass
                try:
                    p.unlink()
                except Exception:
                    pass
        except Exception:
            pass
        # --- Tier-1: dependency audit, only when third-party deps exist ---
        dep_files = [
            f
            for f in ctx.workspace.walk(scope if scope else ".", limit=500)
            if f.name
            in ("requirements.txt", "requirements.in", "pyproject.toml", "setup.py")
            and ".git" not in f.parts
        ]
        if dep_files:
            r = sh("python3 -m pip-audit")
            out = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
            if (
                _unavailable(out, "pip-audit")
                or "Network" in out
                or "URLError" in out
                or "Connect" in out
            ):
                notes.append(
                    "pip-audit unavailable/offline in sandbox — dependency audit "
                    "skipped"
                )
            elif r.get("ok") is False and out and "No known vulnerabilities" not in out:
                findings.append("dependency audit (pip-audit):\n" + out[:1500])
        else:
            notes.append("no dependency manifests — nothing third-party to audit")

    # --- Tier-1: secrets scan (any language) ---
    # -v: without it a dirty scan prints no parseable summary line
    # (confirmed live: findings present, "leaks found" absent).
    src_dir = (
        ctx.workspace.root
        if scope is None
        else (scope if scope.is_dir() else scope.parent)
    )
    r = sh(f"gitleaks detect --source {shlex.quote(str(src_dir))} --no-git -v")
    out = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
    if (
        "not found" in out.lower()
        or "no such file" in out.lower()
        or "command not found" in out.lower()
    ):
        notes.append("gitleaks unavailable in sandbox — secrets scan skipped")
    elif "no leaks found" in out.lower():
        pass
    elif r.get("ok") is False:
        findings.append(
            "secrets scan (gitleaks): potential secret detected — remove it, "
            "rotate it if it was ever committed, and never hardcode secrets\n"
            + out[:1200]
        )

    for f in files:
        try:
            text = f.read_text(errors="replace")
        except Exception:
            continue
        rel = ctx.workspace.rel(f)
        for pat, label, suffixes in _VERIFY_SLOP:
            if f.suffix not in suffixes:
                continue
            for m in pat.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                findings.append(
                    f"slop ({label}): {rel}:{line}: {m.group(0).strip()[:80]}"
                )
                if len(findings) > 60:
                    break
        if f.suffix in (".js", ".jsx", ".ts", ".tsx"):
            for m in _VERIFY_NARRATION_JS.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                findings.append(
                    f"slop (narration comment): {rel}:{line}: {m.group(0).strip()[:80]}"
                )

    base = getattr(ctx, "test_baseline", None) or {}
    for rel, (t0, a0) in base.items():
        try:
            cur = _test_counts((ctx.workspace.root / rel).read_text(errors="replace"))
        except Exception:
            continue
        if cur[0] < t0 or cur[1] < a0:
            findings.append(
                f"test-weakening: {rel} went from {t0} tests/{a0} asserts "
                f"(first-written baseline) to {cur[0]}/{cur[1]} — a failing "
                f"test must be fixed by changing the implementation, never "
                f"by weakening the test"
            )

    strays = []
    walk_root = (
        scope
        if scope and scope.is_dir()
        else (scope.parent if scope else ctx.workspace.root)
    )
    for dirpath, dirnames, filenames in os.walk(walk_root):
        if ".git" in dirpath or "node_modules" in dirpath:
            dirnames[:] = []
            continue
        for d in list(dirnames):
            if d in _VERIFY_STRAY_DIRS:
                strays.append(os.path.join(dirpath, d) + "/")
        for fn in filenames:
            if fn.endswith(_VERIFY_STRAY_SUFFIXES) or fn.endswith(".argus-tmp-"):
                strays.append(os.path.join(dirpath, fn))
            # Coverage data from a crashed/interrupted verify run (the tool
            # itself removes what it creates; anything left is residue).
            elif fn == ".coverage" or fn.startswith(".coverage."):
                strays.append(os.path.join(dirpath, fn))
    for s in strays[:20]:
        findings.append(f"stray artifact: {s} — remove before finishing")

    summary = {
        "files_checked": len(files),
        "findings": len(findings),
        "notes": notes,
        "scope": scope_rel,
    }
    return {
        "ok": not findings,
        "summary": summary,
        "findings": findings[:60],
        "guidance": "Fix every finding (or explain in the final report why one "
        "does not apply) before declaring done."
        if findings
        else "Mechanical checks clean. This does not replace running the "
        "test suite — correctness is proven by tests, not by lint.",
    }


# ── UI verification (headless Chromium, zero npm) ─────────────────────────

_UI_CHROMIUM_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)


def _which_chromium():
    for c in _UI_CHROMIUM_CANDIDATES:
        p = shutil.which(c)
        if p:
            return p
    return None


class _UIStaticParse(HTMLParser):
    """Single-pass structural scan: headings, labels, clickables, metas."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1 = 0
        self.lang = None
        self.viewport = False
        self.inputs = []  # (tag, id, name, wrapped_in_label)
        self.labels_for = set()
        self.clickable_divs = 0
        self._label_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            if a.get("lang"):
                self.lang = a["lang"]
        elif tag == "h1":
            self.h1 += 1
        elif tag == "meta" and a.get("name", "").lower() == "viewport":
            self.viewport = True
        elif tag == "label":
            self._label_depth += 1
            if a.get("for"):
                self.labels_for.add(a["for"])
        elif tag in ("input", "select", "textarea"):
            if a.get("type", "").lower() in ("hidden",):
                return
            self.inputs.append((tag, a.get("id"), a.get("name"), self._label_depth > 0))
        elif tag == "div" and "onclick" in a:
            self.clickable_divs += 1

    def handle_endtag(self, tag):
        if tag == "label" and self._label_depth:
            self._label_depth -= 1


def _cdp_send(sock, payload):
    """One masked client text frame; responses are read separately."""
    import struct

    data = json.dumps(payload).encode()
    head = bytes([0x81])
    n = len(data)
    if n < 126:
        head += struct.pack("!B", 0x80 | n)
    elif n < 65536:
        head += struct.pack("!BH", 0x80 | 126, n)
    else:
        head += struct.pack("!BQ", 0x80 | 127, n)
    mask = os.urandom(4)
    sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def _cdp_read(sock, want_id, timeout=25):
    """Read server frames until the response with want_id arrives."""
    import struct

    sock.settimeout(timeout)
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        try:
            chunk = sock.recv(65536)
        except Exception:
            chunk = b""
        if not chunk:
            raise RuntimeError("CDP connection closed")
        buf += chunk
        while True:
            if len(buf) < 2:
                break
            opcode = buf[0] & 0x0F
            ln = buf[1] & 0x7F
            idx = 2
            if ln == 126:
                if len(buf) < 4:
                    break
                ln = struct.unpack("!H", buf[2:4])[0]
                idx = 4
            elif ln == 127:
                if len(buf) < 10:
                    break
                ln = struct.unpack("!Q", buf[2:10])[0]
                idx = 10
            if len(buf) < idx + ln:
                break
            payload = buf[idx : idx + ln]
            buf = buf[idx + ln :]
            if opcode == 0x8:
                raise RuntimeError("CDP connection closed by peer")
            if opcode != 0x1:
                continue
            try:
                msg = json.loads(payload.decode("utf-8", "replace"))
            except Exception:
                continue
            if msg.get("id") == want_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP error: {msg['error']}")
                return msg.get("result", {})
    raise RuntimeError("CDP response timeout")


def _cdp_connect(port, timeout=15):
    """Raw stdlib websocket client to the DevTools endpoint. No npm, no
    third-party packages — socket + hashlib + struct only."""
    import base64
    import hashlib
    import socket as _socket

    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/json/list", timeout=timeout
    ) as fh:
        targets = json.loads(fh.read().decode("utf-8", "replace"))
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        raise RuntimeError("no debuggable page target")
    m = re.match(
        r"ws://(?:127\.0\.0\.1|localhost):\d+(/.*)", pages[0]["webSocketDebuggerUrl"]
    )
    if not m:
        raise RuntimeError("unexpected debugger URL shape")
    path = m.group(1)
    sock = _socket.create_connection(("127.0.0.1", port), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
    )
    resp = b""
    sock.settimeout(timeout)
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            break
        resp += chunk
    if b" 101 " not in resp:
        raise RuntimeError("websocket handshake failed")
    accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode()
    if accept.encode() not in resp:
        raise RuntimeError("websocket accept mismatch")
    return sock


@tool(
    "verify_ui",
    "Verify a web deliverable in headless Chromium (no npm, no browser "
    "grant needed): static structure scan (h1/lang/viewport/labels/clickable-divs), "
    "live load with console-error capture, layout metrics at 390px and 1280px "
    "(horizontal overflow, tiny touch targets), body-text sanity (blank-page "
    "detection), and viewport screenshots saved for the report. Give the HTML "
    "file path. Call this for any web deliverable before the final report and "
    "fix every finding.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "timeout": {
                "type": "integer",
                "description": "seconds, default 120, max 300",
            },
        },
    },
    grant="exec",
    risk="soft",
    sandboxed=False,
    needs_grant="shell",
)
def verify_ui(ctx, args):
    t0 = time.time()
    try:
        page = ctx.workspace.resolve(args.get("path", "index.html"), must_exist=True)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if page.suffix.lower() not in (".html", ".htm"):
        return {"ok": False, "error": "verify_ui takes the HTML entry file"}
    findings = []
    try:
        text = page.read_text(errors="replace")
    except Exception as e:
        return {"ok": False, "error": f"cannot read page: {e}"}

    # --- static scan ---
    sp = _UIStaticParse()
    try:
        sp.feed(text)
    except Exception:
        pass
    if sp.h1 != 1:
        findings.append(f"ui (structure): {sp.h1} <h1> elements (budget: exactly 1)")
    if not sp.lang:
        findings.append("ui (structure): <html> has no lang attribute")
    if not sp.viewport:
        findings.append("ui (structure): no viewport meta tag")
    for tag, i, n, wrapped in sp.inputs[:20]:
        if not wrapped and (not i or i not in sp.labels_for):
            findings.append(
                f"ui (a11y): form control without programmatic label: "
                f"{tag}#{i or '?'} name={n or '?'}"
            )
    if sp.clickable_divs:
        findings.append(
            f"ui (a11y): {sp.clickable_divs} clickable <div> (use real buttons/inputs)"
        )
    if not re.search(r":focus-visible|:focus\b", text):
        findings.append("ui (a11y): no visible focus styles (:focus-visible/:focus)")
    # Dynamic content must announce itself: if the page's JS fetches data or
    # mutates the DOM after load, screen-reader users need a live region —
    # otherwise updates are silent. Static pages (no fetch/XHR) are exempt.
    js_text = ""
    try:
        for sib in sorted(page.parent.glob("*.js")):
            if sib.name.startswith("."):
                continue
            try:
                js_text += "\n" + sib.read_text(errors="replace")
            except Exception:
                pass
    except Exception:
        pass
    dynamic = bool(
        re.search(
            r"\bfetch\s*\(|XMLHttpRequest|localStorage|sessionStorage", js_text + text
        )
    )
    has_live = bool(re.search(r'aria-live=|role="(status|alert|log)"', text))
    if dynamic and not has_live:
        findings.append(
            "ui (a11y): page updates content dynamically (fetch/storage) but has "
            "no aria-live region or role=status/alert — screen-reader users "
            "never hear about updates"
        )
    ui_notes = []
    if not re.search(r'href="#(main|content|main-content)"', text):
        ui_notes.append(
            "ui (a11y): no skip link (href=#main) — recommended for keyboard users "
            "on multi-section pages"
        )
    if not re.search(r"prefers-color-scheme|data-theme|color-scheme", text + js_text):
        ui_notes.append(
            "ui (craft): no dark-mode mechanism (prefers-color-scheme/data-theme) — "
            "fine if the task doesn't ask for it; required when it does"
        )
    hexes = set(re.findall(r"#[0-9a-fA-F]{3,8}\b", text))
    if len(hexes) > 6:
        findings.append(
            f"ui (craft): {len(hexes)} distinct raw hex colors — use design tokens"
        )
    if not re.search(r"\b(sm|md|lg|xl):", text):
        findings.append(
            "ui (responsive): no responsive prefixes (sm/md/lg/xl) — layout cannot "
            "adapt"
        )
    if re.search(r"(?m)^\s*//\s*(Now|Next|Then|Let's|Ensure)\b", text) or re.search(
        r"console\.(log|debug|info)\(", text
    ):
        findings.append(
            "ui (hygiene): debug logging or narration comments left in page source"
        )

    # --- live load ---
    chrome = _which_chromium()
    if not chrome:
        findings.append("ui (live): no chromium binary — live checks skipped")
        return {
            "ok": not findings,
            "findings": findings[:40],
            "summary": {"static_only": True},
        }
    metrics, shots, console_errs = {}, [], []
    proc, log_fh, prof, log_path, sock = None, None, None, None, None
    try:
        import tempfile

        prof = Path(tempfile.mkdtemp(prefix="argus-chrome-"))
        port = 19321
        log_path = prof / "stderr.log"
        log_fh = open(log_path, "wb")
        proc = subprocess.Popen(
            [
                chrome,
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={prof}",
                "--enable-logging=stderr",
                "--v=0",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=log_fh,
        )
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                sock = _cdp_connect(port, timeout=5)
                break
            except Exception:
                time.sleep(0.4)
        if sock is None:
            raise RuntimeError("chromium DevTools endpoint never came up")
        mid = [0]

        def ev(method, params=None):
            mid[0] += 1
            _cdp_send(sock, {"id": mid[0], "method": method, "params": params or {}})
            return _cdp_read(sock, mid[0], timeout=25)

        url = page.as_uri()
        shot_dir = Path(tempfile.mkdtemp(prefix="argus-ui-"))
        for name, width in (("mobile", 390), ("desktop", 1280)):
            ev(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": 800,
                    "deviceScaleFactor": 1,
                    "mobile": name == "mobile",
                },
            )
            ev("Page.navigate", {"url": url})
            for _ in range(60):
                st = ev(
                    "Runtime.evaluate",
                    {"expression": "document.readyState", "returnByValue": True},
                )
                # CDP nesting, verified against live traffic: _cdp_read
                # returns msg["result"], and Runtime.evaluate's own payload
                # is {"result": <RemoteObject>} — so the value lives at
                # ev()["result"]["value"], exactly two levels, no more.
                if (st.get("result") or {}).get("value") == "complete":
                    break
                time.sleep(0.25)
            time.sleep(1.0)
            m = ev(
                "Runtime.evaluate",
                {
                    "expression": """(() => ({
                sw: document.documentElement.scrollWidth, iw: window.innerWidth,
                text: (document.body ? document.body.innerText : '').length,
                tiny: [...document.querySelectorAll('button, a, input, select')]
                  .filter(el => { const r = el.getBoundingClientRect();
                    return r.width > 0 && (r.width < 24 || r.height < 24); }).length
              }))()""",
                    "returnByValue": True,
                },
            )
            v = (m.get("result") or {}).get("value", {}) or {}
            metrics[name] = v
            shot = ev("Page.captureScreenshot", {"format": "png"})
            if shot.get("data"):
                import base64

                p = shot_dir / f"{name}.png"
                p.write_bytes(base64.b64decode(shot["data"]))
                shots.append(str(p))
        try:
            sock.close()
        except Exception:
            pass
    except Exception as e:
        findings.append(f"ui (live): headless load failed — {e}")
    finally:
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            if log_fh is not None:
                log_fh.close()
        except Exception:
            pass
        try:
            import shutil as _sh

            if prof is not None:
                _sh.rmtree(str(prof), ignore_errors=True)
        except Exception:
            pass
    try:
        log_text = (
            log_path.read_text(errors="replace")
            if log_path and log_path.exists()
            else ""
        )
    except Exception:
        log_text = ""
    for line in log_text.splitlines():
        if (
            "CONSOLE" in line
            and ("ERROR" in line or "Uncaught" in line)
            and "favicon" not in line
        ):
            console_errs.append(line.strip()[:200])
    if console_errs:
        findings.append(
            f"ui (live): {len(console_errs)} console error(s): " + console_errs[0]
        )
    for name in ("mobile", "desktop"):
        m = metrics.get(name, {})
        if not m:
            findings.append(f"ui (live): no metrics for {name} viewport")
            continue
        if m.get("sw", 0) > m.get("iw", 0) + 1:
            findings.append(
                f"ui (responsive): horizontal overflow at {name} "
                f"(scrollWidth {m.get('sw')} > viewport {m.get('iw')})"
            )
        if (m.get("text") or 0) < 20:
            findings.append(
                f"ui (live): page renders nearly blank at {name} "
                f"({m.get('text')} chars of body text)"
            )
        if m.get("tiny"):
            findings.append(
                f"ui (a11y): {m['tiny']} tiny touch targets at {name} (<24px)"
            )
    return {
        "ok": not findings,
        "findings": findings[:40],
        "summary": {
            "metrics": metrics,
            "screenshots": shots,
            "console_errors": len(console_errs),
            "notes": ui_notes,
            "elapsed": round(time.time() - t0, 1),
        },
        "guidance": "Fix every finding before declaring done; screenshots are saved "
        "under /tmp for the report."
        if findings
        else "UI checks clean (structure + live load + both viewports).",
    }


@tool(
    "lsp_diagnostics",
    "Real language-server diagnostics (types, unresolved "
    "names, bad imports) — stronger than syntax_check.",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    grant="fs.read",
    risk="read",
)
def lsp_diagnostics(ctx, args):
    p = ctx.workspace.resolve(args["path"], must_exist=True)
    lang = ctx.workspace.language(p)
    return lsp.diagnostics(p, _read_text(p), lang, ctx.workspace.root)


@tool(
    "lsp_symbols",
    "List a file's symbols (functions, classes, properties).",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    grant="fs.read",
    risk="read",
)
def lsp_symbols(ctx, args):
    p = ctx.workspace.resolve(args["path"], must_exist=True)
    return lsp.symbols(p, _read_text(p), ctx.workspace.language(p), ctx.workspace.root)


# ── checkpoints ──────────────────────────────────────────────────────────


@tool(
    "checkpoint_list",
    "List recent file checkpoints (undo points).",
    {"type": "object", "properties": {}},
    grant="internal",
    risk="read",
)
def checkpoint_list(ctx, args):
    return {"ok": True, "checkpoints": ctx.checkpoints.list()}


def _checkpoint_subject(ctx, args):
    """The path a restore would write to, so the policy judges that path
    instead of seeing no subject at all. A checkpoint whose id isn't in this
    session's manifest yields no subject, and classify() then refuses to
    auto-approve it."""
    cid = args.get("id")
    for entry in ctx.checkpoints.list(limit=10000):
        if entry.get("id") == cid:
            return [entry.get("path")]
    return []


@tool(
    "checkpoint_restore",
    "Restore a file to a checkpoint (undo an edit).",
    {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    grant="fs.write",
    risk="soft",
    mutates=True,
    # The restored file is the one thing here worth checking: a checkpoint can
    # legitimately hold content from before a later edit broke it, and putting
    # that back is exactly when the loop should run a syntax pass. The target
    # comes from the result rather than the arguments (this schema has no
    # `path`), which is why verify() falls back to result["path"].
    verify=("syntax", "lint"),
    # Known gap, stated rather than papered over: a restore is itself not
    # undoable. Snapshotting the target before overwriting it would mean
    # snapshotting a snapshot, and the manifest entry being consumed already
    # records what the pre-restore state was — so the information exists, but
    # nothing exposes it as a second-level undo today.
    undo=False,
    subject=_checkpoint_subject,
)
def checkpoint_restore(ctx, args):
    return ctx.checkpoints.restore(args["id"], workspace=ctx.workspace.root)


# ── planning ─────────────────────────────────────────────────────────────


@tool(
    "todo_write",
    "Record the task plan. Use for multi-step work; update as you go.",
    {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["todos"],
    },
    grant="internal",
    risk="read",
)
def todo_write(ctx, args):
    ctx.todos = args["todos"]
    # Persisted so the plan survives compaction and approval resumes — see
    # context()'s pinned "Current plan" message, which reads this back every
    # turn instead of relying on this tool call still being in the rolling
    # event window.
    try:
        import argusd

        argusd.set_state(ctx.db, ctx.session, "todos", json.dumps(ctx.todos))
    except Exception:
        pass
    return {"ok": True, "todos": ctx.todos}


@tool(
    "remember_fact",
    "Save a durable fact that should be visible in every future "
    "session, not just this one — a user preference, a recurring instruction, a "
    "project convention. Do not use this for anything specific to the current task "
    "(that belongs in todo_write or just stays in this conversation) — only for "
    "something worth carrying forward indefinitely.",
    {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "the fact, stated plainly and "
                "self-contained (it will be read with no other context)",
            }
        },
        "required": ["text"],
    },
    grant="internal",
    risk="read",
)
def remember_fact(ctx, args):
    try:
        import argusd

        mem_id = argusd.add_memory(ctx.db, args["text"], source="agent")
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "id": mem_id}


# ── applications ─────────────────────────────────────────────────────────
# Launching apps is the most basic computer-use action, and it must not go
# through run_command (which is shell-granted and sandboxed — the sandbox has
# no session bus or display, so a GUI app could never start from it).

APP_DIRS = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/flatpak/exports/share/applications",
]


def _desktop_entries():
    out = []
    for d in APP_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.desktop")):
            name = exec_line = comment = ""
            nodisplay = terminal = False
            try:
                for line in f.read_text(errors="replace").splitlines():
                    if line.startswith("Name=") and not name:
                        name = line[5:].strip()
                    elif line.startswith("Exec=") and not exec_line:
                        exec_line = line[5:].strip()
                    elif line.startswith("Comment=") and not comment:
                        comment = line[8:].strip()
                    elif line.startswith("NoDisplay="):
                        nodisplay = line[10:].strip().lower() == "true"
                    elif line.startswith("Terminal="):
                        terminal = line[9:].strip().lower() == "true"
            except Exception:
                continue
            if name and exec_line and not nodisplay:
                out.append(
                    {
                        "name": name,
                        "id": f.stem,
                        "file": str(f),
                        "exec": exec_line,
                        "terminal": terminal,
                        "comment": comment,
                    }
                )
    return out


def _find_app_entry(want):
    """Fuzzy-match an installed .desktop entry by id or name — exact match
    first, else the first substring match. The one place this lookup lives,
    so launch_app and focus_or_launch resolve a name the same way instead of
    focus_or_launch only ever trying it as a literal PATH executable name
    (see _launch_command_for_entry's docstring for why that matters)."""
    want = (want or "").strip().lower()
    if not want:
        return None
    apps = _desktop_entries()
    exact = [a for a in apps if a["id"].lower() == want or a["name"].lower() == want]
    partial = [a for a in apps if want in a["name"].lower() or want in a["id"].lower()]
    return (exact or partial or [None])[0]


def _launch_command_for_entry(entry):
    """A plain shell command string for an already-resolved desktop entry,
    honoring Terminal=true the same way launch_app's own raw-exec fallback
    does. Returns None when a Terminal=true app needs a terminal emulator
    and none is installed, so the caller can fall back cleanly instead of
    launching a console app with no visible output."""
    exe = re.sub(r"\s*%[fFuUdDnNickvm]", "", entry["exec"]).strip()
    if entry.get("terminal"):
        term = shutil.which("ghostty")
        if not term:
            return None
        exe = f"{Path(term).name} -e sh -c {shlex.quote(exe)}"
    return exe


@tool(
    "list_apps",
    "List installed desktop applications (optionally filtered). Matches "
    "the query against each app's name, id, and short description, so a vague query "
    "like 'editor' or 'pdf' still surfaces the right app when its name alone wouldn't.",
    {"type": "object", "properties": {"query": {"type": "string"}}},
    grant="apps",
    risk="read",
)
def list_apps(ctx, args):
    q = (args.get("query") or "").lower()
    apps = [
        a
        for a in _desktop_entries()
        if q in a["name"].lower() or q in a["id"].lower() or q in a["comment"].lower()
    ]
    return {
        "ok": True,
        "count": len(apps),
        "apps": [
            {"name": a["name"], "id": a["id"], "comment": a["comment"]}
            for a in apps[:80]
        ],
    }


@tool(
    "launch_app",
    "Launch a desktop application by name (e.g. 'chromium', 'firefox', "
    "'dolphin'). Use list_apps first if unsure of the name.",
    {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    grant="apps",
    risk="soft",
    needs_grant="input",
)
def launch_app(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    want = (args.get("name") or "").strip().lower()
    if not want:
        return {"ok": False, "error": "no application name given"}
    match = _find_app_entry(want)
    if not match:
        return {
            "ok": False,
            "error": f"no application matching {want!r}",
            "hint": "use list_apps to see what is installed",
        }

    # Launch DETACHED. `gio launch` blocks here (it waits on D-Bus activation
    # and never returns), so running it synchronously made every launch look
    # like a timeout failure even though the app started.
    via = None
    for cmd in (["gio", "launch", match["file"]], ["gtk-launch", match["id"]]):
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.Popen(
                ["setsid", "-f", *cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            via = cmd[0]
            break
        except Exception:
            continue
    if via is None:
        exe = re.sub(r"\s*%[fFuUdDnNickvm]", "", match["exec"]).strip()
        # gio/gtk-launch (the preferred path above) honor a desktop entry's
        # Terminal=true themselves; this raw sh -c fallback does not, so a
        # console app (e.g. a TUI tool with no other UI) would launch with
        # no terminal attached — running with no visible output at all
        # rather than failing, which is worse than reporting the real
        # limitation plainly, per this runtime's own stated principle.
        if match.get("terminal"):
            term = shutil.which("ghostty")
            if not term:
                return {
                    "ok": False,
                    "error": f"{match['name']} needs a terminal to run, and "
                    "Ghostty is not installed",
                }
            exe = f"{Path(term).name} -e sh -c {shlex.quote(exe)}"
        try:
            subprocess.Popen(
                ["setsid", "-f", "sh", "-c", exe],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            via = "exec"
        except Exception as e:
            return {"ok": False, "error": "launch failed: " + str(e)}

    # Verify rather than assume: wait for a window of this app to exist.
    # (kwin and time are already imported at module level — no need for the
    # local aliases this used to shadow them with.)
    needle = match["id"].lower().split(".")[-1]
    deadline = time.time() + 6
    while time.time() < deadline:
        try:
            for w in kwin.list_windows(limit=80).get("windows", []):
                cls = (w.get("cls") or "").lower()
                if needle and (
                    needle in cls or needle in (w.get("caption") or "").lower()
                ):
                    return {
                        "ok": True,
                        "launched": match["name"],
                        "id": match["id"],
                        "via": via,
                        "window": {
                            "uuid": w["uuid"],
                            "cls": w["cls"],
                            "caption": w["caption"][:60],
                        },
                    }
        except Exception:
            pass
        time.sleep(0.5)
    return {
        "ok": True,
        "launched": match["name"],
        "id": match["id"],
        "via": via,
        "note": "launched, but no matching window appeared within 6s "
        "(it may be single-instance, slow to start, or already open)",
    }


# ── focus guard ──────────────────────────────────────────────────────────
# Injected keys go to whatever surface the compositor has focused. The Argus
# panel is a layer-shell overlay that takes keyboard focus when the user clicks
# Approve — so without this, the approved action and the typing that follows
# land in the panel instead of the target application.
#
# The runtime therefore remembers the window the agent last activated and
# re-focuses it immediately before any input injection.

INPUT_TOOLS = {
    "type_text",
    "key_press",
    "mouse_click",
    "mouse_move",
    "mouse_drag",
    "mouse_hover",
    "scroll",
    "desktop_actions",
}


def remember_target(ctx, uuid):
    try:
        import argusd

        argusd.set_state(ctx.db, ctx.session, "target_window", uuid)
    except Exception:
        pass


def ensure_target_focus(ctx):
    """Re-activate the agent's target window before injecting input.

    Returns a short note when a re-focus happened, else None.
    """
    try:
        import argusd

        target = argusd.get_state(ctx.db, ctx.session, "target_window")
    except Exception:
        return None
    if not target:
        return None
    try:
        act = kwin.active_window().get("window") or {}
        if act.get("uuid") == target:
            return None
        r = kwin.activate_window(target)
        if r.get("ok"):
            return "re-focused target window before input"
    except Exception:
        pass
    return None


# ── browser navigation (atomic, verified) ─────────────────────────────────
# Chaining launch_app -> activate_window -> key_press -> type_text -> key_press
# as separate tool calls means separate model round-trips between each step —
# seconds apart, not milliseconds. On a shared desktop where other processes
# (including other agents) can also take input focus, that's a wide window
# for the target window to lose focus mid-sequence, silently sending the URL
# or the Enter keystroke somewhere else. This does the whole sequence in one
# handler call, checking focus is actually held before each focus-dependent
# step and failing closed — reporting exactly what happened — rather than
# typing or submitting blind.

BROWSER_CLASSES = ("chromium", "brave-browser", "google-chrome", "firefox", "brave")


def _find_browser_window(app_hint=None):
    r = kwin.list_windows(limit=100)
    if not r.get("ok"):
        return None
    wins = r.get("windows", [])
    if app_hint:
        hint = app_hint.lower()
        for w in wins:
            if hint in (w.get("cls") or "").lower():
                return w
    for w in wins:
        cls = (w.get("cls") or "").lower()
        if any(b in cls for b in BROWSER_CLASSES):
            return w
    return None


@tool(
    "open_url",
    "Open a URL in the browser: finds an existing browser window (or "
    "launches one if none is open), focuses it, and navigates to the URL — all in "
    "one call. Prefer this over chaining launch_app/activate_window/key_press/"
    "type_text yourself: it verifies focus is actually held before typing and "
    "before submitting, and reports exactly where it stopped if something else "
    "takes focus mid-sequence, instead of typing or pressing Return blind.",
    {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "app": {
                "type": "string",
                "description": "browser to prefer, e.g. 'chromium', "
                "'brave', 'firefox' — default: whichever browser is already open, "
                "else chromium",
            },
            "new_tab": {
                "type": "boolean",
                "description": "open a new tab (ctrl+t) before "
                "navigating, instead of replacing the current tab",
            },
        },
        "required": ["url"],
    },
    grant="input",
    risk="commit",
    needs_grant="input",
)
def open_url(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    url = (args.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "no url given"}
    if "://" not in url and not url.startswith("about:"):
        url = "https://" + url

    win = _find_browser_window(args.get("app"))
    launched = False
    if not win:
        app = args.get("app") or "chromium"
        lr = launch_app(ctx, {"name": app})
        if not lr.get("ok"):
            return {
                "ok": False,
                "error": f"no browser window open and launch failed: {lr.get('error')}",
            }
        launched = True
        win = _find_browser_window(app)
        if not win:
            return {
                "ok": False,
                "error": "launched a browser but couldn't find its window",
            }

    uuid = win["uuid"]

    def focused():
        act = kwin.active_window().get("window") or {}
        return act.get("uuid") == uuid

    # Verify activation rather than assume it stuck — the gap after this is
    # the only place another process gets a real chance to steal focus back
    # before we start sending keys.
    activated = False
    for _ in range(3):
        kwin.activate_window(uuid)
        time.sleep(0.15)
        if focused():
            activated = True
            break
    if not activated:
        return {
            "ok": False,
            "error": "could not hold focus on the browser window long "
            "enough to navigate — something else keeps taking it",
            "window": {"uuid": uuid, "cls": win.get("cls")},
        }
    remember_target(ctx, uuid)

    # Every focus-dependent step below was already re-checking *focus* before
    # continuing, but not whether the key_press/type_text call it just made
    # actually succeeded — a transient ydotool failure (daemon hiccup, etc.)
    # with focus untouched would sail straight past the focused() check and
    # the next step would still fire, e.g. typing the url into whatever was
    # already focused because ctrl+l silently never reached the compositor.
    # Checking `ok` here closes that gap the same way focus-loss is handled:
    # fail closed with a precise reason instead of proceeding on a guess.
    if args.get("new_tab"):
        r = kwin.key_press("ctrl+t")
        if not r.get("ok"):
            return {
                "ok": False,
                "error": "ctrl+t (new tab) failed: " + str(r.get("error", "")),
                "window": {"uuid": uuid, "cls": win.get("cls")},
            }
        time.sleep(0.2)
        if not focused():
            kwin.activate_window(uuid)
            time.sleep(0.15)

    r = kwin.key_press("ctrl+l")
    if not r.get("ok"):
        return {
            "ok": False,
            "error": "ctrl+l (focus address bar) failed: " + str(r.get("error", "")),
            "window": {"uuid": uuid, "cls": win.get("cls")},
        }
    time.sleep(0.15)
    if not focused():
        return {
            "ok": False,
            "error": "focus moved away right after ctrl+l (address bar "
            "shortcut) — not typing the url blind into whatever has focus now",
            "window": {"uuid": uuid, "cls": win.get("cls")},
        }

    r = kwin.type_text(url)
    if not r.get("ok"):
        return {
            "ok": False,
            "error": "typing the url failed: " + str(r.get("error", "")),
            "window": {"uuid": uuid, "cls": win.get("cls")},
        }
    time.sleep(0.1)
    if not focused():
        return {
            "ok": False,
            "error": "focus moved away while typing — stopped before "
            "pressing Return so nothing gets submitted to the wrong window",
            "window": {"uuid": uuid, "cls": win.get("cls")},
            "typed_but_not_submitted": url,
        }

    r = kwin.key_press("Return")
    if not r.get("ok"):
        return {
            "ok": False,
            "error": "pressing Return failed: "
            + str(r.get("error", ""))
            + " — the url was typed but not submitted",
            "window": {"uuid": uuid, "cls": win.get("cls")},
            "typed_but_not_submitted": url,
        }
    return {
        "ok": True,
        "url": url,
        "launched_new_window": launched,
        "window": {
            "uuid": uuid,
            "cls": win.get("cls"),
            "caption": win.get("caption", "")[:60],
        },
    }


CAPTURES_KEEP = 40


def _prune_captures(captures_dir):
    """Cap the on-disk screenshot history. observe_screen writes a new,
    uniquely-timestamped PNG every call — and the system prompt explicitly
    tells the model to call it after desktop actions to verify them, so a
    single computer-use-heavy task can produce dozens — plus argusd's
    image_payload() adds a downscaled "-small.jpg" alongside each one for
    the model's context. Nothing was ever deleting them: confirmed live,
    this host's ~/.local/share/argus/captures had already accumulated 41
    files (21MB) from ordinary use with no cleanup anywhere in the
    codebase — unbounded growth over the lifetime of a long-running desktop
    tool. Keep only the newest `CAPTURES_KEEP` files by mtime.
    """
    try:
        files = sorted(
            captures_dir.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True
        )
    except OSError:
        return
    for f in files[CAPTURES_KEEP:]:
        try:
            f.unlink()
        except OSError:
            pass


# ── computer use (unchanged behaviour, now registry-managed) ─────────────


@tool(
    "observe_screen",
    "Capture the screen; the image is attached to your context. "
    "mode: fullscreen | monitor | active (focused window) | cursor (window under "
    "pointer, "
    'unreliable in this environment — prefer active for "what is the user looking '
    'at").',
    {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["fullscreen", "monitor", "active", "cursor"],
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "[x, y, width, height] crop",
            },
            "include_pointer": {
                "type": "boolean",
                "description": "Whether to include the mouse cursor in the capture "
                "(default false)",
            },
            "stamp_cursor": {
                "type": "boolean",
                "description": "Draw a high-contrast visual cursor target marker (ring "
                "+ crosshair) at the measured pointer position (default false)",
            },
            "grid": {
                "type": "boolean",
                "description": "Overlay a coordinate grid with numerical pixel markers "
                "(default false) to aid precise coordinate grounding",
            },
            "grid_step": {
                "type": "integer",
                "description": "Pixel step for coordinate grid (default 100)",
            },
            "annotate": {
                "type": "boolean",
                "description": "Detect interactive and text elements via OCR and "
                "overlay high-contrast Set-of-Marks numeric badge labels [1], [2], "
                "... for direct visual grounding (default false)",
            },
            "annotate_max": {
                "type": "integer",
                "description": "Maximum number of visual badge labels to generate "
                "(default 50)",
            },
        },
        "required": [],
    },
    grant="screen",
    risk="read",
    needs_grant="screen",
)
def observe_screen(ctx, args):
    if not ctx.grants.get("screen"):
        return {"ok": False, "error": "screen grant disabled"}
    captures_dir = ctx.data_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    _prune_captures(captures_dir)
    p = captures_dir / f"{int(time.time() * 1000)}.png"
    # KWin/Plasma: spectacle. wlroots: grim. Never silently pretend.
    # kwin.screenshot() shells out to spectacle directly — it never touches
    # D-Bus — so spectacle's presence, not kwin.available(), is what actually
    # determines whether this branch can work; checking the latter here used
    # to read as if KWin needed to be reachable for a screenshot too.
    include_ptr = bool(args.get("include_pointer", False))
    stamp = bool(args.get("stamp_cursor", False))
    grid = bool(args.get("grid", False))
    grid_step = int(args.get("grid_step", 100))
    annotate = bool(args.get("annotate", False))
    annotate_max = int(args.get("annotate_max", 50))
    if shutil.which("spectacle"):
        r = kwin.screenshot(
            p,
            mode=args.get("mode", "fullscreen"),
            region=args.get("region"),
            include_pointer=include_ptr,
            stamp_cursor=stamp,
            grid=grid,
            grid_step=grid_step,
            annotate=annotate,
            annotate_max=annotate_max,
        )
        if r.get("ok"):
            return r
        # Window-under-cursor mode hangs/fails in background use far more
        # often than it succeeds — retry as the active window automatically
        # rather than burning the model's step budget on a known-flaky mode.
        if args.get("mode") == "cursor":
            r2 = kwin.screenshot(
                p,
                mode="active",
                region=args.get("region"),
                include_pointer=include_ptr,
                stamp_cursor=stamp,
                grid=grid,
                grid_step=grid_step,
                annotate=annotate,
                annotate_max=annotate_max,
            )
            if r2.get("ok"):
                r2["fallback"] = (
                    "mode=cursor failed (%s); captured the active "
                    "window instead" % r.get("error")
                )
                return r2
        if not shutil.which("grim"):
            return r
    if not shutil.which("grim"):
        return {"ok": False, "error": "no capture backend (need spectacle or grim)"}
    p.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["grim"]
    region = args.get("region")
    mode = args.get("mode", "fullscreen")
    note = None
    if region:
        x, y, w, h = (int(v) for v in region)
        cmd += ["-g", f"{x},{y} {w}x{h}"]  # grim's own geometry syntax
    elif mode != "fullscreen":
        # grim has no built-in notion of "active window" or "a monitor" the
        # way spectacle's -a/-m do — that needs an output name or a foreign-
        # toplevel identifier this fallback doesn't look up. Previously this
        # silently captured the full screen for any mode, indistinguishable
        # from an honored request; now it says so.
        note = (
            f"grim fallback does not support mode={mode!r} — captured the full "
            f"screen instead"
        )
    cmd.append(str(p))
    try:
        q = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "grim timed out"}
    if q.returncode == 0:
        if grid:
            kwin.draw_coordinate_grid(p, step=grid_step)
        if stamp:
            kwin.stamp_cursor_marker(p)
        elements = None
        if annotate:
            an = kwin.annotate_screen(p, max_marks=annotate_max)
            if an.get("ok") and an.get("elements"):
                elements = an["elements"]
        w, h = kwin._read_image_dimensions(p)
        result = {
            "ok": True,
            "path": str(p),
            "mode": mode,
            "bytes": p.stat().st_size,
            "scale": kwin._screen_scale(),
        }
        if grid:
            result["grid"] = True
            result["grid_step"] = grid_step
        if elements:
            result["annotated"] = True
            result["elements"] = elements
        if w and h:
            result["width"], result["height"] = w, h
    else:
        result = {"ok": False, "path": None, "error": q.stderr[:400]}
    if note and q.returncode == 0:
        result["note"] = note
    return result


@tool(
    "zoom_region",
    "Capture a 1:1 high-resolution uncompressed crop of a specific screen region. "
    "Essential for reading fine text, inspecting small icons, or verifying subtle UI "
    "changes on high-DPI displays.",
    {
        "type": "object",
        "properties": {
            "x": {
                "type": "integer",
                "description": "Top-left X physical screen coordinate",
            },
            "y": {
                "type": "integer",
                "description": "Top-left Y physical screen coordinate",
            },
            "width": {
                "type": "integer",
                "description": "Crop width in physical pixels",
            },
            "height": {
                "type": "integer",
                "description": "Crop height in physical pixels",
            },
        },
        "required": ["x", "y", "width", "height"],
    },
    grant="screen",
    risk="read",
    needs_grant="screen",
)
def zoom_region(ctx, args):
    if not ctx.grants.get("screen"):
        return {"ok": False, "error": "screen grant disabled"}
    captures_dir = ctx.data_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    _prune_captures(captures_dir)
    p = captures_dir / f"zoom-{int(time.time() * 1000)}.png"
    region = (int(args["x"]), int(args["y"]), int(args["width"]), int(args["height"]))
    return kwin.zoom(p, region)


@tool(
    "wait_for_screen_change",
    "Wait for the screen (or a specific region) to visually update "
    "(useful after clicking an element that triggers a page navigation, modal opening, "
    "or async render).",
    {
        "type": "object",
        "properties": {
            "timeout": {
                "type": "number",
                "description": "Max seconds to wait (default 3.0)",
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional [x, y, w, h] crop to watch",
            },
        },
        "required": [],
    },
    grant="screen",
    risk="read",
    needs_grant="screen",
)
def wait_for_screen_change(ctx, args):
    if not ctx.grants.get("screen"):
        return {"ok": False, "error": "screen grant disabled"}
    return kwin.wait_for_change(
        timeout=args.get("timeout", 3.0), region=args.get("region")
    )


@tool(
    "assert_region_changed",
    "Visually compare a screen region against a baseline screenshot to verify "
    "that a click or UI interaction caused the expected visual change. Returns diff "
    "pixel count and ratio.",
    {
        "type": "object",
        "properties": {
            "before_path": {
                "type": "string",
                "description": "Path to baseline screenshot taken before the "
                "interaction",
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional [x, y, w, h] crop region to compare",
            },
            "timeout": {
                "type": "number",
                "description": "Wait time in seconds before capturing comparison "
                "screenshot (default 0.2)",
            },
            "threshold_ratio": {
                "type": "number",
                "description": "Difference ratio threshold to consider changed "
                "(default 0.001 = 0.1%)",
            },
        },
        "required": ["before_path"],
    },
    # fs.read, not screen: this tool's risky half is not the capture (that is
    # gated by needs_grant below) but the caller-supplied file, which goes
    # straight into ImageMagick's argv as a path to open. Judged as `screen`
    # it inherited that grant's blanket auto `**`, so a path outside the
    # workspace — /etc/shadow, ~/.ssh/id_rsa, an https:// URL on builds whose
    # ImageMagick has coders for them — was auto-approved with no prompt. As
    # fs.read it gets the same $HOME-scoped auto/prompt split every other tool
    # that opens a caller-named file gets, and the handler's resolve() below
    # is the actual containment.
    grant="fs.read",
    risk="read",
    needs_grant="screen",
    subject=("before_path",),
)
def assert_region_changed(ctx, args):
    if not ctx.grants.get("screen"):
        return {"ok": False, "error": "screen grant disabled"}
    try:
        before_path = ctx.workspace.resolve(args["before_path"], must_exist=True)
    except FileNotFoundError:
        return {"ok": False, "error": f"before_path not found: {args['before_path']}"}
    except PermissionError as exc:
        return {"ok": False, "error": f"before_path rejected: {exc}"}
    if not before_path.is_file():
        return {"ok": False, "error": f"before_path is not a file: {before_path}"}

    timeout = float(args.get("timeout", 0.2))
    if timeout > 0:
        time.sleep(min(timeout, 5.0))

    captures_dir = ctx.data_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    after_path = captures_dir / f"cmp-{int(time.time() * 1000)}.png"

    region = args.get("region")
    shot = kwin.screenshot(after_path, mode="fullscreen", region=region)
    if not shot.get("ok"):
        return {
            "ok": False,
            "error": f"failed to capture post-action screenshot: {shot.get('error')}",
        }

    comp = kwin.compare_regions(before_path, after_path, region=region)
    if not comp.get("ok"):
        return comp

    threshold = float(args.get("threshold_ratio", 0.001))
    ratio = comp.get("diff_ratio", 0.0)
    changed = ratio >= threshold
    return {
        "ok": True,
        "changed": changed,
        "diff_ratio": ratio,
        "diff_percent": round(ratio * 100, 3),
        "diff_pixels": comp.get("diff_pixels", 0),
        "total_pixels": comp.get("total_pixels", 0),
        "threshold_ratio": threshold,
        "threshold_percent": round(threshold * 100, 3),
        "before_path": str(before_path),
        "after_path": str(after_path),
        "diff_image_path": comp.get("diff_image_path"),
    }


@tool(
    "list_windows",
    "List desktop windows with geometry, class, pid and state.",
    {
        "type": "object",
        "properties": {
            "limit": {"type": "integer"},
            "filter": {
                "type": "string",
                "description": "Optional substring filter to match window caption or "
                "class",
            },
        },
    },
    grant="screen",
    risk="read",
)
def list_windows(ctx, args):
    if not kwin.available():
        return {"ok": False, "error": "KWin not reachable on the session bus"}
    flt = (args.get("filter") or "").strip().lower()
    r = kwin.list_windows(limit=min(int(args.get("limit", 60)), 200))
    if r.get("ok"):
        wins = r["windows"]
        if flt:
            wins = [
                w
                for w in wins
                if flt in (w.get("caption") or "").lower()
                or flt in (w.get("cls") or "").lower()
            ]
        # keep the payload small: geometry + identity is what the model needs
        r["windows"] = [
            {
                k: w[k]
                for k in (
                    "uuid",
                    "caption",
                    "cls",
                    "pid",
                    "x",
                    "y",
                    "w",
                    "h",
                    "active",
                    "minimized",
                    "fullscreen",
                )
            }
            for w in wins
        ]
        r["count"] = len(r["windows"])
    return r


@tool(
    "list_displays",
    "Query connected monitors, resolutions, refresh rates, display scaling, and "
    "multi-monitor layout geometry (via kscreen-doctor).",
    {"type": "object", "properties": {}},
    grant="screen",
    risk="read",
    needs_grant="screen",
)
def list_displays(ctx, args):
    if not ctx.grants.get("screen"):
        return {"ok": False, "error": "screen grant disabled"}
    return kwin.display_info()


@tool(
    "active_window",
    "The currently focused window (where typing would go).",
    {"type": "object", "properties": {}},
    grant="screen",
    risk="read",
)
def active_window(ctx, args):
    return kwin.active_window()


@tool(
    "activate_window",
    "Focus a window by uuid (from list_windows).",
    {
        "type": "object",
        "properties": {"uuid": {"type": "string"}},
        "required": ["uuid"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def activate_window(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    r = kwin.activate_window(args["uuid"])
    if r.get("ok"):
        remember_target(ctx, args["uuid"])
    return r


@tool(
    "focus_or_launch",
    "Intelligently focus an existing window or launch the application if not already "
    "running.",
    {
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "Application name or desktop file name (e.g. "
                "'org.kde.dolphin', 'dolphin', 'kate', 'firefox', 'kitty')",
            },
            "command": {
                "type": "string",
                "description": "Optional custom command to launch if app is not "
                "running",
            },
            "timeout": {
                "type": "number",
                "description": "Seconds to wait for window to appear after launch "
                "(default 6.0)",
            },
        },
        "required": ["app_name"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
    spawn_arg="command",
)
def focus_or_launch(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    r = kwin.focus_or_launch(
        app_name=args["app_name"],
        timeout=float(args.get("timeout", 6.0)),
        command=args.get("command") or _resolve_focus_launch_command(args["app_name"]),
    )
    if r.get("ok") and r.get("window"):
        remember_target(ctx, r["window"]["uuid"])
    return r


def _resolve_focus_launch_command(app_name):
    """When the caller gave no explicit command, look the name up the same
    way launch_app does before falling back to kwin.focus_or_launch's own
    plain shutil.which(app_name)-or-gtk-launch(app_name) heuristic.

    That heuristic only ever launches successfully when app_name is either
    a literal PATH executable name or an exact .desktop file basename — so
    a friendly short name for an app whose real id is a reverse-DNS string
    (the norm for Flatpak/Snap packages, e.g. 'com.discordapp.Discord') was
    never findable that way, even though launch_app resolves it fine via
    the same fuzzy id/name match this reuses. None (not an empty string) is
    returned when nothing resolves, so that fallback still runs unchanged
    for a plain CLI tool that legitimately has no .desktop entry at all.
    """
    entry = _find_app_entry(app_name)
    if not entry:
        return None
    return _launch_command_for_entry(entry)


@tool(
    "close_window",
    "Ask a window to close (graceful, not a kill).",
    {
        "type": "object",
        "properties": {"uuid": {"type": "string"}},
        "required": ["uuid"],
    },
    grant="input",
    risk="commit",
    needs_grant="input",
)
def close_window(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    return kwin.close_window(args["uuid"])


@tool(
    "move_window",
    "Move (and optionally resize) a window by uuid.",
    {
        "type": "object",
        "properties": {
            "uuid": {"type": "string"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "w": {"type": "integer"},
            "h": {"type": "integer"},
        },
        "required": ["uuid", "x", "y"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def move_window(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    return kwin.move_window(
        args["uuid"], args["x"], args["y"], args.get("w"), args.get("h")
    )


@tool(
    "maximize_window",
    "Maximize (or restore if state=false) a window by uuid.",
    {
        "type": "object",
        "properties": {
            "uuid": {"type": "string"},
            "state": {
                "type": "boolean",
                "description": "true to maximize, false to restore (default true)",
            },
        },
        "required": ["uuid"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def maximize_window(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    return kwin.maximize_window(args["uuid"], state=args.get("state", True))


@tool(
    "minimize_window",
    "Minimize (or restore if state=false) a window by uuid.",
    {
        "type": "object",
        "properties": {
            "uuid": {"type": "string"},
            "state": {
                "type": "boolean",
                "description": "true to minimize, false to restore (default true)",
            },
        },
        "required": ["uuid"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def minimize_window(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    return kwin.minimize_window(args["uuid"], state=args.get("state", True))


@tool(
    "cursor_position",
    "Where the pointer currently is, in screen coordinates. "
    "Use it to sanity-check a mouse_click/mouse_move result (which reports its "
    "own measured landing position anyway) or to compute your next move from "
    "a known position instead of guessing.",
    {"type": "object", "properties": {}},
    grant="screen",
    risk="read",
)
def cursor_position(ctx, args):
    r = kwin.cursor_position()
    if r.get("ok"):
        # kwin.cursor_position() itself reports KWin's logical coordinate
        # space (what _place_pointer's internal math needs); this tool's
        # contract is screenshot-pixel space, like every other coordinate
        # the model sees (observe_screen, list_windows, mouse_click's own
        # result) — converting only here keeps the low-level primitive and
        # its one caller with real precision needs (_place_pointer) exact.
        r["x"], r["y"] = kwin.to_screenshot_px(r["x"], r["y"])
    return r


@tool(
    "find_text",
    "Find text and UI labels on the screen using OCR (Tesseract). "
    "Returns bounding boxes, center coordinates (ready for mouse_click), and "
    "confidence scores. "
    "Essential for reliably finding buttons, inputs, links, and headings without "
    "guessing coordinates.",
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text or phrase to search for on screen",
            },
            "exact": {
                "type": "boolean",
                "description": "Match text exactly (case-sensitive) vs fuzzy "
                "case-insensitive substring match (default false)",
            },
            "min_confidence": {
                "type": "number",
                "description": "Minimum OCR confidence threshold 0-100 (default 40.0)",
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional [x, y, w, h] crop region to search within",
            },
        },
        "required": ["query"],
    },
    grant="screen",
    risk="read",
    needs_grant="screen",
)
def find_text(ctx, args):
    if not ctx.grants.get("screen"):
        return {"ok": False, "error": "screen grant disabled"}
    return kwin.find_text(
        query=args["query"],
        region=args.get("region"),
        exact=bool(args.get("exact", False)),
        min_confidence=float(args.get("min_confidence", 40.0)),
    )


@tool(
    "click_text",
    "Find text on screen using OCR and click directly on it in one operation. "
    "Supports single/double click, button selection, modifier keys, and optional "
    "bounding region.",
    {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text or label to find and click",
            },
            "clicks": {
                "type": "integer",
                "description": "1 (default) or 2 for double click",
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button (default 'left')",
            },
            "modifiers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional modifier keys e.g. ['ctrl']",
            },
            "exact": {
                "type": "boolean",
                "description": "Match text exactly vs substring (default false)",
            },
            "min_confidence": {
                "type": "number",
                "description": "Minimum OCR confidence threshold (default 40.0)",
            },
            "index": {
                "type": "integer",
                "description": "Match index when multiple text occurrences match on "
                "screen (0 for first, 1 for second, etc., default 0)",
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional [x, y, w, h] crop region",
            },
        },
        "required": ["text"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def click_text(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.click_text(
        query=args["text"],
        clicks=int(args.get("clicks", 1)),
        button=args.get("button", "left"),
        modifiers=args.get("modifiers"),
        region=args.get("region"),
        exact=bool(args.get("exact", False)),
        min_confidence=float(args.get("min_confidence", 40.0)),
        index=int(args.get("index", 0)),
    )
    if note:
        r["focus"] = note
    return r


@tool(
    "click_element",
    "Click an annotated visual element by its numeric badge ID [1], [2], ... "
    "as returned from observe_screen(annotate=true) or desktop_actions(annotate=true). "
    "Directly clicks the element's center without needing manual coordinate "
    "transcription.",
    {
        "type": "object",
        "properties": {
            "id": {
                "type": "integer",
                "description": "Element badge ID number, e.g. 1, 2, 5",
            },
            "clicks": {
                "type": "integer",
                "description": "Number of clicks: 1=single (default), 2=double-click, "
                "3=triple-click",
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button (default 'left')",
            },
            "modifiers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional modifier keys, e.g. ['ctrl']",
            },
        },
        "required": ["id"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def click_element(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.click_element(
        element_id=args["id"],
        button=args.get("button", "left"),
        clicks=int(args.get("clicks", 1)),
        modifiers=args.get("modifiers"),
    )
    if note:
        r["focus"] = note
    return r


@tool(
    "mouse_click",
    "Click a screen coordinate (requires uinput/ydotoold). Set clicks=2 "
    "for a double-click (e.g. to open a file/folder or select a word), or clicks=3 for "
    "a triple-click. "
    "Optionally pass modifiers like ['ctrl'], ['shift'], or ['alt'] for chord clicks "
    "(e.g. ctrl+click). "
    "Placement is closed-loop: the pointer is read back and corrected until it "
    "converges, "
    "and the result reports the measured x/y it actually clicked — read those, "
    "not your request, if a click seems to miss.",
    {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "clicks": {
                "type": "integer",
                "description": "1 (default), 2 (double-click), or 3 (triple-click)",
            },
            "modifiers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional modifier keys to hold during click, e.g. "
                '["ctrl"], ["shift"], ["alt"]',
            },
        },
        "required": ["x", "y"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def mouse_click(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.click(
        args["x"],
        args["y"],
        args.get("button", "left"),
        clicks=args.get("clicks", 1),
        modifiers=args.get("modifiers"),
    )
    if note:
        r["focus"] = note
    return r


@tool(
    "mouse_move",
    "Move the pointer to a screen coordinate (closed-loop: the "
    "result reports the measured position, with residual px off the request).",
    {
        "type": "object",
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
        "required": ["x", "y"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def mouse_move(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.move_pointer(args["x"], args["y"])
    if note:
        r["focus"] = note
    return r


@tool(
    "mouse_hover",
    "Move the pointer to a screen coordinate and hover there to trigger "
    "tooltips, hover cards, or dropdown menus without clicking.",
    {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "duration": {
                "type": "number",
                "description": "Dwell time in seconds (default 0.4)",
            },
        },
        "required": ["x", "y"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def mouse_hover(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.hover(args["x"], args["y"], duration=args.get("duration", 0.4))
    if note:
        r["focus"] = note
    return r


@tool(
    "mouse_down",
    "Press and hold mouse button (left, right, middle), optionally placing the pointer "
    "first.",
    {
        "type": "object",
        "properties": {
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button (default 'left')",
            },
            "x": {
                "type": "integer",
                "description": "Optional X coordinate to move to before pressing",
            },
            "y": {
                "type": "integer",
                "description": "Optional Y coordinate to move to before pressing",
            },
        },
        "required": [],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def mouse_down(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.mouse_down(
        button=args.get("button", "left"), x=args.get("x"), y=args.get("y")
    )
    if note:
        r["focus"] = note
    return r


@tool(
    "mouse_up",
    "Release a held mouse button (left, right, middle), optionally placing the pointer "
    "first.",
    {
        "type": "object",
        "properties": {
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button (default 'left')",
            },
            "x": {
                "type": "integer",
                "description": "Optional X coordinate to move to before releasing",
            },
            "y": {
                "type": "integer",
                "description": "Optional Y coordinate to move to before releasing",
            },
        },
        "required": [],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def mouse_up(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.mouse_up(
        button=args.get("button", "left"), x=args.get("x"), y=args.get("y")
    )
    if note:
        r["focus"] = note
    return r


@tool(
    "mouse_drag",
    "Press, drag from (x1,y1) to (x2,y2), and release the mouse button — "
    "for drag-and-drop, sliders, selection handles. Both ends are placed "
    "closed-loop; the result reports the measured start/end actually used. "
    "Set steps > 1 (e.g. steps=5) for smooth intermediate relative motion ticks.",
    {
        "type": "object",
        "properties": {
            "x1": {"type": "integer"},
            "y1": {"type": "integer"},
            "x2": {"type": "integer"},
            "y2": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "steps": {
                "type": "integer",
                "description": "Number of intermediate motion ticks (default 1)",
            },
            "smooth": {
                "type": "boolean",
                "description": "Use smooth cosine S-curve easing (default true)",
            },
        },
        "required": ["x1", "y1", "x2", "y2"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def mouse_drag(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.drag(
        args["x1"],
        args["y1"],
        args["x2"],
        args["y2"],
        button=args.get("button", "left"),
        steps=args.get("steps", 1),
        smooth=args.get("smooth", True),
    )
    if note:
        r["focus"] = note
    return r


@tool(
    "mouse_gesture",
    "Perform a continuous smooth multi-point mouse drag gesture across a sequence of "
    "waypoints [[x1, y1], [x2, y2], ...] "
    "(for drawing, canvas manipulation, directional swipes, or complex sliders).",
    {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}},
                "description": "List of 2 or more coordinate pairs [[x1, y1], [x2, "
                "y2], ...]",
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button (default 'left')",
            },
            "duration": {
                "type": "number",
                "description": "Total gesture duration in seconds (default 0.5)",
            },
            "smooth": {
                "type": "boolean",
                "description": "Use smooth cosine interpolation (default true)",
            },
        },
        "required": ["points"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def mouse_gesture(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.drag_path(
        points=args.get("points"),
        button=args.get("button", "left"),
        duration=float(args.get("duration", 0.5)),
        smooth=bool(args.get("smooth", True)),
    )
    if note:
        r["focus"] = note
    return r


@tool(
    "scroll",
    "Scroll the mouse wheel. Supports directions: 'down', 'up', 'left', 'right'. "
    "Optionally move to (x, y) first to scroll a specific pane/list (placed "
    "closed-loop).",
    {
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "description": "wheel steps (default 5)"},
            "direction": {
                "type": "string",
                "enum": ["down", "up", "left", "right"],
                "description": "Scroll direction (default 'down')",
            },
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "required": [],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def scroll(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    amt = args.get("amount", 5)
    r = kwin.scroll(
        amt, args.get("x"), args.get("y"), direction=args.get("direction", "down")
    )
    if note:
        r["focus"] = note
    return r


@tool(
    "clipboard_copy",
    "Copy text to the system clipboard (wl-copy). Prefer this over "
    "type_text for long or special-character text: copy then key_press('ctrl+v') is "
    "one "
    "reliable deposit instead of many fragile individual keystrokes.",
    {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    grant="input",
    risk="soft",
    needs_grant="input",
)
def clipboard_copy(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    return kwin.clipboard_set(args["text"])


@tool(
    "clipboard_paste",
    "Read the current system clipboard contents (wl-paste). Note this "
    "can expose whatever the user last copied elsewhere (e.g. from a password manager) "
    "— "
    "gated behind the input grant like other input-adjacent tools, not the read-only "
    "ones.",
    {"type": "object", "properties": {}},
    grant="input",
    risk="read",
    needs_grant="input",
)
def clipboard_paste(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    return kwin.clipboard_get()


@tool(
    "type_text",
    "Type text into the focused field. Set paste=true for instant and "
    "atomic text insertion (via clipboard and ctrl+v), recommended for multiline text, "
    "code snippets, long strings, or commands with flags.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "paste": {
                "type": "boolean",
                "description": "Paste atomically via clipboard (ctrl+v) instead of "
                "typing keystrokes (auto-enabled if text has newlines, >150 chars, "
                "or non-ASCII)",
            },
            "clear_before": {
                "type": "boolean",
                "description": "Select all and erase existing text before typing "
                "(default false)",
            },
        },
        "required": ["text"],
    },
    grant="input",
    risk="commit",
    needs_grant="input",
)
def type_text(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    text = args["text"]
    clear = bool(args.get("clear_before", False))
    paste_mode = args.get("paste")
    if paste_mode is None:
        paste_mode = ("\n" in text) or (len(text) > 150) or (not text.isascii())
    if paste_mode:
        if clear:
            kwin.key_press("ctrl+a")
            time.sleep(0.03)
            kwin.key_press("backspace")
            time.sleep(0.03)
        cb = kwin.clipboard_set(text)
        if not cb.get("ok"):
            r = kwin.type_text(text, clear_before=False)
        else:
            time.sleep(0.05)
            r = kwin.key_press("ctrl+v")
            if r.get("ok"):
                r["pasted"] = True
    else:
        r = kwin.type_text(text, clear_before=clear)
    if note:
        r["focus"] = note
    return r


@tool(
    "key_press",
    "Press a key or chord, e.g. 'Return', 'Escape', 'F5', 'ctrl+t', "
    "'ctrl+shift+t', 'alt+F4', 'super+d'.",
    {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "key name or modifier chord"}
        },
        "required": ["key"],
    },
    grant="input",
    risk="commit",
    needs_grant="input",
)
def key_press(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.key_press(args["key"])
    if note:
        r["focus"] = note
    return r


@tool(
    "key_down",
    "Press and hold a key or modifier down (e.g. 'ctrl', 'shift', 'alt', 'a', "
    "'Return').",
    {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key or modifier name"}
        },
        "required": ["key"],
    },
    grant="input",
    risk="commit",
    needs_grant="input",
)
def key_down(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.key_down(args["key"])
    if note:
        r["focus"] = note
    return r


@tool(
    "key_up",
    "Release a held key or modifier (e.g. 'ctrl', 'shift', 'alt', 'a', 'Return').",
    {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key or modifier name"}
        },
        "required": ["key"],
    },
    grant="input",
    risk="commit",
    needs_grant="input",
)
def key_up(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    r = kwin.key_up(args["key"])
    if note:
        r["focus"] = note
    return r


@tool(
    "desktop_actions",
    "Execute a sequence of desktop actions (click, move, hover, drag, mouse_down, "
    "mouse_up, "
    "type, key, key_down, key_up, scroll, wait, activate, maximize, minimize, close) "
    "in a single batch turn without round-trip latency. Supports window-relative "
    "coordinates (relative_to) "
    "and common action aliases (double_click, right_click, hotkey).",
    {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "description": "List of action objects to execute in sequential order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "click",
                                "move",
                                "hover",
                                "drag",
                                "mouse_down",
                                "mouse_up",
                                "type",
                                "key",
                                "key_down",
                                "key_up",
                                "scroll",
                                "wait",
                                "activate",
                                "maximize",
                                "minimize",
                                "close",
                                "move_window",
                                "resize_window",
                                "clipboard_copy",
                                "clipboard_paste",
                                "wait_for_change",
                                "double_click",
                                "triple_click",
                                "right_click",
                                "middle_click",
                                "hotkey",
                                "click_text",
                                "click_element",
                                "gesture",
                                "focus_or_launch",
                            ],
                        },
                        "x": {
                            "type": "number",
                            "description": "Target logical x coordinate",
                        },
                        "y": {
                            "type": "number",
                            "description": "Target logical y coordinate",
                        },
                        "width": {
                            "type": "number",
                            "description": "Target width for move_window / "
                            "resize_window",
                        },
                        "height": {
                            "type": "number",
                            "description": "Target height for move_window / "
                            "resize_window",
                        },
                        "button": {
                            "type": "string",
                            "enum": ["left", "middle", "right"],
                            "description": "Mouse button for click, drag, or "
                            "mouse_down/up (default 'left')",
                        },
                        "clicks": {
                            "type": "integer",
                            "description": "Number of clicks: 1=single, 2=double, "
                            "3=triple",
                        },
                        "modifiers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Modifier keys for click, e.g. ['ctrl']",
                        },
                        "start_x": {"type": "number", "description": "Drag start x"},
                        "start_y": {"type": "number", "description": "Drag start y"},
                        "end_x": {"type": "number", "description": "Drag end x"},
                        "end_y": {"type": "number", "description": "Drag end y"},
                        "steps": {
                            "type": "integer",
                            "description": "Intermediate motion ticks for drag",
                        },
                        "smooth": {
                            "type": "boolean",
                            "description": "Use smooth cosine S-curve easing for drag "
                            "(default true)",
                        },
                        "points": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "integer"}},
                            "description": "Waypoint list for gesture: [[x1, y1], [x2, "
                            "y2], ...]",
                        },
                        "app_name": {
                            "type": "string",
                            "description": "App or desktop file name for "
                            "focus_or_launch",
                        },
                        "command": {
                            "type": "string",
                            "description": "Optional launch command for "
                            "focus_or_launch",
                        },
                        "exact": {
                            "type": "boolean",
                            "description": "Exact text match for click_text (default "
                            "false)",
                        },
                        "min_confidence": {
                            "type": "number",
                            "description": "Minimum OCR confidence for click_text "
                            "(default 40.0)",
                        },
                        "index": {
                            "type": "integer",
                            "description": "Match index for click_text when multiple "
                            "occurrences exist (default 0)",
                        },
                        "region": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Crop region for click_text",
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Timeout in seconds for focus_or_launch "
                            "(default 6.0)",
                        },
                        "relative_to": {
                            "type": "string",
                            "description": "Optional window identifier ('active', "
                            "UUID, class, or caption) for window-relative "
                            "coordinates",
                        },
                        "duration": {
                            "type": "number",
                            "description": "Seconds to hover, wait, or gesture",
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to type or text to click via "
                            "click_text",
                        },
                        "paste": {
                            "type": "boolean",
                            "description": "Paste atomically via clipboard (ctrl+v) "
                            "instead of typing keystrokes",
                        },
                        "clear_before": {
                            "type": "boolean",
                            "description": "Select all and erase existing text before "
                            "typing",
                        },
                        "key": {
                            "type": "string",
                            "description": "Key or modifier chord, e.g. 'Return', "
                            "'Escape', 'Tab', 'ctrl+a'",
                        },
                        "amount": {
                            "type": "integer",
                            "description": "Wheel ticks to scroll",
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down", "left", "right"],
                            "description": "Scroll direction (default 'down')",
                        },
                        "id": {
                            "type": "string",
                            "description": "Window UUID for activate, maximize, "
                            "minimize, close",
                        },
                        "uuid": {"type": "string", "description": "Alias for id"},
                        "state": {
                            "type": "boolean",
                            "description": "State for maximize/minimize (true=apply, "
                            "false=restore)",
                        },
                    },
                    "required": ["action"],
                },
            },
            "relative_to": {
                "type": "string",
                "description": "Default window identifier ('active', UUID, class, or "
                "caption) to interpret coordinates relative to",
            },
            "stop_on_error": {
                "type": "boolean",
                "description": "Stop sequence immediately if any action fails (default "
                "true)",
            },
            "capture_after": {
                "type": "boolean",
                "description": "Capture a screenshot after all actions complete and "
                "attach to result (default true)",
            },
            "stamp_cursor": {
                "type": "boolean",
                "description": "Draw visual cursor target ring and crosshair on the "
                "resulting screenshot (default true)",
            },
            "grid": {
                "type": "boolean",
                "description": "Overlay coordinate reference grid on the resulting "
                "screenshot (default false)",
            },
            "grid_step": {
                "type": "integer",
                "description": "Pixel step for coordinate grid (default 100)",
            },
            "annotate": {
                "type": "boolean",
                "description": "Overlay Set-of-Marks numeric badge labels on the "
                "resulting screenshot (default false)",
            },
            "annotate_max": {
                "type": "integer",
                "description": "Maximum number of badge marks if annotate is true "
                "(default 50)",
            },
        },
        "required": ["actions"],
    },
    grant="input",
    risk="commit",
    needs_grant="input",
)
def desktop_actions(ctx, args):
    if not ctx.grants.get("input"):
        return {"ok": False, "error": "input grant disabled"}
    note = ensure_target_focus(ctx)
    actions = args.get("actions") or []
    if not isinstance(actions, list) or not actions:
        return {"ok": False, "error": "actions list is required and cannot be empty"}

    stop_on_error = args.get("stop_on_error", True)
    default_rel = args.get("relative_to")
    results = []

    for idx, act in enumerate(actions):
        if not isinstance(act, dict):
            res = {
                "ok": False,
                "error": f"action item at index {idx} must be an object",
            }
            results.append(res)
            if stop_on_error:
                break
            continue

        raw_action = act.get("action")
        atype = str(raw_action or "").strip().lower()
        btn = act.get("button", "left")
        clicks = act.get("clicks", 1)

        # Alias normalization
        if atype == "double_click":
            atype = "click"
            clicks = 2
        elif atype == "triple_click":
            atype = "click"
            clicks = 3
        elif atype == "right_click":
            atype = "click"
            btn = "right"
        elif atype == "middle_click":
            atype = "click"
            btn = "middle"
        elif atype == "hotkey":
            atype = "key"

        rel = act.get("relative_to") or default_rel
        x = act.get("x")
        y = act.get("y")
        rel_err = None

        if rel and x is not None and y is not None:
            trans = kwin.window_to_screen_px(rel, x, y)
            if not trans.get("ok"):
                rel_err = trans.get("error", "window translation failed")
            else:
                x = trans["x"]
                y = trans["y"]

        try:
            if rel_err:
                res = {"ok": False, "error": rel_err}
            elif atype == "click":
                if x is None or y is None:
                    res = {"ok": False, "error": "click requires 'x' and 'y'"}
                else:
                    mods = act.get("modifiers")
                    res = kwin.click(
                        x=x, y=y, button=btn, clicks=clicks, modifiers=mods
                    )
            elif atype == "move":
                if x is None or y is None:
                    res = {"ok": False, "error": "move requires 'x' and 'y'"}
                else:
                    res = kwin.move_pointer(x, y)
            elif atype == "hover":
                if x is None or y is None:
                    res = {"ok": False, "error": "hover requires 'x' and 'y'"}
                else:
                    dur = float(act.get("duration", 0.4))
                    res = kwin.hover(x, y, duration=dur)
            elif atype == "mouse_down":
                res = kwin.mouse_down(button=btn, x=x, y=y)
            elif atype == "mouse_up":
                res = kwin.mouse_up(button=btn, x=x, y=y)
            elif atype == "drag":
                sx = (
                    act.get("start_x")
                    if act.get("start_x") is not None
                    else act.get("x1")
                )
                sy = (
                    act.get("start_y")
                    if act.get("start_y") is not None
                    else act.get("y1")
                )
                ex = act.get("end_x") if act.get("end_x") is not None else act.get("x2")
                ey = act.get("end_y") if act.get("end_y") is not None else act.get("y2")
                if any(v is None for v in (sx, sy, ex, ey)):
                    res = {
                        "ok": False,
                        "error": "drag requires start_x, start_y, end_x, end_y (or x1, "
                        "y1, x2, y2)",
                    }
                else:
                    if rel:
                        ts = kwin.window_to_screen_px(rel, sx, sy)
                        te = kwin.window_to_screen_px(rel, ex, ey)
                        if not ts.get("ok"):
                            res = {
                                "ok": False,
                                "error": f"drag start relative_to error: "
                                f"{ts.get('error')}",
                            }
                        elif not te.get("ok"):
                            res = {
                                "ok": False,
                                "error": f"drag end relative_to error: "
                                f"{te.get('error')}",
                            }
                        else:
                            sx, sy = ts["x"], ts["y"]
                            ex, ey = te["x"], te["y"]
                            steps = act.get("steps", 1)
                            smooth = act.get("smooth", True)
                            res = kwin.drag(
                                sx, sy, ex, ey, button=btn, steps=steps, smooth=smooth
                            )
                    else:
                        steps = act.get("steps", 1)
                        smooth = act.get("smooth", True)
                        res = kwin.drag(
                            sx, sy, ex, ey, button=btn, steps=steps, smooth=smooth
                        )
            elif atype == "type":
                text = act.get("text", "")
                paste_mode = act.get("paste")
                clear = act.get("clear_before", False)
                if paste_mode is None:
                    paste_mode = (
                        ("\n" in text) or (len(text) > 150) or (not text.isascii())
                    )
                if paste_mode:
                    if clear:
                        kwin.key_press("ctrl+a")
                        time.sleep(0.03)
                        kwin.key_press("backspace")
                        time.sleep(0.03)
                    cb = kwin.clipboard_set(text)
                    if not cb.get("ok"):
                        res = kwin.type_text(text, clear_before=clear)
                    else:
                        time.sleep(0.05)
                        res = kwin.key_press("ctrl+v")
                        if res.get("ok"):
                            res["pasted"] = True
                else:
                    res = kwin.type_text(text, clear_before=clear)
            elif atype == "key":
                k = act.get("key", "")
                if not k:
                    res = {"ok": False, "error": "key requires 'key' property"}
                else:
                    res = kwin.key_press(k)
            elif atype == "key_down":
                k = act.get("key", "")
                if not k:
                    res = {"ok": False, "error": "key_down requires 'key' property"}
                else:
                    res = kwin.key_down(k)
            elif atype == "key_up":
                k = act.get("key", "")
                if not k:
                    res = {"ok": False, "error": "key_up requires 'key' property"}
                else:
                    res = kwin.key_up(k)
            elif atype == "scroll":
                # 5, not some other default: matches the standalone `scroll`
                # tool's default exactly, so switching a call between
                # desktop_actions and the single-action tool never silently
                # changes how far an un-specified scroll travels.
                amt = act.get("amount", 5)
                dir_ = act.get("direction", "down")
                res = kwin.scroll(amt, x=x, y=y, direction=dir_)
            elif atype == "wait":
                dur = min(max(float(act.get("duration", 0.5)), 0.0), 10.0)
                time.sleep(dur)
                res = {"ok": True, "action": "wait", "duration": dur}
            elif atype == "activate":
                wid = act.get("uuid") or act.get("id")
                if not wid:
                    res = {"ok": False, "error": "activate requires 'uuid' or 'id'"}
                else:
                    res = kwin.activate_window(wid)
                    if res.get("ok"):
                        remember_target(ctx, wid)
            elif atype == "maximize":
                wid = act.get("uuid") or act.get("id")
                state = bool(act.get("state", True))
                res = (
                    kwin.maximize_window(wid, state=state)
                    if wid
                    else {"ok": False, "error": "maximize requires 'uuid' or 'id'"}
                )
            elif atype == "minimize":
                wid = act.get("uuid") or act.get("id")
                state = bool(act.get("state", True))
                res = (
                    kwin.minimize_window(wid, state=state)
                    if wid
                    else {"ok": False, "error": "minimize requires 'uuid' or 'id'"}
                )
            elif atype == "close":
                wid = act.get("uuid") or act.get("id")
                res = (
                    kwin.close_window(wid)
                    if wid
                    else {"ok": False, "error": "close requires 'uuid' or 'id'"}
                )
            elif atype in ("move_window", "resize_window"):
                wid = act.get("uuid") or act.get("id")
                if not wid and rel:
                    # `rel` is a flexible identifier ('active', a caption/class
                    # substring, or a uuid) — passing it straight to
                    # kwin.move_window used to silently fail as "window not
                    # found: active", because the KWin script it runs only
                    # ever matches an exact internalId. Resolve it the same
                    # way window-relative coordinates already are.
                    target = kwin.resolve_window(rel)
                    wid = target.get("uuid") if target else None
                if not wid:
                    res = {
                        "ok": False,
                        "error": f"{atype} requires 'uuid', 'id', or a "
                        "'relative_to' identifier that matches an open window",
                    }
                elif x is None or y is None:
                    res = {"ok": False, "error": f"{atype} requires 'x' and 'y'"}
                else:
                    # x/y here are already absolute — the shared relative_to
                    # translation above (`if rel and x is not None and y is
                    # not None:`) already ran for every action type,
                    # including this one; re-reading act.get("x")/act.get("y")
                    # instead of these would silently throw that translation
                    # away and always move to raw, untranslated coordinates.
                    ww = act.get("width") or act.get("w")
                    wh = act.get("height") or act.get("h")
                    res = kwin.move_window(wid, x, y, w=ww, h=wh)
            elif atype == "clipboard_copy":
                txt = str(act.get("text") or "")
                res = kwin.clipboard_set(txt)
            elif atype == "clipboard_paste":
                res = kwin.clipboard_get()
            elif atype == "wait_for_change":
                to = float(act.get("timeout", 2.0))
                reg = act.get("region")
                res = kwin.wait_for_change(timeout=to, region=reg)
            elif atype == "click_text":
                t = act.get("text")
                if not t:
                    res = {"ok": False, "error": "click_text requires 'text' property"}
                else:
                    idx = int(act.get("index", 0))
                    res = kwin.click_text(
                        query=t,
                        clicks=clicks,
                        button=btn,
                        modifiers=act.get("modifiers"),
                        region=act.get("region"),
                        exact=bool(act.get("exact", False)),
                        min_confidence=float(act.get("min_confidence", 40.0)),
                        index=idx,
                    )
            elif atype == "click_element":
                eid = (
                    act.get("id")
                    if act.get("id") is not None
                    else act.get("element_id")
                )
                if eid is None:
                    res = {"ok": False, "error": "click_element requires 'id' property"}
                else:
                    res = kwin.click_element(
                        element_id=eid,
                        button=btn,
                        clicks=clicks,
                        modifiers=act.get("modifiers"),
                    )
            elif atype == "gesture":
                pts = act.get("points")
                if not pts or len(pts) < 2:
                    res = {
                        "ok": False,
                        "error": "gesture requires 'points' array with at least 2 "
                        "points",
                    }
                else:
                    clean_pts = pts
                    trans_err = None
                    if rel:
                        translated_pts = []
                        for pt in pts:
                            t_pt = kwin.window_to_screen_px(rel, pt[0], pt[1])
                            if not t_pt.get("ok"):
                                trans_err = t_pt.get("error")
                                break
                            translated_pts.append([t_pt["x"], t_pt["y"]])
                        if trans_err:
                            res = {
                                "ok": False,
                                "error": f"gesture relative_to translation error: "
                                f"{trans_err}",
                            }
                        else:
                            clean_pts = translated_pts
                    if not trans_err:
                        dur = float(act.get("duration", 0.5))
                        sm = bool(act.get("smooth", True))
                        res = kwin.drag_path(
                            clean_pts, button=btn, duration=dur, smooth=sm
                        )
            elif atype == "focus_or_launch":
                aname = act.get("app_name") or act.get("text") or act.get("app")
                if not aname:
                    res = {"ok": False, "error": "focus_or_launch requires 'app_name'"}
                else:
                    to = float(act.get("timeout", 6.0))
                    cmd = act.get("command") or _resolve_focus_launch_command(aname)
                    res = kwin.focus_or_launch(aname, timeout=to, command=cmd)
                    if res.get("ok") and res.get("window"):
                        remember_target(ctx, res["window"]["uuid"])
            else:
                res = {"ok": False, "error": f"unknown action '{raw_action}'"}
        except Exception as e:
            res = {"ok": False, "error": str(e)}

        # A batch result is read by two consumers with different needs: the
        # model (which already knows what it asked for) and the terminal-
        # card summary in argusd.tool_detail (which only ever sees `res`,
        # never the original action spec) — echoing the salient input here,
        # setdefault'd so a handler's own richer field always wins, is what
        # lets that summary show "typed 'foo'" or "pressed ctrl+s" instead of
        # a bare, undifferentiated "step 4: ok".
        if atype in ("key", "key_down", "key_up"):
            res.setdefault("key", act.get("key"))
        elif atype == "type":
            t = act.get("text", "")
            res.setdefault("text_preview", t[:60] + ("…" if len(t) > 60 else ""))
        elif atype == "scroll" and "x" not in res:
            res.setdefault("direction", act.get("direction", "down"))
            res.setdefault("amount", act.get("amount", 5))

        res["step"] = idx
        res["action"] = raw_action
        results.append(res)
        if not res.get("ok", True) and stop_on_error:
            break

    out = {
        "ok": all(r.get("ok", True) for r in results),
        "executed": len(results),
        "total": len(actions),
        "results": results,
    }
    if note:
        out["focus"] = note

    if args.get("capture_after", True):
        if not ctx.grants.get("screen"):
            out["screenshot_error"] = "screen grant disabled"
        else:
            captures_dir = ctx.data_dir / "captures"
            captures_dir.mkdir(parents=True, exist_ok=True)
            _prune_captures(captures_dir)
            p = captures_dir / f"{int(time.time() * 1000)}.png"
            stamp = bool(args.get("stamp_cursor", True))
            grid = bool(args.get("grid", False))
            grid_step = int(args.get("grid_step", 100))
            annotate = bool(args.get("annotate", False))
            annotate_max = int(args.get("annotate_max", 50))
            shot = kwin.screenshot(
                p,
                mode="fullscreen",
                stamp_cursor=stamp,
                grid=grid,
                grid_step=grid_step,
                annotate=annotate,
                annotate_max=annotate_max,
            )
            if shot.get("ok"):
                out["screenshot_path"] = shot.get("path")
                out["path"] = shot.get("path")
                out["width"] = shot.get("width")
                out["height"] = shot.get("height")
                out["scale"] = shot.get("scale")
                if grid:
                    out["grid"] = True
                    out["grid_step"] = grid_step
                if annotate:
                    out["annotated"] = shot.get("annotated", False)
                    out["elements"] = shot.get("elements", [])
            else:
                out["screenshot_error"] = shot.get("error")

    return out


# ── MCP (external tools over stdio) ───────────────────────────────────────


def _mcp_risk(annotations):
    """MCP's tool annotations are optional, unverified hints — a server can
    lie or omit them entirely — so this only ever picks a starting risk
    tier for display/bookkeeping. It does not loosen approval: DEFAULTS["mcp"]
    in policy.py prompts every un-remembered call regardless of risk tier,
    same posture as "net" (an opaque third-party capability), and the
    commit-tier check in classify() only ever forces MORE prompting, never
    less."""
    a = annotations or {}
    if a.get("destructiveHint"):
        return "commit"
    if a.get("readOnlyHint"):
        return "read"
    return "soft"


def _make_mcp_handler(server, tool_name):
    """Closure over the server/tool this REGISTRY entry was built for.
    Re-reads mcp.json on every call (not just at registration time) so a
    server disabled or removed mid-task fails the next call cleanly instead
    of continuing to talk to a config the user just turned off."""

    def handler(ctx, args):
        entry = mcp.load_config()["servers"].get(server)
        if entry is None or not entry.get("enabled"):
            return {
                "ok": False,
                "error": f"MCP server {server!r} is disabled or no longer configured",
            }
        client = ctx.mcp_clients.get(server)
        if client is None:
            client = mcp.MCPClient(
                entry.get("command", ""), entry.get("args"), entry.get("env")
            )
            try:
                client.start()
            except mcp.MCPError as e:
                return {
                    "ok": False,
                    "error": f"could not start MCP server {server!r}: {e}",
                }
            ctx.mcp_clients[server] = client
        return client.call_tool(tool_name, args)

    return handler


def _register_mcp_tools():
    """Populate REGISTRY with one entry per cached tool of every *enabled*
    MCP server in mcp.json, so the model's tool list (argusd.py's
    TOOLS = toolreg.schemas(), built right after this module imports) can
    include them without spawning a single server just to find out what it
    offers — only a tool that is actually called pays that cost (see
    _make_mcp_handler). The tool list is a cache written by mcp.probe_server
    (triggered from the Agent Panel's MCP tab or the mcp-probe CLI
    subcommand), not fetched live here.

    Wrapped so a broken mcp.json can never prevent argusd from starting —
    same "capability-detected, nothing pretends to work" posture as
    kwin.py's own capabilities().
    """
    try:
        doc = mcp.load_config()
        servers = doc.get("servers", {})
    except Exception:
        return
    for server, entry in servers.items():
        if not entry.get("enabled"):
            continue
        for spec in entry.get("tools") or []:
            name = spec.get("name")
            if not name:
                continue
            full_name = mcp.tool_full_name(server, name)
            REGISTRY[full_name] = {
                "name": full_name,
                "description": (
                    spec.get("description") or f"{name} (MCP server {server!r})"
                )[:1024],
                "parameters": spec.get("inputSchema")
                or {"type": "object", "properties": {}},
                "grant": "mcp",
                "risk": _mcp_risk(spec.get("annotations")),
                "mutates": False,
                "verify": [],
                "needs_grant": None,
                "sandboxed": False,
                "subject": (lambda ctx, args, _s=server, _t=name: [f"{_s}.{_t}"]),
                "handler": _make_mcp_handler(server, name),
            }


_register_mcp_tools()
