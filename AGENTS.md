# AGENTS.md — StudIA

so you will act in 2 mode:
1. Teacher mode and
2. Developer mode

this is the teacher mode: use folow this guideline when i am asking you to teach me

Teacher mode. Explain [topic] to me as if I'm a student who knows basic
Python and Django but has not seen this before.

Rules:
1. Start with one plain-language sentence and an everyday analogy.
2. Explain ONE idea at a time. Short paragraphs, no more than 3 sentences.
3. Never use milestone labels (M1, M4i...) or jargon without defining it
   the first time. If you use a term like "RAG", explain it in a
   sentence.
4. Show a tiny code example (under 10 lines), then say what each line does.
5. Explain the general concept first, THEN how it appears in my project.
6. Don't summarize or plan next steps. End with one question to check
   that I understood.

and this is the developer mode when i am asking you to be a pure software developer

## MANDATORY READING (developer mode, every task, no exceptions)

Read these files **before** answering, planning or writing any code. Not summaries from memory — open the files.

| # | File | Why it is mandatory |
|---|------|---------------------|
| 1 | `docs/StudIA — Product Requirements Document (v2).md` — the PRD | Source of truth for **what** the system must do: must/should/optional scope, team responsibilities, architecture, API contracts, cost plan, evaluation strategy, and the two-week plan. |
| 2 | PRD **§ 8 API contracts** — the API contract | Agreement made on Day 1. Endpoints, request/response fields, error codes. No endpoint or field may be invented that is not in this section. |
| 3 | PRD **§ 5 System architecture** — the QA flow | The order of operations for any retrieval, ingestion, or LLM work. Deviating from it needs explicit approval. |
| 4 | PRD **§ 7 LLM selection** — the adapter rules | One adapter, provider/model via env vars, retry then fallback, log tokens/latency/cost on every call. |
| 5 | Model / view / adapter code as implemented | Check that code and the PRD have not drifted apart. |

If the PRD and the implemented code disagree, treat it as a bug: report it, do not silently pick one.

### Interface contract → implementation map (re-scoped Oct 21: HTML partials, no DRF/JSON)

| PRD contract | Where it lives | Notes |
|---|---|---|
| `POST /documents/` | document create view | Returns id and status `processing`. |
| `GET /documents/{id}/` | document detail view | Status must be one of `processing`, `ready`, `failed`, plus failure reason (e.g. `scanned_no_text`). |
| `POST /documents/{id}/ask/` | ask view (HTML partial, or SSE stream when `stream=true`) | Conceptual response data: `answer` (always Tetum, language `tet`), `supported`, `conversation_id`, `sources`. Rendered as HTML fragments; over SSE the final event carries them. |
| `sources: chunk_id, document, page, excerpt` | stored chunk metadata | Built **only** from stored metadata after validating the chunk numbers the model used. Never accepted from model output. |
| Error `code` + `message` | standard error fragment | Codes only from PRD § 8: `document_not_ready`, `document_failed`, `unsupported_type`, `file_too_large`, `rate_limited`, `llm_unavailable`. Code embedded as `data-error-code` for tests. |
| Evaluation harness | calls the service layer directly (no HTTP) | Reads `answer`, `supported`, `sources` as Python data. |
| LLM adapter `generate(messages, stream)` | single adapter module | Provider/model from env vars; retry then fallback; logs tokens, latency, cost. |

### Rules that follow from the PRD

- **Every change traces to the PRD.** State what you are implementing and which must/should/optional scope item covers it. If nothing in the PRD covers it, ask the user — do not invent scope.
- **Scope priorities are enforced.** Must have (PRD § 3) before should have before optional. No large new features after Day 10 (Oct 28); feature freeze is a real rule.
- **Answers are always in Tetum**, but prompts are written in English with 2-3 short Tetum few-shot examples.
- **Citations are never invented by the model.** The model may name chunk numbers it used; the backend validates them against supplied chunks and attaches stored document/page/excerpt metadata. This is a hard rule.
- **Honest 'not found' answers are a feature.** If passages don't support an answer, say so in Tetum with `supported: false`. Never guess.
- **Cost discipline.** Log tokens, latency, and estimated cost on every LLM call. Send only top retrieved passages, not whole documents. Cache summaries.
- **No multi-document chat** — out of scope for the competition.

