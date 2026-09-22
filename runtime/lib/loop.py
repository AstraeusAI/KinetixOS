"""The agent loop: perceive, plan, act, verify — one task per run()."""

import json
import os
import shutil
import time

from . import errlog, kwin, mcp, sandbox, tools as toolreg
from .checkpoints import Checkpoints
from .config import DATA, SLOW_TOOL_SECONDS
from .journal import (
    abandon_calls,
    compact,
    connect,
    context,
    event,
    get_state,
    grants,
    now,
    set_state,
)
from .out import emit
from .policy import Policy
from .render import _clip_strings, _failure_detail, _summarize_args, tool_detail
from .workspace import Workspace

# ── execution context ────────────────────────────────────────────────────


class Context:
    """Per-task toolbox handed to every tool handler."""

    def __init__(self, db, session, workspace, policy, checkpoints, g):
        """Initialize the context's stores, flags, and MCP cache."""
        self.db = db
        self.session = session
        self.workspace = workspace
        self.policy = policy
        self.checkpoints = checkpoints
        self.grants = g
        self.data_dir = DATA
        self.todos = []
        # First-written (test-count, assert-count) per test file, recorded by
        # lib/tools._record_test_baseline on every successful write/edit —
        # verify_deliverable compares against it to catch test-weakening.
        self.test_baseline = {}
        # MCP servers a tool call spawns are cached here for the rest of
        # this Context's lifetime (one task in run(), one call in approve())
        # rather than restarted on every call — see lib/tools.py's
        # _make_mcp_handler. Always stopped via lib/mcp.stop_all before this
        # Context goes out of scope (run()'s finish(), approve()'s finally).
        self.mcp_clients = {}


def verify(ctx, path):
    """Enforced post-write verification: syntax, then lint when available."""
    out = {}
    try:
        syn = toolreg.REGISTRY["syntax_check"]["handler"](ctx, {"path": path})
        out["syntax"] = {
            "ok": syn.get("ok"),
            "error": (syn.get("stderr") or syn.get("error") or "")[:600],
        }
    except Exception as e:
        out["syntax"] = {"ok": False, "error": str(e)}
    try:
        spec = ctx.workspace.tooling(ctx.workspace.resolve(path))["commands"].get(
            "lint"
        )
        if spec:
            lin = toolreg.REGISTRY["lint"]["handler"](ctx, {"path": path})
            out["lint"] = {
                "ok": lin.get("ok"),
                "output": (lin.get("stdout") or lin.get("error") or "")[:800],
            }
    except Exception as e:
        out["lint"] = {"ok": False, "error": str(e)}
    return out


# Some provider/model combinations reject any request that carries image
# content outright rather than just performing worse on it — confirmed live
# running a computer-use task against OpenRouter's free Nemotron Ultra:
# the very first observe_screen call's result was attached to context() as
# an image block, and the next provider_call died with HTTP 404 "No
# endpoints found that support image input". That is a request-shape
# rejection, not a transient failure (it is not in _RETRYABLE_HTTP and
# will reproduce identically on retry), so before the check below existed
# it killed the entire task on the very next screenshot of any computer-use
# session run against a text-only model — the model had already spent
# several tool calls making real progress (launch_app, list_windows) and
# lost all of it over a single image attachment.
_IMAGE_UNSUPPORTED_HINTS = (
    "support image",
    "image input",
    "images are not supported",
    "does not support images",
    "no endpoints found",
)


def _image_unsupported_error(exc):
    """True when an exception says the model rejects image input."""
    msg = str(exc).lower()
    return "image" in msg and any(h in msg for h in _IMAGE_UNSUPPORTED_HINTS)


def _clean_workspace_caches(root):
    """Remove tooling cache dirs (__pycache__, .pytest_cache, .ruff_cache,
    .mypy_cache) and coverage data (.coverage*) under the workspace root.
    Verification runs leave them behind and agents reliably forget to remove
    them; the runtime does it on task finish instead. Only these known
    regenerable names, best-effort."""
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            for d in list(dirnames):
                if d in ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"):
                    shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                    dirnames.remove(d)
            for fn in filenames:
                if fn == ".coverage" or fn.startswith(".coverage."):
                    try:
                        os.unlink(os.path.join(dirpath, fn))
                    except Exception:
                        pass
    except Exception:
        pass


