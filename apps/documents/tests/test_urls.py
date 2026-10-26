import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_root_redirects_to_notebooks(client):
    response = client.get(reverse("home"))

    assert response.status_code == 302
    assert response.url == "/notebooks/"
