import json

import pytest
from django.urls import reverse

from apps.documents.models import Document
from apps.documents.tests.factories import ChunkFactory, DocumentFactory, NotebookFactory
from apps.llm.adapter import LLMUnavailable
from apps.llm.models import UsageRecord
from apps.qa.models import QuizQuestion
from apps.qa.tests.factories import QuizQuestionFactory


class _FakeAdapter:
    def __init__(self, payload=None, exc=None):
        self.payload = payload
        self.exc = exc

    def generate(self, messages, stream=False):
        if self.exc is not None:
            raise self.exc
        return {
            "text": json.dumps(self.payload),
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "latency_ms": 30, "provider": "gemini", "model": "test-model"},
        }


def _seed_notebook(nb_chunks=2):
    notebook = NotebookFactory()
    document = DocumentFactory(notebook=notebook, status=Document.Status.READY)
    for index in range(nb_chunks):
        ChunkFactory(document=document, order_index=index + 1)
    return notebook, document


def _patch(monkeypatch, fake):
    monkeypatch.setattr("apps.qa.services.GeminiAdapter", lambda: fake)


@pytest.mark.django_db
def test_generate_quiz_validates_chunk_numbers(client, monkeypatch):
    notebook, document = _seed_notebook()
    payload = [
        {"question": "Valid?", "choices": {"A": "sia", "B": "y", "C": "x", "D": "z"}, "correct": "A", "chunk": 1},
        {"question": "Bad chunk", "choices": {"A": "a", "B": "b", "C": "c", "D": "d"}, "correct": "B", "chunk": 9},
        {"question": "Valid 2?", "choices": {"A": "a", "B": "b", "C": "c", "D": "d"}, "correct": "C", "chunk": 2},
    ]
    _patch(monkeypatch, _FakeAdapter(payload))
    client.force_login(notebook.user)
    response = client.post(reverse("notebook_quiz_start", args=[notebook.pk]))
    assert response.status_code == 200
    questions = list(QuizQuestion.objects.filter(notebook=notebook).order_by("order"))
    assert len(questions) == 2
    assert questions[0].chunk.order_index == 1
    assert questions[1].chunk.order_index == 2
    assert questions[0].correct_letter == "A"
    assert UsageRecord.objects.filter(purpose=UsageRecord.Purpose.STUDY_QUESTIONS).count() == 1


@pytest.mark.django_db
def test_generate_quiz_replaces_previous_set(client, monkeypatch):
    notebook, _ = _seed_notebook(nb_chunks=1)
    for _ in range(2):
        QuizQuestionFactory(notebook=notebook, chunk__document__notebook=notebook, chunk__document__user=notebook.user, chunk__document__status=Document.Status.READY)
    payload = [
        {"question": "Fresh?", "choices": {"A": "a", "B": "b", "C": "c", "D": "d"}, "correct": "D", "chunk": 1}
    ]
    _patch(monkeypatch, _FakeAdapter(payload))
    client.force_login(notebook.user)
    assert client.post(reverse("notebook_quiz_start", args=[notebook.pk])).status_code == 200
    assert QuizQuestion.objects.filter(notebook=notebook).count() == 1


@pytest.mark.django_db
def test_generate_quiz_no_ready_documents(client):
    notebook = NotebookFactory()
    DocumentFactory(notebook=notebook)  # stays PROCESSING
    client.force_login(notebook.user)
    response = client.post(reverse("notebook_quiz_start", args=[notebook.pk]))
    assert response.status_code == 400
    assert b"document_not_ready" in response.content


@pytest.mark.django_db
def test_generate_quiz_unavailable_llm(client, monkeypatch):
    notebook, _ = _seed_notebook(nb_chunks=1)
    _patch(monkeypatch, _FakeAdapter(exc=LLMUnavailable("Gemini is down")))
    client.force_login(notebook.user)
    response = client.post(reverse("notebook_quiz_start", args=[notebook.pk]))
    assert response.status_code == 400
    assert b"llm_unavailable" in response.content


@pytest.mark.django_db
def test_generate_quiz_all_invalid_json(client, monkeypatch):
    notebook, _ = _seed_notebook(nb_chunks=1)
    _patch(monkeypatch, _FakeAdapter(payload=[{"wrong": "shape"}]))
    client.force_login(notebook.user)
    response = client.post(reverse("notebook_quiz_start", args=[notebook.pk]))
    assert response.status_code == 400
    assert QuizQuestion.objects.filter(notebook=notebook).count() == 0


@pytest.mark.django_db
def test_submit_scores_locally(client):
    notebook = NotebookFactory()
    questions = [
        QuizQuestionFactory(notebook=notebook, correct_letter="A"),
        QuizQuestionFactory(notebook=notebook, correct_letter="B"),
    ]
    client.force_login(notebook.user)
    data = {f"answer_{questions[0].pk}": "A", f"answer_{questions[1].pk}": "A"}
    response = client.post(reverse("notebook_quiz_submit", args=[notebook.pk]), data)
    assert response.status_code == 200
    assert "Score: 1/2" in response.content.decode()
