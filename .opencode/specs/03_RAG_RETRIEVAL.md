# SPEC 03 — Notebook-scoped hybrid RAG retrieval

Status: **DRAFT — awaiting user approval**  
Date: October 26, 2026  
Scope trace: PRD § 3 (retrieval and source tracking), § 5 (QA flow steps 2, 5, and 8), § 6 (pgvector + PostgreSQL full-text search), § 10 (retrieval evaluation)  
Database trace: `docs/DATABASE.md` D2, D8, D9 and § 3–4  

## 1. Objective

Build the retrieval service that selects relevant document chunks for a future grounded answer. A question is embedded with the same local embedding model used during ingestion, compared with stored chunk vectors in pgvector, searched with PostgreSQL full-text search, and merged into one ranked result list.

The service is Notebook-scoped: it searches chunks from every `ready` document in the selected Notebook, never an entire document as one vector. It returns stored metadata so the later QA flow can build citations from database records rather than trusting model-generated citation text.

This specification covers runtime retrieval and retrieval evaluation. It does not implement prompt construction, LLM generation, citation persistence, SSE, OCR, or the ask view.

## 2. Current state and gaps

- `documents.Chunk` already stores `embedding`, `search_vector`, `page_number`, `text`, and its parent `Document`.
- Ingestion already creates normalized local embeddings and populates the keyword index.
- `apps.rag` is currently an empty service-layer app with no retrieval implementation.
- The QA view currently sends conversation content directly to Gemini and does not retrieve chunks.
- The query side must reuse `settings.EMBEDDING_MODEL` and `settings.EMBEDDING_DIM`; changing this pair silently is forbidden by DATABASE.md D2.

## 3. Selected decisions

| Decision | Selected value |
|---|---|
| Retrieval scope | All `ready` documents belonging to the requested Notebook |
| Query embedding | Same configured local model and dimension as ingestion |
| Runtime interface | Typed Python result objects |
| Vector candidates | Top 20 |
| Keyword candidates | Top 20 |
| Final results | Top 8 |
| Keyword matching | PostgreSQL `simple` configuration with AND-matched terms |
| Rank fusion | Reciprocal-rank fusion, `1 / (60 + rank)` |
| No matches | Empty typed result, not an operational error |
| Evaluation format | Versioned JSONL benchmark |
| Evaluation modes | Vector-only, keyword-only, and hybrid |

## 4. Runtime interface

The retrieval service will expose a Python interface similar to:

```python
results = retrieve(
    question="Saida mak ideia prinsipál?",
    notebook_id=notebook_id,
    user=user,
)
```

The public service must return typed objects, not raw model instances or model-generated citation strings:

```python
@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document: str
    page: int
    text: str
    excerpt: str
    vector_rank: int | None
    keyword_rank: int | None
    fused_score: float


@dataclass(frozen=True)
class RetrievalResult:
    question: str
    chunks: tuple[RetrievedChunk, ...]
```

`document` is the stored document title. `page`, `text`, and `excerpt` are read from stored chunk/document metadata. The model is not allowed to supply or override any of these fields.

The service accepts optional dependency injection for the embedding function so tests and evaluation can use deterministic vectors without loading the model. Runtime defaults are:

```python
retrieve(question, notebook_id, *, user=None, embedder=None, final_k=8)
```

`final_k` may be overridden by evaluation code, but the production default is 8. Candidate depth remains 20 for each retrieval leg unless an explicit evaluation call selects another value.

## 5. Retrieval behavior

### 5.1 Query embedding

1. Validate that the question is non-empty after trimming.
2. Embed the question with `settings.EMBEDDING_MODEL`.
3. Normalize the query vector in the same way as ingestion.
4. Reject or exclude stored documents whose `embedding_model` or `embedding_dim` does not match the configured pair.
5. Do not send the query to a hosted embedding provider.

Local query embeddings do not count toward the hosted LLM quota. When a caller supplies user context, the service records the local operation as `UsageRecord.purpose = query_embedding`; evaluation calls may omit user context.

### 5.2 Candidate scope

The base queryset must:

- join `Chunk` to `Document`;
- filter `Document.notebook_id = notebook_id`;
- filter `Document.status = ready`;
- exclude null embeddings for vector search;
- use only documents whose stored embedding model/dimension match the configured pair.

Ownership is validated by the caller/view before invoking this service. The service must not broaden the Notebook scope supplied by the caller.

### 5.3 Vector search

Use pgvector cosine distance against the `Chunk.embedding` HNSW index. Convert the ordered vector candidate list into one-based ranks from 1 through 20.

### 5.4 Keyword search

Use `Chunk.search_vector`, which ingestion builds with PostgreSQL’s `simple` configuration. Normalize the question into PostgreSQL full-text terms and require all terms to match. Order candidates by PostgreSQL relevance and assign one-based ranks from 1 through 20.

### 5.5 Rank fusion

For each chunk appearing in either candidate list, calculate:

```text
fused_score = 1 / (60 + vector_rank) if present
            + 1 / (60 + keyword_rank) if present
```

Return the eight highest-scoring unique chunks. Sort ties deterministically by ascending chunk id. A chunk present in only one retrieval leg remains eligible for the final list.

