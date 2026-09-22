"""SSE transport, streaming retry policy, and provider error types."""

import json
import time
import urllib.error
import urllib.request

from ..config import HTTP_TIMEOUT

# ── streaming (SSE) ──────────────────────────────────────────────────────
# Every provider is called with stream=True and parsed incrementally, so the
# panel can show the model's prose and tool-call arguments as they're
# generated instead of only after the whole turn completes. `on_event` is
# always a callable (a no-op when the CLI wasn't invoked with --stream) so the
# parsers below never need to know whether anyone is listening; the final
# return value has the exact `{"choices": [{"message": {...}}]}` shape the
# non-streaming code used to produce, so the tool-execution loop in `run()`
# needed no changes.


class ProviderError(RuntimeError):
    """A failure the provider itself reported inside the stream — an
    `{"error": ...}` body delivered with HTTP 200 (how OpenRouter and DeepSeek
    report upstream rate limits and provider failures), an `error`/`failed`
    event, or a stream that ended without a completed response.

    Distinct from RuntimeError generally so _call_stream can retry it when
    nothing has been shown to the user yet: a rate limit in the body of a 200
    response is exactly as transient as a 429 status, but used to fail the whole
    task on the first attempt because the retry branch only caught HTTPError and
    URLError (verified: a stubbed in-band error raised after 1 attempt while a
    URLError recovered on the 2nd).
    """


class _MetricsHub:
    """TTFT/token/tps telemetry for one streamed provider turn."""

    __slots__ = ("_on_event", "_start", "_state")

    def __init__(self, on_event, start_time):
        """Initialize the context's stores, flags, and MCP cache."""
        self._on_event = on_event
        self._start = start_time
        self._state = {"first": None, "tokens": 0, "last": 0.0}

    def tick(self, n=1):
        """Record n units of streamed work; the first tick fixes TTFT."""
        if self._state["first"] is None:
            self._state["first"] = time.time()
        self._state["tokens"] += n
        self._emit()

    def flush(self):
        """Force one final metrics event (end of stream, any state)."""
        self._emit(force=True)

    def _emit(self, force=False):
        """Emit one metrics event if cadence/force allows it."""
        state = self._state
        now_t = time.time()
        if state["first"] is None:
            return
        if force or (now_t - state["last"] >= 0.15 and state["tokens"] > 0):
            elapsed = max(now_t - state["first"], 0.001)
            tps = round(state["tokens"] / elapsed, 1)
            ttft_ms = int((state["first"] - self._start) * 1000)
            self._on_event(
                {
                    "type": "metrics",
                    "ttft": ttft_ms,
                    "tokens": state["tokens"],
                    "tps": tps,
                    "elapsed": round(elapsed, 2),
                }
            )
            state["last"] = now_t


def metrics_hub(on_event, start_time):
    """Build the shared metrics emitter for one provider stream.

    The three stream parsers (OpenAI-chat, Anthropic, Codex) previously
    carried byte-identical copies of this closure; one hub keeps the emit
    cadence (≥0.15s between events) and the event payload shape in lockstep.
    """
    return _MetricsHub(on_event, start_time)


def _sse_iter(resp):
    (
        """Yield (event, data) pairs from a text/event-stream response body """
        """following """
        """WHATWG SSE spec."""
    )
    event = "message"
    data_lines = []
    first_line = True
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if first_line:
            line = line.lstrip("\ufeff")
            first_line = False
        if not line:
            if data_lines:
                yield event, "\n".join(data_lines)
            event, data_lines = "message", []
            continue
        if line.startswith(":"):
            continue  # comment / heartbeat / ping
        if ":" in line:
            field, val = line.split(":", 1)
            if val.startswith(" "):
                val = val[1:]
        else:
            field, val = line, ""
        field = field.strip()
        if field == "event":
            event = val.strip()
        elif field == "data":
            data_lines.append(val)
    if data_lines:
        yield event, "\n".join(data_lines)


def _post_stream(url, headers, body):
    """POST body as stream=True SSE and return the raw response."""
    payload = dict(body)
    payload["stream"] = True
    if (
        ("api.openai.com" in url or "openrouter.ai" in url)
        and "messages" in payload
        and "stream_options" not in payload
    ):
        payload["stream_options"] = {"include_usage": True}
    req_headers = {
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    req_headers.update(headers)
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=req_headers, method="POST"
    )
    return urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)


_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
_MAX_PROVIDER_RETRIES = 2


