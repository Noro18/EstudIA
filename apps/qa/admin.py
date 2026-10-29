from django.contrib import admin

from .models import Conversation, Message, MessageSource, QuizQuestion, StudyQuestion


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("seq", "role", "supported", "rewritten_text", "content")
    ordering = ("seq",)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "notebook", "user", "created_at")
    list_filter = ("notebook", "user")
    search_fields = ("notebook__title", "user__username")
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "seq", "role", "supported", "created_at")
    list_filter = ("role", "supported")
    raw_id_fields = ("conversation",)
    ordering = ("conversation", "seq")


@admin.register(MessageSource)
class MessageSourceAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "chunk", "page", "order")
    raw_id_fields = ("message", "chunk")
    readonly_fields = ("message", "chunk", "page", "excerpt", "order")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StudyQuestion)
class StudyQuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "order", "page", "question")
    raw_id_fields = ("document",)
    ordering = ("document", "order")


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ("notebook", "order", "correct_letter")
