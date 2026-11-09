from django.conf import settings

from apps.llm.adapter import build_adapter
from apps.rag.router import estimate_tokens


def build_grounded_messages(question, matches, history=None):
    """Compose the grounded prompt: history block, passages, then the question.

    The answer must stay grounded in the passages — history is context for the
    user's wording, never a citation source (spec 12, decision C2; the citation
    hard rule is unchanged).
    """
    if not matches:
        raise ValueError("At least one retrieved chunk is required.")

    passages = "\n\n".join(
        f"[Chunk {index}]\n{match.text}"
        for index, match in enumerate(matches, start=1)
    )
    history_block = _history_block(history)
    prompt = f"""You are a friendly study assistant for students in Timor-Leste.
Answer in simple Tetum.

How to answer:
1. Start with a clear definition (1-2 sentences).
2. Explain in detail, step by step, using simple words.
3. Give at least one real-life example or analogy that a student can imagine.
4. End with a short summary.
Write a thorough answer, like a patient teacher. Do not be too brief.

Rules:
- Base the answer on the supplied passages. Use them as the main source.
- You may add simple explanations or examples to make the passages easier to understand, but never contradict the passages.
- If the passages do not support the answer, say that you do not find the answer.
- At the end, list the chunk numbers you used as: Used chunks: [1, 2].

Example of the style (do not copy the content):
Question: Saida mak tema prinsipal?
Answer: Tema prinsipal mak ideia ne'ebé esplika iha pasajen. Atu komprende di'ak liu, hanoin ba ida ne'e hanesan ... (analogia/ezemplu). Iha pasajen, ita haree katak ... (esplikasaun detallu). Resumu: ...
Used chunks: [1]

Question: Informação kona-ba buat ne'ebé la iha iha pasajen?
Answer: Ha'u la hetan resposta apoiadu iha pasajen sira.

{history_block}Passages:
{passages}

Question: {question}
"""
    return [{"role": "user", "parts": [{"text": prompt}]}]


def _history_block(history):
    """Render prior turns as context, trimmed to HISTORY_TOKEN_BUDGET.

    Trim drops the OLDEST turns first (newest context matters most). Uses the
    chars/4 estimator from spec 12 decision C4 — no tokenizer dependency.
    """
    if not history:
        return ""

    kept = []
    used = 0
    for turn in reversed(history):
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        size = estimate_tokens(content)
        if used + size > settings.HISTORY_TOKEN_BUDGET:
            break
        kept.append((turn.get("role", "user"), content))
        used += size
    kept.reverse()

    rendered = "\n\n".join(
        f"{role.capitalize()}: {content}" for role, content in kept
    )
    return f"Previous conversation (for context only):\n{rendered}\n\n"


def generate_grounded_answer(question, matches, *, adapter=None, stream=False):
    adapter = adapter or build_adapter()
    messages = build_grounded_messages(question, matches)
    return adapter.generate(messages, stream=stream)
