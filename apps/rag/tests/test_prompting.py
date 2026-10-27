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


def history_turn(role, content):
    return {"role": role, "content": content}


def test_history_is_included_before_passages_with_question_last():
    history = [
        history_turn("user", "Saida mak MCDM?"),
        history_turn("assistant", "MCDM mak metodu desizaun."),
    ]

    prompt = build_grounded_messages(
        "Tanba sa o la temi kona ba TOPSIS?", (match("Passage A"),), history=history
    )[0]["parts"][0]["text"]

    history_position = prompt.index("Previous conversation")
    passage_position = prompt.index("[Chunk 1]")
    question_position = prompt.index("Question: Tanba sa o la temi")
    assert history_position < passage_position < question_position
    assert "Saida mak MCDM?" in prompt
    assert "MCDM mak metodu desizaun." in prompt


def test_empty_conversation_omits_the_history_block_entirely():
    prompt = build_grounded_messages(
        "Saida mak MCDM?", (match("Passage A"),), history=[]
    )[0]["parts"][0]["text"]

    assert "Previous conversation" not in prompt


def test_history_is_trimmed_to_the_token_budget(settings):
    settings.HISTORY_TOKEN_BUDGET = 8  # estimator: len(text) // 4 -> 32 chars
    long_turn = "x" * 100
    history = [history_turn("user", long_turn)]

    prompt = build_grounded_messages("q?", (match("Passage"),), history=history)[0][
        "parts"
    ][0]["text"]

    assert long_turn not in prompt


def test_history_turns_without_content_are_skipped():
    history = [history_turn("user", ""), history_turn("user", None)]

    build_grounded_messages("q?", (match("Passage"),), history=history)
