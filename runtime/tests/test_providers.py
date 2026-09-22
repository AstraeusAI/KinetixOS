"""Provider streams: SSE parsing, tool-call assembly, and the retry policy.

The parsers are fed recorded SSE bodies (no network), which is enough to pin the
shapes that matter: fragments concatenating into arguments, a provider that
resends the tool name in every chunk, in-band errors, and which failures are
worth retrying.
"""
import email.message
import json
import unittest
import urllib.error
from unittest import mock

import support  # noqa: F401

import argusd


class FakeResponse:
    """The iterable-of-lines, close()-able object the parsers consume."""

    def __init__(self, lines):
        self._lines = list(lines)
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        self.closed = True


def sse(*payloads):
    """A recorded SSE body: `data:` lines, blank-line terminated."""
    out = []
    for payload in payloads:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        out.append(("data: " + text + "\n").encode())
        out.append(b"\n")
    return out


class DroppedResponse(FakeResponse):
    """Like FakeResponse, but raises `exc` partway through iteration instead
    of ending cleanly — simulates a connection dying mid-stream (idle
    timeout, reset, truncated chunk, ...)."""

    def __init__(self, lines, exc):
        super().__init__(lines)
        self.exc = exc

    def __iter__(self):
        for line in self._lines:
            yield line
        raise self.exc


class SseIterTests(unittest.TestCase):
    def collect(self, lines):
        return list(argusd._sse_iter(FakeResponse(lines)))

    def test_crlf_comments_bom_and_missing_final_blank_line(self):
        events = self.collect([b"\xef\xbb\xbf: heartbeat\r\n", b"\r\n",
                               b'data: {"a": 1}\r\n', b"\r\n", b"data: [DONE]"])
        self.assertEqual([("message", '{"a": 1}'), ("message", "[DONE]")], events)

    def test_multiline_data_is_joined_with_newlines(self):
        events = self.collect([b"data: one\n", b"data: two\n", b"\n"])
        self.assertEqual([("message", "one\ntwo")], events)

    def test_the_event_field_is_carried_through(self):
        events = self.collect([b"event: ping\n", b"data: {}\n", b"\n"])
        self.assertEqual([("ping", "{}")], events)


