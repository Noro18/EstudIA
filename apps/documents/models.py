from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from pgvector.django import HnswIndex, VectorField


class Notebook(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="notebooks",
    )
    title = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"], name="documents_nb_user_created"),
        ]

    def __str__(self):
        return f"Notebook #{self.pk} {self.title}"


class Document(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing"
        READY = "ready"
        FAILED = "failed"

    class FileType(models.TextChoices):
        PDF = "pdf"
        DOCX = "docx"
        TXT = "txt"

    notebook = models.ForeignKey(
        Notebook,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    title = models.CharField(max_length=300)
    uploaded_file = models.FileField(upload_to="documents/%Y/%m/")
    file_type = models.CharField(max_length=8, choices=FileType.choices)
    page_count = models.IntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PROCESSING,
    )
    failure_reason = models.CharField(max_length=64, null=True, blank=True)
    embedding_model = models.CharField(max_length=120, null=True, blank=True)
    embedding_dim = models.IntegerField(null=True, blank=True)
    summary_text = models.TextField(null=True, blank=True)
    summary_created_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"], name="documents_doc_user_created")
        ]


class Page(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="pages")
    number = models.IntegerField()
    text = models.TextField()
    is_scanned = models.BooleanField(default=False)
    ocr_used = models.BooleanField(default=False)
    char_count = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "number"],
                name="documents_page_doc_number_uniq",
            )
        ]


class Chunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    page_number = models.IntegerField()
    order_index = models.IntegerField()
    text = models.TextField()
    token_count = models.IntegerField(default=0)
    embedding = VectorField(dimensions=settings.EMBEDDING_DIM, null=True)
    search_vector = SearchVectorField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "order_index"],
                name="documents_chunk_doc_order_uniq",
            )
        ]
        indexes = [
            HnswIndex(
                name="documents_chunk_embed_hnsw",
                fields=["embedding"],
                opclasses=["vector_cosine_ops"],
            ),
            GinIndex(name="documents_chunk_svec_gin", fields=["search_vector"]),
            models.Index(fields=["document", "page_number"], name="documents_chunk_doc_page"),
        ]
