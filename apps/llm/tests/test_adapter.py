"""Adapter behavior tests with a stubbed SDK client — no network involved."""
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from apps.llm.adapter import GeminiAdapter, LLMRateLimited, LLMUnavailable, _make_client


def chunk(text, prompt=None, candidates=None, thoughts=None):
    """Stand-in for a google.genai stream chunk."""
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt,
            candidates_token_count=candidates,
            thoughts_token_count=thoughts,
        ),
    )


def usage(prompt, candidates, thoughts=None):
    return chunk(text="", prompt=prompt, candidates=candidates, thoughts=thoughts).usage_metadata


class FakeModels:
    """Replays scripted attempts: each script is a list of chunks (or exceptions)."""

    def __init__(self, scripts):
        self.scripts = scripts
        self.calls = 0

    def _current_script(self):
        if self.calls < len(self.scripts):
            return self.scripts[self.calls]
        return self.scripts[-1]

    def generate_content_stream(self, model=None, contents=None):
        items = self._current_script()
        self.calls += 1
        if isinstance(items, Exception):
            raise items
        for item in items:
            if isinstance(item, Exception):
                raise item
            yield item

    def generate_content(self, model=None, contents=None):
        items = self._current_script()
        self.calls += 1
        if isinstance(items, Exception):
            raise items
        return items[0]


@pytest.fixture
def fast_sleep(monkeypatch):
    monkeypatch.setattr("apps.llm.adapter.time.sleep", lambda seconds: None)


@pytest.fixture
def swap_client(monkeypatch):
    def install(scripts):
        models = FakeModels(scripts)
        monkeypatch.setattr(
            "apps.llm.adapter._make_client",
            lambda api_key, timeout_seconds: SimpleNamespace(models=models),
        )
        return models
    return install


def make_adapter(retries=2):
    return GeminiAdapter(api_key="test-key", model="test-model", timeout_seconds=1, retries=retries)


def test_stream_success_emits_text_chunks_and_authoritative_final_usage(swap_client):
    swap_client([
        [chunk("Ola ", prompt=4, candidates=2), chunk("mundo", prompt=7, candidates=5)],
    ])
    events = list(make_adapter().generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True))

    assert events[0] == {"text": "Ola ", "usage": {"prompt_tokens": 4, "completion_tokens": 2}}
    assert events[1] == {"text": "mundo", "usage": {"prompt_tokens": 7, "completion_tokens": 5}}
    final = events[-1]
    assert final["text"] == ""
    assert final["usage"]["prompt_tokens"] == 7  # cumulative totals, not summed
    assert final["usage"]["completion_tokens"] == 5
    assert final["usage"]["latency_ms"] >= 0
    assert final["usage"]["provider"] == "gemini"
    assert final["usage"]["model"] == "test-model"


def test_completion_tokens_include_billable_thinking_tokens(swap_client):
    swap_client([[chunk("Answer", prompt=10, candidates=4, thoughts=180)]])
    events = list(make_adapter().generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True))

    assert events[0]["usage"]["completion_tokens"] == 184  # 4 visible + 180 thinking


def test_stream_retries_before_the_first_text_byte(swap_client, fast_sleep):
    models = swap_client([
        [Exception("connection reset")],          # attempt 1 dies before any byte
        [chunk("Hello there!", prompt=3, candidates=2)],
    ])
    events = list(make_adapter().generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True))

    assert models.calls == 2
    # The retry replays from scratch: the answer text appears exactly once.
    texts = [event["text"] for event in events]
    assert texts == ["Hello there!", ""]
    assert events[0]["usage"]["prompt_tokens"] == 3


def test_stream_never_resends_after_a_partial_answer(swap_client, fast_sleep):
    swap_client([
        [chunk("Part", prompt=3, candidates=1), Exception("network dropped")],
        [chunk("Part"), chunk("THE DUPLICATE TEST")],  # would run only if retried
    ])
    with pytest.raises(LLMUnavailable, match="interrupted mid-answer"):
        list(make_adapter().generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True))


def test_stream_failure_exhausts_retries_and_names_the_error(swap_client, fast_sleep):
    swap_client([Exception("overloaded"), Exception("overloaded"), Exception("still overloaded")])
    with pytest.raises(LLMUnavailable, match="still overloaded"):
        list(make_adapter(retries=2).generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True))


def test_complete_returns_text_with_usage_and_call_info(swap_client):
    swap_client([[chunk("Hi!", prompt=4, candidates=3, thoughts=5)]])
    result = make_adapter().generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=False)

    assert result["text"] == "Hi!"
    assert result["usage"]["prompt_tokens"] == 4
    assert result["usage"]["completion_tokens"] == 8  # 3 + 5
    assert {"latency_ms", "provider", "model"} <= set(result["usage"])


def test_missing_api_key_fails_fast():
    adapter = GeminiAdapter(api_key="", model="test-model", retries=0)

    with pytest.raises(LLMUnavailable, match="GEMINI_API_KEY"):
        adapter.generate([{"role": "user", "parts": [{"text": "hi"}]}])


def test_make_client_builds_a_fast_failing_sdk_client():
    client = _make_client("some-key", 45)

    assert client.models is not None


QUOTA_MESSAGE = (
    "You exceeded your current quota. * Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
    "limit: 20, model: gemini-3.6-flash. Please retry in 15h59m6.515044973s."
)


def test_rate_limit_stops_retries_and_reports_a_short_message(swap_client):
    models = swap_client([genai_errors.ClientError(429, {"error": {"code": 429, "message": QUOTA_MESSAGE}})])

    with pytest.raises(LLMRateLimited) as caught:
        list(make_adapter(retries=2).generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True))

    assert "20 questions/day" in str(caught.value)          # real limit, parsed
    assert "about 15h59m" in str(caught.value)              # real wait, parsed
    assert caught.value.error_code == "rate_limited"        # PRD § 8 code
    assert str(caught.value).count("Quota exceeded") == 0   # no raw payload leaks
    assert models.calls == 1                                # blind retries abandoned


def test_rate_limit_in_non_stream_calls_uses_the_same_message(swap_client):
    swap_client([genai_errors.ClientError(429, {"error": {"code": 429, "message": QUOTA_MESSAGE}})])

    with pytest.raises(LLMRateLimited, match="20 questions/day"):
        make_adapter().generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=False)


def test_rate_limit_without_parseable_details_falls_back_to_a_stable_line(swap_client):
    swap_client([genai_errors.ClientError(429, {"error": {"code": 429, "message": "quota is gone"}})])

    with pytest.raises(LLMRateLimited, match="try again later"):
        list(make_adapter().generate([{"role": "user", "parts": [{"text": "hi"}]}], stream=True))
