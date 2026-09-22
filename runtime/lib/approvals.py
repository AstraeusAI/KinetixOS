"""Approval flow: resolve a pending approval, execute, and resume."""

import json

from . import mcp, tools as toolreg
from .checkpoints import Checkpoints
from .journal import connect, grants, journal_approval_outcome
from .loop import Context, _policy_subjects, run
from .out import emit
from .policy import Policy
from .render import _failure_detail, tool_detail
from .workspace import Workspace


def approve(
    approval_id, allow, workspace_root, resume=True, stream=False, always=False
):
    """Resolve a pending approval; optionally execute and resume the task."""
    db = connect()
    row = db.execute(
        "SELECT tool,args,status,session,call_id FROM approvals WHERE id=?",
        (approval_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "text": "Approval no longer exists."}
    tool, raw, status, session, call_id = row
    session = session or "default"
    # Answer the model's own tool_call when it is known — see run()'s INSERT.
    # Older pending approvals (and any row from before this column existed) fall
    # back to the approval id, which is what the journal used before.
    answer_id = call_id or approval_id
    if status != "pending":
        return {"ok": False, "text": "Approval was already resolved."}
    args = json.loads(raw)
    if not allow:
        db.execute("UPDATE approvals SET status='denied' WHERE id=?", (approval_id,))
        db.commit()
        journal_approval_outcome(
            db, session, answer_id, tool, {"ok": False, "error": "denied by user"}
        )
        e = {
            "kind": "commit",
            "summary": tool + " denied",
            "status": "blocked",
            "id": approval_id,
        }
        if stream:
            emit({"type": "event", **e})
        return {
            "ok": True,
            "text": "Action denied and retained in the audit journal.",
            "events": [e],
        }
    if stream:
        emit(
            {
                "type": "event",
                "kind": "commit",
                "summary": f"{tool} running…",
                "status": "ok",
                "id": approval_id,
            }
        )
    ctx = None
    try:
        ws = Workspace(workspace_root)
        policy = Policy(ws.root)
        ctx = Context(db, session, ws, policy, Checkpoints(session), grants())
        spec = toolreg.REGISTRY.get(tool)
        result = (
            spec["handler"](ctx, args)
            if spec
            else {"ok": False, "error": "unknown tool"}
        )
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    finally:
        # A resumed approval executes exactly one tool call, so there is no
        # reason to keep whatever MCP server it spawned alive after —
        # unlike run()'s finish(), which amortizes a server across a whole
        # task's worth of calls.
        if ctx is not None:
            mcp.stop_all(ctx.mcp_clients)
    if tool == "todo_write" and result.get("ok") and stream:
        emit({"type": "todos", "todos": ctx.todos})
    db.execute(
        "UPDATE approvals SET status=? WHERE id=?",
        ("executed" if result.get("ok") else "blocked", approval_id),
    )
    db.commit()
    journal_approval_outcome(db, session, answer_id, tool, result)

    # "Always allow" persists a rule keyed on the exact subject that was
    # approved (never a wildcard) — see policy.py's `_matches`. This must use
    # the tool's own declared `subject=` (via _policy_subjects, the same
    # derivation policy_decision() itself judges the call against), not just
    # args["command"]/args["path"]: confirmed live, approving an MCP tool
    # call with --always executed it but silently left no rule behind — its
    # subject is a callable producing "server.tool" (lib/tools.py's
    # _register_mcp_tools), which neither literal argument name matches, so
    # the very next identical call prompted again as if `always` had done
    # nothing. run_command has no declared subject at all (classify() reads
    # its command text directly instead), so the literal-argument fallback
    # stays for it and for any other tool in the same position. A
    # computer-use commit action (type_text, key_press, ...) has neither a
    # declared subject nor a command/path argument, so `always` still
    # behaves like a one-time approval for those, same as before.
    if always and result.get("ok"):
        subjects = list(_policy_subjects(spec, ctx, args)) if spec else []
        if not subjects:
            legacy = args.get("command") or args.get("path")
            if legacy:
                subjects = [legacy]
        for subject in subjects:
            policy.remember(subject, True)

    ev = {
        "kind": "commit",
        "summary": tool,
        "status": "ok" if result.get("ok") else "blocked",
        "id": approval_id,
        "detail": tool_detail(tool, result),
    }
    if stream:
        emit({"type": "event", **ev})
    out = {
        "ok": bool(result.get("ok")),
        "text": "Approved action completed."
        if result.get("ok")
        else "Approved action failed closed: " + _failure_detail(result),
        "events": [ev],
    }

    # Resume the conversation. Without this the task simply stops at the
    # approval and the user has to re-send it — which makes multi-step
    # computer use (ctrl+l, then type) unusable.
    if resume and result.get("ok"):
        try:
            cont = run(
                f"Continue the previous task. The approved action "
                f"({tool}) executed successfully. Take the next step, or "
                f"report the outcome if the task is complete.",
                session,
                workspace_root,
                stream=stream,
                is_continuation=True,
            )
            out["events"] = out["events"] + (cont.get("events") or [])
            out["text"] = cont.get("text") or out["text"]
            out["ok"] = cont.get("ok", out["ok"])
            if cont.get("approval"):
                out["approval"] = cont["approval"]
            if cont.get("todos"):
                out["todos"] = cont["todos"]
        except Exception as e:
            out["text"] = out["text"] + f" (could not resume: {e})"
    return out
