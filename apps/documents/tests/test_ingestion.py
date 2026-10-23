import pytest

from apps.documents.models import Document
from apps.documents.services import finalize_ingestion_status, ingest_document
from apps.documents.tests.factories import DocumentFactory

pytestmark = pytest.mark.django_db


def test_ingest_txt_extracts_chunks_and_embeddings(monkeypatch):
    document = DocumentFactory(
        status=Document.Status.PROCESSING,
        uploaded_file__data=(
            "Ideia prinsipál ida kona-ba edukasaun.\n\n"
            "Ideia prinsipál rua kona-ba komunidade.\n\n"
            "Ideia prinsipál tolu kona-ba futuru."
        ).encode("utf-8"),
        uploaded_file__filename="lesson.txt",
        file_type=Document.FileType.TXT,
    )
    monkeypatch.setattr(
        "apps.documents.services._embed_texts",
        lambda texts: [[0.1] * 1024 for _ in texts],
    )

    ingest_document(document)

    document.refresh_from_db()
    assert document.status == Document.Status.READY
    assert document.page_count == 1
    assert document.embedding_model
    assert document.embedding_dim == 1024
    assert document.pages.count() == 1
    assert document.chunks.count() == 1
    chunk = document.chunks.get()
    assert chunk.text.startswith("Ideia prinsipál")
    assert chunk.token_count > 0
    assert chunk.embedding is not None


def test_ingest_marks_document_failed_when_text_cannot_be_decoded():
    document = DocumentFactory(
        status=Document.Status.PROCESSING,
        uploaded_file__data=b"\xff\xfe\xfa",
        uploaded_file__filename="broken.txt",
        file_type=Document.FileType.TXT,
    )

    ingest_document(document)

    document.refresh_from_db()
    assert document.status == Document.Status.FAILED
    assert document.failure_reason == "extraction_failed"
    assert document.page_count is None
    assert document.pages.count() == 0
    assert document.chunks.count() == 0


def test_finalize_ingestion_status_marks_incomplete_document_failed():
    document = DocumentFactory(status=Document.Status.PROCESSING)

    finalize_ingestion_status(document)

    document.refresh_from_db()
    assert document.status == Document.Status.FAILED
    assert document.failure_reason == "ingestion_incomplete"
