"""OpenAI-compatible adapter — for the hosted Labadain API (PRD § 7).

Selected with LLM_PROVIDER=openai_compat; the endpoint and key come from
OPENAI_COMPAT_BASE_URL / OPENAI_COMPAT_API_KEY, the model from LLM_MODEL.
The upstream is free for the team (prize for 1st place, Nov 11), so estimated
cost is $0 per call (PRD § 9 still wants tokens, latency, and cost logged —
they go to the logger every call).

The endpoint streams real SSE (`stream: true`): answer deltas arrive in
`choices[].delta.content`, thinking tokens in `delta.reasoning`. Reasoning
deltas are never yielded — thinking is off for this app (LLM_THINK, decided
Nov 11) and, even if the server streams a reasoning chunk anyway, it must not
reach the UI. Retries only happen before the first text delta: once text has
moved to the caller, a failure raises instead of re-sending (no duplication).
"""
import json
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
        think=None,
        transport=None,
    ):
        self.base_url = (base_url if base_url is not None else settings.OPENAI_COMPAT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.OPENAI_COMPAT_API_KEY
        self.model = model if model is not None else settings.LLM_MODEL
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.LLM_TIMEOUT_SECONDS
        )
        self.retries = retries if retries is not None else settings.LLM_RETRIES
        # Thinking mode (decided Nov 11: off — faster answers, retrieval
        # already grounds the response). env: LLM_THINK=true to re-enable.
        self.think = (
            think if think is not None else getattr(settings, "LLM_THINK", False)
        )
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
        started_at = time.perf_counter()
        for attempt in range(self.retries + 1):
            emitted_text = False
            try:
                with self._client() as client:
                    with client.stream(
                        "POST",
                        "/chat/completions",
                        headers=self._headers(),
                        json=self._payload(messages, stream=True),
                    ) as response:
                        _check_status(response)
                        usage = {}
                        for line in response.iter_lines():
                            chunk = _sse_chunk(line)
                            if chunk is None:
                                continue
                            if chunk.get("usage"):
                                usage = chunk["usage"]
                            content = _delta_content(chunk)
                            if content:
                                emitted_text = True
                                yield {"text": content, "usage": {}}
            except (httpx.TimeoutException, httpx.TransportError, HTTPRateLimited, HTTPStatusError) as exc:
                if isinstance(exc, HTTPRateLimited):
                    # The server already told us to slow down — blind retries
                    # would just repeat the same answer.
                    logger.warning("%s rate limit exhausted; not retrying", self.model)
                    raise LLMRateLimited(
                        "Rate limit reached — the model server is busy; try again shortly."
                    ) from None
                if emitted_text:
                    # Text already delivered to the caller — never re-send.
                    logger.exception("stream interrupted after a partial answer")
                    raise LLMUnavailable(
                        "The stream was interrupted mid-answer."
                    ) from exc
                if attempt == self.retries:
                    logger.exception(
                        "%s stream failed after %s attempts (%s)",
                        self.model,
                        attempt + 1,
                        exc,
                    )
                    raise LLMUnavailable(
                        f"{self.model} did not return an answer in time."
                    ) from exc
                logger.warning("%s stream failed; retrying attempt=%s", self.model, attempt + 1)
                time.sleep(2**attempt)
            else:
                usage = _usage_from_body(usage)
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
                # The QA view keeps the last usage it sees (adapter contract),
                # so the authoritative totals ride the final empty-text event.
                yield {"text": "", "usage": usage}
                return

    def _request(self, messages):
        """POST once (with retries) and return (response, usage)."""
        started_at = time.perf_counter()
        payload = self._payload(messages)
        for attempt in range(self.retries + 1):
            try:
                with self._client() as client:
                    response = client.post(
                        "/chat/completions", headers=self._headers(), json=payload
                    )
                _check_status(response)
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

    def _client(self):
        return httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds, connect=5.0),
            transport=self._transport,
        )

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages, stream=False):
        payload = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "think": self.think,
        }
        if stream:
            payload["stream"] = True
        return payload


class HTTPRateLimited(Exception):
    """The upstream responded 429."""


class HTTPStatusError(Exception):
    """The upstream returned a persistent HTTP error status."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


def _check_status(response):
    if response.status_code == 429:
        raise HTTPRateLimited()
    if response.status_code >= 400:
        raise HTTPStatusError(response.status_code)


def _sse_chunk(line):
    """Parse one SSE line into a chunk dict, or None for blanks/[DONE]/junk."""
    line = (line or "").strip()
    if not line.startswith("data:"):
        return None
    data = line[len("data:"):].strip()
    if not data or data == "[DONE]":
        return None
    try:
        return json.loads(data)
    except ValueError:
        logger.warning("Skipping malformed SSE chunk: %r", line[:120])
        return None


def _delta_content(chunk):
    """Answer text from one chunk; reasoning deltas never leave this module."""
    choices = chunk.get("choices") or [{}]
    delta = choices[0].get("delta") or {}
    return delta.get("content")


def _text_from_response(response):
    body = response.json()
    choices = body.get("choices") or [{}]
    message = choices[0].get("message") or {}
    return message.get("content") or ""


def _usage_from_response(response):
    return _usage_from_body(response.json().get("usage") or {})


def _usage_from_body(usage):
    return {
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or 0,
    }
