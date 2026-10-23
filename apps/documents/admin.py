from django.contrib import admin

from .models import Chunk, Document, Notebook, Page


class PageInline(admin.TabularInline):
    model = Page
    extra = 0


class ChunkInline(admin.TabularInline):
    model = Chunk
    extra = 0


@admin.register(Notebook)
class NotebookAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "created_at")
    search_fields = ("title", "user__username")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "notebook", "title", "user", "file_type", "status", "page_count", "created_at")
    list_filter = ("status", "file_type")
    search_fields = ("title", "notebook__title")
    inlines = [PageInline, ChunkInline]


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "number", "is_scanned", "char_count")
    raw_id_fields = ("document",)
    ordering = ("document", "number")


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "page_number", "order_index", "token_count")
    raw_id_fields = ("document",)
    ordering = ("document", "order_index")
