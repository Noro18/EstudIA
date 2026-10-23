import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render

from apps.llm.adapter import GeminiAdapter, LLMUnavailable
from apps.llm.models import UsageRecord

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

    if request.POST.get("stream") == "true":
        return _stream_answer(request.user, conversation, message)

    return render(
        request,
        "qa/_user_message.html",
        {"message": message, "conversation": conversation},
    )


def _gemini_messages(conversation):
    return [
        {
            "role": "user" if message.role == Message.Role.USER else "model",
            "parts": [{"text": message.content}],
        }
        for message in conversation.messages.order_by("seq")
    ]


def _sse(event, payload):
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _stream_answer(user, conversation, user_message):
    def events():
        yield _sse("user", {"conversation_id": conversation.pk, "text": user_message.content})
        adapter = GeminiAdapter()
        answer_parts = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0}
        try:
            for part in adapter.generate(_gemini_messages(conversation), stream=True):
                answer_parts.append(part["text"])
                usage.update({key: value for key, value in part["usage"].items() if value})
                if part["text"]:
                    yield _sse("message", {"text": part["text"]})
        except LLMUnavailable as exc:
            yield _sse("error", {"message": str(exc)})
            return

        answer = "".join(answer_parts)
        next_seq = conversation.messages.order_by("-seq").first().seq + 1
        assistant = Message.objects.create(
            conversation=conversation,
            seq=next_seq,
            role=Message.Role.ASSISTANT,
            content=answer,
        )
        UsageRecord.objects.create(
            user=user,
            message=assistant,
            purpose=UsageRecord.Purpose.ASK,
            provider=usage.get("provider", "gemini"),
            model=usage.get("model", settings.LLM_MODEL),
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            latency_ms=usage["latency_ms"],
            cost_usd=0,
        )
        yield _sse("done", {"conversation_id": conversation.pk})

    response = StreamingHttpResponse(events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
