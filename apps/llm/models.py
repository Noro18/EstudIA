from django.conf import settings
from django.db import models


class UsageRecord(models.Model):
    class Purpose(models.TextChoices):
        ASK = "ask"
        REWRITE = "rewrite"
        SUMMARY = "summary"
        STUDY_QUESTIONS = "study_questions"
        INGEST_EMBEDDING = "ingest_embedding"
        QUERY_EMBEDDING = "query_embedding"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_records",
    )
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_records",
    )
    message = models.ForeignKey(
        "qa.Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_records",
    )
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=120)
    prompt_tokens = models.IntegerField()
    completion_tokens = models.IntegerField()
    latency_ms = models.IntegerField()
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"], name="llm_usagerecord_user_created"),
            models.Index(fields=["document"], name="llm_usagerecord_document"),
        ]

    def __str__(self):
        tokens = self.prompt_tokens + self.completion_tokens
        return f"{self.purpose} {self.model} {tokens}t"
