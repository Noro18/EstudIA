import pytest
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.documents.tests.factories import DocumentFactory, NotebookFactory
from apps.qa.tests.factories import ConversationFactory, MessageFactory

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
