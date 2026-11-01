import pytest

from apps.rag.retrieval import (
    KeywordMatch,
    RetrievedChunk,
    fuse_ranked_chunks,
    rrf_score,
)


def _vector_match(chunk_id):
    return RetrievedChunk(chunk_id, 1, "Document", 1, f"text {chunk_id}", f"text {chunk_id}", 0.9)


def _keyword_match(chunk_id):
    return KeywordMatch(chunk_id, 1, "Document", 1, f"text {chunk_id}", f"text {chunk_id}", 1.0)


def test_rrf_score_adds_both_rank_contributions():
    assert rrf_score(1, 1) == pytest.approx(2 / 61)


def test_fusion_deduplicates_and_prioritizes_shared_chunks():
    results = fuse_ranked_chunks(
        (_vector_match(1), _vector_match(2)),
        (_keyword_match(2), _keyword_match(3)),
        limit=3,
    )

    assert [result.chunk_id for result in results] == [2, 1, 3]
    assert results[0].vector_rank == 2
    assert results[0].keyword_rank == 1
