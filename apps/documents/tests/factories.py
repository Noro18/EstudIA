import factory

from apps.accounts.tests.factories import UserFactory
from apps.documents.models import Chunk, Document, Notebook


class NotebookFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Notebook

    user = factory.SubFactory(UserFactory)
    title = factory.Sequence(lambda n: f"Semester notebook {n}")


class DocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Document

    notebook = factory.SubFactory(NotebookFactory)
    user = factory.LazyAttribute(lambda o: o.notebook.user)
    title = factory.Sequence(lambda n: f"Lecture document {n}")
    uploaded_file = factory.django.FileField(data=b"Dummy file content", filename="lecture.txt")
    file_type = Document.FileType.TXT


class ChunkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Chunk

    document = factory.SubFactory(DocumentFactory)
    page_number = 1
    order_index = factory.Sequence(lambda n: n + 1)
    text = factory.Sequence(lambda n: f"Chunk body text {n}. This passage explains the topic in plain words.")

