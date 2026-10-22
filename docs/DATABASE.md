# StudIA — Database design

The single source of truth for what the database stores and why. Contract source: `docs/StudIA — Product Requirements Document (v2).md` (below: "PRD"). If SQL and this document disagree, it is a bug: report it, do not silently pick one.

App layout follows the approved structure: `documents`, `qa`, `llm`, `rag` (service layer, no tables), `accounts` (thin profile).

---

## 1. Decisions (final)

| # | Decision | Value | Reason |
|---|---|---|---|
| D1 | Page table | **Keep** | OCR detection, re-chunking without re-OCR, citation sanity (PRD § 5 step 2) |
| D2 | Embedding model / dimensions | **One model: `EMBEDDING_MODEL` env var (default SEA-LION-ModernBERT-300M), dim frozen empirically** at first embedding run, then never changed silently | AGENTS.md rule: query embedding must use the same model/dims as stored chunks; PRD § 9.4 |
| D3 | Quota limits | **On `Profile` (per-user)**, default falls back to settings | PRD "per-user usage limits" (must-have 3, RNF07); allows per-user overrides + admin demo controls |
| D4 | Rewrite calls | **Always rewrite when the conversation has history; rewritten text stored; counts toward quota** | PRD § 5 step 4; § 9 cost discipline (a real API call is a real cost row) |
| D5 | Chat history storage | **Normalized `Message` rows** (never JSON blobs on Conversation) | FK integrity for citations, `supported`/`rewritten_text` per bubble, ordered reads (§ 8 ask contract) |
| D6 | Summary storage | **Columns on Document** (`summary_text`, `summary_created_at`), regenerate only when `NULL` or user forces | PRD: "generate once per document and cache" |
| D7 | Answer-prompt history budget | **Sliding window: keep the newest messages under `HISTORY_TOKEN_BUDGET` (default 2,500 tokens), drop the rest; history shrinks before retrieved chunks** | caps per-turn cost/latency growth and attention dilution; document facts are never carried in history — chunks are re-retrieved fresh every ask (§ 4.2) |

---

## 2. Entity overview

```text
User (Django auth) ──1:1──> Profile
      │
      └─owns─> Document ──1:N──> Page           (extracted text per page)
      │             │    └─1:N──> Chunk         (RAG atom: text + vector + tsvector)
      │             │    └─sum──> [columns]     (cached summary)
      │             │    └─1:N──> StudyQuestion (cached generated Q&A)
      │             └─1:N──> Conversation ──1:N──> Message ──1:N──> MessageSource ──N:1──> Chunk
      └─fuels─> UsageRecord                    (cost/quota ledger, one row per LLM call)
```

Rules enforced by shape:

- A **Conversation belongs to exactly one Document** (no multi-document chat — PRD scope; § 8 `ask` takes an optional `conversation_id`).
- **Citations are never free text**: the UI reads `MessageSource` rows only; the model's chunk numbers are validated against supplied chunks before any row is written (PRD § 5 step 8).
- **Every LLM call = one `UsageRecord` row.** Quota checking is `COUNT(UsageRecord WHERE user=today)` — no counters, no race conditions beyond the count being eventually consistent.

---

## 3. Tables in detail

### `documents.Document`

One uploaded file.

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto PK | used in all URLs (`/documents/{id}/`) |
| `user` | FK User, `PROTECT` | per-user isolation (PRD § 4 B; listing is per-user) |
| `title` | CharField(300) | human-readable (file stem at upload) |
| `uploaded_file` | FileField(upload_to=`documents/%Y/%m/`) | original bytes preserved |
| `file_type` | CharField (`pdf`/`docx`/`txt`) | drives the extractor; `unsupported_type` error if not in whitelist |
| `page_count` | IntegerField, null until processing finishes | surfaced in detail view (PRD § 8) |
| `status` | CharField, choices: `processing` / `ready` / `failed`, default `processing` | PRD § 8 — exactly these values |
| `failure_reason` | CharField, null | e.g. `scanned_no_text` (PRD § 8) |
| `embedding_model` | CharField(120), null until ready | D2: query-side model must match; details view exposes it |
| `embedding_dim` | IntegerField, null until ready | D2 |
| `summary_text` | TextField, null | D6 cached Tetum summary |
| `summary_created_at` | DateTimeField, null | D6 |
| `created_at`, `updated_at` | auto timestamps | |