### 5.6 Empty and degraded results

- If the Notebook has no ready documents, return an empty `RetrievalResult`; the future ask layer maps this condition to `document_not_ready`.
- If ready documents exist but no keyword/vector candidates match, return an empty `RetrievalResult`; the future answer layer produces an honest unsupported response.
- If some documents are ready but have incompatible embedding metadata, exclude them and log the mismatch; compatible ready documents remain searchable.
- Retrieval must never fabricate a page, document, excerpt, or chunk id.

## 6. Evaluation harness

Add a versioned JSONL benchmark under `dataset/` or the project’s existing evaluation location. Each line represents one labeled retrieval question:

```json
{
  "id": "tetum-001",
  "question": "Saida mak ideia prinsipál husi dokumentu ne'e?",
  "language": "tet",
  "document": "Labadain-30k+.txt",
  "relevant_chunk_ids": [12, 13]
}
```

The harness must:

- load questions without changing application data;
- run vector-only, keyword-only, and hybrid retrieval against the same corpus;
- calculate recall@1, recall@3, recall@5, and recall@8;
- report per-question misses and aggregate scores;
- support Tetum, Portuguese, and English questions/documents;
- make no LLM calls.

The benchmark must contain at least 30 labeled questions before evaluation is considered complete. The initial repository currently contains only a small document set, so the harness must clearly report insufficient benchmark coverage rather than claiming a valid comparison.

## 7. Project structure

```text
apps/rag/
  embeddings.py       shared configured embedding implementation
  retrieval.py        typed runtime retrieval service and rank fusion
  tests/
    test_embeddings.py
    test_retrieval.py
    test_evaluation.py

experiments/evaluation/
  retrieval_recall.py  benchmark runner and recall@k reporting

dataset/
  retrieval_questions.jsonl  labeled retrieval questions
```

If the implementation keeps evaluation code under a different existing evaluation directory, the behavior and JSONL contract above remain unchanged.

`apps/documents/services.py` will be updated only as needed to reuse `apps.rag.embeddings`; ingestion behavior and stored vector dimensions must remain unchanged.

## 8. Code style

Use small pure functions for scoring and parsing, Django querysets for database filtering, and dependency injection for model loading:

```python
def rrf_score(vector_rank, keyword_rank):
    score = 0.0
    if vector_rank is not None:
        score += 1 / (60 + vector_rank)
    if keyword_rank is not None:
        score += 1 / (60 + keyword_rank)
    return score
```

Names should describe retrieval concepts directly: `vector_rank`, `keyword_rank`, `fused_score`, `candidate_k`, and `final_k`. Avoid embedding provider-specific or LLM-specific logic in `apps.rag`.

## 9. Testing strategy

Use the project’s existing `pytest` and `pytest-django` setup with factory_boy factories.

Unit tests must cover:

- deterministic RRF scores;
- typed result construction;
- empty results;
- deterministic tie ordering;
- injected deterministic embeddings;
- AND keyword matching.

Database tests must cover:

- Notebook isolation;
- ready versus processing/failed documents;
- vector ranking;
- keyword ranking;
- hybrid deduplication and fusion;
- incompatible model/dimension filtering;
- stored document/page/text metadata in results.

Evaluation tests must cover:

- JSONL loading;
- malformed-record validation;
- recall@k calculation;
- vector-only, keyword-only, and hybrid report generation.

Verification commands:

```bash
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest apps/rag apps/documents/tests/test_ingestion.py
uv run python experiments/evaluation/retrieval_recall.py --help
```

## 10. Boundaries

### Always do

- Follow PRD § 5 retrieval order.
- Search only ready chunks in the requested Notebook.
- Reuse the configured ingestion embedding model and dimension.
- Build result metadata from stored database fields.
- Use factory_boy for test data.
- Keep vector-only, keyword-only, and hybrid modes available for evaluation.

### Ask first

- Changing the embedding model or dimension.
- Adding a hosted embedding provider.
- Changing chunk fields, indexes, or migrations.
- Changing the RRF constant, candidate depth, final result count, or keyword semantics.
- Integrating retrieval into the ask view or LLM prompt.
- Adding dependencies.

### Never do

- Compare query vectors against whole documents instead of chunks.
- Search documents outside the selected Notebook.
- return citations invented by the model;
- silently mix incompatible embedding spaces;
- send full documents to the LLM from this retrieval service;
- commit `.env`, API keys, benchmark secrets, or generated artifacts.

## 11. Success criteria

This specification is implemented when:

1. A question can be embedded with the configured local model.
2. Retrieval searches all ready documents in one Notebook.
3. Vector and keyword candidates are both produced and fused using the selected RRF formula.
4. The service returns at most eight typed, deduplicated results with stored metadata.
5. Empty and incompatible-data cases behave as specified.
6. Runtime and database tests pass.
7. The JSONL evaluation harness reports recall@1/3/5/8 for vector-only, keyword-only, and hybrid retrieval.
8. No ask-view, LLM, SSE, OCR, or citation-persistence behavior changes as part of this spec.

## 12. Open questions

None for this retrieval slice. Changes to the selected values above require a new user decision and an update to this specification before implementation.
