# SPEC 04 — Notebook workspace front-end (templates + HTMX islands + SSE)

**Status:** DRAFT — open decisions O1–O6 asked Oct 23; answers flip them to decided rows before build.
**Date:** Oct 23, 2026
**Scope trace:** PRD § 5 (architecture + QA flow), § 6 (stack: "Django templates + HTMX", decided Oct 21), § 8 (HTML-over-the-wire contract: endpoints, SSE shape, six error codes) · DB contract: `docs/DATABASE.md` § 4.1–4.5 (statuses, ask/summary/quota rules consumed as-is).
**Supersedes:** nothing. Complements specs 00 (bank), 01/02/03 (backend logic this spec renders), 05/05b (summary/study-page + quota internals).

**User framing (verbatim, Oct 23, condensed):** "one page front end where every interaction happens there… when in a notebook, it's like a single page for each notebook… the live updating of the frontend is the document upload and also the chat response stream… when I create another chat session or conversation, that is when the whole page reloads… group the ones that can reload the whole page and the ones that are live events."

## Yes — what this is

Not an SPA. One **workspace page per notebook** (`GET /notebooks/{id}/`) hosts uploads, documents, conversations, and the chat room. Interaction is split into exactly two groups, matching the contract:

## A. Full-page-load group (plain navigation; never an HTMX fetch)

| # | Interaction | Mechanism | Contract |
|---|---|---|---|
| A1 | Open the home page (list of own notebooks) | `GET /notebooks/` full page | § 8 |
| A2 | Enter a notebook (click its card) | `GET /notebooks/{id}/` full page — THE workspace | § 8 |
| A3 | **New chat session** | navigate (full reload) to the workspace rendered with an **empty chat pane**; no conversation row exists yet — the first question creates it (ask endpoint with no `conversation_id`), per § 8 "creates a notebook conversation if omitted" | § 8 |
| A4 | Switch/reopen a conversation | `GET /conversations/{id}/` full page (full history reset) | § 8 |
| A5 | Document detail page | `GET /documents/{id}/` full page (status, pages, failure reason, summary/study-question actions) | § 8 |
| A6 | Login/logout shells | Django built-in auth views + minimal templates (internal tooling — § 8 defines no auth endpoint; O6) | — |

## B. Live group (HTMX swaps + SSE; no page reload)

| # | Interaction | Mechanism | Contract |
|---|---|---|---|
| B1 | **Upload a document** + live progress ring | `hx-post /notebooks/{id}/documents/` (multipart) → returns a document card fragment with `status=processing` ring → the card polls `GET /documents/{id}/` every ~2 s (`hx-get`, `hx-swap="outerHTML"`) until it re-renders as **ready** (page-count chip, open link) or **failed** (failure reason e.g. `scanned_no_text`)· upload-time violations (`unsupported_type`, `file_too_large`) render the error fragment immediately — no document row (validation-first, § 4.1) | § 8, § 4.1 |
| B2 | **Ask + streamed answer** | form `hx-post` → view returns the **SSE stream itself** (`stream=true`, same endpoint per § 8): a small vanilla-JS reader (Read POST `ReadableStream`, no EventSource — POST is not an event-source) renders each `message` event as **answer-so-far**, swapped with `innerHTML` (replace, not append — markdown re-rendered server-side via mistune, always escaped)· the **final** event replaces the streaming bubble with the settled answer, the `supported` chip, and the **sources list** (`document`, `page`, `excerpt`) for the notebook's documents· user bubble inserted optimistically; send button disabled while streaming; `conversation_id` from the response is written into the pane for follow-ups | § 8 |
| B3 | Error fragments in place | the six codes render as an error fragment with `data-error-code` (`rate_limited`, `document_not_ready`, `llm_unavailable`, …) inside the active region | § 8 |
| B4 | Summary / study questions | on the **document detail** page: `hx-post` the § 8 endpoints → spinner → cached fragment (map–reduce cache, § 4.3/4.4) | § 8 |
| B5 | Create notebook (from the home page) | `POST /notebooks/` **returns a rendered fragment** per § 8 → HTMX inserts the new card live (this one is a fragment flow by contract, so it lives in Group B), then clicking the card does a full reload (A2) | § 8 |

