"""provider_call: credential/auth dispatch to the per-provider streams."""

from ..config import _REASONING_BUDGET, auth_mode
from ..prompt import CLAUDE_IDENTITY, SYSTEM_PROMPT
from .adapters import TOOLS, to_anthropic, to_codex, to_openai
from .anthropic import _stream_anthropic
from .codex import _stream_codex
from .openai_chat import _stream_openai_chat


def provider_call(messages, on_event):
    """Pick the configured provider and stream one model turn."""
    import argusd as _facade

    prefs = _facade.prefs
    vault = _facade.vault
    _call_stream = _facade._call_stream
    p = prefs()
    v = vault()
    provider = p.get("provider", "openai")
    model = p.get("model", "")
    if not model:
        raise RuntimeError("No model selected")
    # "off" by default and whenever the saved value isn't recognized, so a
    # model that doesn't support reasoning sees an unmodified request body —
    # the parameter is only ever added, never sent as an explicit "off"/
    # zero-budget value the API would have to interpret.
    reasoning = p.get("reasoning", "off")
    if reasoning not in _REASONING_BUDGET:
        reasoning = "off"

    if provider == "anthropic":
        mode, key = auth_mode(
            p, "anthropic", v, "ANTHROPIC_API_KEY", "ANTHROPIC_SUB_TOKEN"
        )
        if not key:
            raise RuntimeError("No credential configured for anthropic")
        system, msgs = to_anthropic(messages)
        if mode == "sub":
            system = (CLAUDE_IDENTITY + "\n\n" + system).strip()
            headers = {
                "Authorization": "Bearer " + key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "oauth-2025-04-20,claude-code-20250219",
                "content-type": "application/json",
            }
        else:
            headers = {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        body = {
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "messages": msgs,
            "tools": [
                {
                    "name": x["function"]["name"],
                    "description": x["function"]["description"],
                    "input_schema": x["function"]["parameters"],
                }
                for x in TOOLS
            ],
        }
        if reasoning != "off":
            budget = _REASONING_BUDGET[reasoning]
            body["max_tokens"] = budget + 4096
            body["thinking"] = {"type": "enabled", "budget_tokens": budget}
            # Known limitation, not silently pretended: thinking blocks are
            # streamed live via reasoning_delta (see _stream_anthropic) and
            # then dropped — context() never journals them, so a later turn
            # that replays this conversation does not resend the prior
            # thinking block/signature the way strict interleaved-thinking
            # continuity wants. Anthropic's API tolerates this (it does not
            # reject the turn), but the model's own reasoning does not
            # carry forward across turns the way its final text/tool calls do.
        return _call_stream(
            _stream_anthropic,
            "https://api.anthropic.com/v1/messages",
            headers,
            body,
            on_event,
        )

    elif provider == "openai":
        mode, key = auth_mode(p, "openai", v, "OPENAI_API_KEY", "OPENAI_CODEX_TOKEN")
        if not key:
            raise RuntimeError("No credential configured for openai")
        if mode == "sub":
            instructions, items = to_codex(messages)
            body = {
                "model": model,
                "store": False,
                "instructions": instructions or SYSTEM_PROMPT,
                "input": items,
                "tools": [
                    {
                        "type": "function",
                        "name": x["function"]["name"],
                        "description": x["function"]["description"],
                        "parameters": x["function"]["parameters"],
                    }
                    for x in TOOLS
                ],
                "tool_choice": "auto",
            }
            if reasoning != "off":
                body["reasoning"] = {"effort": reasoning}
            headers = {
                "Authorization": "Bearer " + key,
                "content-type": "application/json",
            }
            acct = v.get("OPENAI_CODEX_ACCOUNT", "")
            if acct:
                headers["ChatGPT-Account-Id"] = acct
            return _call_stream(
                _stream_codex,
                "https://chatgpt.com/backend-api/codex/responses",
                headers,
                body,
                on_event,
            )
        else:
            url = "https://api.openai.com/v1/chat/completions"
            body = {
                "model": model,
                "messages": to_openai(messages),
                "tools": TOOLS,
                "tool_choice": "auto",
            }
            if reasoning != "off":
                body["reasoning_effort"] = reasoning
                # Headroom so reasoning tokens cannot consume the whole
                # completion budget and leave zero content (empty-reply
                # ProviderError above still guards the degenerate case).
                body.setdefault("max_tokens", 8192)
            headers = {
                "Authorization": "Bearer " + key,
                "content-type": "application/json",
            }
            return _call_stream(_stream_openai_chat, url, headers, body, on_event)
    else:
        conf = {
            "openrouter": (
                "https://openrouter.ai/api/v1/chat/completions",
                "OPENROUTER_API_KEY",
            ),
            "opencode": (
                "https://opencode.ai/zen/go/v1/chat/completions",
                "OPENCODE_API_KEY",
            ),
        }
        url, keyname = conf.get(provider, conf["openrouter"])
        key = v.get(keyname, "")
        if not key:
            raise RuntimeError("No credential configured for " + provider)
        body = {
            "model": model,
            "messages": to_openai(messages),
            "tools": TOOLS,
            "tool_choice": "auto",
        }
        if reasoning != "off":
            # OpenRouter's own unified format — it translates or drops this
            # per the backing model rather than erroring on an unsupported
            # model, which is what makes it safe to send unconditionally
            # here (unlike the direct-provider paths above, where an
            # unsupported field can be rejected outright).
            body["reasoning"] = {"effort": reasoning}
            # Explicit completion headroom: without it, a reasoning-heavy
            # turn can hit the provider default max_tokens with finish_reason
            # =length and zero content — the empty-reply failure mode fixed
            # in _stream_openai_chat. 8192 leaves ample room for thinking
            # plus the actual answer on flash-class models.
            body.setdefault("max_tokens", 8192)
        headers = {"Authorization": "Bearer " + key, "content-type": "application/json"}
        if provider == "openrouter":
            headers.update({"HTTP-Referer": "https://argus.os", "X-Title": "Argus OS"})
        return _call_stream(_stream_openai_chat, url, headers, body, on_event)
