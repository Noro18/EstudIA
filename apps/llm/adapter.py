"""Gemini adapter — the only module that talks to Google's Gemini API (PRD § 7).

Provider and model come from environment variables (GEMINI_API_KEY, LLM_MODEL).
Every call reports prompt tokens, completion tokens (including hidden thinking
tokens, which Google bills), latency, provider, and model.
"""
import logging
import time

from django.conf import settings
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Raised when the provider cannot produce an answer after retries."""


def _make_client(api_key, timeout_seconds):
    """Build a fast-failing Gemini client.

    The SDK's own retries are disarmed on purpose: the adapter's retry loop
    (LLM_RETRIES) keeps control, so nothing is ever re-sent after the first
    text byte (no mid-stream duplication).
    """
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=timeout_seconds * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def _usage_from_metadata(metadata):
    """Map SDK usage metadata to the adapter usage contract.

    completion_tokens includes thinking tokens because Google bills them:
    total = prompt + candidates + thoughts.
    """
    if metadata is None:
        return {}
    return {
        "prompt_tokens": metadata.prompt_token_count or 0,
        "completion_tokens": (metadata.candidates_token_count or 0)
        + (metadata.thoughts_token_count or 0),
    }


class GeminiAdapter:
    """Answers from the Gemini API behind generate(messages, stream)."""

    def __init__(self, api_key=None, model=None, timeout_seconds=None, retries=None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.LLM_MODEL
        self.timeout_seconds = timeout_seconds if timeout_seconds else settings.LLM_TIMEOUT_SECONDS
        self.retries = retries if retries is not None else settings.LLM_RETRIES
        self._client = None

    def generate(self, messages, stream=False):
        if not self.api_key:
            raise LLMUnavailable("GEMINI_API_KEY is not configured.")
        client = self._get_client()
        if stream:
            return self._stream(client, messages)
        return self._complete(client, messages)

    def _get_client(self):
        if self._client is None:
            self._client = _make_client(self.api_key, self.timeout_seconds)
        return self._client

    def _complete(self, client, messages):
        started_at = time.perf_counter()
        for attempt in range(self.retries + 1):
            try:
                response = client.models.generate_content(model=self.model, contents=messages)
                usage = _usage_from_metadata(response.usage_metadata)
                usage["latency_ms"] = int((time.perf_counter() - started_at) * 1000)
                usage["provider"] = "gemini"
                usage["model"] = self.model
                return {"text": response.text or "", "usage": usage}
            except Exception as exc:
                if attempt == self.retries:
                    logger.exception("Gemini request failed after %s attempts", attempt + 1)
                    raise LLMUnavailable(f"Gemini did not return an answer: {exc}") from exc
                logger.warning("Gemini request failed; retrying attempt=%s (%s)", attempt + 1, exc)
                time.sleep(2**attempt)
        raise LLMUnavailable("Gemini did not return an answer.")  # pragma: no cover

    def _stream(self, client, messages):
        started_at = time.perf_counter()
        usage = {}
        for attempt in range(self.retries + 1):
            try:
                # Gemini sends cumulative usage on every event: the last value
                # is the authoritative total (views keep the last, by contract).
                for chunk in client.models.generate_content_stream(model=self.model, contents=messages):
                    usage.update(_usage_from_metadata(chunk.usage_metadata))
                    if chunk.text:
                        yield {"text": chunk.text, "usage": dict(usage)}
                break
            except Exception as exc:
                if usage:  # text already delivered to the caller — never re-send
                    logger.exception("Gemini stream interrupted after a partial answer")
                    raise LLMUnavailable("Gemini stream was interrupted mid-answer.") from exc
                if attempt == self.retries:
                    logger.exception("Gemini streaming failed after %s attempts", attempt + 1)
                    raise LLMUnavailable(f"Gemini streaming failed: {exc}") from exc
                logger.warning("Gemini streaming failed; retrying attempt=%s (%s)", attempt + 1, exc)
                time.sleep(2**attempt)
        usage["latency_ms"] = int((time.perf_counter() - started_at) * 1000)
        usage["provider"] = "gemini"
        usage["model"] = self.model
        yield {"text": "", "usage": usage}
