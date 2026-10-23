import pytest

from apps.documents.tests.factories import DocumentFactory
from apps.accounts.tests.factories import UserFactory
from apps.llm.models import UsageRecord
from apps.llm.tests.factories import UsageRecordFactory

pytestmark = pytest.mark.django_db


def test_create_minimal_record():
    record = UsageRecordFactory()

    assert record.pk is not None
    assert record.created_at is not None
    assert record.purpose == "ask"
    assert record.provider == "gemini"
    assert record.model == "gemini-3.8-flash"
    assert record.prompt_tokens == 1000
    assert record.completion_tokens == 300
    assert record.latency_ms == 900


def test_embedding_records_have_no_user():
    record = UsageRecordFactory(
        purpose=UsageRecord.Purpose.QUERY_EMBEDDING,
        user=None,
        message=None,
        document=DocumentFactory(),
    )

    assert record.user_id is None
    assert record.message_id is None
    assert record.document_id is not None


def test_purpose_tokens_are_exactly_the_contract_six():
    contract = {
        "ask",
        "rewrite",
        "summary",
        "study_questions",
        "ingest_embedding",
        "query_embedding",
    }

    assert {code for code, _ in UsageRecord.Purpose.choices} == contract


def test_quota_and_cost_indexes_exist():
    names = {idx.name for idx in UsageRecord._meta.indexes}

    assert "llm_usagerecord_user_created" in names
    assert "llm_usagerecord_document" in names


def test_deleting_user_anonymizes_but_keeps_ledger():
    record = UsageRecordFactory()
    user = record.user

    user.delete()

    record.refresh_from_db()
    assert record.user_id is None


def test_deleting_document_keeps_cost_row():
    record = UsageRecordFactory(document=DocumentFactory())
    document = record.document

    document.delete()

    record.refresh_from_db()
    assert record.document_id is None


def test_str_is_readable():
    record = UsageRecordFactory()

    assert str(record).startswith("ask")
