from django.db import transaction

from .models import Document, Page


@transaction.atomic
def extract_txt_document(document):
    """Extract a UTF-8 text document into one page and mark it ready."""
    text = document.uploaded_file.read().decode("utf-8-sig")

    document.pages.all().delete()
    Page.objects.create(
        document=document,
        number=1,
        text=text,
        is_scanned=False,
        ocr_used=False,
        char_count=len(text),
    )
    document.page_count = 1
    document.status = Document.Status.READY
    document.failure_reason = None
    document.save(update_fields=["page_count", "status", "failure_reason", "updated_at"])