- **Structural deviations from the reference (user-directed Oct 23):** (1) a **top navigation bar** on every page — `<nav class="topbar">` in `base.html`, fixed 60px strip under the theme palette, holding the bold **"StudIA"** logo (22px, `.brand`); (2) right beside the logo: a **notebook selector** — a theme-styled custom dropdown (`nb-select-btn` trigger + `nb-panel` list, open/close animated 140ms fade+rise, driven by `aria-expanded`; native `<select>` was replaced Oct 23 because its OS-drawn popup cannot blend with the UI or animate; picking a notebook = link → full page load to that workspace), plus a **"+" button** (`nb-plus`) opening a native `<dialog>` create form (open animation: 160ms pop-in + backdrop fade) that POSTs the contract `POST /notebooks/` endpoint and redirects full-page to the new workspace (Group A reload); selector+plus render only on pages with a notebook in context (list page keeps its own create form); (3) English labels kept from the reference (O1).

## Page anatomy (workspace)

```text
┌ topbar: (empty — team fills it later)
┌ header: notebook title · quota chip (O5) · "New chat" (A3)
├ left rail: upload dropzone (B1) · document cards with rings (B1) · conversations list
│            (A4 links) · ORE "new chat" hint
├────────── chat pane: bubbles (user/assistant) + supported chip + sources (B2/B3)
└ each region = server-rendered partial; statuses never invented client-side
```

Chat pane shows the notebook's **most recent conversation** on this page; empty state = upload CTA (zero documents → chat disabled with a Tetum hint). If some documents are processing/ready while others lag, the chat proceeds over the ready ones and the pane shows a "processing" chip — the `document_not_ready` code **only** fires when nothing in the notebook is ready (§ 8 + § 4.2 draft rule).

## SSE consumption rules (from § 8, restated for the front-end)

1. `event: message` payloads are the **whole answer so far**, already rendered markdown→HTML and escaped server-side; the client swaps with `innerHTML` — never appends, never parses model markdown client-side.
2. `event: final` carries `supported`, `conversation_id`, `sources[]` (chunk_id/document/page/excerpt from stored metadata only).
3. On stream failure → the error fragment (`llm_unavailable`) replaces the streaming bubble; a retry button re-issues the ask (server-side conversation_id keeps seq consistent).
4. Auto-scroll the pane only when the user is not scrolled up.

## Edge cases rendered by this spec

- Zero documents → chat lane disabled with upload CTA.
- Upload blocked client-side impossible to know; server enforces `file_too_large`/`unsupported_type` fragments (contract).
- Failed document card shows failure reason + links; not ready → participates in `document_not_ready` semantics only.
- Quota `rate_limited` → error fragment in the ask form lane; send button re-enabled.
- No conversations yet → empty chat pane state (A3 flow).
- SSE connection mid-answer drops → retry re-asks; partial text is discarded (server truth: answer not finalized — per spec 03 backend rules).

## Verification checklist (definition of done)

1. Template-rendering tests with `pytest` + Django test client over factory data (no view logic mocks needed beyond a fake LLM stream into a stub service; partials rendered from real views).
2. HTMX attribute assertions for each island (`hx-post`, `hx-get` poll cadence, `hx-swap` targets).
3. SSE consumer unit test with a fake event stream (message events → innerHTML content assertions; final event → chip+sources).
4. Every § 8 error code renders and carries `data-error-code` (assert per code).
5. Vendor file `static/htmx.min.js` present (no npm); the only custom JS is the ask-stream reader (single file, ≤ ~60 lines, no framework).
6. Full suite green; `makemigrations --check` dry-run shows no drift.

