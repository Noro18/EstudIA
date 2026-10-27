from types import SimpleNamespace

import pytest

from apps.rag.prompting import build_grounded_messages, generate_grounded_answer


def match(text):
    return SimpleNamespace(text=text)


def test_build_grounded_messages_numbers_retrieved_passages_and_requires_tetum():
    messages = build_grounded_messages("Saida mak tema?", (match("Passage A"), match("Passage B")))
    prompt = messages[0]["parts"][0]["text"]

    assert "Answer in simple Tetum" in prompt
    assert "[Chunk 1]" in prompt
    assert "[Chunk 2]" in prompt
    assert "Passage A" in prompt
    assert "Passage B" in prompt


def test_generate_grounded_answer_passes_messages_to_adapter():
    class FakeAdapter:
        def generate(self, messages, stream):
            return {"messages": messages, "stream": stream}

    result = generate_grounded_answer("Saida mak tema?", (match("Passage A"),), adapter=FakeAdapter())

    assert result["stream"] is False
    assert "Passage A" in result["messages"][0]["parts"][0]["text"]


def test_build_grounded_messages_rejects_empty_retrieval():
    with pytest.raises(ValueError, match="retrieved chunk"):
        build_grounded_messages("Saida mak tema?", ())
