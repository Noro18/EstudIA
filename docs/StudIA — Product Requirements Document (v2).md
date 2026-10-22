# StudIA — Product Requirements Document (v2)

*Revised draft · October 19, 2026 · Team of 3 (roles to be re-assigned, see § 4) · Working demo due November 2, 2026*

## 1. What changed from v1

- **LLM via hosted API.** The model sits behind a provider adapter so we can swap providers. Self-hosting and fine-tuning an open-weight model move to the post-competition roadmap.
- **Model bake-off.** Section 7 defines how we choose the model with evidence instead of opinion.
- **Cost and sustainability plan.** Section 9 answers the judges' likely questions: how would you run this later, and who pays for the API?
- **Documents in any common local language.** Source documents may be in Tetum, Portuguese, English, or Indonesian. Answers are always in Tetum.
- **Re-prioritized features.** Summaries and study questions are must-have. Multi-document chat is out of scope.
- **Retrieval hardening.** Hybrid search by default, OCR for scanned PDFs, and query rewriting for follow-up questions.
- **Stronger API contract.** Ingestion status, streaming answers, conversations, and a standard error format.
- **Dates fixed.** Day 1 is October 19, Day 14 is November 1, and November 2 is a buffer day.

## 2. Project overview

StudIA is an AI study assistant for students in Timor-Leste. A user uploads a document, asks questions about it, and receives answers in Tetum with verifiable page-level citations. StudIA can also summarize the document and generate study questions.

Inspired by Google NotebookLM, StudIA's differentiator is being Tetum-first: explaining course materials, including those written in Portuguese, English, or Indonesian, in the language students think in.

StudIA does not train its own language model. It calls a hosted LLM API for generation and uses its own retrieval pipeline so that every answer is grounded in the uploaded document.

**Target users:** university students, students using Tetum or foreign-language materials, teachers and lecturers, and people who need to understand government publications and reports.

## 3. Scope and priorities

**Must have**

1. PDF upload with text extraction, page tracking, and clear handling of scanned (image-only) PDFs.
2. Question answering grounded in the document, answered in Tetum.
3. Source citations (page number and excerpt) generated from retrieved chunks, never invented by the model.
4. Document summary in Tetum.
5. Study questions (practice questions with answers) generated from the document.
6. Follow-up questions within a conversation.
7. Graceful 'not found in the document' answers.
8. Responsive web UI with loading, streaming, and error states.
9. End-to-end testing on real documents.

**Should have**

1. DOCX and TXT uploads.
2. Cost and latency tracking per request, reported in the evaluation results.
3. Per-user usage limits (also needed for the cost plan).
4. A fallback LLM provider.
5. An evaluation results slide for the presentation.

**Optional**

1. Multiple-choice quiz mode with scoring.
2. Multi-document conversations.
3. Audio summaries.
4. Portuguese or Indonesian user interface.

**Post-competition roadmap**

- Fine-tuned or self-hosted open-weight model for lower per-question cost (see Section 9).

Prioritize a reliable core over optional features. No large new features after Day 10.

## 4. Team structure and responsibilities

**Status: OPEN.** The team is now 3 people. The previous per-person assignments below are records of what each work area contains — the owners have been removed and will be re-decided together (tracked in § 14). Ownership stays legible and independent until then.

### Work area A — AI/LLM lead and technical lead

**Covers:** model selection, prompts, evaluation, and technical coordination.

- Choose a provisional model on Day 1 so the others can integrate immediately.
- Build the Tetum benchmark with the team's Tetum speakers (Section 7) and run the model bake-off. Final model decision by Day 3 (October 21).
- Write and maintain the prompts: grounded Q&A, query rewriting for follow-ups, map-reduce summaries, and study-question generation.
- Define the LLM adapter interface with the backend area.
- Build the evaluation harness and record accuracy, latency, and token cost per model.
- Own architecture decisions and API contracts.

**Deliverables:** selected primary and fallback models, benchmark and results, prompt set, evaluation report.

### Work area B — Backend engineering

**Covers:** API, application logic, background processing, and deployment. *(Owner left the team — duties currently unassigned.)*

- Django views (plain Django, no DRF) with PostgreSQL: documents, chunks, conversations, usage records.
- Asynchronous document ingestion with a status field (processing, ready, failed).
- Streaming answers (Server-Sent Events).
- Implement the LLM provider adapter: one interface, provider and model chosen by environment variables, token usage logged on every call.
- Basic authentication, per-user document isolation, file validation (type and size), rate limits and daily quotas.
- Standard error format, secrets management, and Docker Compose deployment. Test the target environment by Day 3.

