"""Gemini adapter — the only module that talks to Google's Gemini API (PRD § 7).

Provider and model come from environment variables (GEMINI_API_KEY, LLM_MODEL).
Every call reports prompt tokens, completion tokens (including hidden thinking
tokens, which Google bills), latency, provider, and model.
"""
import logging
import re
import time

from django.conf import settings
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Raised when the provider cannot produce an answer after retries."""

    error_code = "llm_unavailable"


class LLMRateLimited(LLMUnavailable):
    """Provider quota exhausted — surfaced with the PRD § 8 `rate_limited` code.

    Carries a short user-facing message instead of the raw provider payload.
    """

    error_code = "rate_limited"


_RATE_LIMIT_FALLBACK = (
    "Daily limit reached — try again later, or ask the admin to switch models."
)


def _rate_limit_message(exc):
    """Build a short, human message from a provider 429 response.

    Google's payload names the actual limit ("limit: 20") and, on Free Tier
    daily caps, a wait ("Please retry in 15h59m…"). Pull both out so users see
    one line instead of a JSON dump.
    """
    detail = str(getattr(exc, "message", "") or exc)
    limit = re.search(r"limit: ?(\d+)", detail)
    delay = re.search(r"retry in ?([\dhms.]+)", detail)
    parts = []
    if limit:
        parts.append(f"{limit.group(1)} questions/day on this model")
        if delay:
            parts.append(f"try again in about {delay.group(1).rstrip('.')}")
        else:
            parts.append("try again tomorrow")
        return "Daily limit reached: " + " — ".join(parts) + ", or ask the admin to switch models."
    if delay:
        return f"Rate limit reached — try again in about {delay.group(1).rstrip('.')}."
    return _RATE_LIMIT_FALLBACK


def _rate_limit_error(exc):
    return LLMRateLimited(_rate_limit_message(exc))


def _is_rate_limited(exc):
    return isinstance(exc, genai_errors.ClientError) and getattr(exc, "code", None) == 429


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
        # Explicit values win — including an explicitly empty key, which lets
        # tests and fail-fast deployments catch misconfiguration immediately.
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = model if model is not None else settings.LLM_MODEL
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.LLM_TIMEOUT_SECONDS
        )
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
                if _is_rate_limited(exc):
                    logger.warning("Gemini quota exhausted; not retrying")
                    raise _rate_limit_error(exc) from exc
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
                if _is_rate_limited(exc):
                    logger.warning("Gemini quota exhausted; not retrying")
                    raise _rate_limit_error(exc) from exc
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