_RANK = {"auto": 0, "prompt": 1, "deny": 2}


def _build_ws_info(ws, progress):
    """Perception preamble: probe the workspace, describe tooling + desktop
    capabilities to the model, and emit the perceive progress event.

    Extracted from run() (was CC-heavy inline boilerplate); returns the
    ws_info string context() embeds every step.
    """
    proj = ws.project()
    probe = None
    for f in ws.walk(".", limit=200):
        if f.suffix in (
            ".py",
            ".qml",
            ".ts",
            ".js",
            ".rs",
            ".c",
            ".cpp",
            ".sh",
            ".lua",
        ):
            probe = f
            break
    tooling = ws.tooling(probe)["commands"] if probe else {}
    available = {k: " ".join(v) for k, v in tooling.items() if v}
    missing = [k for k, v in tooling.items() if not v]
    # Tell the model what the desktop can actually do, so it reports a missing
    # capability instead of burning steps retrying something that cannot work.
    caps = kwin.capabilities()
    desktop = (
        f"screen capture={'yes' if caps['screenshots'] else 'NO'}, "
        f"window inventory={'yes' if caps['window_inventory'] else 'NO'}, "
        f"window control={'yes' if caps['window_control'] else 'NO'}, "
        f"keyboard input={'yes' if caps['keyboard'] else 'NO'}, "
        f"pointer input={'yes' if caps['pointer'] else 'NO'}"
    )
    if not caps["keyboard"]:
        desktop += f" — keyboard unavailable: {caps['keyboard_detail']}"
    if not caps["pointer"]:
        desktop += f" — pointer unavailable: {caps['pointer_detail']}"
    # Unlike node's npm test / cargo's cargo test, Python's test runner
    # can't be inferred from a project marker file — pytest vs. plain
    # unittest.discover depends only on what's actually importable, and
    # Python needs no marker at all to be a valid choice, so a brand-new/
    # empty workspace gives the probe-file-based `available` detection
    # above nothing to go on for it specifically. Reported unconditionally,
    # not gated behind finding a .py file first, so the model knows which
    # style to write *before* writing its first test — confirmed live:
    # without this, in an empty workspace with pytest not installed, the
    # model defaulted to writing pytest-style tests (the idiomatic default)
    # and they failed to even import when run_tests actually ran them.
    py_test_cmd = Workspace._python_test_cmd()
    py_test_line = (
        "Python test runner: "
        + (
            " ".join(py_test_cmd)
            if py_test_cmd
            else "none installed — do NOT `import pytest`; write plain "
            "unittest.TestCase tests"
        )
        + "\n"
    )
    ws_info = (
        f"Workspace root: {ws.root}\nProject kind: {proj['kind']}\n"
        f"Available verification commands: {available or 'none'}\n"
        + (
            f"Not installed (do not try these): {', '.join(missing)}\n"
            if missing
            else ""
        )
        + py_test_line
        + f"Desktop capabilities: {desktop}\n"
        + "If a capability is NO, say so plainly instead of retrying it.\n"
        + "Sandbox: "
        + (
            "bwrap + cgroup limits"
            if sandbox.available()
            else "UNAVAILABLE — commands run unsandboxed"
        )
    )
    progress(
        "perceive",
        f"Workspace {ws.root} · {proj['kind']} · sandbox={sandbox.available()}"
        + (f" · verify: {', '.join(available)}" if available else ""),
    )
    return ws_info