**Deliverables:** working backend API, deployable service, usage and cost logging.

### Work area C — RAG and document processing

**Covers:** ingestion, retrieval, embeddings, and source tracking.

- Extract text from PDFs with PyMuPDF and keep page numbers. Detect pages with no text and run OCR (Tesseract with Portuguese, English, and Indonesian packs) or report a clear error.
- Chunk documents (start with roughly 300-600 tokens and some overlap) with page and document metadata attached to every chunk.
- Evaluate embedding models on Tetum queries against Tetum, Portuguese, and English passages (cross-lingual retrieval).
- Implement hybrid retrieval: vector search (pgvector) plus Postgres full-text search, merged with rank fusion.
- Return chunk\_id, document, page, and excerpt for each retrieved passage.
- Build a labeled retrieval test set (at least 30 questions) and report recall@k.

**Deliverables:** ingestion pipeline, searchable index, retrieval interface, retrieval evaluation results.

### Work area D — Frontend and demo experience

**Covers:** user interface and demo flow. *(Owner left the team — duties currently unassigned.)*

- Document library and upload with processing status.
- Chat interface with streamed answers and conversation history.
- Citation display: clicking a citation shows the excerpt and page number.
- Buttons for 'Summarize' and 'Study questions'.
- Loading states, error messages, and a responsive layout.
- Work against mocked API responses from Day 1.
- Framework: **Django templates + HTMX (decided Oct 21).** No React/npm toolchain. Interactive parts: HTMX partial swaps for the chat and document library, SSE extension for streamed answers, polling for upload status.

**Deliverables:** functional responsive UI, citation and source display, polished demo flow.

**With 3 members, work areas A-D will be re-assigned across them — see the pending decision in § 14.** Keep ownership independent, hold a short daily check-in, and merge small changes often.

## 5. System architecture

StudIA uses Retrieval-Augmented Generation (RAG) with a hosted LLM.

```text
Frontend (Django templates + HTMX)
    |  HTML fragments + streaming (SSE)
Backend (plain Django views)
    |-- PostgreSQL + pgvector: users, documents, chunks, conversations, usage
    |-- Ingestion worker: PDF -> text (OCR if scanned) -> chunks -> embeddings + keyword index
    |-- Retrieval: hybrid (vector + keyword) -> top passages with page numbers
    '-- LLM adapter: Provider A (primary) / Provider B (fallback)
```

### Question-answering flow

1. The user uploads a document. The backend stores it and creates a record with status 'processing'.
2. The worker extracts text and page numbers (OCR if needed), chunks it, and builds the vector and keyword indexes. The status becomes 'ready'.
3. The user asks a question in Tetum.
4. For follow-ups, the LLM first rewrites the question into a standalone question using the conversation history.
5. Hybrid retrieval returns the most relevant chunks with page numbers.
6. The backend sends the question and numbered chunks to the LLM.
7. The model answers in Tetum and lists the chunk numbers it used.
8. The backend validates that those chunk numbers were actually supplied, then attaches the stored document name, page, and excerpt. Citations always come from stored metadata.
9. The frontend streams the answer and shows the sources.

### Prompting rules

- Write instructions in English (models follow them more reliably) and require the output in Tetum.
- Include two or three short Tetum example answers in the prompt (few-shot).
- Answer only from the supplied passages. If they do not support an answer, say so in Tetum and set the 'supported' flag to false.
- Prefer short, simple Tetum. When a technical term has no common Tetum equivalent, keep the original term and briefly explain it.

### Summaries and study questions

- **Summaries:** map-reduce. Summarize sections, then combine the section summaries. Generate once per document and cache.
- **Study questions:** generated from sampled or selected sections, each with an answer and a page reference.

## 6. Technology stack

| Component | Choice | Notes |
| --- | --- | --- |
| Frontend | **Django templates + HTMX** (decided Oct 21, replacing "React + TypeScript + Vite + Tailwind, or Django templates + HTMX — decide Day 1") | No npm/build toolchain; server-rendered HTML fragments; SSE for streaming; team has no React experience |
| Backend | Django with plain views + HTML partials (no DRF — dropped Oct 21: HTMX consumes HTML fragments, so a JSON API layer is unnecessary), `uv` | Python 3.x |
| Database | PostgreSQL + pgvector | One datastore for records and vectors |
| Background jobs | Lightweight worker (for example Django-Q2 or Procrastinate) | Avoid Celery unless the team already knows it |
| Streaming | Server-Sent Events | Answers appear as they are generated |
| PDF processing | PyMuPDF, plus Tesseract OCR for scanned pages | Portuguese, English, Indonesian language packs |
| Embeddings | Evaluate a multilingual open model (for example BGE-M3 or multilingual-e5) against a provider embedding API | Choose by retrieval evaluation, not reputation |
| Keyword search | Postgres full-text search | Combined with vectors by rank fusion |
| LLM | Hosted API behind an adapter, primary plus fallback | See Section 7 |
| Deployment | Docker Compose on a single cloud VM | Secrets in environment variables |
| Version control | Git + GitHub | Small, frequent merges |

