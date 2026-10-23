from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import Document, Notebook


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
        },
    )


@login_required
def document_detail(request, pk):
    document = get_object_or_404(Document, pk=pk, user=request.user)
    return render(
        request,
        "documents/document_detail.html",
        {
            "document": document,
            "notebook": document.notebook,
            "notebooks": request.user.notebooks.all(),
        },
    )