def _finish_nudges(db, session, choice, todos, st, step_idx, max_steps):
    """One-shot stop-time nudges: unfinished todos, then missing verification.

    Returns ``(user_message, progress_summary)`` to inject (caller journals
    the user event, emits progress, and continues the step loop), or None to
    let the turn finish normally. `st` is run()'s mutable flag bag:
    {"nudged_todos", "nudged_verify", "mutated_testable", "ran_tests"}.
    """
    pending = [t for t in todos if t.get("status") != "completed"]
    if pending and not st["nudged_todos"] and step_idx < max_steps - 1:
        st["nudged_todos"] = True
        items = "; ".join(t.get("content", "") for t in pending[:5])
        event(db, session, "assistant", {"text": choice.get("content") or ""})
        return (
            "Your own plan (todo_write) still has "
            f"unfinished items: {items}. Continue and finish "
            "them, or call todo_write to update the plan if "
            "they are no longer needed, before stopping.",
            "unfinished todo items — continuing instead of stopping",
        )
    if (
        st["mutated_testable"]
        and not st["ran_tests"]
        and not st["nudged_verify"]
        and step_idx < max_steps - 1
    ):
        st["nudged_verify"] = True
        event(db, session, "assistant", {"text": choice.get("content") or ""})
        return (
            "You edited code in a project that has a "
            "test command available, but never ran run_tests. "
            "If this change has real logic behind it, verify it "
            "now before finishing; if it was genuinely a trivial "
            "change (config, comments, a rename) say so and "
            "finish.",
            "no test run yet — continuing instead of stopping",
        )
    return None


def _policy_subjects(spec, ctx, args):
    """Every path-like value the policy should judge for this call.

    Which argument holds the subject is declared by the tool itself
    (`subject=` in lib/tools.py) rather than assumed to be `path`, because
    assuming it meant move_file (src/dst) and checkpoint_restore (id) were
    classified with no subject at all.
    """
    declared = spec.get("subject")
    if callable(declared):
        return [s for s in (declared(ctx, args) or []) if s]
    names = declared if isinstance(declared, (list, tuple)) else ("path",)
    return [args.get(n) for n in names if args.get(n)]


def policy_decision(policy, spec, ctx, args):
    """The policy verdict for one tool call.

    Every path-like subject the tool declares is judged, and the strictest
    verdict wins (deny > prompt > auto) — a move has two, src and dst, and
    approving the source says nothing about the destination. run_command's
    `net` flag is a capability request the base "exec" classification never
    sees ($SAFE/$WORKSPACE patterns only look at the command text), so it can
    only escalate, never downgrade: a command already denied or already
    prompting stays that way.
    """
    decision, reason = "auto", ""
    for subject in _policy_subjects(spec, ctx, args) or [None]:
        d, r = policy.classify(
            spec["grant"],
            path=subject,
            command=args.get("command"),
            tool=spec["name"],
            risk=spec["risk"],
        )
        if _RANK[d] > _RANK[decision]:
            decision, reason = d, r
    if spec["name"] == "run_command" and args.get("net") and decision == "auto":
        decision, reason = policy.classify("net", command=args.get("command"))
    # Every exec-grant tool that takes no free-text `command` argument
    # (syntax_check, lint, format_file, run_tests — only run_command takes
    # one) dispatches to a fixed command it assembles itself from trusted
    # Python logic (see Workspace.tooling()/_python_test_cmd() and the
    # per-language branches in syntax_check/format_file), never from
    # model-supplied shell text. There is no injection surface for $SAFE to
    # be guarding here in the first place — but classify()'s exec-grant path
    # only ever auto-approves via a $SAFE match against `command`, so with
    # none to check these tools fell through to "exec outside the
    # auto-approved scope" on every single call, prompting exactly like a
    # risk="commit" action regardless of their own declared risk tier.
    # Confirmed live twice: a run_tests call stopped a real eval task dead at
    # "run the tests and confirm they pass", and — after that first instance
    # was fixed as a run_tests-only special case — the *same* mismatch showed
    # up again on syntax_check in a second, unrelated eval, which is why this
    # is now general rather than one more name check. Each of these tools'
    # own handler already calls Workspace.resolve(path, must_exist=True),
    # which refuses any path outside the workspace before this is reached, so
    # nothing left unauto'd here is still actually undecided — downgrade only
    # the specific "exec outside the auto-approved scope"/"exec requires
    # approval" prompts this mismatch produces, never a real deny from a
    # hard-deny rule or saved policy memory.
    if (
        spec["grant"] == "exec"
        and "command" not in spec["parameters"].get("properties", {})
        and decision == "prompt"
        and reason.startswith("exec ")
    ):
        decision, reason = (
            "auto",
            f"auto: {spec['name']} is a fixed, sandboxed, workspace-scoped action",
        )
    return decision, reason


