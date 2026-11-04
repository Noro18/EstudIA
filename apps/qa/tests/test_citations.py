"""Citations end-to-end (spec 13): marker parsing, validation, MessageSource
writing, `supported`, and the SSE `done` payload. Factory-first, per the
test-factories convention.
"""
import json

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.documents.models import Chunk
from apps.documents.tests.factories import (
    ChunkFactory,
    DocumentFactory,
    NotebookFactory,
)
from apps.llm.models import UsageRecord
from apps.qa.services import finalize_assistant_message, parse_used_chunks, strip_used_chunks
from apps.qa.tests.factories import ConversationFactory, MessageFactory, MessageSourceFactory
from apps.rag.retrieval import HybridMatch

pytestmark = pytest.mark.django_db

MARKER = "Used chunks: [1, 2]"


def make_match(chunk, *, vector_rank=1):
    """Build the retrieval-shaped match for one stored chunk."""
    return HybridMatch(
        chunk_id=chunk.pk,
        document_id=chunk.document_id,
        document=chunk.document.title,
        page=chunk.page_number,
        text=chunk.text,
        excerpt=chunk.text[:280],
        vector_rank=vector_rank,
        keyword_rank=None,
        fused_score=0.5,
    )


def make_matches(notebook, count=2, pages=(1, 2)):
    """Notebook → `count` chunks (across one document for simplicity)+matches."""
    document = DocumentFactory(notebook=notebook, status="ready")
    chunks = [
        ChunkFactory(
            document=document,
            page_number=page,
            text=f"Passage {index} body. " + "x" * 350,
        )
        for index, page in enumerate(pages, start=1)
    ]
    return chunks, tuple(make_match(chunk) for chunk in chunks)


# --- parse_used_chunks (pure) -------------------------------------------------


def test_parse_happy_path():
    assert parse_used_chunks(f"Resposta iha ne'e.\n\n{MARKER}") == (1, 2)


def test_parse_tolerates_spacing_and_trailing_period():
    assert parse_used_chunks("Resposta.\nUsed chunks: [1,2].") == (1, 2)


def test_parse_dedupes_in_first_appearance_order():
    assert parse_used_chunks("A.\nUsed chunks: [2, 2, 5, 1]") == (2, 5, 1)


def test_parse_no_marker():
    assert parse_used_chunks("Plain Tetum answer with no citations.") == ()


def test_parse_malformed_marker_is_not_citations():
    assert parse_used_chunks("A.\nUsed chunks: one, two") == ()


def test_parse_marker_must_be_the_last_line():
    assert parse_used_chunks(f"{MARKER}\n\nExtra thought about the answer.") == ()


def test_parse_ignores_numbers_outside_brackets():
    assert parse_used_chunks("A. Chunks 1 and 3 look good.\nUsed chunks: [3]") == (3,)


def test_parse_ignores_zero_and_negative():
    assert parse_used_chunks("A.\nUsed chunks: [0, -1, 2]") == (2,)


# --- strip_used_chunks (pure) -------------------------------------------------


def test_strip_removes_marker_and_leaves_answer_intact():
    answer = "Resposta prinsipal.\n\nDetale.\n\nUsed chunks: [1]"
    assert strip_used_chunks(answer) == "Resposta prinsipal.\n\nDetale."


def test_strip_keeps_answer_without_marker_untouched():
    assert strip_used_chunks("Resposta ne'e ho rasun.") == "Resposta ne'e ho rasun."


# --- prompt contract -----------------------------------------------------------


def test_grounded_prompt_pins_the_marker_wording():
    """Reference test (spec 13 § 2): changing the prompt wording must break THIS
    test first, so the parser in qa/services is never left behind."""
    from apps.rag.prompting import build_grounded_messages

    match = HybridMatch(
        chunk_id=1,
        document_id=1,
        document="D",
        page=1,
        text="Nobody reads this at runtime.",
        excerpt="nobody",
        vector_rank=1,
        keyword_rank=None,
        fused_score=1.0,
    )
    messages = build_grounded_messages("Saida mak X?", [match])
    assert "Used chunks: [1, 2]" in messages[0]["parts"][0]["text"]


# --- finalize_assistant_message (DB) -------------------------------------------


def test_finalize_writes_assistant_message_sources_and_usage():
    notebook = NotebookFactory()
    chunks, matches = make_matches(notebook)
    conversation = ConversationFactory(notebook=notebook)
    MessageFactory(conversation=conversation, seq=1, role="user", content="Saida mak X?")
    answer = f"Resposta.\n\n{MARKER}"

    message = finalize_assistant_message(
        conversation,
        notebook.user,
        matches,
        answer,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 100},
    )

    assert message.seq == 2
    assert message.role == "assistant"
    assert message.supported is True
    assert "Used chunks" not in message.content
    assert message.content.startswith("Resposta.")
    assert "{x}" not in message.content

    sources = list(message.sources.all())
    assert [source.chunk_id for source in sources] == [chunks[0].pk, chunks[1].pk]
    assert [source.page for source in sources] == [1, 2]
    # DATABASE.md: snapshot excerpt = first 280 chars + "…" when truncated
    assert all(source.excerpt.endswith("…") for source in sources)
    assert all(len(source.excerpt) == 281 for source in sources)

    usage_row = UsageRecord.objects.get(message=message)
    assert usage_row.purpose == UsageRecord.Purpose.ASK
    assert usage_row.prompt_tokens == 10
    assert usage_row.completion_tokens == 5


