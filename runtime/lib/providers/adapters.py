"""Message-shape adapters: neutral format to each provider's wire format."""

import json

from .. import tools as toolreg

TOOLS = toolreg.schemas()


# ── provider adapters ────────────────────────────────────────────────────


def to_anthropic(messages):
    """Convert neutral messages to Anthropic system+messages shape.

    The system side comes back as an ordered list of `{"text", "cache"}`
    entries rather than one joined string. That used to be a plain
    `"\n\n".join(...)`, which is lossy in a way that mattered: Anthropic only
    lets a `cache_control` breakpoint sit on a *block*, so a flattened system
    string has exactly one cacheable unit, and this runtime's system messages
    are not uniformly volatile — the prompt and the workspace preamble are
    byte-identical on every call of a task, while memories, the condensed
    history and the plan change underneath them. One breakpoint over the joined
    whole therefore misses on every call after the first change to any of
    them, and since the tool schemas plus the system prompt are ~13.7k tokens
    on this host, that is the difference between paying for them once per task
    and paying for them on all 64 steps of it.

    Each entry keeps the `cache` tier its author declared (see journal.context):
    "stable" for content that cannot change within a task, "semi" for content
    that changes rarely. `anthropic_system_blocks` turns the tiers into
    breakpoints. Every other adapter reads only `role`/`content` and ignores
    the key, so nothing else has to know this exists.
    """
    systems, out = [], []
    for m in messages:
        role = m["role"]
        if role == "system":
            systems.append({"text": m["content"], "cache": m.get("cache")})
            continue
        if role == "user":
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
            else:
                blocks = []
                for b in content:
                    if b.get("type") == "text":
                        blocks.append({"type": "text", "text": b["text"]})
                    elif b.get("type") == "image":
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": b["mime"],
                                    "data": b["b64"],
                                },
                            }
                        )
                out.append({"role": "user", "content": blocks or ""})
        elif role == "assistant":
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for c in m.get("tool_calls", []) or []:
                fn = c.get("function", {})
                try:
                    inp = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    inp = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": c.get("id", "call"),
                        "name": fn.get("name", ""),
                        "input": inp,
                    }
                )
            out.append({"role": "assistant", "content": blocks or m.get("content", "")})
        elif role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.get("tool_call_id", "history"),
                            "content": m.get("content", ""),
                        }
                    ],
                }
            )
    return systems, out


def anthropic_system_blocks(systems):
    """Anthropic `system` content blocks, with prompt-cache breakpoints.

    Two tiers, in the order Anthropic reads them: `cache_control` is placed on
    the last "stable" block and on the last "semi" block, so the stable prefix
    is written once per task and the semi-stable band is re-written only when
    the model actually records a memory or ticks off a todo.

    Everything *after* a breakpoint is outside that cache unit, so the volatile
    tail of the system list — the budget notice the loop appends when the step
    count runs low — does not invalidate either tier. It did before this
    existed only because there was a single unit covering all of it.

    The last block always carries a breakpoint even if nothing declared a tier,
    so a request that somehow carries no cacheable system content still gets
    the tools-side cache that `cached_tools` puts on the last tool.
    """
    entries = [(s["text"], s.get("cache")) for s in systems if s.get("text")]
    blocks = [{"type": "text", "text": t} for t, _ in entries]
    marked = set()
    for tier in ("stable", "semi"):
        for i in range(len(entries) - 1, -1, -1):
            if i in marked:
                continue
            if entries[i][1] == tier:
                blocks[i]["cache_control"] = {"type": "ephemeral"}
                marked.add(i)
                break
    if blocks and not marked:
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def cached_tools(tools):
    """The tools array with a cache breakpoint on its last entry.

    Anthropic caches in the order tools → system → messages, so a breakpoint
    here covers the whole tool schema block. That block is the single largest
    fixed cost in a request here (~8.2k tokens across 59 tools on this host)
    and it is byte-identical for the life of the process: `TOOLS` is built once
    at adapters import, and MCP tools are registered into the registry at
    tools.py import too, so nothing mutates it mid-task and the prefix stays
    warm across all of a task's calls.
    """
    out = [dict(t) for t in tools]
    if out:
        out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    return out


def to_openai(messages):
    """Convert neutral messages to OpenAI chat.completions shape."""
    out = []
    for m in messages:
        if m["role"] == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                }
            )
        elif m["role"] == "user" and not isinstance(m["content"], str):
            blocks = []
            for b in m["content"]:
                if b.get("type") == "text":
                    blocks.append({"type": "text", "text": b["text"]})
                elif b.get("type") == "image":
                    blocks.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:" + b["mime"] + ";base64," + b["b64"]
                            },
                        }
                    )
            out.append({"role": "user", "content": blocks})
        elif m["role"] == "system":
            # Rebuilt rather than passed through. System messages now carry a
            # `cache` tier for the Anthropic breakpoint logic, and OpenAI's
            # chat.completions rejects a message with an unrecognized property
            # ("Unrecognized request argument supplied: cache") — so passing
            # the dict straight through would have turned a caching
            # improvement into a 400 on every OpenAI and OpenRouter call.
            out.append({"role": "system", "content": m["content"]})
        else:
            out.append(m)
    return out


def to_codex(messages):
    """Convert neutral messages to Codex Responses items + instructions."""
    instructions, items = "", []
    for m in messages:
        role = m["role"]
        if role == "system":
            instructions = (instructions + "\n\n" + m["content"]).strip()
            continue
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": m.get("tool_call_id", ""),
                    "output": m.get("content", ""),
                }
            )
        elif role == "assistant":
            if m.get("content"):
                items.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": m["content"]}],
                    }
                )
            for c in m.get("tool_calls", []) or []:
                fn = c.get("function", {})
                items.append(
                    {
                        "type": "function_call",
                        "call_id": c.get("id", "call"),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments") or "{}",
                    }
                )
        else:
            content = m["content"]
            if isinstance(content, str):
                items.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": content}],
                    }
                )
            else:
                blocks = []
                for b in content:
                    if b.get("type") == "text":
                        blocks.append({"type": "input_text", "text": b["text"]})
                    elif b.get("type") == "image":
                        blocks.append(
                            {
                                "type": "input_image",
                                "image_url": "data:"
                                + b["mime"]
                                + ";base64,"
                                + b["b64"],
                            }
                        )
                items.append({"role": "user", "content": blocks})
    return instructions, items
