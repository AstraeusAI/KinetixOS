"""Message-shape adapters: neutral format to each provider's wire format."""

import json

from .. import tools as toolreg

TOOLS = toolreg.schemas()


# ── provider adapters ────────────────────────────────────────────────────


def to_anthropic(messages):
    """Convert neutral messages to Anthropic system+messages shape."""
    systems, out = [], []
    for m in messages:
        role = m["role"]
        if role == "system":
            systems.append(m["content"])
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
    return "\n\n".join(x for x in systems if x), out


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
