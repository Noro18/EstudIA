import factory

from apps.documents.tests.factories import ChunkFactory, DocumentFactory, NotebookFactory
from apps.qa.models import Conversation, Message, MessageSource, StudyQuestion


class ConversationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Conversation

    notebook = factory.SubFactory(NotebookFactory)
    user = factory.LazyAttribute(lambda o: o.notebook.user)


class MessageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Message

    conversation = factory.SubFactory(ConversationFactory)
    seq = factory.Sequence(lambda n: n + 1)
    content = factory.Sequence(lambda n: f"Message content {n}")


def _excerpt(text: str) -> str:
    return (text[:280] + "…") if len(text) > 280 else text


class MessageSourceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MessageSource

    message = factory.SubFactory(
        MessageFactory,
        role=Message.Role.ASSISTANT,
        supported=True,
    )
    chunk = factory.SubFactory(ChunkFactory)
    page = factory.LazyAttribute(lambda o: o.chunk.page_number)
    excerpt = factory.LazyAttribute(lambda o: _excerpt(o.chunk.text))
    order = factory.Sequence(lambda n: n + 1)


class StudyQuestionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StudyQuestion

    document = factory.SubFactory(DocumentFactory)
    order = factory.Sequence(lambda n: n + 1)
    question = factory.Sequence(lambda n: f"Study question {n}")
    answer = factory.Sequence(lambda n: f"Study answer {n}")
    page = factory.Sequence(lambda n: n)
