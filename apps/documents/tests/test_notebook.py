import pytest
from django.db.models import ProtectedError

from apps.documents.models import Document, Notebook
from apps.documents.tests.factories import DocumentFactory, NotebookFactory

pytestmark = pytest.mark.django_db


def test_create_notebook_defaults():
    notebook = NotebookFactory()

    assert notebook.pk is not None
    assert notebook.created_at is not None
    assert notebook.updated_at is not None
    assert notebook.user_id is not None
    assert str(notebook).startswith(f"Notebook #{notebook.pk}")


def test_notebook_list_index_exists():
    names = {idx.name for idx in Notebook._meta.indexes}
    assert "documents_nb_user_created" in names


def test_deleting_owner_with_notebooks_is_protected():
    notebook = NotebookFactory()

    with pytest.raises(ProtectedError):
        notebook.user.delete()

    assert Notebook.objects.count() == 1


def test_deleting_notebook_cascades_to_documents():
    document = DocumentFactory()
    notebook = document.notebook

    assert Document.objects.count() == 1

    notebook.delete()

    assert Notebook.objects.count() == 0
    assert Document.objects.count() == 0
