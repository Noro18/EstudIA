from functools import lru_cache

from django.conf import settings


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.EMBEDDING_MODEL, device="cpu")


def embed_query(question: str) -> list[float]:
    question = question.strip()
    if not question:
        raise ValueError("Question must not be empty.")

    vector = _get_model().encode([question], normalize_embeddings=True)[0]
    vector = vector.tolist()
    if len(vector) != settings.EMBEDDING_DIM:
        raise ValueError(
            f"Embedding dimension {len(vector)} does not match configured "
            f"dimension {settings.EMBEDDING_DIM}."
        )
    return vector