def test_finalize_invalid_numbers_means_unsupported_no_sources():
    notebook = NotebookFactory()
    _, matches = make_matches(notebook, count=2)
    conversation = ConversationFactory(notebook=notebook)
    answer = "Resposta.\n\nUsed chunks: [3, 99]"  # both out of the supplied range

    message = finalize_assistant_message(conversation, notebook.user, matches, answer, usage={})

    assert message.supported is False
    assert message.sources.count() == 0


def test_finalize_no_marker_means_unsupported():
    notebook = NotebookFactory()
    _, matches = make_matches(notebook)
    conversation = ConversationFactory(notebook=notebook)
    answer = "La iha resposta apoiadu iha pasajen sira."

    message = finalize_assistant_message(conversation, notebook.user, matches, answer, usage={})

    assert message.supported is False
    assert message.sources.count() == 0


def test_finalize_deduplicates_repeated_numbers():
    notebook = NotebookFactory()
    _, matches = make_matches(notebook)
    conversation = ConversationFactory(notebook=notebook)
    answer = "Resposta.\n\nUsed chunks: [2, 2]"

    message = finalize_assistant_message(conversation, notebook.user, matches, answer, usage={})

    assert message.sources.count() == 1
    assert message.supported is True
    assert message.sources.first().order == 1


def test_finalize_keeps_answer_clean_when_only_partial_citations_validate():
    notebook = NotebookFactory()
    _, matches = make_matches(notebook)
    conversation = ConversationFactory(notebook=notebook)
    answer = "Resposta.\nUsed chunks: [1, 7]"  # 7 is junk → dropped, 1 stays

    message = finalize_assistant_message(conversation, notebook.user, matches, answer, usage={})

    assert message.supported is True
    assert [source.order for source in message.sources.all()] == [1]


# --- SSE done event (view level) -----------------------------------------------


class _FakeAdapter:
    def generate(self, messages, stream=False):
        parts = ["Resposta.\n\nUsed chunks: [1, 2]"]
        if stream:
            return iter({"text": part, "usage": {}} for part in parts)
        return {"text": parts[0], "usage": {}}


def _read_sse(events):
    parsed = {}
    for raw in events:
        stripped = raw.decode() if isinstance(raw, bytes) else raw
        body = [line for line in stripped.split("\n") if line.startswith("data:")]
        if body:
            event_line = [line for line in stripped.split("\n") if line.startswith("event:")]
            name = event_line[0][6:].strip() if event_line else "message"
            parsed[name] = json.loads(body[0][5:].strip())
    return parsed


def test_streamed_ask_done_event_carries_supported_and_sources(monkeypatch, client):
    user = UserFactory()
    notebook = NotebookFactory(user=user)
    _, matches = make_matches(notebook)
    monkeypatch.setattr("apps.qa.views.retrieve_hybrid_chunks", lambda *a, **kw: matches)
    monkeypatch.setattr("apps.qa.views.GeminiAdapter", _FakeAdapter)
    client.force_login(user)

    response = client.post(
        reverse("notebook_ask", args=(notebook.pk,)),
        {"question": "Saida mak X?", "stream": "true"},
    )
    events = _read_sse(response.streaming_content)
    done = events["done"]

    conversation = notebook.conversations.get(user=user)
    assert done["conversation_id"] == conversation.pk
    assert done["supported"] is True
    assert [source["document"] for source in done["sources"]] == [
        matches[0].document,
        matches[1].document,
    ]
    assert [source["page"] for source in done["sources"]] == [1, 2]
    stored = conversation.messages.get(seq=2)
    assert stored.supported is True


def test_streamed_ask_done_event_unsupported_when_no_valid_citations(monkeypatch, client):
    user = UserFactory()
    notebook = NotebookFactory(user=user)
    _, matches = make_matches(notebook)

    class _JunkAdapter:
        def generate(self, messages, stream=False):
            parts = ["Resposta.\n\nUsed chunks: [9]"]
            if stream:
                return iter({"text": part, "usage": {}} for part in parts)
            return {"text": parts[0], "usage": {}}

    monkeypatch.setattr("apps.qa.views.retrieve_hybrid_chunks", lambda *a, **kw: matches)
    monkeypatch.setattr("apps.qa.views.GeminiAdapter", _JunkAdapter)
    client.force_login(user)

    response = client.post(
        reverse("notebook_ask", args=(notebook.pk,)),
        {"question": "Saida mak X?", "stream": "true"},
    )
    done = _read_sse(response.streaming_content)["done"]
    assert done["supported"] is False
    assert done["sources"] == []


# --- server-rendered sources (conversation replay) ------------------------------


def test_conversation_detail_renders_sources_from_stored_rows(client):
    user = UserFactory()
    document = DocumentFactory(user=user, title="Doc Rumdok")
    chunk = ChunkFactory(document=document, page_number=4, text="Z" * 10)
    message = MessageFactory(
        conversation__notebook=document.notebook,
        conversation__user=user,
        role="assistant",
        supported=True,
    )
    MessageSourceFactory(
        message=message,
        chunk=chunk,
        page=chunk.page_number,
        excerpt="Z" * 10,
        order=1,
    )

    client.force_login(user)
    response = client.get(reverse("conversation_detail", args=(message.conversation.pk,)))

    content = response.content.decode()
    assert "Doc Rumdok" in content
    assert "p. 4" in content
    assert "ZZZZZZZZZZ" in content


def test_conversation_detail_no_sources_section_for_unsupported_message(client):
    user = UserFactory()
    message = MessageFactory(
        conversation__user=user,
        role="assistant",
        supported=False,
    )

    client.force_login(user)
    response = client.get(reverse("conversation_detail", args=(message.conversation.pk,)))

    assert b"sources" not in response.content
