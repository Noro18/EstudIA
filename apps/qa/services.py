"""Quiz generation service — optional PRD § 3 "multiple-choice quiz mode".

Rules honored here (PRD § 5/§ 7): the model must name the passage it used, and
every generated question is validated against the chunks that were actually
sent. Citations never come from the model's words. One UsageRecord per LLM
call. Quiz content language is English (user decision, Oct 30 2026) — the
Tetum-first rule stays untouched for the QA answer flow.
"""
import json
import logging
import re

from django.conf import settings
from django.db import transaction

from apps.documents.models import Document
from apps.llm.adapter import GeminiAdapter, LLMUnavailable
from apps.llm.models import UsageRecord

from .models import QuizQuestion

logger = logging.getLogger(__name__)

LETTERS = ("A", "B", "C", "D")

QUIZ_PROMPT_HEAD = """You are StudIA, a study assistant for students in Timor-Leste.

Below are numbered passages from the student's documents. Write exactly one
multiple-choice question for each passage.

Rules:
- Output ONLY a JSON list (no intro text, no markdown fence).
- Each item has keys: "question", "choices" (object with keys "A", "B", "C", "D"),
  "correct" (one of "A", "B", "C", "D"), "chunk" (the passage number you used).
- The question and all choices MUST be written in English.
- Test only facts that appear in the passage; never invent content.

Example output:
[{"question": "What does governance mainly require?", "choices": {"A": "Openness", "B": "Fairness", "C": "Color", "D": "Speed"}, "correct": "B", "chunk": 1}]


The passages:

"""


class QuizNotReady(Exception):
    """Notebook has no ready documents to build a quiz from."""

    error_code = "document_not_ready"


def _take_chunks(notebook, count):
    """Pick `count` chunks from ready documents, spread round-robin across them."""
    documents = notebook.documents.filter(status=Document.Status.READY).order_by("created_at")
    queues = [list(doc.chunks.order_by("order_index")) for doc in documents]
    picked = []
    while len(picked) < count and any(queues):
        for queue in queues:
            if queue and len(picked) < count:
                picked.append(queue.pop(0))
    return picked


def _parse_quiz_json(text):
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    plain = re.search(r"\[.*\]", text, re.DOTALL)
    match = fenced or plain
    if not match:
        raise LLMUnavailable("Model returned no quiz JSON.")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMUnavailable("Model returned unparseable quiz JSON.") from exc


def _validated_rows(items, chunks):
    """Keep only model items whose chunk number and letters we can verify."""
    rows, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            continue
        number = item.get("chunk")
        if not isinstance(number, int) or not 1 <= number <= len(chunks) or number in seen:
            continue
        letter = item.get("correct")
        choices = item.get("choices")
        question = item.get("question")
        if letter not in LETTERS or not isinstance(question, str) or not question.strip():
            continue
        if not isinstance(choices, dict) or any(
            not isinstance(choices.get(key), str) or not choices.get(key).strip() for key in LETTERS
        ):
            continue
        seen.add(number)
        rows.append((chunks[number - 1], question, {key: choices[key] for key in LETTERS}, letter))
    return rows


def generate_quiz(notebook):
    """Generate one active quiz set for the notebook; replaces the previous set."""
    chunks = _take_chunks(notebook, settings.QUIZ_QUESTION_COUNT)
    if not chunks:
        raise QuizNotReady("This notebook has no ready documents to make a quiz from.")

    prompt = QUIZ_PROMPT_HEAD + "\n\n".join(
        f"[{index}] {chunk.text}" for index, chunk in enumerate(chunks, start=1)
    )
    result = GeminiAdapter().generate(
        [{"role": "user", "parts": [{"text": prompt}]}],
        stream=False,
    )
    usage = result["usage"]

    rows = _validated_rows(_parse_quiz_json(result["text"]), chunks)
    if not rows:
        raise LLMUnavailable("Model produced no valid quiz questions.")

    logger.info("Quiz generated: notebook=%s valid=%s/%s", notebook.pk, len(rows), len(chunks))
    UsageRecord.objects.create(
        user=notebook.user,
        purpose=UsageRecord.Purpose.STUDY_QUESTIONS,
        provider=usage.get("provider", "gemini"),
        model=usage.get("model") or settings.LLM_MODEL,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        latency_ms=usage.get("latency_ms", 0),
        cost_usd=0,
    )

    with transaction.atomic():
        QuizQuestion.objects.filter(notebook=notebook).delete()
        questions = [
            QuizQuestion(
                notebook=notebook,
                chunk=chunk,
                order=index,
                question=question,
                choices=choices,
                correct_letter=letter,
            )
            for index, (chunk, question, choices, letter) in enumerate(rows, start=1)
        ]
        QuizQuestion.objects.bulk_create(questions)
    return QuizQuestion.objects.filter(notebook=notebook).order_by("order")