# A model that repeats the exact same call *back to back* is flailing, not
# making progress. This used to count cumulatively over the whole task instead
# of consecutively — so a zero/fixed-argument tool that's legitimately called
# more than once over a longer task (observe_screen, active_window,
# list_windows: exactly what the system prompt itself tells the model to do
# for verification) got falsely flagged as a stuck duplicate on its second
# use, no matter how much unrelated, useful work happened in between.
# Tracking only the single most recent signature (reset the moment a
# different call happens) still catches the actual flailing pattern — the
# same call with nothing else in between — without penalizing ordinary
# spaced-out reuse. Hard stop: below this threshold the model is redirected
# with the previous result instead of aborted (see _dispatch_calls).
_REPEAT_ABORT = 5


def _dispatch_calls(
    db,
    session,
    ctx,
    policy,
    g,
    calls,
    progress,
    finish,
    step_idx,
    st,
    tool_durations,
    stream,
):
    """Execute one assistant turn's tool calls.

    Returns the finish() payload when the turn must end the whole run
    (stuck-repeat abort or an approval prompt), or None when every call was
    handled and the step loop should continue. `st` is run()'s shared mutable
    bag (flail tracking + verification flags); `finish` is run()'s closure so
    approval/stuck exits journal exactly as before.
    """
    for c_idx, c in enumerate(calls):
        name = c["function"]["name"]
        try:
            args = json.loads(c["function"].get("arguments") or "{}")
        except Exception:
            args = {}
        cid = c.get("id", str(now()))
        spec = toolreg.REGISTRY.get(name)
        if not spec:
            result = {"ok": False, "error": "unknown tool: " + name}
            event(db, session, "tool", {"id": cid, "name": name, "result": result})
            progress("act", f"{name} (unknown tool)", "blocked", id=cid)
            continue

        sig = name + ":" + json.dumps(args, sort_keys=True)
        st["consecutive"] = st["consecutive"] + 1 if sig == st["last_sig"] else 1
        st["last_sig"] = sig
        if st["consecutive"] >= _REPEAT_ABORT:
            last = st["last_results"].get(sig, {})
            errlog.warning(
                "task_stuck_repeat",
                session=session,
                step=step_idx,
                tool=name,
                args=_summarize_args(args),
                repeats=st["consecutive"],
                last_result=_clip_strings(last, 300),
            )
            abandon_calls(
                db,
                session,
                calls,
                c_idx,
                "not executed — the runtime stopped this task as stuck",
                progress,
            )
            return finish(
                f"Stopped: {name} was called {st['consecutive']} times in a row with "
                f"identical arguments and is not making progress. Last result: "
                f"{json.dumps(last)[:300]}",
                ok=False,
            )
        if st["consecutive"] >= 2:
            # Correct rather than abort: hand the model the previous result
            # plus explicit guidance, and let it choose a different action.
            result = {
                "ok": False,
                "error": f"duplicate call: {name} was already called with "
                f"these exact arguments. The result is unchanged.",
                "previous_result": st["last_results"].get(sig, {}),
                "guidance": "Do not repeat this call. Take a different "
                "action, or report the blocker if none is possible.",
            }
            event(db, session, "tool", {"id": cid, "name": name, "result": result})
            progress("act", f"{name} (duplicate — redirected)", "blocked", id=cid)
            continue

        ng = spec.get("needs_grant")
        if ng and not g.get(ng):
            result = {"ok": False, "error": ng + " grant disabled"}
            event(db, session, "tool", {"id": cid, "name": name, "result": result})
            progress("act", f"{name} (blocked: no {ng} grant)", "blocked", id=cid)
            continue

        decision, reason = policy_decision(policy, spec, ctx, args)
        if decision == "deny":
            result = {"ok": False, "error": "policy: " + reason}
            event(db, session, "tool", {"id": cid, "name": name, "result": result})
            progress("act", f"{name} denied — {reason}", "blocked", id=cid)
            continue
        if decision == "prompt":
            aid = f"a-{now()}"
            # call_id is the model's own tool_call id: the resumed turn's
            # history declares that id, so the result approve() journals has
            # to answer *that* call, not the approval handle.
            db.execute(
                "INSERT INTO approvals(id,ts,tool,args,status,session,call_id) "
                "VALUES(?,?,?,?,?,?,?)",
                (aid, now(), name, json.dumps(args), "pending", session, cid),
            )
            db.commit()
            progress("act", f"{name} awaiting approval", "blocked", id=cid)
            # Answer this call right away with a placeholder that approve()
            # later overwrites. Both halves matter: a turn whose declared
            # calls are not all answered is rejected by the provider, and so
            # is a call answered twice — and the resume cannot happen until
            # the user decides, so the placeholder is what keeps the journal
            # consistent in between.
            event(
                db,
                session,
                "tool",
                {
                    "id": cid,
                    "name": name,
                    "result": {
                        "ok": False,
                        "pending_approval": True,
                        "error": f"awaiting user approval ({aid})",
                    },
                },
            )
            # A sibling call in the same turn will not run while this one
            # waits; it still has to be answered in the journal.
            abandon_calls(
                db,
                session,
                calls,
                c_idx + 1,
                "not executed — a sibling call in the same turn is awaiting "
                "approval; re-issue it after the approval if it is still needed",
                progress,
            )
            return finish(
                f"Approval required: {name}",
                approval={
                    "id": aid,
                    "summary": name + " " + json.dumps(args)[:200],
                    "risk": spec["risk"],
                    "reason": reason,
                },
            )

        # Marks the live tool-call card "running" between the streamed
        # arguments finishing and the handler actually returning — the gap
        # can be seconds for run_command, and without this the card just
        # sits there with no sign the runtime picked it up.
        progress("act", f"{name} running…", "ok", id=cid)

        tool_t0 = time.time()
        crashed = False
        try:
            result = spec["handler"](ctx, args)
        except PermissionError as e:
            # Expected, model-facing failures (bad path, missing file) —
            # not a runtime bug, so no traceback, just a plain record.
            result = {"ok": False, "error": str(e)}
        except FileNotFoundError as e:
            result = {"ok": False, "error": "not found: " + str(e)}
        except Exception as e:
            # traceback.format_exc() only sees anything while the except
            # block that caught it is still on the stack, so the log call
            # has to happen here — not after the try/except returns, by
            # which point sys.exc_info() has already been cleared and
            # every traceback comes back empty.
            result = {"ok": False, "error": "tool crashed: " + str(e)}
            crashed = True
            errlog.exception(
                "tool_crashed",
                e,
                tool=name,
                session=session,
                step=step_idx,
                args=_summarize_args(args),
                seconds=round(time.time() - tool_t0, 2),
            )
        tool_dur = time.time() - tool_t0
        td = tool_durations.setdefault(name, {"count": 0, "seconds": 0.0})
        td["count"] += 1
        td["seconds"] += tool_dur

        if not crashed and not result.get("ok"):
            # Not every ok:false result is a bug (a lint failure or a bad
            # regex is the model's mistake, not the runtime's), but logging
            # all of them costs nothing and means a *systemic* one — a
            # sandbox timeout, a policy the model keeps tripping, a tool
            # that's silently broken — shows up as a repeated `event` in
            # the log instead of only ever being visible in the one
            # journal entry that gets compacted away.
            # _failure_detail(), not str(result.get("error")): run_tests/
            # run_command have no "error" key at all on a normal non-zero
            # exit (see _failure_detail's own docstring) — their failure
            # lives in stdout/stderr. The naive version logged the
            # literal string "None" for every one of those, which is
            # exactly the case this log exists to make diagnosable
            # (confirmed live: chased a run_tests loop through this log
            # during an eval and got nothing but "error: None" for it).
            errlog.warning(
                "tool_failed",
                tool=name,
                session=session,
                step=step_idx,
                error=_failure_detail(result)[:500],
                args=_summarize_args(args),
                seconds=round(tool_dur, 2),
            )
        if tool_dur > SLOW_TOOL_SECONDS:
            errlog.warning(
                "slow_tool_call",
                tool=name,
                session=session,
                step=step_idx,
                seconds=round(tool_dur, 2),
                args=_summarize_args(args),
            )

        if name == "todo_write" and result.get("ok") and stream:
            emit({"type": "todos", "todos": ctx.todos})

        if spec["mutates"] and result.get("ok") and args.get("path"):
            v = verify(ctx, args["path"])
            result["verify"] = v
            ok = v.get("syntax", {}).get("ok")
            progress(
                "verify",
                f"{name} → syntax {'ok' if ok else 'FAILED'}"
                + (" · lint ok" if v.get("lint", {}).get("ok") else ""),
                "ok" if ok else "blocked",
                id=cid,
            )
            if not st["mutated_testable"]:
                try:
                    p = ctx.workspace.resolve(args["path"])
                    if ctx.workspace.tooling(p)["commands"].get("test"):
                        st["mutated_testable"] = True
                except Exception:
                    pass
        if name == "run_tests":
            st["ran_tests"] = True

        st["last_results"][sig] = result
        event(db, session, "tool", {"id": cid, "name": name, "result": result})
        summary = name
        if name in ("edit_file", "write_file", "multi_edit"):
            summary = f"{name} {result.get('path', '')}"
        elif name == "run_command":
            summary = f"run_command: {str(args.get('command', ''))[:60]}"
        progress(
            "act",
            summary,
            "ok" if result.get("ok") else "blocked",
            id=cid,
            detail=tool_detail(name, result),
        )
    return None


