import logging
import re
import time
from io import BytesIO

from django.conf import settings
from django.contrib.postgres.search import SearchVector
from django.db import transaction

from apps.llm.models import UsageRecord

from .models import Chunk, Document, Page

logger = logging.getLogger(__name__)

CHUNK_MAX_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150


class IngestionError(Exception):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def _read_document_pages(document):
    content = document.uploaded_file.read()

    if document.file_type == Document.FileType.TXT:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise IngestionError("extraction_failed", "The text file is not valid UTF-8.") from exc
        if not text.strip():
            raise IngestionError("extraction_failed", "The text file is empty.")
        return [(1, text, False, False)]

    if document.file_type == Document.FileType.DOCX:
        try:
            from docx import Document as DocxDocument

            source = DocxDocument(BytesIO(content))
        except Exception as exc:
            raise IngestionError("extraction_failed", "Could not read the DOCX file.") from exc
        text = "\n\n".join(paragraph.text.strip() for paragraph in source.paragraphs if paragraph.text.strip())
        if not text:
            raise IngestionError("extraction_failed", "The DOCX file has no extractable text.")
        return [(1, text, False, False)]

    if document.file_type == Document.FileType.PDF:
        try:
            import pymupdf

            source = pymupdf.open(stream=content, filetype="pdf")
        except Exception as exc:
            raise IngestionError("extraction_failed", "Could not read the PDF file.") from exc
        pages = []
        try:
            for number, page in enumerate(source, start=1):
                text = page.get_text("text").strip()
                pages.append((number, text, not text, False))
        finally:
            source.close()
        if not pages or all(not text for _, text, _, _ in pages):
            raise IngestionError("scanned_no_text", "This PDF has no selectable text.")
        return pages

    raise IngestionError("unsupported_type", "Unsupported document type.")


def _split_text(text, max_chars=CHUNK_MAX_CHARS, overlap_chars=CHUNK_OVERLAP_CHARS):
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks = []
    current = ""
    for paragraph in paragraphs:
        pieces = [paragraph]
        if len(paragraph) > max_chars:
            words, pieces, piece = paragraph.split(), [], ""
            for word in words:
                if piece and len(piece) + len(word) + 1 > max_chars:
                    pieces.append(piece)
                    piece = ""
                piece = f"{piece} {word}".strip()
            if piece:
                pieces.append(piece)
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > max_chars:
                chunks.append(current)
                overlap = current[-overlap_chars:].strip()
                current = f"{overlap}\n\n{piece}" if overlap else piece
            else:
                current = f"{current}\n\n{piece}".strip()
    if current:
        chunks.append(current)
    return chunks


def _embed_texts(texts):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(settings.EMBEDDING_MODEL, device="cpu")
    vectors = model.encode(texts, normalize_embeddings=True)
    return vectors.tolist()


def _mark_failed(document, reason):
    document.status = Document.Status.FAILED
    document.failure_reason = reason
    document.save(update_fields=["status", "failure_reason", "updated_at"])


def finalize_ingestion_status(document):
    """Ensure a worker cannot leave a document indefinitely in processing."""
    document.refresh_from_db()
    if document.status != Document.Status.PROCESSING:
        return document.status

    has_pages = document.pages.exists()
    has_chunks = document.chunks.exists()
    has_unembedded_chunks = document.chunks.filter(embedding__isnull=True).exists()
    if has_pages and has_chunks and not has_unembedded_chunks:
        document.status = Document.Status.READY
        document.failure_reason = None
    else:
        document.status = Document.Status.FAILED
        document.failure_reason = "ingestion_incomplete"
    document.save(update_fields=["status", "failure_reason", "updated_at"])
    return document.status


def extract_txt_document(document):
    """Extract a UTF-8 text document into one page and mark it ready."""
    ingest_document(document)


def ingest_document(document, embedder=None):
    """Extract, chunk, embed, and persist one document's ingestion result."""
    embedder = embedder or _embed_texts
    started_at = time.perf_counter()
    document.status = Document.Status.PROCESSING
    document.failure_reason = None
    document.save(update_fields=["status", "failure_reason", "updated_at"])

    try:
        with transaction.atomic():
            extracted_pages = _read_document_pages(document)
            Page.objects.filter(document=document).delete()
            Chunk.objects.filter(document=document).delete()

            page_rows = [
                Page(
                    document=document,
                    number=number,
                    text=text,
                    is_scanned=is_scanned,
                    ocr_used=ocr_used,
                    char_count=len(text),
                )
                for number, text, is_scanned, ocr_used in extracted_pages
            ]
            Page.objects.bulk_create(page_rows)

            chunk_payload = []
            for number, text, _, _ in extracted_pages:
                for chunk_text in _split_text(text):
                    chunk_payload.append((number, chunk_text))
            if not chunk_payload:
                raise IngestionError("extraction_failed", "The document has no extractable text.")

            vectors = embedder([text for _, text in chunk_payload])
            if len(vectors) != len(chunk_payload) or any(
                len(vector) != settings.EMBEDDING_DIM for vector in vectors
            ):
                raise IngestionError("embedding_failed", "The embedding dimension does not match the configured model.")

            chunks = [
                Chunk(
                    document=document,
                    page_number=page_number,
                    order_index=index,
                    text=text,
                    token_count=len(text.split()),
                    embedding=vector,
                )
                for index, ((page_number, text), vector) in enumerate(zip(chunk_payload, vectors), start=1)
            ]
            Chunk.objects.bulk_create(chunks)
            Chunk.objects.filter(document=document).update(search_vector=SearchVector("text", config="simple"))

            document.page_count = len(page_rows)
            document.embedding_model = settings.EMBEDDING_MODEL
            document.embedding_dim = settings.EMBEDDING_DIM
            document.status = Document.Status.READY
            document.failure_reason = None
            document.save(
                update_fields=[
                    "page_count",
                    "embedding_model",
                    "embedding_dim",
                    "status",
                    "failure_reason",
                    "updated_at",
                ]
            )
            UsageRecord.objects.create(
                user=document.user,
                document=document,
                purpose=UsageRecord.Purpose.INGEST_EMBEDDING,
                provider="local",
                model=settings.EMBEDDING_MODEL,
                prompt_tokens=sum(chunk.token_count for chunk in chunks),
                completion_tokens=0,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                cost_usd=0,
            )
    except IngestionError as exc:
        _mark_failed(document, exc.reason)
        logger.warning("Document %s ingestion failed: %s", document.pk, exc)
    except Exception:
        _mark_failed(document, "extraction_failed")
        logger.exception("Document %s ingestion failed unexpectedly", document.pk)