The stack is provisional. Prefer tools the team can operate reliably within the deadline.

## 7. LLM selection (hosted API)

### Candidates

Shortlist in alphabetical order (not a ranking). Check each provider's current model list on Day 1 and test one cheaper and one stronger model from each:

- Anthropic Claude (Haiku-tier and Sonnet-tier models)
- Google Gemini (Flash-class and Pro-class models)
- OpenAI GPT (a small and a mid-tier model)
- One open-weight model (for example a Qwen model) through a hosted endpoint, as the open-source reference point

### Bake-off protocol

1. **Benchmark:** 40 items drawn from 4 real documents (Tetum, Portuguese, English, and one with poor scan quality). Categories: factual questions, comprehension, summarization, instruction following, unanswerable questions, and cross-language questions (Tetum question, foreign-language passage).
2. **Fair test:** every model receives the same fixed passages and the same system prompt, so we measure the LLM and not retrieval.
3. **Blind rating:** at least two Tetum speakers rate answers with model names hidden: Tetum quality (1-5), correctness against the passage (1-5), and pass/fail on unanswerable items.
4. **Record:** latency and token cost for each item.
5. **Weighted score:** Tetum quality 35%, correctness and faithfulness 30%, handling unanswerable questions 10%, latency 10%, cost 15%.
6. **Decision:** primary model is the highest score. Fallback is the best model from a different provider.

**Minimum bar:** mean Tetum quality of at least 3.5 out of 5 and at least 80% faithful answers. If no model clears it, use simpler, shorter Tetum answers and always show the original-language excerpt next to the answer.

**Timing:** provisional model on Day 1 (October 19), final decision on Day 3 (October 21). Re-check if prices change.

### Adapter requirements

- One function: generate(messages, stream) returning text, token usage, and finish reason.
- Provider and model are set by environment variables. No provider-specific code outside the adapter.
- Automatic retry, then fallback provider on failure or rate limit.
- Every call logs input tokens, output tokens, latency, and estimated cost.

## 8. Interface contract

Agreed on Day 1 (JSON form) and **re-scoped on Oct 21** to HTML-over-the-wire after the frontend decision (Django templates + HTMX): same endpoints, same behavior, but views return **HTML partials** instead of JSON. The evaluation harness (§ 10) calls the Python service layer directly, so it still reads `answer`, `supported`, and `sources` as data without HTTP. Mocking still applies: fixtures are partial templates until the real views exist.

| Endpoint | Purpose |
| --- | --- |
| `POST /documents/` | Upload a document. Returns id and status 'processing' (rendered fragment / redirect). |
| `GET /documents/` | List the user's documents (HTML fragment or page). |
| `GET /documents/{id}/` | Metadata, status (processing, ready, failed), page count, failure reason (for example scanned\_no\_text). |
| `GET /documents/{id}/sources/` | Document metadata and available source information. |
| `POST /documents/{id}/ask/` | Ask a question. Optional conversation\_id; creates a conversation if omitted. Returns a rendered answer partial, or an SSE stream when `stream=true`. |
| `POST /documents/{id}/summary/` | Tetum summary with page references (cached), rendered partial. |
| `POST /documents/{id}/study-questions/` | Study questions with answers and page references. Body: count. |

**Ask request fields:** question (required), conversation\_id (optional), stream (optional boolean).

**Ask response (conceptual data, regardless of rendering):** answer, language (always 'tet'), supported (boolean), conversation\_id, sources (list of chunk\_id, document, page, excerpt). Over SSE: the prompt asks for markdown; each `message` event carries the **whole answer-so-far re-rendered from markdown to HTML** (escaped — no raw HTML from the model), so bolding and bullets appear live; the client swaps with `innerHTML` (replace, not append). The final event carries/renders supported, conversation\_id, and the sources list.

Example question: *Saida mak ideia prinsipál husi dokumentu ne'e?*

