import pytest
from django.db.models import ProtectedError

from apps.qa.models import MessageSource
from apps.qa.tests.factories import MessageSourceFactory

pytestmark = pytest.mark.django_db


def test_create_citation_snapshot():
    source = MessageSourceFactory(order=1)

    assert source.pk is not None
    assert source.chunk_id is not None
    assert source.page == source.chunk.page_number
    assert source.excerpt.startswith(source.chunk.text[:20])
    assert list(source.message.sources.all()) == [source]


def test_excerpt_is_snapshot_not_live_link():
    source = MessageSourceFactory()

    chunk = source.chunk
    chunk.text = "Completely rewritten body text"
    chunk.save()

    source.refresh_from_db()

    assert source.excerpt != chunk.text


def test_deleting_chunk_is_protected():
    source = MessageSourceFactory()

    with pytest.raises(ProtectedError):
        source.chunk.delete()

    assert MessageSource.objects.count() == 1


def test_deleting_message_cascades_to_sources():
    source = MessageSourceFactory()
    message = source.message

    message.delete()

    assert MessageSource.objects.count() == 0


def test_message_order_index_exists():
    names = {idx.name for idx in MessageSource._meta.indexes}
    assert "qa_messagesource_message_order" in names
