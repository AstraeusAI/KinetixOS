"""OpenAI Responses API (Codex) stream parser and reply decoder."""

import json
import time

from .sse import ProviderError, _sse_iter, metrics_hub


def parse_codex(reply):
    """Decode a completed Responses-API payload into chat-shaped choices."""
    calls, text = [], []
    for item in reply.get("output", []) or []:
        if item.get("type") == "function_call":
            calls.append(
                {
                    "id": item.get("call_id") or item.get("id", "call"),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments") or "{}",
                    },
                }
            )
        elif item.get("type") == "message":
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    text.append(c["text"])
    return {"choices": [{"message": {"content": "".join(text), "tool_calls": calls}}]}


def _stream_codex(url, headers, body, on_event):
    """OpenAI Responses API SSE (ChatGPT Codex backend). The incremental
    events drive live UI feedback only; `response.completed` carries the
    full, authoritative output (same shape parse_codex already handled for
    the non-streaming call), so execution correctness never depends on this
    module's read of the less-documented delta event names."""
    import argusd as _facade

    _post_stream = _facade._post_stream
    resp = _post_stream(url, headers, body)
    tool_started, final = set(), None
    start_time = time.time()
    metrics = metrics_hub(on_event, start_time)

    try:
        for _event, data in _sse_iter(resp):
            if not data:
                continue
            try:
                obj = json.loads(data)
            except Exception:
                continue
            et = obj.get("type", "")
            if et == "response.output_text.delta":
                t = obj.get("delta", "")
                if t:
                    on_event({"type": "delta", "text": t})
                    metrics.tick()
            elif et == "response.output_item.added":
                item = obj.get("item", {}) or {}
                if item.get("type") == "function_call":
                    cid = item.get("call_id") or item.get("id", "call")
                    if cid not in tool_started:
                        tool_started.add(cid)
                        on_event(
                            {
                                "type": "tool_call_start",
                                "id": cid,
                                "name": item.get("name", ""),
                            }
                        )
            elif et == "response.function_call_arguments.delta":
                cid = obj.get("call_id") or obj.get("item_id", "")
                frag = obj.get("delta", "")
                if frag:
                    on_event({"type": "tool_call_delta", "id": cid, "arguments": frag})
                    metrics.tick(max(1, len(frag) // 4))
            elif et == "response.function_call_arguments.done":
                cid = obj.get("call_id") or obj.get("item_id", "")
                try:
                    parsed = json.loads(obj.get("arguments") or "{}")
                except Exception:
                    parsed = {}
                on_event(
                    {
                        "type": "tool_call_ready",
                        "id": cid,
                        "name": "",
                        "arguments": parsed,
                    }
                )
            elif et == "response.reasoning_summary_text.delta":
                t = obj.get("delta", "")
                if t:
                    on_event({"type": "reasoning_delta", "text": t})
                    metrics.tick()
            elif et == "response.completed":
                final = obj.get("response", obj)
                usage = final.get("usage") if isinstance(final, dict) else None
                if usage and isinstance(usage, dict):
                    p_tok = usage.get("input_tokens", usage.get("prompt_tokens", 0))
                    c_tok = usage.get(
                        "output_tokens", usage.get("completion_tokens", 0)
                    )
                    t_tok = usage.get("total_tokens", p_tok + c_tok)
                    on_event(
                        {
                            "type": "usage",
                            "prompt_tokens": p_tok,
                            "completion_tokens": c_tok,
                            "total_tokens": t_tok,
                        }
                    )
            elif et in ("response.failed", "error"):
                err = (
                    obj.get("response", {}).get("error")
                    if "response" in obj
                    else obj.get("error")
                )
                raise ProviderError(
                    str(
                        (err or {}).get("message", err)
                        if isinstance(err, dict)
                        else err
                    )
                )
    finally:
        resp.close()
    metrics.flush()
    if final is None:
        raise ProviderError("stream ended without response.completed")
    return parse_codex(final)
