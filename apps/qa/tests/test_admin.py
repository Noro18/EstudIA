import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.tests.factories import SuperUserFactory
from apps.qa.admin import MessageSourceAdmin
from apps.qa.models import MessageSource
from apps.qa.tests.factories import (
    ConversationFactory,
    MessageFactory,
    MessageSourceFactory,
    StudyQuestionFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_login(client):
    client.force_login(SuperUserFactory())
    return client


def test_qa_admin_list_pages_render(admin_login):
    ConversationFactory()
    MessageFactory()
    MessageSourceFactory()
    StudyQuestionFactory()

    urls = [
        "qa_conversation_changelist",
        "qa_message_changelist",
        "qa_messagesource_changelist",
        "qa_studyquestion_changelist",
    ]

    for url_name in urls:
        url = reverse(f"admin:{url_name}")
        assert admin_login.get(url).status_code == 200, url_name


def test_conversation_admin_renders_message_inline(admin_login):
    conversation = ConversationFactory()
    MessageFactory(conversation=conversation, seq=1)

    url = reverse("admin:qa_conversation_change", args=(conversation.pk,))
    response = admin_login.get(url)

    assert response.status_code == 200
    assert b"Message content" in response.content


def test_citation_rows_are_not_manually_editable():
    user = SuperUserFactory()
    request = RequestFactory().get("/")
    request.user = user
    model_admin = MessageSourceAdmin(MessageSource, admin.site)

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False


def test_citation_fields_render_readonly_on_change_page(admin_login):
    source = MessageSourceFactory()

    url = reverse("admin:qa_messagesource_change", args=(source.pk,))
    response = admin_login.get(url)

    assert response.status_code == 200
    b_page = b'name="page"'
    b_chunk = b'name="chunk"'
    assert b_page not in response.content
    assert b_chunk not in response.content
