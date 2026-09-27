"""OpenAI-compatible chat.completions SSE stream parser."""

import json
import time

from .sse import ProviderError, _sse_iter, metrics_hub


def _stream_openai_chat(url, headers, body, on_event):
    """OpenAI-compatible chat.completions SSE (OpenAI, OpenRouter, OpenCode
    Go): each tool_call delta carries an `index`; `function.arguments`
    fragments concatenate in order into the full JSON string per index."""
    import argusd as _facade

    _post_stream = _facade._post_stream
    resp = _post_stream(url, headers, body)
    text_parts, tools, order, started = [], {}, [], set()
    start_time = time.time()
    metrics = metrics_hub(on_event, start_time)
    finish_reason = None
    reasoning_chars = 0

    truncated_reason = None
    try:
        for _event, data in _sse_iter(resp):
            data = data.strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except Exception:
                continue

            # Detect provider error mid-stream
            if "error" in obj:
                err = obj["error"]
                msg = (
                    err.get("message", str(err)) if isinstance(err, dict) else str(err)
                )
                raise ProviderError(f"Provider stream error: {msg}")

            # Capture usage if present (e.g. OpenAI / OpenRouter stream_options)
            usage = obj.get("usage")
            if usage and isinstance(usage, dict):
                p_tok = usage.get("prompt_tokens", 0)
                c_tok = usage.get("completion_tokens", 0)
                t_tok = usage.get("total_tokens", p_tok + c_tok)
                on_event(
                    {
                        "type": "usage",
                        "prompt_tokens": p_tok,
                        "completion_tokens": c_tok,
                        "total_tokens": t_tok,
                    }
                )

            choices = obj.get("choices") or []
            if not choices:
                continue
            ch0 = choices[0]
            # finish_reason is the only reliable signal distinguishing
            # "model said nothing on purpose" from "reasoning ate the whole
            # completion budget" (finish_reason=length) — carried into the
            # empty-reply ProviderError below so retries and the incident
            # log can name the actual cause.
            if ch0.get("finish_reason"):
                finish_reason = ch0["finish_reason"]
            delta = ch0.get("delta", {}) or {}
            if delta.get("content"):
                t = delta["content"]
                text_parts.append(t)
                on_event({"type": "delta", "text": t})
                metrics.tick()
            # A few OpenAI-compatible gateways deliver the FINAL message as
            # `choices[0].message` (non-delta) instead of a content delta.
            # Missing that shape produced a silent empty reply even though
            # the model had written the whole answer — salvage it once.
            msg_field = ch0.get("message")
            if (
                isinstance(msg_field, dict)
                and msg_field.get("content")
                and not text_parts
            ):
                t = msg_field["content"]
                text_parts.append(t)
                on_event({"type": "delta", "text": t})
            # Not OpenAI's own field — OpenRouter's unified format (`reasoning`)
            # and some direct reasoning-model APIs, e.g. DeepSeek
            # (`reasoning_content`), stream chain-of-thought this way ahead
            # of `content`. Neither is part of the returned message; it's
            # shown live and then dropped, same as other providers' "thinking".
            reasoning = delta.get("reasoning") or delta.get("reasoning_content")
            if reasoning:
                reasoning_chars += len(reasoning)
                on_event({"type": "reasoning_delta", "text": reasoning})
                metrics.tick()
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                if idx not in tools:
                    tools[idx] = {
                        "id": tc.get("id") or f"call_{idx}",
                        "name": "",
                        "arguments": "",
                    }
                    order.append(idx)
                fn = tc.get("function") or {}
                if fn.get("name"):
                    # OpenAI sends the name once, in the first delta for that
                    # index, so fragments are normally concatenated. Some
                    # OpenAI-compatible servers resend the whole name in every
                    # chunk instead; appending there produced a name like
                    # "read_fileread_file…" and the call came back as an unknown
                    # tool, so an exact resend of what is already accumulated is
                    # ignored rather than doubled.
                    if not tools[idx]["name"]:
                        tools[idx]["name"] = fn["name"]
                    elif fn["name"] != tools[idx]["name"]:
                        tools[idx]["name"] += fn["name"]
                if idx not in started and tools[idx]["name"]:
                    started.add(idx)
                    on_event(
                        {
                            "type": "tool_call_start",
                            "id": tools[idx]["id"],
                            "name": tools[idx]["name"],
                        }
                    )
                if fn.get("arguments"):
                    tools[idx]["arguments"] += fn["arguments"]
                    on_event(
                        {
                            "type": "tool_call_delta",
                            "id": tools[idx]["id"],
                            "arguments": fn["arguments"],
                        }
                    )
                    metrics.tick(max(1, len(fn["arguments"]) // 4))
    except Exception as e:
        # A connection-level failure partway through (dropped socket, idle
        # timeout, truncated chunk, an in-band ProviderError, ...). Nothing
        # arrived yet: there is nothing to salvage, so let the caller's
        # normal retry-from-scratch handle it (see _call_stream) exactly as
        # before this existed. Something DID arrive: salvaging it and
        # letting run() ask the model to continue from there is strictly
        # better than discarding it — confirmed live (twice, same failure,
        # "Upstream idle timeout exceeded" against a slow free model) that a
        # mid-generation drop killed the whole task and threw away
        # everything the model had already written, even though the panel
        # had already shown it to the user.
        if not text_parts and not tools:
            raise
        truncated_reason = str(e)
    finally:
        resp.close()
    metrics.flush()
    if truncated_reason is not None:
        # Discard any tool call, complete or not: this streaming shape gives
        # no signal that a call finished independent of the whole response
        # ending, so there's no safe way to tell a genuinely complete call
        # apart from one truncated mid-arguments. Resending a maybe-broken
        # tool_calls array risks a hard provider-side rejection or the model
        # acting on truncated arguments; continuing from the text alone and
        # letting the model re-decide its next tool call is the safe,
        # simple recovery — see run()'s handling of _stream_truncated.
        return {
            "choices": [
                {"message": {"content": "".join(text_parts), "tool_calls": []}}
            ],
            "_stream_truncated": True,
            "_truncation_reason": truncated_reason,
        }
    calls = []
    for i in order:
        t = tools[i]
        try:
            parsed = json.loads(t["arguments"] or "{}")
        except Exception:
            parsed = {}
        on_event(
            {
                "type": "tool_call_ready",
                "id": t["id"],
                "name": t["name"],
                "arguments": parsed,
            }
        )
        calls.append(
            {
                "id": t["id"],
                "type": "function",
                "function": {"name": t["name"], "arguments": t["arguments"] or "{}"},
            }
        )
    # A stream that ends with neither content nor tool calls is a FAILED
    # reply, not an empty-success one. Observed live (mimo-v2.6-flash via
    # OpenRouter): a reasoning-only turn — zero chunks, or finish_reason=
    # "length" with reasoning consuming the whole completion budget, or
    # reasoning then stop — used to fall through to run()'s
    # "(The model returned no text.)" with no exception, so _call_stream's
    # retry (which exists for exactly this blip) never fired and no
    # provider_call_failed was ever logged. ProviderError retries while
    # nothing durable was emitted (reasoning/metrics are non-durable), and
    # after the retries it surfaces as a real ⚠️ failure instead of a
    # silent placeholder.
    if not text_parts and not calls:
        fr = finish_reason or "no finish_reason (empty body / zero data events)"
        hint = ""
        if fr == "length":
            # Escalate for the retry _call_stream is about to attempt: `body`
            # is the exact dict object the retry loop reuses (same `rest`
            # tuple passed back into `fn`), so mutating it here actually
            # changes the next attempt instead of repeating the identical
            # doomed request. Observed live (mimo-v2.6-flash via OpenRouter,
            # quality_loop.py round 1, trial 2): all _MAX_PROVIDER_RETRIES
            # attempts failed identically at the fixed 8192 floor — reasoning
            # alone consumed it every time, so retrying without more headroom
            # cannot change the outcome.
            old = body.get("max_tokens", 8192)
            new = min(old * 2, 32000)
            body["max_tokens"] = new
            hint = (
                " — reasoning appears to have consumed the entire "
                "completion budget; max_tokens headroom raised "
                f"{old}->{new} for the retry"
            )
        raise ProviderError(
            f"stream ended with no content and no tool calls "
            f"(finish_reason={fr}; reasoning_chars={reasoning_chars}){hint}"
        )
    return {
        "choices": [{"message": {"content": "".join(text_parts), "tool_calls": calls}}]
    }
