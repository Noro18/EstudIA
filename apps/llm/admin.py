from django.contrib import admin

from .models import UsageRecord


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "purpose",
        "user",
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "cost_usd",
        "created_at",
    )
    list_filter = ("purpose", "provider", "model")
    raw_id_fields = ("user", "document", "message")
    readonly_fields = (
        "user",
        "document",
        "message",
        "purpose",
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "cost_usd",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
