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


def test_stream_yields_the_whole_answer_then_final_usage(fast_sleep):
    adapter, _ = make_adapter([completion_response("Resposta osan")])

    events = list(
        adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True)
    )

    # Upstream cannot stream: one text event, then the authoritative empty-text
    # usage event (the contract the QA view keeps the last of).
    assert [event["text"] for event in events] == ["Resposta osan", ""]
    assert events[-1]["usage"]["completion_tokens"] == 5


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
