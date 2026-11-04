"""OpenAI-compatible adapter — for self-hosted endpoints behind a tunnel.

Selected with LLM_PROVIDER=openai_compat; the endpoint and key come from
OPENAI_COMPAT_BASE_URL / OPENAI_COMPAT_API_KEY, the model from LLM_MODEL.
The upstream is self-hosted, so estimated cost is $0 per call (PRD § 9 still
wants tokens, latency, and cost logged — they go to the logger every call).

The Kaggle server does not implement streaming ("Streaming is not supported"),
so stream=True performs one blocking POST and yields the finished answer as a
single event; the SSE view typewrites it client-side. There is therefore no
mid-stream re-send risk: a retry replays the whole POST before any text moved.
"""
import logging
import time

import httpx

from django.conf import settings

from apps.llm.adapter import LLMRateLimited, LLMUnavailable

logger = logging.getLogger(__name__)


def to_openai_messages(messages):
    """Convert Gemini-style messages (role + parts) to OpenAI chat format.

    The rest of the app speaks the Gemini shape (list of {"role", "parts"}) —
    prompt building, tests, and the QA view all pass that through. This adapter
    is the boundary where the shape is translated; it also accepts OpenAI-style
    dicts unchanged so future call sites need no conversion.
    """
    converted = []
    for message in messages:
        if "parts" in message:
            content = "".join(part.get("text", "") for part in message["parts"])
        else:
            content = message.get("content", "")
        converted.append({"role": message.get("role", "user"), "content": content})
    return converted


class OpenAICompatAdapter:
    """Answers from an OpenAI-compatible /chat/completions endpoint."""

    def __init__(
        self,
        base_url=None,
        api_key=None,
        model=None,
        timeout_seconds=None,
        retries=None,
        transport=None,
    ):
        self.base_url = (base_url if base_url is not None else settings.OPENAI_COMPAT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.OPENAI_COMPAT_API_KEY
        self.model = model if model is not None else settings.LLM_MODEL
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.LLM_TIMEOUT_SECONDS
        )
        self.retries = retries if retries is not None else settings.LLM_RETRIES
        # transport lets tests swap in httpx.MockTransport — no network.
        self._transport = transport

    def generate(self, messages, stream=False):
        if not self.api_key:
            raise LLMUnavailable("OPENAI_COMPAT_API_KEY is not configured.")
        if not self.base_url:
            raise LLMUnavailable("OPENAI_COMPAT_BASE_URL is not configured.")
        if stream:
            return self._generate_stream(messages)
        response, usage = self._request(messages)
        return {"text": _text_from_response(response), "usage": usage}

    def _generate_stream(self, messages):
        # The upstream cannot stream: yield the finished answer in one go.
        # The SSE view typewrites it client-side, so the UX stays the same.
        response, usage = self._request(messages)
        yield {"text": _text_from_response(response), "usage": {}}
        yield {"text": "", "usage": usage}

    def _request(self, messages):
        """POST once (with retries) and return (response, usage)."""
        started_at = time.perf_counter()
        payload = {
            "model": self.model,
            "messages": to_openai_messages(messages),
        }
        for attempt in range(self.retries + 1):
            try:
                response = self._post(payload)
                break
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == self.retries:
                    logger.exception(
                        "%s request failed after %s attempts", self.model, attempt + 1
                    )
                    raise LLMUnavailable(
                        f"{self.model} did not return an answer in time."
                    ) from None
                logger.warning(
                    "%s request failed; retrying attempt=%s", self.model, attempt + 1
                )
                time.sleep(2**attempt)
            except HTTPRateLimited:
                # The server already told us to slow down — blind retries would
                # just repeat the same answer.
                logger.warning("%s rate limit exhausted; not retrying", self.model)
                raise LLMRateLimited(
                    "Rate limit reached — the model server is busy; try again shortly."
                ) from None
            except HTTPStatusError as exc:
                if attempt == self.retries:
                    logger.exception("%s returned %s", self.model, exc.status)
                    raise LLMUnavailable(
                        f"{self.model} returned HTTP {exc.status}."
                    ) from None
                logger.warning(
                    "%s returned HTTP %s; retrying attempt=%s",
                    self.model,
                    exc.status,
                    attempt + 1,
                )
                time.sleep(2**attempt)

        usage = _usage_from_response(response)
        usage["latency_ms"] = int((time.perf_counter() - started_at) * 1000)
        usage["provider"] = "openai_compat"
        usage["model"] = self.model
        logger.info(
            "llm call: provider=%s model=%s prompt_tokens=%s completion_tokens=%s "
            "latency_ms=%s cost_usd=0.00",
            usage["provider"],
            usage["model"],
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage["latency_ms"],
        )
        return response, usage

    def _post(self, payload):
        with httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds, connect=5.0),
            transport=self._transport,
        ) as client:
            response = client.post(
                "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code == 429:
            raise HTTPRateLimited()
        if response.status_code >= 400:
            raise HTTPStatusError(response.status_code)
        return response


class HTTPRateLimited(Exception):
    """The upstream responded 429."""


class HTTPStatusError(Exception):
    """The upstream returned a persistent HTTP error status."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


def _text_from_response(response):
    body = response.json()
    choices = body.get("choices") or [{}]
    message = choices[0].get("message") or {}
    return message.get("content") or ""


def _usage_from_response(response):
    body = response.json()
    usage = body.get("usage") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or 0,
    }
