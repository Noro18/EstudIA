import pytest
from django.db.models import ProtectedError

from apps.documents.tests.factories import DocumentFactory, NotebookFactory
from apps.qa.models import Conversation
from apps.qa.tests.factories import ConversationFactory

pytestmark = pytest.mark.django_db


def test_create_minimal_conversation():
    conversation = ConversationFactory()

    assert conversation.pk is not None
    assert conversation.created_at is not None
    assert conversation.notebook_id is not None
    assert conversation.user_id == conversation.notebook.user.pk
    assert list(conversation.notebook.conversations.all()) == [conversation]
    assert list(conversation.notebook.user.conversations.all()) == [conversation]


def test_many_conversations_per_notebook():
    notebook = NotebookFactory()
    first = ConversationFactory(notebook=notebook)
    second = ConversationFactory(notebook=notebook)

    assert first != second
    assert notebook.conversations.count() == 2


def test_deleting_notebook_cascades_to_conversations():
    survivor = ConversationFactory()
    doomed = ConversationFactory()
    notebook = doomed.notebook

    notebook.delete()

    assert Conversation.objects.count() == 1
    assert Conversation.objects.get(pk=survivor.pk) == survivor


def test_deleting_document_does_not_touch_conversations():
    conversation = ConversationFactory()
    document = DocumentFactory(notebook=conversation.notebook)

    document.delete()

    assert Conversation.objects.count() == 1
    assert Conversation.objects.get(pk=conversation.pk) == conversation


def test_deleting_owner_with_history_is_protected():
    conversation = ConversationFactory()
    user = conversation.user

    with pytest.raises(ProtectedError):
        user.delete()

    assert Conversation.objects.count() == 1


def test_str_is_readable():
    conversation = ConversationFactory()

    assert str(conversation).startswith("Conversation #")


def test_user_notebook_index_exists():
    names = {idx.name for idx in Conversation._meta.indexes}
    assert "qa_conversation_user_notebook" in names
