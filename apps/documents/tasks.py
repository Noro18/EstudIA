from django.shortcuts import get_object_or_404
from django_q.tasks import async_task

from .models import Document
from .services import finalize_ingestion_status, ingest_document


def ingest_document_task(document_id):
    document = get_object_or_404(Document, pk=document_id)
    ingest_document(document)
    finalize_ingestion_status(document)


def enqueue_document_ingestion(document_id):
    return async_task("apps.documents.tasks.ingest_document_task", document_id)
