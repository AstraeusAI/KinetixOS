"""Tool-result formatting: model-facing JSON clipping and terminal cards."""

import json


def _clip_strings(value, cap):
    """Truncate long strings in a tool result, wherever they sit."""
    if isinstance(value, str):
        if len(value) <= cap:
            return value
        return value[:cap] + f"\n… [truncated: {len(value) - cap} more characters]"
    if isinstance(value, list):
        return [_clip_strings(v, cap) for v in value]
    if isinstance(value, dict):
        return {k: _clip_strings(v, cap) for k, v in value.items()}
    return value


_RESULT_KEEP_KEYS = (
    "ok",
    "path",
    "error",
    "name",
    "id",
    "count",
    "truncated",
    "lines",
    "shown",
    "language",
    "code",
)


def _summarize_args(args, cap=300):
    """Tool arguments, bounded for the incident log — a write_file call's
    `content` can be megabytes; the log needs enough to identify the call,
    not the payload itself."""
    return _clip_strings(args, cap)


def tool_result_text(result, limit=20_000):
    """The tool result as the model receives it: valid JSON, always.

    This used to be `json.dumps(res)[:limit]` — a slice of serialized JSON cuts
    whatever field is long enough to reach the boundary, so the model was handed
    a broken object (verified: `json.loads` on a truncated read_file result
    raises "Unterminated string", with the cut landing in the middle of the file
    content). Truncating has to happen at field level, before serializing, so
    what arrives is parseable and says what was dropped.
    """
    text = json.dumps(result)
    if len(text) <= limit:
        return text
    slim = _clip_strings(result, max(600, limit // 4))
    if len(json.dumps(slim)) <= limit:
        return json.dumps(slim)
    if not isinstance(slim, dict):
        return json.dumps(
            {
                "ok": False,
                "truncated": True,
                "note": "tool result exceeded the size limit and was dropped; "
                "re-run the call with a narrower scope",
            }
        )
    # Still too large: drop the payload fields, biggest first, keeping the
    # identity/metadata keys the model needs to understand what happened.
    for key in sorted(slim, key=lambda k: -len(json.dumps(slim.get(k, "")))):
        if len(json.dumps(slim)) <= limit:
            break
        if key in _RESULT_KEEP_KEYS:
            continue
        slim[key] = (
            "[omitted — this result exceeded the size limit; re-run the call "
            "with a narrower range (offset/limit, a smaller path, fewer results)]"
        )
    if len(json.dumps(slim)) <= limit:
        return json.dumps(slim)
    return json.dumps(
        {
            "ok": False,
            "truncated": True,
            "note": "tool result exceeded the size limit and was dropped; "
            "re-run the call with a narrower scope",
        }
    )


# ANSI red for stderr/errors so the panel's terminal card (TerminalCard.qml,
# which renders SGR color codes as QML rich text — deliberately not xterm.js,
# see docs/07) shows failures in-place rather than needing a separate status line.
_ANSI_RED, _ANSI_RESET = "\x1b[31m", "\x1b[0m"

_SIMPLE_DIFF_TOOLS = frozenset({"edit_file", "write_file", "multi_edit"})
_LINT_TOOLS = frozenset({"syntax_check", "lint", "format_file"})


def _detail_desktop_action_line(i, r):
    """One formatted line for step `i` of a desktop_actions batch."""
    act = r.get("action", "step")
    ok_marker = "\u2713" if r.get("ok", True) else (_ANSI_RED + "\u2717" + _ANSI_RESET)
    line = f"[{i}] {ok_marker} {act}"
    # Ordered most-specific first: click_element/click_text both also carry
    # a top-level x/y (the point actually clicked), so checking those generic
    # fields first would always win and this branch would never fire — badge
    # id or matched text is the more useful label for those two specifically.
    if act == "click_element" and "id" in r:
        line += f" badge [{r.get('id')}]"
        if r.get("text"):
            line += f" '{r['text']}'"
    elif act == "click_text" and isinstance(r.get("target"), dict):
        t = r["target"]
        line += f" '{t.get('text', '')}' -> ({t.get('x')}, {t.get('y')})"
    elif "start" in r and "end" in r:
        line += f" {r['start']} -> {r['end']}"
    elif "x" in r and "y" in r:
        line += f" -> ({r['x']}, {r['y']})"
    elif r.get("key"):
        line += f" '{r['key']}'"
    elif "text_preview" in r:
        line += f" '{r['text_preview']}'"
    elif "direction" in r and "amount" in r:
        line += f" {r['direction']} x{r['amount']}"
    elif act == "clipboard_paste" and "text" in r:
        line += f" '{(r['text'] or '')[:60]}'"
    elif isinstance(r.get("window"), dict):
        w = r["window"]
        line += f" -> {w.get('caption') or w.get('cls') or w.get('uuid', '')}"[:80]
    elif isinstance(r.get("result"), str):
        line += f" -> {r['result']}"
    elif "changed" in r:
        line += f" -> changed={r.get('changed')}"
    elif act == "wait" and "duration" in r:
        line += f" {r['duration']}s"
    if r.get("error"):
        line += f" - {_ANSI_RED}{r['error']}{_ANSI_RESET}"
    return line


def _detail_desktop_actions(result):
    """Terminal card for a desktop_actions batch result."""
    lines = []
    if result.get("results"):
        for i, r in enumerate(result["results"], 1):
            lines.append(_detail_desktop_action_line(i, r))
    if result.get("screenshot_path"):
        lines.append(f"screenshot: {result['screenshot_path']}")
    elif result.get("screenshot_error"):
        lines.append(
            _ANSI_RED + f"screenshot failed: {result['screenshot_error']}" + _ANSI_RESET
        )
    if result.get("error"):
        lines.append(_ANSI_RED + f"error: {result['error']}" + _ANSI_RESET)
    text = "\n".join(lines).strip()
    return {"kind": "desktop", "text": text[:4000]} if text else None


def _detail_desktop_single(name, result):
    """Terminal card for the single-shot desktop/OCR/clipboard tools."""
    if name == "find_text":
        matches = result.get("matches") or []
        lines = [f"Found {len(matches)} match(es) for '{result.get('query', '')}':"]
        for i, m in enumerate(matches[:15], 1):
            box = m.get("box", [])
            lines.append(
                f' [{i}] "{m.get("text", "")}" @ center=({m.get("x")}, {m.get("y")}) '
                f"box={box} conf={m.get('confidence', 0)}%"
            )
        return {"kind": "desktop", "text": "\n".join(lines)[:4000]}
    if name == "click_text":
        target = result.get("target") or {}
        if target:
            idx = result.get("index", 0)
            total = result.get("matches_found", 1)
            text = (
                f"Clicked '{target.get('text', '')}' at ({target.get('x')}, "
                f"{target.get('y')}) [match {idx + 1}/{total}]"
            )
            return {"kind": "desktop", "text": text}
        return None
    if name == "click_element":
        el = result.get("element") or {}
        if el:
            text = (
                f"Clicked mark [{result.get('id')}] '{el.get('text', '')}' at "
                f"({result.get('x')}, {result.get('y')})"
            )
            return {"kind": "desktop", "text": text}
        return None
    if name == "list_displays":
        displays = result.get("displays") or []
        lines = [f"Displays ({len(displays)}):"]
        for d in displays:
            lines.append(
                f" - {d.get('name', 'Display')}: {d.get('width')}x{d.get('height')} @ "
                f"({d.get('x', 0)},{d.get('y', 0)}) scale={d.get('scale', 1.0)} "
                f"({d.get('refresh_rate', 0)}Hz)"
            )
        return {"kind": "desktop", "text": "\n".join(lines)[:4000]}
    if name == "assert_region_changed":
        changed = result.get("changed")
        pct = result.get("diff_percent", 0.0)
        status = "CHANGED" if changed else "UNCHANGED"
        text = (
            f"Region diff: {status} ({pct:.2f}% pixels changed, "
            f"threshold={result.get('threshold_percent', 0.1)}%)"
        )
        return {"kind": "desktop", "text": text}
    if name == "wait_for_screen_change":
        status = "CHANGED" if result.get("changed") else "TIMEOUT"
        reason = result.get("reason", "no details")
        return {"kind": "desktop", "text": f"Screen change: {status} ({reason})"}
    if name in ("clipboard_paste", "clipboard_get"):
        txt = result.get("text", "")
        if txt:
            return {
                "kind": "shell",
                "text": f"Clipboard ({len(txt)} chars):\n{txt[:1000]}",
            }
        return None
    return None


def tool_detail(name, result):
    """Pull the part of a tool result worth showing in a terminal-style card.
    Returns None when there is nothing more useful than the one-line summary
    already in the event (e.g. a window activation).

    Split from a single ~120-branch if-chain (CC 70) into per-family
    formatters; this dispatcher stays a flat routing table.
    """
    if not isinstance(result, dict):
        return None
    if name == "run_command":
        parts = []
        if result.get("stdout"):
            parts.append(result["stdout"])
        if result.get("stderr"):
            parts.append(_ANSI_RED + result["stderr"] + _ANSI_RESET)
        text = "\n".join(parts).strip()
        return {"kind": "shell", "text": text[-4000:]} if text else None
    if name in _SIMPLE_DIFF_TOOLS and result.get("diff"):
        return {"kind": "diff", "text": result["diff"][:4000]}
    if name in _LINT_TOOLS:
        text = (result.get("stdout") or "") + (
            ("\n" + result["stderr"]) if result.get("stderr") else ""
        )
        text = text.strip()
        return {"kind": "shell", "text": text[:4000]} if text else None
    if name == "read_file" and result.get("content"):
        return {"kind": "code", "text": result["content"][:4000]}
    if name == "grep" and result.get("matches"):
        text = "\n".join(
            f"{m['file']}:{m['line']}: {m['text']}" for m in result["matches"][:60]
        )
        return {"kind": "code", "text": text} if text else None
    if name == "desktop_actions":
        return _detail_desktop_actions(result)
    detail = _detail_desktop_single(name, result)
    if detail is not None:
        return detail
    if not result.get("ok") and result.get("error"):
        return {
            "kind": "error",
            "text": _ANSI_RED + str(result["error"])[:2000] + _ANSI_RESET,
        }
    return None


def _failure_detail(result):
    """Best available diagnostic text for a failed tool result. An
    explicit "error" key means an infra-level failure (timeout, missing
    binary); a command that ran and simply exited non-zero (run_tests,
    run_command) has no "error" key at all — its failure lives in stderr/
    stdout. Falling straight to a bare "unknown" for that second, very
    common case (confirmed live: an approved run_tests failure surfaced to
    the user as just "Approved action failed closed: unknown", discarding
    the actual ModuleNotFoundError traceback that explained it) makes a
    diagnosable failure look opaque."""
    if result.get("error"):
        return str(result["error"])
    for key in ("stderr", "stdout"):
        text = (result.get(key) or "").strip()
        if text:
            return text[:500]
    # Gate-style tools report structured findings rather than a shell error.
    # Preserve the first one in the incident log so repeated failures are
    # diagnosable without reopening a compacted task journal.
    findings = result.get("findings") or []
    if findings:
        return str(findings[0])[:500]
    guidance = result.get("guidance")
    if guidance:
        return str(guidance)[:500]
    return "unknown"