Indexes: `(user, -created_at)` for the library list; `uploaded_file` served by MEDIA storage, not DB.

### `documents.Page`

One extracted page (D1). Source of truth for "what did page N say".

| Field | Type | Notes |
|---|---|---|
| `document` | FK Document, CASCADE | |
| `number` | IntegerField | 1-based; `unique_together (document, number)` |
| `text` | TextField | post-extraction, post-OCR |
| `is_scanned` | BooleanField | no extractable text layer detected |
| `ocr_used` | BooleanField | OCR (Tesseract pt/en/id) actually produced this text |
| `char_count` | IntegerField | cheap QA metric for the `scanned_no_text` decision |

Indexes: `(document, number)` unique — doubles as the lookup index.

### `documents.Chunk`

The retrieval atom. Written only during ingestion; never modified after `ready`.

| Field | Type | Notes |
|---|---|---|
| `document` | FK Document, CASCADE | |
| `page_number` | IntegerField | citation metadata (never from model output) |
| `order_index` | IntegerField | chunk order within the document; `unique_together (document, order_index)` |
| `text` | TextField | the chunk content (~300-600 tokens, overlap per PRD § 4 C) |
| `token_count` | IntegerField | honest size for prompt budgeting |
| `embedding` | VectorField(**NULLABLE until D2 dim frozen**), then NOT NULL | pgvector; HNSW index |
| `search_vector` | SearchVectorField | Postgres full-text index; GIN index; updated at chunk creation |

Indexes:
- `HNSW (embedding vector_cosine_ops)` — vector half of hybrid retrieval (PRD § 6)
- `GIN (search_vector)` — keyword half (Postgres FTS, PRD § 6)
- `(document, page_number)` — citation assembly and per-document chunk fetch

### `qa.Conversation`

One chat session = one document (D5).

| Field | Type | Notes |
|---|---|---|
| `document` | FK Document, CASCADE | |
| `user` | FK User | ownership check on every ask |
| `created_at` | auto | |

Indexes: `(user, document)` for listing a document's conversations.

### `qa.Message`

One bubble. `role=user` and `role=assistant` rows alternate.

| Field | Type | Notes |
|---|---|---|
| `conversation` | FK Conversation, CASCADE | |
| `seq` | IntegerField | dense ordering **within the conversation** (1, 2, 3...); enforced unique per conversation in ` save()`; history reads are `conversation.messages.order_by("seq")` |
| `role` | CharField (`user`/`assistant`) | |
| `content` | TextField | the markdown source text as produced/consumed |
| `supported` | BooleanField, null | `null` for user rows; True/False on assistant rows — drives the honest `supported: false` UI state (PRD § 5 step 8) |
| `rewritten_text` | TextField, null | D4 — the standalone rewritten question that actually went to retrieval; user rows only; stored for debugging + eval, never shown |
| `created_at` | auto | |

Indexes: `(conversation, seq)` unique — doubles as the history-scan index.

Reads of history for the answer prompt always pass through the D7 sliding-window budget (settings env `HISTORY_TOKEN_BUDGET`; see § 4.2 step 5). The rewrite step reads a fixed small tail (last 6 messages) and is not budgeted.

One memory, two readers, no duplication: the Message table is the only store of chat history; the answer prompt (sliding window) and the rewrite step (fixed last-6 tail) each read a slice of the same rows. No feature may copy history into a second store — D5's normalized rows plus `seq` ordering exist precisely so slices can be derived at read time.

