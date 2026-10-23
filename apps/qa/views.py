from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render

from .models import Conversation, Message


@login_required
def conversation_detail(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, user=request.user)
    return render(
        request,
        "qa/conversation_detail.html",
        {
            "conversation": conversation,
            "notebook": conversation.notebook,
            "notebooks": request.user.notebooks.all(),
        },
    )


@login_required
def notebook_ask(request, pk):
    notebook = get_object_or_404(request.user.notebooks, pk=pk)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    question = request.POST.get("question", "").strip()
    if not question:
        return HttpResponseBadRequest("Question required")

    conversation_id = request.POST.get("conversation_id")
    with transaction.atomic():
        if conversation_id:
            conversation = get_object_or_404(
                Conversation,
                pk=conversation_id,
                notebook=notebook,
                user=request.user,
            )
        else:
            conversation = Conversation.objects.create(notebook=notebook, user=request.user)

        last_message = conversation.messages.order_by("-seq").first()
        next_seq = last_message.seq + 1 if last_message else 1
        message = Message.objects.create(
            conversation=conversation,
            seq=next_seq,
            role=Message.Role.USER,
            content=question,
        )

    return render(
        request,
        "qa/_user_message.html",
        {"message": message, "conversation": conversation},
    )
