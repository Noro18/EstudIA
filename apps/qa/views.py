import json
import logging
import queue
import re
import time
import threading

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
import mistune
from django.utils.safestring import mark_safe

from apps.llm.adapter import GeminiAdapter, LLMUnavailable
from apps.llm.models import UsageRecord

from .models import Conversation, Message, QuizQuestion
from .services import QuizNotReady, generate_quiz

render_markdown = mistune.create_markdown(escape=True)
logger = logging.getLogger(__name__)

# While the model thinks, bytes must still flow to the browser, or proxies
# and browsers kill the idle SSE connection (the "Network Error" symptom).
HEARTBEAT_SECONDS = 15
KEEP_ALIVE = ": keep-alive\n\n"
STREAM_WORDS_PER_EVENT = 1
STREAM_WORD_DELAY_SECONDS = 0.035


@login_required
def conversation_detail(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, user=request.user)
    rows = []
    for message in conversation.messages.all():
        if message.role == Message.Role.ASSISTANT:
            # Render once, at request time, so the replay looks like the live stream.
            rows.append({"message": message, "html": mark_safe(render_markdown(message.content))})
        else:
            rows.append({"message": message, "html": None})
    return render(
        request,
        "qa/conversation_detail.html",
        {
            "conversation": conversation,
            "notebook": conversation.notebook,
            "notebooks": request.user.notebooks.all(),
            "rows": rows,
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


def _stream_word_groups(text, words_per_group=STREAM_WORDS_PER_EVENT):
    """Split provider text without dropping whitespace or Markdown newlines."""
    tokens = re.findall(r"\s*\S+", text)
    if not tokens:
        if text:
            yield text
        return
    for index in range(0, len(tokens), words_per_group):
        yield "".join(tokens[index : index + words_per_group])


def _run_llm(adapter, messages, out):
    """Consume the adapter generator in a worker thread, forwarding every part.

    Running the (possibly hung) SDK call off the request thread lets the view
    emit heartbeats while nothing arrives, so the SSE connection never idles.
    """
    try:
        for part in adapter.generate(messages, stream=True):
            out.put(part)
    except LLMUnavailable as exc:
        out.put(exc)
    except Exception as exc:
        logger.exception("LLM streaming raised an unexpected error")
        out.put(LLMUnavailable(f"Unexpected LLM failure: {exc}"))
    finally:
        out.put(None)  # sentinel: no more items will ever arrive


def _stream_answer(user, conversation, user_message):
    def events():
        yield _sse("user", {"conversation_id": conversation.pk, "text": user_message.content})
        adapter = GeminiAdapter()
        answer_parts = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0}
        out = queue.Queue()
        worker = threading.Thread(
            target=_run_llm,
            args=(adapter, _gemini_messages(conversation), out),
            daemon=True,
        )
        worker.start()
        while True:
            try:
                item = out.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                yield KEEP_ALIVE
                continue
            if item is None:
                break
            if isinstance(item, LLMUnavailable):
                yield _sse(
                    "error",
                    {"message": str(item), "code": getattr(item, "error_code", "llm_unavailable")},
                )
                return
            usage.update({key: value for key, value in item["usage"].items() if value})
            if item["text"]:
                groups = list(_stream_word_groups(item["text"]))
                for index, group in enumerate(groups):
                    answer_parts.append(group)
                    yield _sse("message", {"html": render_markdown("".join(answer_parts))})
                    if index < len(groups) - 1:
                        time.sleep(STREAM_WORD_DELAY_SECONDS)
        worker.join()

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


def _quiz_error(request, code, message):
    """PRD § 8 error shape, reused from the documents error partial."""
    return render(
        request,
        "documents/_error_fragment.html",
        {"error_code": code, "message": message},
        status=400,
    )


@login_required
def notebook_quiz_start(request, pk):
    """Generate a fresh quiz for the notebook and return question cards (HTMX)."""
    notebook = get_object_or_404(request.user.notebooks, pk=pk)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        questions = generate_quiz(notebook)
    except QuizNotReady as exc:
        return _quiz_error(request, exc.error_code, str(exc))
    except LLMUnavailable as exc:
        return _quiz_error(request, getattr(exc, "error_code", "llm_unavailable"), str(exc))
    return render(request, "quiz/_cards.html", {"notebook": notebook, "questions": questions})


@login_required
def notebook_quiz_submit(request, pk):
    """Score the submitted quiz locally — comparison, not a second LLM call."""
    notebook = get_object_or_404(request.user.notebooks, pk=pk)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    questions = list(QuizQuestion.objects.filter(notebook=notebook).order_by("order"))
    if not questions:
        return _quiz_error(request, "document_not_ready", "No active quiz for this notebook.")
    rows, correct = [], 0
    for question in questions:
        picked = request.POST.get(f"answer_{question.pk}", "")
        is_correct = picked == question.correct_letter
        if is_correct:
            correct += 1
        rows.append({
            "question": question,
            "picked": picked,
            "picked_text": question.choices.get(picked) or "",
            "correct_text": question.choices.get(question.correct_letter, ""),
            "is_correct": is_correct,
        })
    return render(
        request,
        "quiz/_results.html",
        {"notebook": notebook, "score": correct, "total": len(questions), "rows": rows},
    )

