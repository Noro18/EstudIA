from dataclasses import dataclass

from django.contrib.postgres.search import SearchQuery, SearchRank
from pgvector.django import CosineDistance

from apps.documents.models import Chunk, Document

from .embeddings import embed_query


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document: str
    page: int
    text: str
    excerpt: str
    similarity: float


@dataclass(frozen=True)
class KeywordMatch:
    chunk_id: int
    document_id: int
    document: str
    page: int
    text: str
    excerpt: str
    score: float


@dataclass(frozen=True)
class HybridMatch:
    chunk_id: int
    document_id: int
    document: str
    page: int
    text: str
    excerpt: str
    vector_rank: int | None
    keyword_rank: int | None
    fused_score: float


def rrf_score(vector_rank: int | None, keyword_rank: int | None) -> float:
    score = 0.0
    if vector_rank is not None:
        score += 1 / (60 + vector_rank)
    if keyword_rank is not None:
        score += 1 / (60 + keyword_rank)
    return score


def fuse_ranked_chunks(
    vector_chunks: tuple[RetrievedChunk, ...],
    keyword_chunks: tuple[KeywordMatch, ...],
    *,
    limit: int = 8,
) -> tuple[HybridMatch, ...]:
    merged = {}
    for rank, chunk in enumerate(vector_chunks, start=1):
        merged[chunk.chunk_id] = {
            "chunk": chunk,
            "vector_rank": rank,
            "keyword_rank": None,
        }
    for rank, chunk in enumerate(keyword_chunks, start=1):
        row = merged.setdefault(
            chunk.chunk_id,
            {"chunk": chunk, "vector_rank": None, "keyword_rank": None},
        )
        row["keyword_rank"] = rank

    matches = []
    for row in merged.values():
        chunk = row["chunk"]
        matches.append(
            HybridMatch(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document=chunk.document,
                page=chunk.page,
                text=chunk.text,
                excerpt=chunk.excerpt,
                vector_rank=row["vector_rank"],
                keyword_rank=row["keyword_rank"],
                fused_score=rrf_score(row["vector_rank"], row["keyword_rank"]),
            )
        )
    matches.sort(key=lambda match: (-match.fused_score, match.chunk_id))
    return tuple(matches[:limit])


def retrieve_vector_chunks(
    question: str,
    notebook_id: int,
    *,
    limit: int = 8,
    embedder=embed_query,
) -> tuple[RetrievedChunk, ...]:
    query_vector = embedder(question)
    chunks = (
        Chunk.objects.filter(
            document__notebook_id=notebook_id,
            document__status=Document.Status.READY,
            embedding__isnull=False,
        )
        .annotate(distance=CosineDistance("embedding", query_vector))
        .select_related("document")
        .order_by("distance", "pk")[:limit]
    )
    return tuple(
        RetrievedChunk(
            chunk_id=chunk.pk,
            document_id=chunk.document_id,
            document=chunk.document.title,
            page=chunk.page_number,
            text=chunk.text,
            excerpt=chunk.text[:280],
            similarity=1.0 - float(chunk.distance),
        )
        for chunk in chunks
    )


def retrieve_keyword_chunks(
    question: str,
    notebook_id: int,
    *,
    limit: int = 20,
) -> tuple[KeywordMatch, ...]:
    query = SearchQuery(question.strip(), config="simple")
    chunks = (
        Chunk.objects.filter(
            document__notebook_id=notebook_id,
            document__status=Document.Status.READY,
            search_vector__isnull=False,
        )
        .annotate(keyword_score=SearchRank("search_vector", query))
        .filter(keyword_score__gt=0)
        .select_related("document")
        .order_by("-keyword_score", "pk")[:limit]
    )
    return tuple(
        KeywordMatch(
            chunk_id=chunk.pk,
            document_id=chunk.document_id,
            document=chunk.document.title,
            page=chunk.page_number,
            text=chunk.text,
            excerpt=chunk.text[:280],
            score=float(chunk.keyword_score),
        )
        for chunk in chunks
    )


def retrieve_hybrid_chunks(
    question: str,
    notebook_id: int,
    *,
    final_limit: int = 8,
    candidate_limit: int = 20,
    embedder=embed_query,
) -> tuple[HybridMatch, ...]:
    vector_chunks = retrieve_vector_chunks(
        question,
        notebook_id,
        limit=candidate_limit,
        embedder=embedder,
    )
    keyword_chunks = retrieve_keyword_chunks(
        question,
        notebook_id,
        limit=candidate_limit,
    )
    return fuse_ranked_chunks(vector_chunks, keyword_chunks, limit=final_limit)