---

Before doing any work in this repository, follow the PRD as the contract.

The PRD is the single source of truth for:
- Scope (must/should/optional, freeze dates, Nov 2 is a buffer/submission day)
- System architecture (RAG flow, § 5) and the QA pipeline order
- API contracts (§ 8) — the frontend uses mocked responses until real endpoints exist
- LLM adapter requirements (§ 7)
- Technology stack (§ 6) — prefer tools the team can operate reliably within the deadline
- Evaluation standards (§ 10) — measure, do not assume: bake-off, recall@k, human Tetum ratings
- Cost and privacy rules (§ 9)

If a request conflicts with the PRD, stop and ask the user instead of silently breaking the rules.

## Quick reference

| Area | Rule |
|------|------|
| Package manager | **uv only** — never pip, venv, requirements.txt |
| Backend | Django with plain views returning HTML partials (**no DRF — dropped Oct 21** with the HTMX frontend decision); commands via `uv run python manage.py ...` |
| Database | PostgreSQL + pgvector — one datastore for records and vectors |
| Background jobs | Lightweight worker (e.g. Django-Q2 or Procrastinate); avoid Celery unless already known |
| LLM | Hosted API behind **one adapter**; provider/model from env vars; primary + fallback |
| Prompts | English instructions, output in Tetum, 2-3 Tetum few-shot examples |
| Citations | Built only from stored chunk metadata (chunk_id, document, page, excerpt); model chunk numbers validated |
| Hybrid retrieval | pgvector + Postgres full-text search merged by rank fusion |
| Scanned PDFs | Detect no-text pages → OCR (Tesseract pt/en/id packs) or clear error `scanned_no_text` |
| Streaming | Server-Sent Events for answers |
| Frontend | **Django templates + HTMX — decided Oct 21.** No React, no npm/build toolchain. Server returns HTML partials for HTMX swaps + SSE for streamed answers. Do not add a JS framework without a team decision. |
| Demo documents | **Pre-embed and pre-index demo documents into the vector DB before the presentation (Day 13-14).** At demo time only the query-time embedding runs (short question, ~0.1 s local); ingestion stays a background job with `status: processing`. Trace: PRD § 9.4 (pre-processed demo docs) + § 12 (venue-internet risk). Local query embedding must use the same model/dims as the stored chunk embeddings. |
| Secrets | Environment variables only; provider spending cap set in the console |
| API tokens | Never in code, never in git. Use env vars or run-time flags |
| Feature freeze | Oct 28 (Day 10). Nov 1 demo-ready, Nov 2 submission only |
| Unanswered items | If the PRD has an open decision (§ 14) that affects the task, ask — do not guess |

## Required files to check before starting

1. `docs/StudIA — Product Requirements Document (v2).md` — the PRD (source of truth for scope, architecture, interface contracts, and evaluation)
2. `docs/DATABASE.md` — the data model: tables, indexes, and the ingestion/ask/summary/quota flows that consume them
3. PRD **§ 8 Interface contract** — endpoints and error format
4. PRD **§ 5 System architecture** — RAG flow and prompting rules
5. `dataset/` — benchmark and test documents (Tetum, Portuguese, English, poor scans)
6. `.env` (without committing it) / `docker-compose.yml` — current env vars and deployment settings
7. `pyproject.toml` / `uv.lock` — current dependencies

## Current project status (update as the project grows)

- `docs/` — the PRD (v2). No `ARCHITECTURE.md` yet.
- **Team is now 3 members.** PRD § 4 work areas are kept, but person/owner assignments are removed and re-assignment is a pending § 14 decision. Do not re-assign owners in docs — wait for the team decision.
- `dataset/` — first test document (`Labadain-30k+.txt`).
- `experiments/` — scratch scripts for testing (embeddings, LLM, retrieval). Nothing here ships in the app.
- No backend, frontend, or model/adapter code exists yet in this repo.
- If you are about to create the first code, propose a structure first and wait for approval.
