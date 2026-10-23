import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.tests.factories import SuperUserFactory
from apps.llm.admin import UsageRecordAdmin
from apps.llm.models import UsageRecord
from apps.llm.tests.factories import UsageRecordFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_login(client):
    client.force_login(SuperUserFactory())
    return client


def test_usage_record_admin_list_renders(admin_login):
    UsageRecordFactory()

    url = reverse("admin:llm_usagerecord_changelist")
    assert admin_login.get(url).status_code == 200


def test_ledger_rows_are_immutable_in_admin():
    user = SuperUserFactory()
    request = RequestFactory().get("/")
    request.user = user
    model_admin = UsageRecordAdmin(UsageRecord, admin.site)

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False