**Error format:** the same six codes (`document_not_ready`, `document_failed`, `unsupported_type`, `file_too_large`, `rate_limited`, `llm_unavailable`) rendered as an error fragment showing the message; the code is embedded (e.g. as a `data-error-code` attribute) so tests and the harness can assert on it.

## 9. Cost, sustainability, and the judges' questions

### 9.1 Cost per question

A typical grounded question sends about 3,000-6,000 input tokens (instructions, retrieved passages, and history) and receives about 300-600 output tokens. One thousand questions is therefore roughly 3-6 million input tokens and 0.3-0.6 million output tokens. Summaries cost more because they read the whole document once, but they are generated once and cached.

The real cost is tokens multiplied by the chosen provider's current prices. Smaller model tiers usually bring 1,000 questions down to a low single-digit number of US dollars, while flagship tiers cost substantially more. Verify against current pricing pages and replace these estimates with measured numbers from the bake-off.

| Measure | Value (fill in on Day 3) |
| --- | --- |
| Average cost per question |  |
| Cost per summary |  |
| Cost per active student per month (at 100 questions) |  |

### 9.2 Who pays during the competition

- The team covers a small prototype budget with a hard spending cap set in the provider console (suggested: US$20-50), plus any free credits or trial tiers.
- Per-user daily quotas, answer caching, and pre-processed demo documents keep the demo cost small and predictable.
- One team member holds the API account and billing. Decide who by October 20.

### 9.3 Who pays after the competition

These options can be combined:

1. **Freemium for students:** a free daily question quota, with a paid plan for heavier use, priced for local affordability and local payment methods.
2. **Institutional licensing:** universities or faculties pay per seat or a flat fee. Start with a free pilot at one faculty to collect feedback and real usage-cost data.
3. **Sponsorship and grants:** education and development organizations, government education programs, and AI provider startup or education credit programs.
4. **Telecom partnership:** zero-rated or bundled access with mobile operators, which also helps users with limited data.

**Recommended path:** faculty pilot first, then institutional or sponsor funding, then a freemium student tier once the cost per student is known.

### 9.4 Cost control

- Per-user daily limits and a maximum document size.
- Cache summaries and repeated questions.
- Use a cheaper model for query rewriting and simple questions, and the stronger model only when needed.
- Send only the top retrieved passages, not whole documents.
- Daily token-usage dashboard and provider spending alerts.

### 9.5 Technical roadmap after the competition

- **Phase A (first 3 months):** pilot with a faculty. Collect consented feedback and corrected answers.
- **Phase B:** build a Tetum training and evaluation dataset from corrections and open Tetum sources. Fine-tune an open-weight model (LoRA or QLoRA) and compare it against the API model on the same benchmark and on held-out examples.
- **Phase C:** hybrid routing. A self-hosted model handles simple questions, and the API handles hard ones. This lowers the marginal cost per question. Consider a low-bandwidth and offline-friendly client given Timor-Leste's connectivity.
- **Provider independence:** the adapter and the fallback provider reduce lock-in at every phase.

### 9.6 Data privacy

- Uploaded text is sent to the LLM provider, and to the embedding provider if a hosted embedding API is used.
- Use API terms under which customer data is not used for training (verify for the chosen provider), and tell users plainly in the UI.
- Discourage uploading sensitive personal documents. Allow users to delete their documents and conversations.

### 9.7 Suggested answers for the judges

**How would you implement this later?** StudIA calls a hosted LLM through an adapter, so we can change models as prices and quality change. We would start with a faculty pilot, learn the real usage and cost, and use consented feedback to build a Tetum dataset. We would then test a fine-tuned open-weight model against the API on our benchmark and route simple questions to it to reduce cost.

**Who pays for the API?** During the competition, the team pays a small capped budget; we measured about \[measured cost\] per question. After launch, institutional licenses and sponsors fund usage, with a free daily quota for students. Quotas, caching, and cheaper models for simple questions keep the cost low.

**What are the limitations?** StudIA needs an internet connection and depends on a third-party provider. Tetum quality varies by model, which is why we benchmarked several, and why the interface always shows the source passage so users can verify the answer.

## 10. Evaluation strategy

Do not assume a model or retrieval method works well in Tetum. Measure it.

