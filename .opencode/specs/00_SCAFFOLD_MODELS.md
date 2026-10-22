# SPEC 00 — Django scaffold + data models (all five apps)

Status: **AWAITING SPEC_APPROVED (v2 — apps/ layout added Oct 22)**
Date: Oct 22, 2026
Scope trace: PRD § 3 (must-haves), § 5 (QA flow step 1), § 6 (stack), § 8 (status values) · DB contract: `docs/DATABASE.md` § 1–3 (D1–D8)

## What this spec covers

The skeleton only: Django project config, the five apps, **all 9 database models** with indexes and constraints, migrations, the Postgres dev environment (docker-compose + `.env.example`), and a verification checklist. No views, no HTMX, no SSE, no worker tasks, no LLM adapter — those get their own specs next.

## 1. Components to create

Layout mirrors EC-Backlog-Management conventions (v2 of this spec, Oct 22): **apps live under an `apps/` package**, templates at `./templates`, static at `./static`. Module path is `apps.<name>`; each AppConfig sets `name = "apps.<name>"`, `label = "<label>"` — labels stay bare (accounts/documents/qa/llm/rag), so DB table names (`accounts_profile`, `documents_document`, ...) are unchanged from v1.

```text
manage.py                      (created by startproject, kept as-is)
config/                        __init__.py, settings.py (single file, NOT EC's settings/ package — simpler until needed),
                               urls.py (minimal: admin only), wsgi.py
apps/                          __init__.py (empty package marker)
  accounts/                    Profile model + admin registration; apps.py: AppsConfig(name="apps.accounts", label="accounts")
  documents/                   Document, Page, Chunk + admin registration; label="documents"
  qa/                          Conversation, Message, MessageSource, StudyQuestion + admin registration; label="qa"
  llm/                         UsageRecord + admin registration; label="llm" (adapter module comes in a later spec)
  rag/                         NO models — service-layer package: __init__.py only (later spec)
templates/                     (empty this spec — populated by spec 04)
static/                        (empty this spec — HTMX vendor file lands in spec 04)
docker-compose.yml             one service: postgres (pgvector/pgvector:pg17), port 5432, named volume
.env.example                   DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT/DJANGO_SECRET_KEY/DJANGO_DEBUG + placeholders
```

## 2. Database schema changes

**Contract: `docs/DATABASE.md` § 3, decisions D1–D8.** The spec restates only Django-realisation details; if anything below disagrees with DATABASE.md, DATABASE.md wins and it is reported as a bug.

| Model (app) | Key fields (types) | Constraints & indexes |
|---|---|---|
| `Profile` (accounts) | `user` OneToOne, `daily_question_limit` IntegerField null | signal-created on user creation; `settings.DEFAULT_DAILY_QUESTION_LIMIT` default |
| `Document` (documents) | `user` FK PROTECT, `title` Char(300), `uploaded_file` FileField(`documents/%Y/%m/`), `file_type` Char choices pdf/docx/txt, `page_count` Int null, `status` Char TextChoices processing/ready/failed (default processing), `failure_reason` Char null, `embedding_model` Char(120) null, `embedding_dim` Int null, `summary_text` Text null, `summary_created_at` DateTime null, timestamps | index `(user, -created_at)` |
| `Page` (documents) | `document` FK CASCADE, `number` Int, `text` Text, `is_scanned` Bool, `ocr_used` Bool, `char_count` Int | unique `(document, number)` |
| `Chunk` (documents) | `document` FK CASCADE, `page_number` Int, `order_index` Int, `text` Text, `token_count` Int, `embedding` pgvector `VectorField`, dims set at migration-generation time per D2 freeze,  `search_vector` SearchVectorField | unique `(document, order_index)`; index `(document, page_number)`; HNSW on `embedding` (vector_cosine_ops, library defaults); GIN on `search_vector` (db_index) |
| `Conversation` (qa) | `document` FK CASCADE, `user` FK PROTECT, `created_at` auto | index `(user, document)` |
| `Message` (qa) | `conversation` FK CASCADE, `seq` Int, `role` Char TextChoices user/assistant, `content` Text, `supported` Bool null, `rewritten_text` Text null, `created_at` auto | unique `(conversation, seq)` (per-connection writes serialized by the ask view later — DATABASE.md § 4.2 step 2) |
| `MessageSource` (qa) | `message` FK CASCADE (assistant rows only, enforced in app code), `chunk` FK PROTECT, `page` Int, `excerpt` Text (280+… rule), `order` Int | index `(message, order)` |
| `StudyQuestion` (qa) | `document` FK CASCADE, `order` Int, `question` Text, `answer` Text, `page` Int | unique `(document, order)` |
| `UsageRecord` (llm) | `user` FK null, `document` FK null, `message` FK null, `purpose` Char TextChoices ask/rewrite/summary/study_questions/ingest_embedding/query_embedding, `provider` Char, `model` Char, `prompt_tokens` Int, `completion_tokens` Int, `latency_ms` Int, `cost_usd` Numeric(10,6), `created_at` auto | index `(user, created_at)`, `(document)` |

Notes fixed by existing decisions (no new decisions made here):
- `Chunk.embedding` per D2: single typed `VectorField`; dimension value comes from the `EMBEDDING_MODEL` env var already in settings (SEA-LION default); the dimension constant is set in code from settings so model name and dims travel together. The empirical freeze happens at the first real embedding run (later spec), and this migration is regenerated then if needed — no silent change.
- `search_vector` is filled during ingestion only (D8: `to_tsvector('simple', ...)`). For THIS spec it may remain null/empty — populating is the ingestion spec's job.

## 3. I/O payloads

None in this spec — no views exist. Admin UI only (model registrations), which counts as x-internal tooling for the team.

## 4. Edge cases handled at model level

- No user → no Documents (FK PROTECT prevents accidental user deletion; CASCADE cleans owned data).
- Empty values everywhere legal: Document before processing has null page_count/failure_reason; Message with null supported (user rows); Chunk with null/zero search_vector pre-ingestion.
- `.env` missing → settings fail fast with a clear `DJANGO_SECRET_KEY` KeyError (no silent defaults).
- `(conversation, seq)` collisions are structurally impossible at DB level (unique constraint) even though the lock arrives later with the ask flow.

## 5. Verification checklist (definition of done)

1. `docker compose up -d` → Postgres + pgvector healthy on :5432
2. `uv run python manage.py makemigrations accounts documents qa llm` → clean initial migrations
3. `uv run python manage.py migrate` on the compose database → all 9 tables created, pgvector extension loaded
4. `uv run python manage.py check` → no warnings
5. `uv run pytest` → one smoke test per skill (django-db-integrity + django-tdd-loop): create user→Document→Page→Chunk(with small vector)→Conversation→Message→MessageSource→UsageRecord in one transaction, assert row roundtrip + one unique-constraint violation raised on duplicate `(conversation, seq)`
6. `.gitignore` confirmed to still exclude `.env`; compose file has no secrets

## Out of scope (later specs)

Upload view + ingestion worker + chunking (spec 01), LLM adapter (spec 02), ask view + SSE + rewrite (spec 03), template/HTMX shell (spec 04), summary/study-questions (spec 05), quota enforcement in views (spec 05b).