def run(task, session, workspace_root, stream=False, is_continuation=False):
    """Execute one task end to end: journal, loop tools, return the result."""
    import argusd as _facade

    provider_call = _facade.provider_call
    MAX_STEPS = _facade.MAX_STEPS
    MAX_TASK_SECONDS = _facade.MAX_TASK_SECONDS
    MAX_STREAM_TRUNCATIONS = _facade.MAX_STREAM_TRUNCATIONS
    db = connect()
    event(db, session, "user", {"text": task})
    # `is_continuation` is only true for the synthetic "Continue the previous
    # task..." message approve() sends after a resumed approval — the same
    # task still in flight, not a new instruction. A real new task replaces
    # the pinned anchors so a stale plan from a previous, unrelated request
    # can't leak forward and get mistaken for the current one; a continuation
    # leaves them alone so the task and plan survive the resume.
    if is_continuation:
        saved_todos = get_state(db, session, "todos") or "[]"
        task_started = float(get_state(db, session, "task_started") or time.time())
        steps_used = int(get_state(db, session, "task_steps") or 0)
    else:
        task_started = time.time()
        steps_used = 0
        set_state(db, session, "current_task", task)
        set_state(db, session, "todos", "[]")
        set_state(db, session, "task_started", task_started)
        set_state(db, session, "task_steps", steps_used)
        saved_todos = "[]"
    try:
        ws = Workspace(workspace_root)
    except Exception as e:
        return {"ok": False, "text": f"⚠️ Invalid workspace: {e}"}
    policy = Policy(ws.root)
    cps = Checkpoints(session)
    g = grants()
    ctx = Context(db, session, ws, policy, cps, g)
    try:
        ctx.todos = json.loads(saved_todos)
    except Exception:
        ctx.todos = []
    if stream and ctx.todos:
        emit({"type": "todos", "todos": ctx.todos})
    comp = compact(db, session)
    events = []
    started = time.time()

    def progress(kind, summary, status="ok", id=None, detail=None):
        """Record one action-feed event and stream it when --stream is on."""
        e = {"kind": kind, "summary": summary, "status": status}
        if id is not None:
            e["id"] = id
        if detail is not None:
            e["detail"] = detail
        events.append(e)
        if stream:
            emit({"type": "event", **e})

    # Fired for every streamed provider delta (prose tokens, tool-call name/
    # arguments as the model generates them). A no-op when not streaming, so
    # the SSE parsers never need to know whether anyone is listening.
    def stream_cb(evt):
        """Forward a provider stream event to NDJSON stdout when streaming."""
        if stream:
            emit(evt)

    def finish(text, ok=True, **extra):
        """Every exit path goes through here, so the journal always ends with
        the assistant's final words — a truncated journal made the panel look
        like it had silently died."""
        mcp.stop_all(ctx.mcp_clients)
        _clean_workspace_caches(ws.root)
        event(db, session, "assistant", {"text": text})
        res = {
            "ok": ok,
            "text": text,
            "events": events,
            "compaction": comp,
            "todos": ctx.todos,
        }
        res.update(extra)
        return res

    # Tell the model what it is working with before it starts guessing:
    # the root, the project kind, and which verify commands actually exist.
    ws_info = _build_ws_info(ws, progress)

    # Nudge (at most once per run) rather than trust a stop that leaves the
    # model's own plan half-done: a model that quietly abandons pending
    # todo_write items and starts chatting is drifting off task just as much
    # as one that wanders into unrelated work mid-stream. Same one-shot idea
    # for verification (see _finish_nudges); flags live in the shared bag.
    st = {
        "nudged_todos": False,
        "nudged_verify": False,
        "mutated_testable": False,
        "ran_tests": False,
        "last_sig": None,
        "consecutive": 0,
        "last_results": {},
    }

    # A mid-stream connection drop after real content already arrived (see
    # _DURABLE_STREAM_EVENT_TYPES) used to kill the whole task outright —
    # confirmed live twice ("Upstream idle timeout exceeded" against a slow
    # free model), discarding whatever the model had already written.
    # provider_call now salvages that partial text instead of raising (see
    # _stream_openai_chat/_stream_anthropic), and this just bounds how many
    # times in a row this task will accept "keep going from a drop" before
    # giving up for real — a persistently flaky connection should still end
    # the task rather than silently eat the whole step budget retrying.
    stream_truncations = 0

    # Per-tool timing, kept only to explain *why* a task ran out of budget —
    # "stopped after 600s" alone doesn't say whether that was one slow
    # run_command or twenty ordinary steps. Logged (never shown to the model)
    # whenever the task is stopped by a limit rather than finishing cleanly.
    tool_durations = {}
    provider_seconds = 0.0

    def _log_budget_incident(event_name, **extra):
        """Log why a task hit a step/time limit (never shown to the model)."""
        errlog.warning(
            event_name,
            session=session,
            step=step_idx,
            elapsed=round(time.time() - started, 2),
            provider_seconds=round(provider_seconds, 2),
            tool_durations={
                k: {"count": v["count"], "seconds": round(v["seconds"], 2)}
                for k, v in tool_durations.items()
            },
            last_tool=st.get("last_sig"),
            **extra,
        )

    for step_idx in range(steps_used, MAX_STEPS):
        set_state(db, session, "task_steps", step_idx + 1)
        task_elapsed = time.time() - task_started
        if task_elapsed > MAX_TASK_SECONDS:
            _log_budget_incident(
                "task_budget_exceeded",
                budget_seconds=MAX_TASK_SECONDS,
                task_elapsed=round(task_elapsed, 2),
            )
            return finish(
                f"Stopped after the {MAX_TASK_SECONDS}s cumulative task budget. "
                "Partial progress is in the action feed.",
                ok=False,
            )
        # A single run() can itself emit far more than MAX_CONTEXT_EVENTS
        # (an assistant + tool event per step, up to MAX_STEPS steps), so
        # compaction must be re-checked every step, not just once at entry —
        # otherwise the original task can scroll out of context() mid-task.
        c = compact(db, session)
        if c:
            comp = c
        remaining = MAX_STEPS - step_idx
        step_info = None
        if remaining <= 5:
            step_info = (
                f"Step budget: {step_idx + 1} of {MAX_STEPS} used this task, "
                f"{remaining} left. If the work is close to done, stop exploring "
                "and wrap up now: verify what you changed and report the outcome "
                "before the budget runs out mid-action."
            )
        provider_t0 = time.time()
        try:
            reply = provider_call(context(db, session, ws_info, step_info), stream_cb)
        except Exception as e:
            if (
                _image_unsupported_error(e)
                and get_state(db, session, "no_image_support") != "1"
            ):
                # One-shot self-heal: strip images and retry this same step
                # rather than aborting the whole task over one screenshot —
                # see the comment on _image_unsupported_error. Guarded by the
                # state flag so a *different*, genuinely fatal request error
                # still fails the task instead of looping.
                set_state(db, session, "no_image_support", "1")
                errlog.warning(
                    "model_lacks_image_support",
                    session=session,
                    step=step_idx,
                    detail=str(e)[:300],
                )
                progress(
                    "act",
                    "current model can't accept image input — continuing "
                    "without screenshots",
                    "ok",
                )
                continue
            errlog.exception(
                "provider_call_failed",
                e,
                session=session,
                step=step_idx,
                elapsed=round(time.time() - started, 2),
            )
            return finish("⚠️ " + str(e), ok=False)
        provider_seconds += time.time() - provider_t0
        if reply.get("_stream_truncated"):
            stream_truncations += 1
            text = (reply.get("choices", [{}])[0].get("message", {}) or {}).get(
                "content"
            ) or ""
            if text:
                event(db, session, "assistant", {"text": text})
            reason = str(reply.get("_truncation_reason", "connection interrupted"))[
                :200
            ]
            errlog.warning(
                "stream_truncated_recovered",
                session=session,
                step=step_idx,
                reason=reason,
                recovered_chars=len(text),
                attempt=stream_truncations,
            )
            if stream_truncations > MAX_STREAM_TRUNCATIONS:
                return finish(
                    f"⚠️ The connection to the model kept dropping mid-reply "
                    f"({stream_truncations} times this task) — stopping instead "
                    "of retrying indefinitely. Partial progress is in the "
                    "action feed.",
                    ok=False,
                )
            progress(
                "act",
                "connection dropped mid-reply — continuing from what was received",
                "ok",
                detail=reason,
            )
            event(
                db,
                session,
                "user",
                {
                    "text": "Your last reply was cut off mid-stream by "
                    "a connection drop. Continue exactly where you left "
                    "off — do not restart or repeat what you already said."
                },
            )
            continue
        choice = reply.get("choices", [{}])[0].get("message", {})
        calls = choice.get("tool_calls", [])
        if not calls:
            nudge = _finish_nudges(
                db, session, choice, ctx.todos, st, step_idx, MAX_STEPS
            )
            if nudge is not None:
                nudge_text, nudge_summary = nudge
                event(db, session, "user", {"text": nudge_text})
                progress("act", nudge_summary, "ok")
                continue
            return finish(choice.get("content") or "(The model returned no text.)")
        event(db, session, "assistant", {"text": "", "tool_calls": calls})

        done = _dispatch_calls(
            db,
            session,
            ctx,
            policy,
            g,
            calls,
            progress,
            finish,
            step_idx,
            st,
            tool_durations,
            stream,
        )
        if done is not None:
            return done

    step_idx = max(steps_used - 1, MAX_STEPS - 1)
    _log_budget_incident("task_step_limit_exceeded", step_budget=MAX_STEPS)
    return finish(
        f"Stopped after {MAX_STEPS} tool steps without finishing. "
        "The action feed shows what was attempted.",
        ok=False,
    )