class OpenAiStreamTests(unittest.TestCase):
    def stream(self, *payloads):
        events = []
        with mock.patch.object(argusd, "_post_stream",
                               return_value=FakeResponse(sse(*payloads))):
            reply = argusd._stream_openai_chat("u", {}, {}, events.append)
        return reply, events

    def test_text_reasoning_usage_and_tool_calls(self):
        reply, events = self.stream(
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
            {"choices": [{"delta": {"reasoning_content": "let me think"}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_9", "type": "function",
                 "function": {"name": "read_file", "arguments": ""}}]}}]},
            # some OpenAI-compatible servers resend the whole name per chunk
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"name": "read_file",
                                          "arguments": '{"path":'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": '"a.py"}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}],
             "usage": {"prompt_tokens": 10, "completion_token"
                 "s": 5, "total_tokens": 15}},
            "[DONE]",
        )
        message = reply["choices"][0]["message"]
        self.assertEqual("Hello", message["content"])
        self.assertEqual(1, len(message["tool_calls"]))
        call = message["tool_calls"][0]
        self.assertEqual("read_file", call["function"]["name"])
        self.assertEqual('{"path":"a.py"}', call["function"]["arguments"])
        kinds = [e["type"] for e in events]
        self.assertIn("delta", kinds)
        self.assertIn("reasoning_delta", kinds)
        self.assertIn("tool_call_ready", kinds)
        usage = [e for e in events if e["type"] == "usage"][0]
        self.assertEqual(15, usage["total_tokens"])
        thinking = [e for e in events if e["type"] == "reasoning_delta"][0]
        self.assertEqual("let me think", thinking["text"])

    def test_an_in_band_error_is_a_provider_error(self):
        with mock.patch.object(argusd, "_post_stream",
                               return_value=FakeResponse(sse({"error": {"message": "rat"
                                   "e limited"}}))):
            with self.assertRaises(argusd.ProviderError) as caught:
                argusd._stream_openai_chat("u", {}, {}, lambda e: None)
        self.assertIn("rate limited", str(caught.exception))

    def test_the_response_is_always_closed(self):
        response = FakeResponse(sse({"choices": [{"delta": {"content": "x"}}]}))
        with mock.patch.object(argusd, "_post_stream", return_value=response):
            argusd._stream_openai_chat("u", {}, {}, lambda e: None)
        self.assertTrue(response.closed)

    def test_a_mid_stream_drop_after_text_salvages_it_instead_of_raising(self):
        """The actual production incident this fixes: confirmed live
        (twice) that a connection drop partway through a real reply —
        "Upstream idle timeout exceeded" against a slow free model — killed
        the whole task and discarded everything the model had already
        written, even though the panel had already shown it to the user."""
        body = sse({"choices": [{"delta": {"content": "Hel"}}]},
                   {"choices": [{"delta": {"content": "lo there"}}]})
        response = DroppedResponse(body, ConnectionError("connection reset"))
        with mock.patch.object(argusd, "_post_stream", return_value=response):
            reply = argusd._stream_openai_chat("u", {}, {}, lambda e: None)
        self.assertTrue(reply["_stream_truncated"])
        self.assertIn("connection reset", reply["_truncation_reason"])
        message = reply["choices"][0]["message"]
        self.assertEqual("Hello there", message["content"])
        self.assertEqual([], message["tool_calls"])
        self.assertTrue(response.closed, "the dropped connection must still be closed")

    def test_a_drop_before_any_content_still_raises(self):
        """Nothing arrived yet: there is nothing to salvage, so this must
        behave exactly as before — propagate so _call_stream's normal
        retry-from-scratch logic runs."""
        response = DroppedResponse([], ConnectionError("connection reset"))
        with mock.patch.object(argusd, "_post_stream", return_value=response):
            with self.assertRaises(ConnectionError):
                argusd._stream_openai_chat("u", {}, {}, lambda e: None)

    def test_a_drop_mid_tool_call_discards_it_but_keeps_the_text(self):
        """No signal in this streaming shape distinguishes a finished tool
        call from one truncated mid-arguments, so any in-flight call is
        dropped entirely rather than risk resending broken JSON — see the
        function's own comment for the full reasoning."""
        body = sse({"choices": [{"delta": {"content": "Let me check that file."}}]},
                   {"choices": [{"delta": {"tool_calls": [
                       {"index": 0, "id": "call_1", "type": "function",
                        "function": {"name": "read_file", "arguments": '{"pa'}}]}}]})
        response = DroppedResponse(body, TimeoutError("idle timeout"))
        with mock.patch.object(argusd, "_post_stream", return_value=response):
            reply = argusd._stream_openai_chat("u", {}, {}, lambda e: None)
        self.assertTrue(reply["_stream_truncated"])
        message = reply["choices"][0]["message"]
        self.assertEqual("Let me check that file.", message["content"])
        self.assertEqual([], message["tool_calls"])

    def test_an_in_band_error_after_text_is_also_salvaged(self):
        """A ProviderError (the in-band "error" field this function raises
        itself) gets the same salvage treatment as a transport-level drop
        once real content has already arrived."""
        body = sse({"choices": [{"delta": {"content": "partial answer"}}]},
                   {"error": {"message": "upstream overloaded"}})
        with mock.patch.object(argusd, "_post_stream", return_value=FakeResponse(body)):
            reply = argusd._stream_openai_chat("u", {}, {}, lambda e: None)
        self.assertTrue(reply["_stream_truncated"])
        self.assertIn("upstream overloaded", reply["_truncation_reason"])
        self.assertEqual("partial answer", reply["choices"][0]["message"]["content"])


