import pytest
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.documents.tests.factories import NotebookFactory
from apps.qa.tests.factories import ConversationFactory, MessageFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in(client):
    user = UserFactory()
    client.force_login(user)
    return client, user


def test_conversation_detail_renders_full_history(logged_in):
    client, user = logged_in
    notebook = NotebookFactory(user=user)
    conversation = ConversationFactory(notebook=notebook, user=user)
    MessageFactory(conversation=conversation, seq=1, role="user", content="Saida mak bobot?")

    response = client.get(reverse("conversation_detail", args=(conversation.pk,)))

    assert response.status_code == 200
    assert b"Saida mak bobot?" in response.content


def test_conversation_detail_isolated_from_other_users(logged_in):
    client, user = logged_in
    conversation = ConversationFactory()

    response = client.get(reverse("conversation_detail", args=(conversation.pk,)))

    assert response.status_code == 404


def test_messages_render_in_seq_order(logged_in):
    client, user = logged_in
    notebook = NotebookFactory(user=user)
    conversation = ConversationFactory(notebook=notebook, user=user)
    MessageFactory(conversation=conversation, seq=2, content="second answer bubble")
    MessageFactory(conversation=conversation, seq=1, content="first question bubble")

    response = client.get(reverse("conversation_detail", args=(conversation.pk,)))

    html = response.content
    assert html.index(b"first question bubble") < html.index(b"second answer bubble")


def test_ask_creates_conversation_and_user_message(logged_in):
    client, user = logged_in
    notebook = NotebookFactory(user=user)

    response = client.post(
        reverse("notebook_ask", args=(notebook.pk,)),
        {"question": "Saida mak edukasaun?"},
    )

    assert response.status_code == 200
    conversation = notebook.conversations.get(user=user)
    message = conversation.messages.get(seq=1)
    assert message.role == "user"
    assert message.content == "Saida mak edukasaun?"
    assert message.supported is None
    assert b"Saida mak edukasaun?" in response.content
    assert f'data-conversation-id="{conversation.pk}"'.encode() in response.content
