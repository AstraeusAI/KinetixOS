"""Anthropic messages SSE stream parser."""

import json
import time

from .sse import ProviderError, _sse_iter, metrics_hub


def _stream_anthropic(url, headers, body, on_event):
    """https://docs.anthropic.com/en/api/messages-streaming — tool_use input
    arrives as `input_json_delta.partial_json` fragments that concatenate
    into the full arguments JSON string once the block closes."""
    import argusd as _facade

    _post_stream = _facade._post_stream
    resp = _post_stream(url, headers, body)
    text_parts, tools, order = [], {}, []
    start_time = time.time()
    metrics = metrics_hub(on_event, start_time)
    prompt_tokens = 0
    completion_tokens = 0

    truncated_reason = None
    try:
        for _event, data in _sse_iter(resp):
            if not data:
                continue
            try:
                obj = json.loads(data)
            except Exception:
                continue
            et = obj.get("type")
            if et == "message_start":
                msg = obj.get("message", {}) or {}
                usage = msg.get("usage", {}) or {}
                if usage:
                    prompt_tokens = usage.get("input_tokens", 0)
                    on_event(
                        {
                            "type": "usage",
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens,
                        }
                    )
            elif et == "content_block_start":
                idx = obj.get("index", 0)
                block = obj.get("content_block", {}) or {}
                if block.get("type") == "tool_use":
                    tools[idx] = {
                        "id": block.get("id") or f"call_{idx}",
                        "name": block.get("name", ""),
                        "json": "",
                    }
                    order.append(idx)
                    on_event(
                        {
                            "type": "tool_call_start",
                            "id": tools[idx]["id"],
                            "name": tools[idx]["name"],
                        }
                    )
            elif et == "content_block_delta":
                idx = obj.get("index", 0)
                delta = obj.get("delta", {}) or {}
                dt = delta.get("type")
                if dt == "text_delta":
                    t = delta.get("text", "")
                    if t:
                        text_parts.append(t)
                        on_event({"type": "delta", "text": t})
                        metrics.tick()
                elif dt == "input_json_delta" and idx in tools:
                    frag = delta.get("partial_json", "")
                    if frag:
                        tools[idx]["json"] += frag
                        on_event(
                            {
                                "type": "tool_call_delta",
                                "id": tools[idx]["id"],
                                "arguments": frag,
                            }
                        )
                        metrics.tick(max(1, len(frag) // 4))
                elif dt == "thinking_delta":
                    # Extended thinking. `signature_delta` (the block's
                    # crypto signature, not user-facing text) is otherwise
                    # ignored on purpose.
                    t = delta.get("thinking", "")
                    if t:
                        on_event({"type": "reasoning_delta", "text": t})
                        metrics.tick()
            elif et == "content_block_stop":
                idx = obj.get("index", 0)
                if idx in tools:
                    try:
                        parsed = json.loads(tools[idx]["json"] or "{}")
                    except Exception:
                        parsed = {}
                    on_event(
                        {
                            "type": "tool_call_ready",
                            "id": tools[idx]["id"],
                            "name": tools[idx]["name"],
                            "arguments": parsed,
                        }
                    )
            elif et == "message_delta":
                usage = obj.get("usage", {}) or {}
                if usage:
                    completion_tokens = usage.get("output_tokens", completion_tokens)
                    on_event(
                        {
                            "type": "usage",
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens,
                        }
                    )
            elif et == "error":
                err = obj.get("error") or {}
                msg = (
                    err.get("message", "stream error")
                    if isinstance(err, dict)
                    else str(err)
                )
                raise ProviderError(f"Anthropic stream error: {msg}")
    except Exception as e:
        # See the matching comment in _stream_openai_chat: nothing arrived
        # yet -> let the caller's normal retry-from-scratch handle it;
        # something DID arrive -> salvage the text and let run() ask the
        # model to continue rather than discarding it.
        if not text_parts and not tools:
            raise
        truncated_reason = str(e)
    finally:
        resp.close()
    metrics.flush()
    if truncated_reason is not None:
        # Discard any tool_use block, complete or not — see the matching
        # comment in _stream_openai_chat for why this stays uniform across
        # providers even though Anthropic's content_block_stop could in
        # principle distinguish a finished block from a cut-off one.
        return {
            "choices": [
                {"message": {"content": "".join(text_parts), "tool_calls": []}}
            ],
            "_stream_truncated": True,
            "_truncation_reason": truncated_reason,
        }
    calls = [
        {
            "id": tools[i]["id"],
            "type": "function",
            "function": {
                "name": tools[i]["name"],
                "arguments": tools[i]["json"] or "{}",
            },
        }
        for i in order
    ]
    return {
        "choices": [{"message": {"content": "".join(text_parts), "tool_calls": calls}}]
    }
