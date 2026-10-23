from django.conf import settings
from django.db import models


class Conversation(models.Model):
    notebook = models.ForeignKey(
        "documents.Notebook",
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="conversations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "notebook"], name="qa_conversation_user_notebook"),
        ]

    def __str__(self):
        return f"Conversation #{self.pk} (notebook={self.notebook_id})"


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    seq = models.IntegerField()
    role = models.CharField(max_length=12, choices=Role.choices)
    content = models.TextField()
    supported = models.BooleanField(null=True, blank=True)
    rewritten_text = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "seq"],
                name="qa_message_conversation_seq_uniq",
            )
        ]

    def __str__(self):
        return f"Message #{self.seq} ({self.role}) in conv #{self.conversation_id}"


class MessageSource(models.Model):
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="sources",
    )
    chunk = models.ForeignKey(
        "documents.Chunk",
        on_delete=models.PROTECT,
        related_name="message_sources",
    )
    page = models.IntegerField()
    excerpt = models.TextField()
    order = models.IntegerField()

    class Meta:
        indexes = [
            models.Index(fields=["message", "order"], name="qa_messagesource_message_order"),
        ]

    def __str__(self):
        return f"Source p.{self.page} for message #{self.message_id}"


class StudyQuestion(models.Model):
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.CASCADE,
        related_name="study_questions",
    )
    order = models.IntegerField()
    question = models.TextField()
    answer = models.TextField()
    page = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "order"],
                name="qa_studyquestion_doc_order_uniq",
            )
        ]

    def __str__(self):
        return f"Study question #{self.order} (doc={self.document_id})"



