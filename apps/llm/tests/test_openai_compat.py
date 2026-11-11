"""OpenAI-compat adapter tests with an httpx.MockTransport — no network."""
import json

import httpx
import pytest

from apps.llm.adapter import LLMRateLimited, LLMUnavailable
from apps.llm.openai_compat import OpenAICompatAdapter, to_openai_messages


def completion_response(text, prompt_tokens=9, completion_tokens=5):
    body = {
        "id": "chatcmpl-x",
        "model": "test-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }
    return httpx.Response(200, json=body)


def make_adapter(scripts, retries=2):
    """Replay one httpx.Response (or exception) per attempt."""
    calls = []

    def handler(request):
        calls.append(request)
        item = scripts[len(calls) - 1 if len(calls) <= len(scripts) else -1]
        if isinstance(item, Exception):
            raise item
        return item

    transport = httpx.MockTransport(handler)
    adapter = OpenAICompatAdapter(
        base_url="https://upstream.test/v1",
        api_key="test-key",
        model="test-model",
        timeout_seconds=120,
        retries=retries,
        transport=transport,
    )
    return adapter, calls


@pytest.fixture
def fast_sleep(monkeypatch):
    monkeypatch.setattr("apps.llm.openai_compat.time.sleep", lambda seconds: None)


def test_to_openai_messages_flattens_gemini_parts():
    messages = [{"role": "user", "parts": [{"text": "Saida mak diabetes?"}]}]

    assert to_openai_messages(messages) == [
        {"role": "user", "content": "Saida mak diabetes?"}
    ]


def test_to_openai_messages_passes_openai_style_through():
    messages = [{"role": "assistant", "content": "hi"}]

    assert to_openai_messages(messages) == [{"role": "assistant", "content": "hi"}]


def test_complete_returns_text_with_usage_and_call_info(fast_sleep):
    adapter, calls = make_adapter([completion_response("Ola!")])

    result = adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}])

    assert result["text"] == "Ola!"
    assert result["usage"]["prompt_tokens"] == 9
    assert result["usage"]["completion_tokens"] == 5
    assert result["usage"]["latency_ms"] >= 0
    assert result["usage"]["provider"] == "openai_compat"
    assert result["usage"]["model"] == "test-model"
    sent = json.loads(calls[0].content)
    assert sent["model"] == "test-model"
    assert sent["messages"] == [{"role": "user", "content": "hi"}]


def sse_body(*deltas, usage=None):
    """Encode SSE chunks the way the Labadain endpoint sends them."""
    events = []
    for item in deltas:
        events.append("data: " + json.dumps(item))
    if usage:
        events.append("data: " + json.dumps({"choices": [], "usage": usage}))
    events.append("data: [DONE]")
    return ("\n\n".join(events) + "\n").encode()


def delta(text=None, reasoning=None):
    payload = {}
    if text is not None:
        payload["content"] = text
    if reasoning is not None:
        payload["reasoning"] = reasoning
    return {"choices": [{"index": 0, "delta": payload, "finish_reason": None}]}


def test_stream_yields_each_delta_then_final_usage(fast_sleep):
    body = sse_body(
        delta(text="Resposta "),
        delta(text="osan"),
        usage={"prompt_tokens": 9, "completion_tokens": 5},
    )
    adapter, _ = make_adapter([httpx.Response(200, content=body)])

    events = list(
        adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True)
    )

    # Real SSE now: one text event per delta, then the authoritative
    # empty-text usage event (the contract the QA view keeps the last of).
    assert [event["text"] for event in events] == ["Resposta ", "osan", ""]
    assert events[-1]["usage"]["completion_tokens"] == 5


def test_stream_skips_reasoning_and_done_sentinels(fast_sleep):
    body = sse_body(
        delta(reasoning="Thinking Process:"),
        delta(reasoning="1. Analyze"),
        delta(text="Ola!"),
        delta(text=None),
    )
    adapter, _ = make_adapter([httpx.Response(200, content=body)])

    events = list(
        adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True)
    )

    assert [event["text"] for event in events] == ["Ola!", ""]


def test_stream_retries_transport_failure_before_any_text(fast_sleep):
    body = sse_body(delta(text="back"), usage={"prompt_tokens": 1, "completion_tokens": 1})
    adapter, calls = make_adapter(
        [httpx.ConnectError("down"), httpx.Response(200, content=body)]
    )

    events = list(
        adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True)
    )

    assert [event["text"] for event in events] == ["back", ""]
    assert len(calls) == 2


def test_stream_failure_after_text_never_retries(fast_sleep):
    class _DyingStream(httpx.SyncByteStream):
        """A stream that delivers one delta, then the connection dies."""

        def __iter__(self):
            yield ("data: " + json.dumps(delta(text="partial")) + "\n\n").encode()
            raise httpx.ReadTimeout("connection died")

    adapter, calls = make_adapter(
        [httpx.Response(200, stream=_DyingStream()), httpx.Response(500)]
    )

    events = adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True)
    assert next(events)["text"] == "partial"

    # Mid-stream death must surface, not silently re-send into the same bubble.
    with pytest.raises(LLMUnavailable, match="interrupted mid-answer"):
        next(events)
    assert len(calls) == 1


def test_retries_transport_failures_then_succeeds(fast_sleep):
    adapter, calls = make_adapter(
        [httpx.ConnectError("tunnel down"), completion_response("back")]
    )

    result = adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}])

    assert result["text"] == "back"
    assert len(calls) == 2


def test_persistent_timeout_exhausts_retries(fast_sleep):
    adapter, calls = make_adapter(
        [httpx.ConnectError("down"), httpx.ConnectError("down"), httpx.ConnectError("down")]
    )

    with pytest.raises(LLMUnavailable, match="did not return an answer in time"):
        adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}])

    assert len(calls) == 3


def test_rate_limit_stops_retries(fast_sleep):
    adapter, calls = make_adapter([httpx.Response(429, json={"detail": "busy"})])

    with pytest.raises(LLMRateLimited, match="busy; try again shortly"):
        adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}])

    assert len(calls) == 1  # 429 must not be retried blindly


def test_http_error_exhausts_retries_and_names_the_status(fast_sleep):
    adapter, calls = make_adapter([httpx.Response(500, text="boom")] * 3)

    with pytest.raises(LLMUnavailable, match="HTTP 500"):
        adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}])

    assert len(calls) == 3


def test_empty_content_and_missing_usage_are_tolerated(fast_sleep):
    adapter, _ = make_adapter(
        [httpx.Response(200, json={"choices": [{"message": {"content": None}}]})]
    )

    result = adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}])

    assert result["text"] == ""
    assert result["usage"]["prompt_tokens"] == 0
    assert result["usage"]["completion_tokens"] == 0


def test_missing_api_key_fails_fast():
    adapter = OpenAICompatAdapter(
        base_url="https://upstream.test/v1", api_key="", model="test-model"
    )

    with pytest.raises(LLMUnavailable, match="OPENAI_COMPAT_API_KEY"):
        adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}])


def test_missing_base_url_fails_fast():
    adapter = OpenAICompatAdapter(base_url="", api_key="k", model="test-model")

    with pytest.raises(LLMUnavailable, match="OPENAI_COMPAT_BASE_URL"):
        adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}])
