from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import Conversation


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
