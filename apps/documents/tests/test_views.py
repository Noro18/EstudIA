import io
import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.tests.factories import UserFactory
from apps.documents.tests.factories import DocumentFactory, NotebookFactory
from apps.qa.tests.factories import ConversationFactory, MessageFactory
from apps.documents.services import extract_txt_document

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in(client):
    user = UserFactory()
    client.force_login(user)
    return client, user


def test_notebook_list_requires_login(client):
    assert client.get(reverse("notebook_list")).status_code == 302


def test_notebook_list_renders_notebook_cards(logged_in):
    client, user = logged_in
    NotebookFactory(title="Physics 10", user=user)

    response = client.get(reverse("notebook_list"))

    assert response.status_code == 200
    assert b"Physics 10" in response.content


def test_notebook_create_creates_and_redirects(logged_in):
    client, user = logged_in

    response = client.post(reverse("notebook_list"), {"title": "Biology notes"})

    created = user.notebooks.get(title="Biology notes")
    assert created is not None
    assert response.status_code == 302


def test_workspace_shell_renders_documents_and_history(logged_in):
    client, user = logged_in
    notebook = NotebookFactory(title="Physics 10", user=user)
    NotebookFactory(title="Biology 7", user=user)
    DocumentFactory(
        notebook=notebook,
        user=user,
        title="Chapter 1.pdf",
        status="processing",
    )
    conversation = ConversationFactory(notebook=notebook, user=user)
    MessageFactory(conversation=conversation, seq=1, role="user", content="Saida mak sutat ne'e?")

    response = client.get(reverse("notebook_workspace", args=(notebook.pk,)))

    assert response.status_code == 200
    assert b'nav class="topbar"' in response.content
    assert b">StudIA<" in response.content
    assert b'nb-select' in response.content
    assert b"Physics 10" in response.content
    assert b"Biology 7" in response.content
    assert b'aria-current="page"' in response.content
    assert b'nb-plus' in response.content
    assert b'nb-new-dialog' in response.content
    assert b"Physics 10" in response.content
    assert b"Chapter 1.pdf" in response.content
    assert b"Reading" in response.content
    assert b"Saida mak sutat" in response.content
    assert b"ne&#x27;e?" in response.content
    assert b"Upload document" in response.content


def test_workspace_isolated_from_other_users(logged_in):
    client, user = logged_in
    other_notebook = NotebookFactory()

    response = client.get(reverse("notebook_workspace", args=(other_notebook.pk,)))

    assert response.status_code == 404


def test_document_detail_renders_status_and_reason(logged_in):
    client, user = logged_in
    document = DocumentFactory(
        user=user,
        title="Scanned chapter.pdf",
        status="failed",
        failure_reason="scanned_no_text",
    )

    response = client.get(reverse("document_detail", args=(document.pk,)))

    assert response.status_code == 200
    assert b"Scanned chapter.pdf" in response.content
    assert b"scanned_no_text" in response.content


def test_document_detail_isolated_from_other_users(logged_in):
    client, user = logged_in
    other_document = DocumentFactory()

    response = client.get(reverse("document_detail", args=(other_document.pk,)))

    assert response.status_code == 404


def test_login_page_renders(client):
    response = client.get(reverse("login"))

    assert response.status_code == 200


def test_upload_document_creates_processing_record(logged_in):
    client, user = logged_in
    notebook = NotebookFactory(title="Test Notebook", user=user)

    # Create a simple text file
    txt_content = b"Hello world\nThis is a test document."
    uploaded_file = SimpleUploadedFile(
        "test.txt",
        txt_content,
        content_type="text/plain",
    )

    response = client.post(
        reverse("notebook_upload_document", args=(notebook.pk,)),
        {"file": uploaded_file},
    )

    # Should return 200 with document card fragment
    assert response.status_code == 200
    assert b"test" in response.content  # title in card
    assert b"Reading" in response.content  # processing status

    # Document should exist in DB with processing status
    document = notebook.documents.get(title="test")
    assert document.status == "processing"
    assert document.file_type == "txt"
    assert document.user == user
    assert document.notebook == notebook


def test_upload_document_rejects_unsupported_type(logged_in):
    client, user = logged_in
    notebook = NotebookFactory(user=user)

    uploaded_file = SimpleUploadedFile(
        "test.exe",
        b"not a document",
        content_type="application/octet-stream",
    )

    response = client.post(
        reverse("notebook_upload_document", args=(notebook.pk,)),
        {"file": uploaded_file},
    )

    assert response.status_code == 400
    assert b"unsupported_type" in response.content
    assert notebook.documents.count() == 0


def test_upload_document_rejects_oversized_file(logged_in, settings):
    client, user = logged_in
    notebook = NotebookFactory(user=user)
    settings.MAX_UPLOAD_SIZE_BYTES = 100  # tiny limit

    uploaded_file = SimpleUploadedFile(
        "big.pdf",
        b"x" * 200,
        content_type="application/pdf",
    )

    response = client.post(
        reverse("notebook_upload_document", args=(notebook.pk,)),
        {"file": uploaded_file},
    )

    assert response.status_code == 400
    assert b"file_too_large" in response.content
    assert notebook.documents.count() == 0


def test_extract_txt_document_creates_page_and_marks_document_ready(monkeypatch):
    document = DocumentFactory(
        status="processing",
        uploaded_file__data="Primeira linha.\nSegunda linha.".encode("utf-8"),
        uploaded_file__filename="notes.txt",
        file_type="txt",
    )

    monkeypatch.setattr(
        "apps.documents.services._embed_texts",
        lambda texts: [[0.1] * 1024 for _ in texts],
    )

    extract_txt_document(document)

    document.refresh_from_db()
    page = document.pages.get(number=1)
    assert page.text == "Primeira linha.\nSegunda linha."
    assert page.char_count == len(page.text)
    assert page.is_scanned is False
    assert page.ocr_used is False
    assert document.page_count == 1
    assert document.status == "ready"