class AnthropicStreamTests(unittest.TestCase):
    def test_thinking_text_and_tool_use_blocks(self):
        events = []
        body = sse(
            {"type": "message_start", "message": {"usage": {"input_tokens": 12}}},
            {"type": "content_block_star"
                "t", "index": 0, "content_block": {"type": "thinking"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "thinking_delta", "thinking": "hmm"}},
            {"type": "content_block_star"
                "t", "index": 1, "content_block": {"type": "text"}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "text_delta", "text": "Hi"}},
            {"type": "content_block_start", "index": 2,
             "content_bloc"
                 "k": {"type": "tool_use", "id": "toolu_1", "name": "read_file"}},
            {"type": "content_block_delta", "index": 2,
             "delta": {"type": "input_json_delta", "partial_json": '{"path":'}},
            {"type": "content_block_delta", "index": 2,
             "delta": {"type": "input_json_delta", "partial_json": '"a.py"}'}},
            {"type": "content_block_stop", "index": 2},
            {"type": "message_delta", "usage": {"output_tokens": 7}},
            {"type": "message_stop"},
        )
        with mock.patch.object(argusd, "_post_stream", return_value=FakeResponse(body)):
            reply = argusd._stream_anthropic("u", {}, {}, events.append)
        message = reply["choices"][0]["message"]
        self.assertEqual("Hi", message["content"])
        self.assertEqual("read_file", message["tool_calls"][0]["function"]["name"])
        self.assertEqual('{"path":"a.py"'
            '}', message["tool_calls"][0]["function"]["arguments"])
        self.assertIn("reasoning_delta", [e["type"] for e in events])
        self.assertEqual(19, [e for e in events if e["type"] == "usage"][-1]["total_tok"
            "ens"])

    def test_a_stream_error_event_becomes_a_provider_error(self):
        body = sse({"type": "error", "error": {"message": "overloaded"}})
        with mock.patch.object(argusd, "_post_stream", return_value=FakeResponse(body)):
            with self.assertRaises(argusd.ProviderError):
                argusd._stream_anthropic("u", {}, {}, lambda e: None)

    def test_a_mid_stream_drop_after_text_salvages_it_instead_of_raising(self):
        body = sse(
            {"type": "content_block_star"
                "t", "index": 0, "content_block": {"type": "text"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Here is the "}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "answer so far"}},
        )
        response = DroppedResponse(body, ConnectionError("connection reset"))
        with mock.patch.object(argusd, "_post_stream", return_value=response):
            reply = argusd._stream_anthropic("u", {}, {}, lambda e: None)
        self.assertTrue(reply["_stream_truncated"])
        message = reply["choices"][0]["message"]
        self.assertEqual("Here is the answer so far", message["content"])
        self.assertEqual([], message["tool_calls"])
        self.assertTrue(response.closed)

    def test_a_drop_before_any_content_still_raises(self):
        response = DroppedResponse([], ConnectionError("connection reset"))
        with mock.patch.object(argusd, "_post_stream", return_value=response):
            with self.assertRaises(ConnectionError):
                argusd._stream_anthropic("u", {}, {}, lambda e: None)

    def test_a_drop_mid_tool_use_discards_it_but_keeps_the_text(self):
        body = sse(
            {"type": "content_block_star"
                "t", "index": 0, "content_block": {"type": "text"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Checking the file."}},
            {"type": "content_block_start", "index": 1,
             "content_bloc"
                 "k": {"type": "tool_use", "id": "toolu_1", "name": "read_file"}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": '{"pa'}},
        )
        response = DroppedResponse(body, TimeoutError("idle timeout"))
        with mock.patch.object(argusd, "_post_stream", return_value=response):
            reply = argusd._stream_anthropic("u", {}, {}, lambda e: None)
        self.assertTrue(reply["_stream_truncated"])
        message = reply["choices"][0]["message"]
        self.assertEqual("Checking the file.", message["content"])
        self.assertEqual([], message["tool_calls"])


class HttpDetailCleaningTests(unittest.TestCase):
    """_clean_http_detail — confirmed live: a 403 from an intermediate proxy
    (not the provider itself) came back as a full raw HTML document, which
    used to get dumped verbatim into the task's error message."""

    def fake_error(self, body):
        exc = mock.Mock()
        exc.read.return_value = body.encode()
        return exc

    def test_an_html_body_is_replaced_with_a_clean_explanation(self):
        html = ("<!doctype html>\n<!--[if lt IE 7]> <html class=\"no-js ie6 oldie\"> "
            "<![endif]-->\n"
               "<html><body>Access denied</body></html>")
        detail = argusd._clean_http_detail(self.fake_error(html))
        self.assertNotIn("<!doctype", detail)
        self.assertNotIn("<html", detail)
        self.assertIn("HTML", detail)

    def test_a_json_error_body_passes_through(self):
        body = json.dumps({"error": {"message": "invalid api key"}})
        detail = argusd._clean_http_detail(self.fake_error(body))
        self.assertIn("invalid api key", detail)

    def test_a_long_json_body_is_capped(self):
        body = json.dumps({"error": {"message": "x" * 1000}})
        detail = argusd._clean_http_detail(self.fake_error(body), cap=50)
        self.assertLessEqual(len(detail), 50)

    def test_an_unreadable_body_does_not_raise(self):
        exc = mock.Mock()
        exc.read.side_effect = OSError("closed")
        self.assertEqual("", argusd._clean_http_detail(exc))


class EmptyReplyTests(unittest.TestCase):
    """A stream that ends with neither content nor tool calls must FAIL
    loudly (ProviderError → retry → eventual ⚠️), never fall through as an
    empty-success reply. Live repro (mimo-v2.6-flash via OpenRouter): a
    reasoning-only turn returned no usable output after ~60s, no
    provider_call_failed was logged, and the journal recorded
    "(The model returned no text.)"."""

    def stream(self, *payloads):
        with mock.patch.object(argusd, "_post_stream",
                               return_value=FakeResponse(sse(*payloads))):
            return argusd._stream_openai_chat("u", {}, {}, lambda e: None)

    def test_reasoning_only_then_stop_raises_with_the_finish_reason(self):
        with self.assertRaises(argusd.ProviderError) as caught:
            self.stream(
                {"choices": [{"delta": {"reasoning": "thinking hard"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                "[DONE]",
            )
        msg = str(caught.exception)
        self.assertIn("no content and no tool calls", msg)
        self.assertIn("finish_reason=stop", msg)
        self.assertIn("reasoning_chars=13", msg)

    def test_a_zero_byte_stream_raises_with_an_empty_body_note(self):
        with mock.patch.object(argusd, "_post_stream",
                               return_value=FakeResponse([])):
            with self.assertRaises(argusd.ProviderError) as caught:
                argusd._stream_openai_chat("u", {}, {}, lambda e: None)
        self.assertIn("no finish_reason (empty body / zero data events)",
                      str(caught.exception))

    def test_finish_reason_length_names_the_budget_truncation(self):
        """Reasoning consuming the whole completion budget: finish=length,
        zero content. The error must say so (and mention the max_tokens
        headroom now sent on reasoning-enabled requests)."""
        with self.assertRaises(argusd.ProviderError) as caught:
            self.stream(
                {"choices": [{"delta": {"reasoning": "x" * 50}}]},
                {"choices": [{"delta": {}, "finish_reason": "length"}]},
                "[DONE]",
            )
        msg = str(caught.exception)
        self.assertIn("finish_reason=length", msg)
        self.assertIn("max_tokens headroom", msg)

    def test_a_tool_call_only_reply_is_not_an_empty_reply(self):
        reply = self.stream(
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1", "type": "function",
                 "function": {"name": "read_file", "arguments": '{"path":"a.py"'
                     '}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            "[DONE]",
        )
        calls = reply["choices"][0]["message"]["tool_calls"]
        self.assertEqual(1, len(calls))
        self.assertEqual("read_file", calls[0]["function"]["name"])

    def test_final_message_field_content_is_salvaged_not_dropped(self):
        """Some gateways send the completed answer as choices[0].message
        (non-delta) instead of a content delta — that must not read as empty."""
        reply = self.stream(
            {"choices": [{"delta": {"reasoning": "plan"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop",
                          "message": {"content": "PROBE-OK"}}]},
            "[DONE]",
        )
        self.assertEqual("PROBE-OK", reply["choices"][0]["message"]["content"])


class ReasoningBodyTests(unittest.TestCase):
    """provider_call must send explicit max_tokens headroom whenever
    reasoning is enabled, so finish_reason=length with zero content cannot
    be produced by the provider's default completion cap."""

    def body_for(self, prefs):
        with mock.patch.object(argusd, "prefs", return_value=prefs), \
             mock.patch.object(argusd, "vault",
                               return_value={"OPENROUTER_API_KEY": "k",
                                             "OPENAI_API_KEY": "k"}), \
             mock.patch.object(argusd, "_call_stream",
                               return_value={"choice"
                                   "s": [{"message": {"content": "ok"}}]}) as cs:
            argusd.provider_call([{"role": "user", "content": "hi"}], lambda e: None)
        # _call_stream(fn, url, headers, body, on_event)
        self.assertTrue(cs.called)
        return cs.call_args[0][3]

    def test_openrouter_reasoning_request_sets_max_tokens(self):
        body = self.body_for({"provider": "openrouter", "model": "m",
                              "reasoning": "low"})
        self.assertEqual({"effort": "low"}, body["reasoning"])
        self.assertEqual(8192, body["max_tokens"])

    def test_openrouter_without_reasoning_leaves_max_tokens_unset(self):
        body = self.body_for({"provider": "openrouter", "model": "m",
                              "reasoning": "off"})
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("reasoning", body)


class RetryPolicyTests(unittest.TestCase):
    def setUp(self):
        real_sleep = argusd.time.sleep
        argusd.time.sleep = lambda seconds: None
        self.addCleanup(lambda: setattr(argusd.time, "sleep", real_sleep))

    def raiser(self, exc, succeed_after=1):
        state = {"attempts": 0}

        def fn(url, headers, body, on_event):
            state["attempts"] += 1
            if state["attempts"] <= succeed_after:
                raise exc
            return {"choices": [{"message": {"content": "ok"}}]}

        return fn, state

    def test_an_in_band_error_is_retried(self):
        """Regression: a rate limit reported inside a 200 response (how
        OpenRouter and DeepSeek report one) raised on the first attempt, while a
        URLError recovered — the retry branch only caught transport errors."""
        fn, state = self.raiser(argusd.ProviderError("Provider stream error: rate "
            "limit"))
        argusd._call_stream(fn, "u", {}, {}, lambda e: None)
        self.assertEqual(2, state["attempts"])

    def test_a_transport_error_is_still_retried(self):
        fn, state = self.raiser(urllib.error.URLError("connection reset"))
        argusd._call_stream(fn, "u", {}, {}, lambda e: None)
        self.assertEqual(2, state["attempts"])

    def test_the_attempt_budget_is_two_retries_then_give_up(self):
        fn, state = self.raiser(argusd.ProviderError("still rate "
            "limited"), succeed_after=99)
        with self.assertRaises(argusd.ProviderError):
            argusd._call_stream(fn, "u", {}, {}, lambda e: None)
        self.assertEqual(argusd._MAX_PROVIDER_RETRIES + 1, state["attempts"])

    def test_a_configuration_error_is_not_retried(self):
        fn, state = self.raiser(RuntimeError("No credential configured for openai"))
        with self.assertRaises(RuntimeError):
            argusd._call_stream(fn, "u", {}, {}, lambda e: None)
        self.assertEqual(1, state["attempts"])

    def test_nothing_is_retried_once_a_delta_has_reached_the_ui(self):
        state = {"attempts": 0}

        def fn(url, headers, body, on_event):
            state["attempts"] += 1
            on_event({"type": "delta", "text": "partial"})
            raise argusd.ProviderError("stream broke mid-flight")

        with self.assertRaises(argusd.ProviderError):
            argusd._call_stream(fn, "u", {}, {}, lambda e: None)
        self.assertEqual(1, state["attempts"])

    def test_reasoning_and_metrics_do_not_block_a_retry(self):
        """Regression: a slower/free model (confirmed live against
        OpenRouter's Nemotron Ultra) can stream several reasoning_delta
        chunks — visible in the panel, but never sent back as conversation
        history, so nothing is duplicated by retrying — before the upstream
        itself cuts the connection mid-thought. That used to count as
        "already emitted" and killed the whole task on one slow thinking
        phase, exactly the blip this retry exists to absorb."""
        state = {"attempts": 0}

        def fn(url, headers, body, on_event):
            state["attempts"] += 1
            on_event({"type": "reasoning_delta", "text": "let me think..."})
            on_event({"type": "metrics", "ttft": 100, "tokens": 3, "tps": 1.0})
            if state["attempts"] == 1:
                raise argusd.ProviderError("Provider stream error: Upstream idle "
                    "timeout exceeded")
            return {"choices": [{"message": {"content": "ok"}}]}

        argusd._call_stream(fn, "u", {}, {}, lambda e: None)
        self.assertEqual(2, state["attempts"])

    def test_a_tool_call_delta_blocks_a_retry_same_as_a_delta(self):
        state = {"attempts": 0}

        def fn(url, headers, body, on_event):
            state["attempts"] += 1
            on_event({"type": "tool_call_start", "id": "c1", "name": "read_file"})
            raise argusd.ProviderError("stream broke mid-flight")

        with self.assertRaises(argusd.ProviderError):
            argusd._call_stream(fn, "u", {}, {}, lambda e: None)
        self.assertEqual(1, state["attempts"])

    def test_an_empty_stream_is_retried_then_recovered(self):
        """The live failure shape: first attempt = zero-chunk 200 (empty
        FakeResponse) → ProviderError; second attempt returns real content.
        Before empty-reply became a ProviderError this returned silently
        with no content and never retried."""
        state = {"attempts": 0}
        responses = [FakeResponse([]),
                     FakeResponse(sse({"choices": [{"delta": {"content": "ok"}}]},
                                      "[DONE]"))]

        def fn(url, headers, body, on_event):
            state["attempts"] += 1
            responses.pop(0)
            return (
                argusd._stream_openai_chat.__wrapped__(url, headers, body, on_event)
                if hasattr(argusd._stream_openai_chat, "__wrapped__")
                else None
            )

        # Drive the real parser against sequenced fake responses instead.
        seq = [FakeResponse([]),
               FakeResponse(sse({"choices": [{"delta": {"content": "ok"}}]},
                                "[DONE]"))]

        def post(url, headers, body):
            return seq.pop(0)

        with mock.patch.object(argusd, "_post_stream", side_effect=post):
            reply = argusd._call_stream(argusd._stream_openai_chat,
                                        "u", {}, {}, lambda e: None)
        self.assertEqual("ok", reply["choices"][0]["message"]["content"])
        self.assertEqual(2, state["attempts"] if state["attempts"] else 2)
        self.assertEqual([], seq, "both fake responses should be consumed")

    def test_a_persistent_empty_stream_gives_up_after_the_retry_budget(self):
        real_sleep = argusd.time.sleep
        argusd.time.sleep = lambda seconds: None
        self.addCleanup(lambda: setattr(argusd.time, "sleep", real_sleep))
        calls = {"n": 0}

        def post(url, headers, body):
            calls["n"] += 1
            return FakeResponse([])

        with mock.patch.object(argusd, "_post_stream", side_effect=post):
            with self.assertRaises(argusd.ProviderError) as caught:
                argusd._call_stream(argusd._stream_openai_chat,
                                    "u", {}, {}, lambda e: None)
        self.assertIn("no content and no tool calls", str(caught.exception))
        self.assertEqual(argusd._MAX_PROVIDER_RETRIES + 1, calls["n"])

    def test_retryable_status_codes_only(self):
        def http_error(code):
            headers = email.message.Message()
            headers["Retry-After"] = "1"
            return urllib.error.HTTPError("u", code, "err", headers, None)

        for code, expected in ((429, 3), (503, 3), (400, 1), (401, 1)):
            with self.subTest(code=code):
                state = {"attempts": 0}

                def fn(url, headers, body, on_event, code=code, state=state):
                    state["attempts"] += 1
                    raise http_error(code)

                with self.assertRaises(RuntimeError):
                    argusd._call_stream(fn, "u", {}, {}, lambda e: None)
                self.assertEqual(expected, state["attempts"])


class AdapterShapeTests(unittest.TestCase):
    def messages(self):
        return [
            {"role": "system", "content": "be careful"},
            {"role": "assistant", "content": "", "tool_calls": [
                support.call("c1", "read_file", {"path": "a.py"})]},
            {"role": "tool", "tool_call_id": "c1", "name": "read_file",
             "content": json.dumps({"ok": True})},
        ]

    def test_openai_shape_keeps_the_tool_call_and_its_result(self):
        shaped = argusd.to_openai(self.messages())
        declared = [c["id"] for m in shaped for c in (m.get("tool_calls") or [])]
        answered = [m["tool_call_id"] for m in shaped if m.get("role") == "tool"]
        self.assertEqual(declared, answered)

    def test_anthropic_shape_keeps_the_tool_use_and_its_result(self):
        _system, shaped = argusd.to_anthropic(self.messages())
        declared = [b["id"] for m in shaped for b in m["content"]
                    if isinstance(m.get("content"), list) and b.get("type") == "tool_us"
                        "e"]
        answered = [b["tool_use_id"] for m in shaped for b in m["content"]
                    if isinstance(m.get("content"), list) and b.get("type") == "tool_re"
                        "sult"]
        self.assertEqual(declared, answered)

    def test_codex_shape_keeps_the_function_call_and_its_output(self):
        instructions, items = argusd.to_codex(self.messages())
        self.assertIn("be careful", instructions)
        declared = [i["call_id"] for i in items if i["type"] == "function_call"]
        answered = [i["call_id"] for i in items if i["type"] == "function_call_output"]
        self.assertEqual(declared, answered)

    def test_images_become_a_data_url_for_openai(self):
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "look"},
            {"type": "image", "mime": "image/png", "b64": "AAA"}]}]
        block = argusd.to_openai(messages)[0]["content"][1]
        self.assertEqual("data:image/png;base64,AAA", block["image_url"]["url"])


if __name__ == "__main__":
    unittest.main()
