from apps.llm.adapter import GeminiAdapter


def build_grounded_messages(question, matches):
    if not matches:
        raise ValueError("At least one retrieved chunk is required.")

    passages = "\n\n".join(
        f"[Chunk {index}]\n{match.text}"
        for index, match in enumerate(matches, start=1)
    )
    prompt = f"""You are a study assistant for students in Timor-Leste.
Answer in simple Tetum and use only the supplied passages.
If the passages do not support the answer, say that you do not find the answer.
At the end, list the chunk numbers you used as: Used chunks: [1, 2].

Examples:
Question: Saida mak tema prinsipal?
Answer: Tema prinsipal mak ideia ne'ebé esplika iha pasajen.

Question: Informação kona-ba buat ne'ebé la iha iha pasajen?
Answer: Ha'u la hetan resposta apoiadu iha pasajen sira.

Passages:
{passages}

Question: {question}
"""
    return [{"role": "user", "parts": [{"text": prompt}]}]


def generate_grounded_answer(question, matches, *, adapter=None, stream=False):
    adapter = adapter or GeminiAdapter()
    messages = build_grounded_messages(question, matches)
    return adapter.generate(messages, stream=stream)
