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
