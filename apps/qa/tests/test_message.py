import pytest
from django.db import IntegrityError

from apps.qa.models import Message
from apps.qa.tests.factories import MessageFactory

pytestmark = pytest.mark.django_db


def test_create_user_message_defaults():
    message = MessageFactory(role=Message.Role.USER, seq=1)

    assert message.pk is not None
    assert message.created_at is not None
    assert message.supported is None
    assert message.rewritten_text is None
    assert list(message.conversation.messages.all()) == [message]


def test_create_assistant_message_with_support_flag():
    message = MessageFactory(
        role=Message.Role.ASSISTANT,
        seq=2,
        supported=True,
        content="**Resposta** markdown",
    )

    assert message.role == "assistant"
    assert message.supported is True
    assert message.content == "**Resposta** markdown"


def test_duplicate_seq_within_conversation_is_rejected():
    message = MessageFactory(seq=1)

    with pytest.raises(IntegrityError):
        MessageFactory(conversation=message.conversation, seq=1)


def test_same_seq_is_allowed_across_conversations():
    first = MessageFactory(seq=1)
    second = MessageFactory(seq=1)

    assert first.seq == second.seq == 1
    assert first.conversation_id != second.conversation_id


def test_deleting_conversation_cascades_to_messages():
    message = MessageFactory()
    conversation = message.conversation

    conversation.delete()

    assert Message.objects.count() == 0


def test_role_choices_are_user_and_assistant():
    assert {code for code, _ in Message.Role.choices} == {"user", "assistant"}


def test_str_is_readable():
    message = MessageFactory(seq=3)

    assert str(message).startswith("Message #3")
