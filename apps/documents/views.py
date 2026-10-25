import os

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
import mistune

from apps.qa.models import Message

from .models import Document, Notebook
from .tasks import enqueue_document_ingestion

render_markdown = mistune.create_markdown(escape=True)


def _history_rows(conversation):
    """Server-rendered chat history; assistant answers come pre-rendered so the
    workspace looks identical to the live-streamed chat."""
    rows = []
    for message in conversation.messages.all():
        if message.role == Message.Role.ASSISTANT:
            rows.append({"message": message, "html": mark_safe(render_markdown(message.content))})
        else:
            rows.append({"message": message, "html": None})
    return rows


@login_required
def notebook_list(request):
    if request.method == "POST" and request.POST.get("title", "").strip():
        notebook = Notebook.objects.create(
            user=request.user,
            title=request.POST["title"].strip(),
        )
        return redirect("notebook_workspace", pk=notebook.pk)
    return render(request, "notebooks/notebook_list.html", {"notebooks": request.user.notebooks.all()})


@login_required
def notebook_workspace(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)
    conversation = notebook.conversations.order_by("-created_at").first()
    return render(
        request,
        "notebooks/notebook_workspace.html",
        {
            "notebook": notebook,
            "notebooks": request.user.notebooks.all(),
            "conversation": conversation,
            "rows": _history_rows(conversation) if conversation else [],
        },
    )


@login_required
def document_detail(request, pk):
    document = get_object_or_404(Document, pk=pk, user=request.user)

    # HTMX polling requests get the card partial; direct navigation gets full page
    if request.headers.get("HX-Request"):
        return render(
            request,
            "documents/_document_card.html",
            {"document": document, "notebook": document.notebook},
        )

    return render(
        request,
        "documents/document_detail.html",
        {
            "document": document,
            "notebook": document.notebook,
            "notebooks": request.user.notebooks.all(),
        },
    )


@login_required
def notebook_upload_document(request, pk):
    notebook = get_object_or_404(Notebook, pk=pk, user=request.user)

    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return HttpResponseBadRequest("No file provided")

    # Validate file type
    ext = os.path.splitext(uploaded_file.name)[1].lower().lstrip(".")
    allowed_types = {"pdf", "docx", "txt"}
    if ext not in allowed_types:
        return render(
            request,
            "documents/_error_fragment.html",
            {"error_code": "unsupported_type", "message": f"Unsupported file type: .{ext}. Allowed: PDF, DOCX, TXT"},
            status=400,
        )

    # Validate file size
    max_size = getattr(settings, "MAX_UPLOAD_SIZE_BYTES", 20 * 1024 * 1024)
    if uploaded_file.size > max_size:
        max_mb = max_size // (1024 * 1024)
        return render(
            request,
            "documents/_error_fragment.html",
            {"error_code": "file_too_large", "message": f"File too large. Maximum size: {max_mb} MB"},
            status=400,
        )

    # Create Document with processing status
    document = Document.objects.create(
        notebook=notebook,
        user=request.user,
        title=os.path.splitext(uploaded_file.name)[0],
        uploaded_file=uploaded_file,
        file_type=ext,
        status=Document.Status.PROCESSING,
    )

    enqueue_document_ingestion(document.pk)

    # Return document card fragment for HTMX swap
    return render(
        request,
        "documents/_document_card.html",
        {"document": document, "notebook": notebook},
    )