## Out of scope (later specs)

- Backend logic of upload/validation, ask flow, retrieval (specs 01/03); adapter (spec 02).
- Summary/study-questions internals + document-page build (spec 05); quota enforcement code (spec 05b) — this spec renders its fragments only.
- Notebook/document deletion (no § 8 endpoint exists — contract change required before any UI).
- Mobile/responsive polish, dark mode, i18n machinery (labels are literal strings — language = O1).
- Production SSE deployment concerns (ops spec).

## Decisions (resolved Oct 23 — user approved the draft and build: "okay … copy the html structure … and let's implement it")

| # | Decision | Outcome |
|---|---|---|
| O1 | Workspace language | **English labels, verbatim from the visual reference** (reference shell is English; Tetum-flip later = template string change, no machinery). Answer *content* stays Tetum per PRD |
| O2 | Upload progress | **status-poll ring ~2 s** (honest server truth; byte-% impossible without chunked-upload machinery) |
| O3 | New-chat mechanics | **lazy-create** via ask-omitted-`conversation_id` (contract-faithful) |
| O4 | Switching conversations | **full reload** to `GET /conversations/{id}/` |
| O5 | Quota chip | **visible chip** (server-computed per render; landing in the ask-form island cycle, spec 03) |
| O6 | Auth shells | **Django built-in `LoginView`/`LogoutView` + `registration/login.html`** |

## Visual reference (user-provided Oct 23: `Chat with your documents.html`)

The interface LOOK is this user-supplied prototype, copied structurally 1:1:

- **Layout:** left `<aside class="side">` (280px panel: title, `.up` upload button, hidden multi-file input, `.hint` microcopy, `.docs` list of `.doc` rows span+small+×); hamburger `.menu` button outside the aside; `<main class="chat">` with `.feed` (aria-live=polite) + `.bar` (textarea autosize ≤140px + `.send`).
- **Theme (verbatim, since overridden Oct 23):** the reference's CSS-variable set with the user's color decision — **light-only, blue primary `#2563eb`** (`--bg:#f4f7fb --panel:#fff --ink:#1c2531 --muted:#64708a --line:#e2e8f2 --soft:#e4eefe`); the reference's dark blocks (`prefers-color-scheme:dark` + `[data-theme="dark"]`) are **dropped** — a theme toggle or dark mode is a separate future ask. File lives as `static/workspace.css`, no build step.
- **Behaviors to port:** drawer toggle + close-on-feed-tap (`static/workspace.js`), textarea autosize, Enter-to-send without shift, `aria-live` feed, optimistic user bubble, "Thinking…" placeholder bubble, `.msg.sys` system notes, send disabled while busy.
- **NOT copied from the reference (deliberately):** pdf.js/mammoth in-browser extraction + `MAX=150000` client-side slicing + direct Claude invocation — their jobs belong to the server pipeline (PRD § 5: upload → worker → chunks/embeddings/retrieval → adapter). The reference is a mock of what the backend now does properly.
- **The `.doc` row's × button:** kept for the look, **inert** — deleting a document has no § 8 endpoint (contract change required before wiring; flagged in Open scope).
- **Interactive status mapping** for the doc row's `<small>` slot: `processing → "Reading…"`, `ready → "{page_count} pages"`, `failed → "Failed"` (`.doc.err` red border).

## Build phases of this spec

1. **Shell cycle (Oct 23):** static assets (`workspace.css`, `workspace.js`, vendored `htmx.min.js` 2.0.6), templates (base, notebook list, workspace, conversation reopen, document detail, login), GET views + `POST /notebooks/` create, `django.contrib.auth` urls wired. Islands inert until their backend specs land.
2. **Island cycles:** B1 upload (spec 01 backend), B2/B3 ask+SSE (spec 03 backend), B4 summary/study-questions (spec 05), O5 quota chip (spec 03/05b side-render).
