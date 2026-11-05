"""QA services — quiz generation and answer-citation finalization.

Quiz rules (PRD § 3 optional, Oct 30 2026): the model must name the passage it
used, and every generated question is validated against the chunks that were
actually sent. Citations never come from the model's words. One UsageRecord
per LLM call — the same rule the citation finalizer follows (spec 13). Quiz
content language is English (user decision, Oct 30 2026); the Tetum-first
rule stays untouched for the QA answer flow.
"""
import json
import logging
import re

from django.conf import settings
from django.db import transaction

from apps.documents.models import Document
from apps.llm.adapter import GeminiAdapter, LLMUnavailable
from apps.llm.models import UsageRecord

from .models import QuizQuestion, QuizChunkUsage

logger = logging.getLogger(__name__)

LETTERS = ("A", "B", "C", "D")

# The exact marker the grounded prompt (apps/rag/prompting.py) pins in its
# instruction ("Used chunks: [1, 2]") — one format, two consumers, tested
# against each other (spec 13). Brackets are allowed to carry anything; every
# piece must be a positive integer or it is dropped (never guessed).
_USED_CHUNKS_RE = re.compile(r"^Used chunks: \[(?P<numbers>[^\]]*)\]\.?\s*$")


def parse_used_chunks(answer):
    """Chunk numbers the model claims to have used (spec 13 C1/C5).

    Reads the string emitted by the grounded prompt's `Used chunks:` line —
    the LAST non-empty line of the answer, nothing else. Malformed or missing
    markers yield zero citations, never guesses. First-appearance order,
    deduplicated; validation against the supplied chunks happens later.
    """
    text = (answer or "").rstrip()
    if not text:
        return ()
    last_line = text.rsplit("\n", 1)[-1].strip()
    match = _USED_CHUNKS_RE.match(last_line)
    if not match:
        return ()
    numbers, seen = [], set()
    for piece in match.group("numbers").split(","):
        piece = piece.strip()
        if not piece or not piece.isdigit():
            continue
        number = int(piece)
        if number > 0 and number not in seen:
            seen.add(number)
            numbers.append(number)
    return tuple(numbers)


def strip_used_chunks(answer):
    """Answer text with the trailing `Used chunks:` marker line removed (C4).

    Only the recognized marker is removed — malformed lines stay visible, so
    parsing problems surface in the UI instead of hiding.
    """
    text = (answer or "").rstrip()
    if not text:
        return text
    last_line = text.rsplit("\n", 1)[-1].strip()
    if _USED_CHUNKS_RE.match(last_line):
        return text.rsplit("\n", 1)[0].rstrip()
    return text


def _citation_excerpt(text):
    """Snapshot rule (DATABASE.md § 3): first 280 chars, `…` when truncated."""
    return (text[:280] + "…") if len(text) > 280 else text


def finalize_assistant_message(conversation, user, matches, answer, usage):
    """Persist the answer bubble with its validated citations (spec 13).

    Steps (PRD § 5 step 8, DATABASE.md § 4.2 step 7): parse the model's chunk
    numbers → validate ⊆ supplied chunk ids → one MessageSource row per
    distinct chunk with page + excerpt snapshots → `supported` set mechanically
    (citations ≥ 1) → one UsageRecord row for the call. Returns the Message.
    """
    from .models import Message, MessageSource  # local import avoids cycles

    valid, seen_chunk_ids = [], set()
    for number in parse_used_chunks(answer):
        index = number - 1
        if not 0 <= index < len(matches):
            continue
        match = matches[index]
        if match.chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(match.chunk_id)
        valid.append(match)

    with transaction.atomic():
        last_seq = (
            conversation.messages.order_by("-seq").values_list("seq", flat=True).first() or 0
        )
        message = Message.objects.create(
            conversation=conversation,
            seq=last_seq + 1,
            role=Message.Role.ASSISTANT,
            content=strip_used_chunks(answer),
            supported=bool(valid),
        )
        MessageSource.objects.bulk_create(
            MessageSource(
                message=message,
                chunk_id=match.chunk_id,
                page=match.page,
                excerpt=_citation_excerpt(match.text),
                order=order,
            )
            for order, match in enumerate(valid, start=1)
        )
        UsageRecord.objects.create(
            user=user,
            message=message,
            purpose=UsageRecord.Purpose.ASK,
            provider=usage.get("provider", "gemini"),
            model=usage.get("model") or settings.LLM_MODEL,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=usage.get("latency_ms", 0),
            cost_usd=0,
        )
    if not valid:
        logger.warning(
            "Assistant message %s has no validated citations -> supported=False",
            message.pk,
        )
    return message


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
    """Pick `count` chunks from ready documents, spread round-robin across them.

    Chunks already used in an earlier quiz are skipped.
    """
    documents = notebook.documents.filter(status=Document.Status.READY).order_by("created_at")
    queues = [
        list(doc.chunks.filter(quiz_usage__isnull=True).order_by("order_index"))
        for doc in documents
    ]
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
        # NEW: pesan diubah, karena sekarang chunk bisa habis terpakai
        raise QuizNotReady(
            "No new material left for a quiz. Add a document, or all current material has already been used."
        )
 
    # NEW: aturan bahasa soal
    language_rule = (
        f"Write every question and every answer choice in {settings.QUIZ_LANGUAGE}. "
        "Keep the JSON keys in English. Use only facts that appear in the numbered passages."
    )
 
    prompt = (  # NEW: language_rule disisipkan di antara QUIZ_PROMPT_HEAD dan isi chunk
        QUIZ_PROMPT_HEAD
        + "\n\n"
        + language_rule
        + "\n\n"
        + "\n\n".join(f"[{index}] {chunk.text}" for index, chunk in enumerate(chunks, start=1))
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
        QuizChunkUsage.objects.bulk_create(
            [QuizChunkUsage(chunk=chunk) for chunk, _q, _c, _l in rows],
            ignore_conflicts=True,
        )
    return QuizQuestion.objects.filter(notebook=notebook).order_by("order")