### `qa.MessageSource`

One citation row per chunk the answer used. Written **only** after validation against supplied chunk ids (PRD § 5 step 8).

| Field | Type | Notes |
|---|---|---|
| `message` | FK Message (assistant), CASCADE | |
| `chunk` | FK Chunk, `PROTECT` | citations keep working even if chunks are ever cleaned up |
| `page` | IntegerField | snapshot from chunk metadata |
| `excerpt` | TextField | snapshot (first N chars) — the UI shows this, not `chunk.text` |
| `order` | IntegerField | display order of citations |

Indexes: `(message, order)`.

### `qa.StudyQuestion`

Generated study Q&A banking (must-have 2; `POST /documents/{id}/study-questions/`).

| Field | Type | Notes |
|---|---|---|
| `document` | FK Document, CASCADE | |
| `order` | IntegerField | |
| `question` | TextField | Tetum |
| `answer` | TextField | Tetum |
| `page` | IntegerField | citation-ish reference for study mode |

Indexes: `(document, order)` unique. Regeneration = delete rows for the document, insert new set inside one transaction.

### `llm.UsageRecord`

The cost ledger (PRD § 7: "every call logs tokens, latency, cost") and the quota counter (RNF07, D3).

| Field | Type | Notes |
|---|---|---|
| `user` | FK User, null allowed | ingestion-time embedding has no chat user |
| `document` | FK Document, null | links a call to the document it served |
| `message` | FK Message, null | links an ask/rewrite call to its bubble |
| `purpose` | CharField: `ask` / `rewrite` / `summary` / `study_questions` / `ingest_embedding` / `query_embedding` | exactly these tokens; adapter sets it |
| `provider`, `model` | CharField | what actually served (fallbacks visible) |
| `prompt_tokens`, `completion_tokens` | IntegerField | § 7 requirement |
| `latency_ms` | IntegerField | § 7 requirement |
| `cost_usd` | NumericField(10, 6) | estimated; price table in the adapter, updated per provider |
| `created_at` | auto | quota window = calendar day (Asia/Dili) |

Indexes: `(user, created_at)` — the quota query; `(document,)` for per-demo-document cost checks (§ 9 table).

### `accounts.Profile`

| Field | Type | Notes |
|---|---|---|
| `user` | OneToOne User, PK-adjacent | |
| `daily_question_limit` | IntegerField, null | `null` → falls back to `settings.DEFAULT_DAILY_QUESTION_LIMIT`; demo accounts can be raised/lowered live |

---

## 4. Flows

### 4.1 Ingestion (player: worker via django-q2)

```text
upload view:  create Document(status=processing) → enqueue task → return id + status
worker task:
  1. extract text per page
       - PDF: PyMuPDF text layer
       - page with no text layer → OCR (Tesseract pt/en/id)
       - OCR yields < threshold chars on ALL pages → status=failed, reason=scanned_no_text
       - unsupported/corrupt file → status=failed, reason=unsupported_type
  2. write Page rows (number, text, is_scanned, ocr_used, char_count)
  3. chunk: ~300-600 tokens, overlap (same algorithm as experiments/studia_rag → promoted into rag/)
  4. embed chunks (query-embed model + dim) → UPDATE document.embedding_model/embedding_dim (D2)
  5. write Chunk rows: text, page_number, order_index, embedding, search_vector
  6. status=ready, page_count set; on unhandled error → status=failed (+reason UsageRecord failure logged)
usage: ingest_embedding rows land in UsageRecord (cost of pre-embedding demo docs, PRD § 9.4)
```

Failure contract: `Document` rows always transition `processing → ready | failed`; nothing else. Views keyed on exact PRD § 8 tokens.

### 4.2 Ask (player: request; streaming via SSE)

