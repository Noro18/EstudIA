import pytest
from django.urls import reverse

from apps.accounts.tests.factories import SuperUserFactory
from apps.documents.tests.factories import NotebookFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_login(client):
    client.force_login(SuperUserFactory())
    return client


def test_notebook_admin_is_registered(admin_login):
    notebook = NotebookFactory()

    url = reverse("admin:documents_notebook_change", args=(notebook.pk,))
    response = admin_login.get(url)

    assert response.status_code == 200
