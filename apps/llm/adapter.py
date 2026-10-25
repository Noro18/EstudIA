import json
import logging
import time

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    pass


def _text_from_payload(payload):
    candidates = payload.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def _usage_from_payload(payload):
    usage = payload.get("usageMetadata", {})
    return {
        "prompt_tokens": usage.get("promptTokenCount", 0),
        "completion_tokens": usage.get("candidatesTokenCount", 0),
    }


class GeminiAdapter:
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.LLM_MODEL
        self.retries = settings.LLM_RETRIES

    def generate(self, messages, stream=False):
        if not self.api_key:
            raise LLMUnavailable("GEMINI_API_KEY is not configured.")
        if stream:
            return self._stream(messages)
        return self._complete(messages)

    def _headers(self):
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _body(self, messages):
        return {"contents": messages}

    def _complete(self, messages):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        started_at = time.perf_counter()
        for attempt in range(self.retries + 1):
            try:
                response = httpx.post(url, headers=self._headers(), json=self._body(messages), timeout=60)
                response.raise_for_status()
                break
            except httpx.HTTPError as exc:
                if attempt == self.retries:
                    raise LLMUnavailable("Gemini did not return an answer.") from exc
                logger.warning("Gemini request failed; retrying attempt=%s", attempt + 1)
                time.sleep(2**attempt)
        payload = response.json()
        usage = _usage_from_payload(payload)
        usage["latency_ms"] = int((time.perf_counter() - started_at) * 1000)
        usage["provider"] = "gemini"
        usage["model"] = self.model
        return {"text": _text_from_payload(payload), "usage": usage}

    def _stream(self, messages):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:streamGenerateContent?alt=sse"
        started_at = time.perf_counter()
        for attempt in range(self.retries + 1):
            try:
                with httpx.stream("POST", url, headers=self._headers(), json=self._body(messages), timeout=60) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = json.loads(line.removeprefix("data:").strip())
                        usage = _usage_from_payload(payload)
                        text = _text_from_payload(payload)
                        if text:
                            yield {"text": text, "usage": usage}
                        if usage["prompt_tokens"] or usage["completion_tokens"]:
                            yield {"text": "", "usage": usage}
                break
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                if attempt == self.retries:
                    logger.exception("Gemini streaming failed")
                    raise LLMUnavailable("Gemini streaming failed.") from exc
                logger.warning("Gemini streaming failed; retrying attempt=%s", attempt + 1)
                time.sleep(2**attempt)
        yield {
            "text": "",
            "usage": {
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "provider": "gemini",
                "model": self.model,
            },
        }