```text
POST /documents/{id}/ask/  (question, conversation_id?, stream?)
  1. resolve Document: user-ownership + status checks first
       - not ready  → error fragment document_not_ready
       - failed     → error fragment document_failed
  2. resolve Conversation:
       - conversation_id given → fetch (re-validate owner+document) else create new (D5: fresh folder)
  3. rewrite step (only if this conversation already has messages — PRD § 5 step 4):
       - standalone = llm.generate(prompt=REWRITE, history=last 6 Messages, question)  [non-stream]
       - Message(role=user, seq=next, content=question, rewritten_text=standalone)
       - UsageRecord(purpose=rewrite)
       (first question in a conversation: standalone = question, no call, same Message rows)
  4. hybrid retrieval on `standalone` (rag/ service):
       - vector: cosine top-k over embedding HNSW (model+dim match check per D2)
       - keyword: tsquery over chunk.search_vector
       - rank fusion (RRF default) → top N chunks ordered by relevance
  5. prompt build (PRD § 5): English instructions, numbered top-N chunks, history+standalone,
       2-3 Tetum few-shot examples; instruction to answer in Tetum markdown and to cite
       only chunk numbers from the numbered list, or to say plainly it is not supported
       - history enters under the D7 sliding window: walk Messages newest → oldest,
         include until HISTORY_TOKEN_BUDGET (default 2,500 tokens, cheap estimator ok)
         is hit, drop the rest
       - when over budget: shrink history first → then reduce top-k (never below top-3
         without a logged note); if the prompt would still exceed model max context:
         truncate history to 0, reduce top-k, and mark the ask UsageRecord row
         (note=ctx_truncated) so overflow is visible in the § 9 cost table
  6. stream (SSE) llm.generate(prompt, stream=True):
       - each chunk → accumulate text → mistune render-so-far (escaped) → SSE event
       - UsageRecord(purpose=ask) finalized at stream end with real token counts
  7. on finish: parse model's used-chunk numbers → validate ⊆ supplied ids (PRD § 5 step 8)
       - assistant Message: seq next, content=full text, supported=any_citations | model said unsupported
       - MessageSource row per validated chunk (page/excerpt snapshot from chunk)
       - if no valid citation + model said unsupported → supported=False, zero MessageSource rows
       - conversation_id handed back to the client for follow-ups
```

Post-condition invariant: for any assistant message, `supported=True ⇒ count(MessageSources) ≥ 1`; citations shown in UI come from those rows only — never parsed from `content`.

### 4.3 Summary (map–reduce, cached)

```text
POST /documents/{id}/summary/
  - Document.summary_text set (+created_at) → return cached fragment, no LLM call
  - else: sections per Page run (map) → combined to Tetum summary (reduce)
      UsageRecord(purpose=summary); write summary_text + summary_created_at (D6)
```

### 4.4 Study questions

```text
POST /documents/{id}/study-questions/ body: count
  - if StudyQuestion rows exist for this document → serialize cached rows
  - else LLM generates (mirror of summary's map-reduce over top-level structure)
      UsageRecord(purpose=study_questions); persist count rows with page refs
```

### 4.5 Quota + rate limiting (RNF07)

```text
before every ask / summary / study_questions request:
  limit = profile.daily_question_limit ?? settings.DEFAULT_DAILY_QUESTION_LIMIT
  used  = COUNT(UsageRecord WHERE user=? AND created_at=today AND purpose IN (ask, rewrite, summary, study_questions))
  used >= limit → error fragment rate_limited (PRD § 8 code list)
```

---

## 5. Not modeled on purpose

| Excluded | Why |
|---|---|
| Multi-document conversations | PRD optional-scope-out (line 51); Conversation is pinned to one Document |
| JSON message blob on Conversation | D5; FK integrity + per-bubble flags win |
| Per-user document quotas (separate table) | RNF07 asks usage limits, not storage limits; revisit only if the PRD grows |
| Separate Summary/LLMLog tables | D6 + single-lens UsageRecord |
