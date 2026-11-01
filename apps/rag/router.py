"""Fast intent router and standalone-question rewriter (spec 12, issue #11).

Two jobs before hybrid retrieval runs:
- classify_intent: decide whether the message needs passages at all ("why
  didn't you tell me?" is about the conversation, not the documents).
- rewrite_standalone: resolve follow-up wording ("what about TOPSIS?") into a
  question that can be searched on its own.

Both calls are best-effort: on any failure we return the safe default
("retrieve" / the original question), which reproduces today's behavior
exactly — spec 12 decision C1. They run on a small, separate model selected
with LLM_ROUTER_MODEL; when that variable is unset, these functions are
never called and the pipeline behaves byte-identically to the pre-router flow.
"""
import logging
import re

from django.conf import settings

from apps.llm.adapter import LLMUnavailable, build_adapter

logger = logging.getLogger(__name__)

_RETRIEVE_MARK = "RETRIEVE:"
_HISTORY_MARK = "HISTORY:"


def estimate_tokens(text):
    """Cheap token estimate (spec 12 decision C4): ~4 characters per token."""
    return len(text) // 4


def build_router_messages(question, history, instructions, examples):
    """Small reusable prompt: English instructions, Tetum few-shots, history."""
    rendered_history = "\n".join(
        f"{turn.get('role', 'user').capitalize()}: {(turn.get('content') or '').strip()}"
        for turn in history
        if (turn.get("content") or "").strip()
    )
    prompt = f"""{instructions}

Examples:
{examples}

Previous conversation:
{rendered_history}

New question: {question}"""
    return [{"role": "user", "parts": [{"text": prompt}]}]


def _router_answer(messages):
    """Run the router call; raise LLMUnavailable when routed from settings."""
    model = settings.LLM_ROUTER_MODEL
    if not model:
        raise LLMUnavailable("LLM_ROUTER_MODEL is not configured — router disabled.")
    adapter = build_adapter()
    adapter.model = model  # same provider plumbing, small model name
    result = adapter.generate(messages, stream=False)
    logger.info(
        "router call: prompt_tokens=%s completion_tokens=%s",
        result["usage"].get("prompt_tokens"),
        result["usage"].get("completion_tokens"),
    )
    return result["text"]


def classify_intent(question, history):
    """Return "retrieve" or "history". Failure → "retrieve" (safe default)."""
    instructions = """You triage study-assistant questions. Decide what the NEW question needs:
- if answering it requires the study document passages, reply with a line starting "RETRIEVE:" then the question rewritten to stand alone.
- if it is about the conversation itself (a comment, a clarification on what was said, or a request to explain earlier wording), reply with a line starting "HISTORY:" then the question rewritten to stand alone.
Always answer the fact or comment in Tetum. Reply with exactly one line."""
    examples = """Question: Saida mak presiza pasajen sira?
Answer: RETRIEVE: Saida mak presiza pasajen sira?

Question: Tanba sa o la temi kona ba metodu TOPSIS ohin?
Answer: HISTORY: Tanba sa ita la hetan informasaun kona-ba TOPSIS ohin?"""

    try:
        answer = _router_answer(
            build_router_messages(question, history, instructions, examples)
        )
    except Exception as exc:
        logger.warning("router failed; defaulting to retrieval (%s)", exc)
        return "retrieve"

    return "history" if _HISTORY_MARK in answer else "retrieve"


def rewrite_standalone(question, history):
    """Return a self-contained question; any failure returns the original."""
    instructions = """Rewrite the NEW question so it stands alone for document search:
carry over the specific topic implied by the conversation (pronouns like
"this", "that", "it" name a prior topic — say what it actually is). Reply with
only the rewritten question in Tetum."""
    examples = """Question: Saida mak TOPSIS?
Answer: Saida mak metodu TOPSIS iha desizaun multi-kriteriu?

Question: What did you use for its weights?
Answer: Saida mak peso ne'ebé ita uza ba kriteriu TOPSIS?"""

    try:
        answer = _router_answer(
            build_router_messages(question, history, instructions, examples)
        )
    except Exception as exc:
        logger.warning("rewriter failed; using the raw question (%s)", exc)
        return question

    rewritten = re.sub(rf"^(?:({_RETRIEVE_MARK})|({_HISTORY_MARK}))\s*", "", answer).strip()
    return rewritten or question


def route_question(question, history):
    """Full pre-retrieval step: returns ("intent", question-to-search)."""
    intent = classify_intent(question, history)
    if intent == "retrieve":
        return intent, rewrite_standalone(question, history)
    return intent, question