- **LLM bake-off:** Section 7.
- **Retrieval:** a labeled set of at least 30 questions across Tetum, Portuguese, and English documents. Report recall@k for vector-only, keyword-only, and hybrid search.
- **Answer quality:** is each answer supported by the retrieved passages? Rate faithfulness, completeness, and Tetum quality with at least two Tetum speakers.
- **Language check:** automatically verify that answers are in Tetum and flag answers that drift into Indonesian, Portuguese, or English.
- **Unanswerable questions:** include at least 10 questions the document cannot answer. The system must say so instead of guessing.
- **Citations:** check a sample by hand that each cited page actually contains the excerpt.
- **Summaries and study questions:** human review on at least 3 documents.
- **Held-out documents:** keep 1-2 documents unseen until Day 11 and use them for the final test, so prompts are not tuned only on known documents.
- **Operations:** record latency and cost per request.

## 11. Two-week execution plan

| Phase | Days and dates | Main objectives |
| --- | --- | --- |
| 1. Baseline | Days 1-3 (Oct 19-21) | Provisional model, API contracts, repo and Docker setup, benchmark, bake-off, final model decision on Oct 21 |
| 2. Parallel development | Days 3-5 (Oct 21-23) | Backend and adapter, ingestion and retrieval, UI against mocks |
| 3. First integration | Days 6-7 (Oct 24-25) | Connect frontend, backend, retrieval, and the chosen model |
| 4. Improvement | Days 8-10 (Oct 26-28) | Summaries, study questions, hybrid search, OCR, cost tracking, error handling. Feature freeze on Oct 28 |
| 5. Testing | Days 11-12 (Oct 29-30) | End-to-end evaluation on held-out documents, bug fixing |
| 6. Demo preparation | Days 13-14 (Oct 31-Nov 1) | Polish, demo documents, rehearsal, backup recording |
| Buffer | Nov 2 | Submission and last-minute fixes only |

**Milestones**

- **Day 5 (Oct 23):** upload a document, retrieve text, send it to the LLM, display an answer. The provisional model is fine.
- **Day 7 (Oct 25):** all four components integrated.
- **Day 10 (Oct 28):** feature freeze.
- **Day 14 (Nov 1):** stable, demo-ready, with limitations and evaluation results ready to present.

Team members have other commitments, so keep ownership independent, hold a short daily check-in, and merge small changes often.

## 12. Risks and mitigation

| Risk | Mitigation |
| --- | --- |
| Tetum quality is weak in every model | Bake-off, Tetum few-shot examples, short simple answers, always show the source excerpt |
| API outage, rate limit, or poor internet at the demo venue | Fallback provider, cached answers for demo documents, recorded backup demo, test the venue connection |
| API cost overrun | Hard spending cap, quotas, caching |
| Hallucinated citations | Citations built only from stored metadata, and chunk numbers validated |
| Scanned PDFs return no text | Detect and OCR, or show a clear error |
| Poor retrieval on Tetum | Hybrid search and retrieval evaluation |
| Cross-language mismatch (Tetum question, foreign-language document) | Test early, multilingual embeddings, optional query translation |
| Privacy of uploaded documents | UI notice, provider data terms, deletion option |
| Dependence on a proprietary provider | Adapter, fallback provider, open-weight roadmap |
| Integration delays | Day 1 contracts and mocked responses |
| Limited team hours | Clear ownership, short check-ins, feature freeze |

## 13. Definition of done

- A user can upload a PDF, and scanned or unreadable files produce a clear message.
- The application extracts and indexes the content.
- A user can ask a question and receive a useful answer in Tetum.
- Every answer shows verifiable page references and excerpts.
- Unsupported questions get an honest 'not found' answer.
- Summaries and study questions work on the demo documents.
- The full workflow runs reliably in the demonstration environment, with a fallback plan for network failure.
- The team can explain model selection, retrieval design, evaluation results, cost, and the post-competition plan.

## 14. Open decisions

| Decision | Owner | Due |
| --- | --- | --- |
| **Re-assign work areas A-D across the 3 remaining team members (backend and frontend roles are unassigned)** | Team | TBD |
| Competition rules: is a hosted API allowed, and are there connectivity, offline, or data requirements? | Noro | Oct 19 |
| Frontend approach — **DECIDED Oct 21: Django templates + HTMX** (team has no React experience; simpler deploy for 3 members) | Noro | ~~Oct 19~~ done |
| Provisional model | TBD | Oct 19 |
| API account holder and spending cap | Team | Oct 20 |
| Final primary and fallback models | TBD | Oct 21 |
| Demo hosting target | TBD | Oct 21 |
| Embedding model | TBD | Oct 22 |

**Guiding principle:** build the working product early, evaluate the AI honestly, and spend the remaining time on what matters most to users.