def _clean_http_detail(exc, cap=300):
    """The body of an HTTPError, cleaned up for a human/model to read.

    Confirmed live: a 403 from an intermediate proxy (not the provider
    itself — a WAF/CDN block page) came back as a full raw
    "<!doctype html>...<!--[if lt IE 7]>..." document, which _call_stream
    used to dump verbatim into the task's error message. That is technically
    "the response body" but tells whoever reads it nothing about what
    actually went wrong, and drowns out the one thing that matters (the
    status code) in markup. A provider's own error responses are JSON; an
    HTML body means something other than the provider produced this one.
    """
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:
        return ""
    stripped = raw.strip()
    if stripped[:1] == "<" or "<html" in stripped[:400].lower():
        return (
            "non-JSON (HTML) error page, not a provider-reported API error — "
            "likely an intermediate proxy/CDN block page, rate-limit challenge, "
            "or gateway error"
        )
    return stripped[:cap]


def _retry_delay(attempt, http_error=None):
    """Exponential backoff seconds for attempt n (honours Retry-After)."""
    if http_error is not None and http_error.headers:
        ra = http_error.headers.get("Retry-After")
        if ra:
            try:
                return min(float(ra), 20)
            except ValueError:
                pass
    return min(2**attempt, 8)


# Events that represent durable, visible conversation content — retrying
# after one of these has streamed would re-run the model turn from scratch
# and duplicate whatever the panel already rendered. reasoning_delta and
# metrics are deliberately excluded: reasoning/thinking text is never sent
# back to the model as conversation history (see AgentState.qml's
# appendReasoning — it's ephemeral, shown once and discarded) and metrics
# are pure telemetry, so neither leaves anything behind to duplicate.
# Confirmed live against a free/slower model (OpenRouter's Nemotron Ultra):
# it streamed several reasoning_delta chunks, then the upstream itself cut
# the connection with "Upstream idle timeout exceeded" before a single real
# token of the actual reply — before this distinction, that counted as
# "already emitted" and killed the whole task on one slow thinking phase,
# exactly the blip this function exists to absorb.
_DURABLE_STREAM_EVENT_TYPES = {
    "delta",
    "tool_call_start",
    "tool_call_delta",
    "tool_call_ready",
}


def _call_stream(fn, *args):
    """Retry a transient provider failure (rate limit / 5xx / connect-level
    network error) with backoff — a single flaky request used to kill the
    whole task, which looked to the user like the agent had given up rather
    than hit a blip. Retries stop the moment durable content has actually
    been streamed to the UI for this attempt (see _DURABLE_STREAM_EVENT_TYPES):
    retrying past that point would re-run the model turn from scratch and
    duplicate whatever the panel already rendered, which is worse than
    surfacing the error — so that case still raises immediately, same as
    before this existed.
    """
    on_event = args[-1]
    rest = args[:-1]
    emitted = False

    def guarded(evt):
        """Wrap on_event: mark durable events for the retry policy."""
        nonlocal emitted
        if evt.get("type") in _DURABLE_STREAM_EVENT_TYPES:
            emitted = True
        on_event(evt)

    for attempt in range(_MAX_PROVIDER_RETRIES + 1):
        emitted = False
        try:
            return fn(*rest, guarded)
        except urllib.error.HTTPError as e:
            detail = _clean_http_detail(e)
            if (
                attempt < _MAX_PROVIDER_RETRIES
                and e.code in _RETRYABLE_HTTP
                and not emitted
            ):
                time.sleep(_retry_delay(attempt + 1, e))
                continue
            raise RuntimeError(f"Provider request failed: HTTP {e.code} {detail}")
        except ProviderError:
            # In-band failure reported inside a 200 response, or a stream that
            # ended early. Same reasoning as the HTTPError branch above: retry
            # only while nothing has been streamed, since a retry re-runs the
            # whole model turn. ProviderError is deliberately not a bare
            # RuntimeError so this branch cannot also swallow credential and
            # configuration errors, which retrying would never fix.
            if attempt < _MAX_PROVIDER_RETRIES and not emitted:
                time.sleep(_retry_delay(attempt + 1))
                continue
            raise
        except RuntimeError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < _MAX_PROVIDER_RETRIES and not emitted:
                time.sleep(_retry_delay(attempt + 1))
                continue
            raise RuntimeError("Provider request failed: " + str(e))
        except Exception as e:
            raise RuntimeError("Provider request failed: " + str(e))
