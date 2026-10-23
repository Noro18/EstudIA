from apps.llm.adapter import _text_from_payload, _usage_from_payload


def test_gemini_payload_parsing():
    payload = {
        "candidates": [{"content": {"parts": [{"text": "Ola "}, {"text": "mundo."}]}}],
        "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 3},
    }

    assert _text_from_payload(payload) == "Ola mundo."
    assert _usage_from_payload(payload) == {"prompt_tokens": 4, "completion_tokens": 3}
