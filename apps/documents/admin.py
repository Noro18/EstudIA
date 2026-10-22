from django.contrib import admin

from .models import Chunk, Document, Page


class PageInline(admin.TabularInline):
    model = Page
    extra = 0


class ChunkInline(admin.TabularInline):
    model = Chunk
    extra = 0


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "file_type", "status", "page_count", "created_at")
    list_filter = ("status", "file_type")
    search_fields = ("title",)
    inlines = [PageInline, ChunkInline]


admin.site.register(Page)
admin.site.register(Chunk)
