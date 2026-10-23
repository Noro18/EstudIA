# Spec 10 — Notebook: multi-document chat (B)

**Status:** APPROVED and BUILT — completed Oct 23 (build approval: "alright let's re-edit the whole created current models to the shape of B..."; code green: 28/28 tests, `documents/0002` + `qa/0005` applied, `makemigrations --check --dry-run` clean). § 5 doc updates landed same day per user instruction; § 2.1 index renamed `documents_nb_user_created` (Django 30-char cap); FK adds carried a non-interactive one-off `default=0` (tables empty at generation time — value never applied to any row).
**Date:** Oct 23, 2026
**Supersedes:** the "no multi-document chat" scope decision (DATABASE.md line 41; stood since PRD v2).
**User decision (verbatim, Oct 23):** "i want one conversation covering several documents at once, so i can like ask a question and it checks the documents i uploaded as answers that's what i want"

## 1. The shape after this spec

```text
User ──< Notebook ──< Document ──< Chunk        (knowledge, now grouped)
                 │
                 └─< Conversation ──< Message ──< MessageSource ──> Chunk
                        (each chat session answers from ALL of the
                         notebook's documents' chunks)
```

## 2. Data model changes

### 2.1 New: `documents.Notebook` (lives in the documents app — it primarily organizes documents; qa already depends on the documents namespace)

| Field | Type |
|---|---|
| `user` | FK AUTH_USER_MODEL, PROTECT, `related_name="notebooks"` |
| `title` | CharField(300) |
| `created_at` / `updated_at` | auto_now_add / auto_now |

Index: `(user, -created_at)` named `documents_nb_user_created` (mirrors Document list index pattern; abbreviated to stay under Django's 30-char index-name cap).

### 2.2 `documents.Document`

- New field `notebook` FK Notebook, CASCADE, `related_name="documents"` — **required** (no null): every upload happens inside a notebook.
- All other fields, status flow, chunk composition: unchanged.

### 2.3 `qa.Conversation` — the only qa change

- `document` FK **removed**; replaced by `notebook` FK `documents.Notebook`, CASCADE, `related_name="conversations"`.
- `user` FK stays (PROTECT, user-with-history protected).
- Deletion semantics change: deleting a **document** no longer deletes chats; deleting a **notebook** does. Removing an already-cited document is still guarded by `MessageSource.chunk` PROTECT (approved Oct 22) — delete fails loudly; no silent citation loss.

### 2.4 Explicitly unchanged

`Message`, `MessageSource`, `StudyQuestion`, per-document summaries (D6), quota counting (D3), sliding-window history (D7), full-text/`'simple'` config (D8), `seq` uniqueness + write locking (audit fix), 280-char excerpt snapshots.

## 3. Retrieval / contract teaser (NOT executed in this spec)

- Hybrid-retrieval filter becomes `chunk.document.notebook_id == conversation.notebook_id` — implemented under the rag/ask spec (03), not here.
- PRD § 8 endpoints re-key from `/documents/{id}/ask/` to notebook/conversation endpoints — contract rewrite drafted with spec 04. PRD § 14 ledger entry records this re-scope after SPEC_APPROVED.

## 4. Tests + factories (red-green, factory-first)

New factories: `NotebookFactory`; `DocumentFactory` gains `notebook = SubFactory(NotebookFactory)`; `DocumentFactory.user` → `LazyAttribute(o: o.notebook.user)`; `ConversationFactory` → `notebook = SubFactory(NotebookFactory)`, `user = LazyAttribute(o: o.notebook.user)`.

New/changed tests:
- `documents/tests/test_notebook.py` — create defaults, list index name, owner PROTECT, cascade to documents.
- `qa/tests/test_models.py` — rewritten: notebook delete cascades conversations; user delete still protected; no per-document pinning.
- `test_message*, test_message_source, test_study_question` — untouched (chains flow through factories).

Sequence: RED Notebook → GREEN (document 0002: Notebook + Document.notebook) → RED Conversation re-key → GREEN (qa 0005 alter) → full suite → `makemigrations --check --dry-run` clean.

## 5. Docs updates (after code green, same session)

- DATABASE.md: D9 ledger entry (supersede + quote above), § 1–3 edits, line 41 reworded.
- PRD: § 14 decision entry; § 8 note that endpoint re-key lands via spec 04.

## 6. Named micro-choices (vetoable)

Notebook app placement = `documents`; `notebook` required on Document; conversation cascade moves to Notebook; constraint/index names `documents_notebook_user_created`, conversation FK index none beyond unique patterns; factory owner-inheritance as listed in § 4.
