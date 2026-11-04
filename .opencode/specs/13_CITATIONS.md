# Spec 13 — Citations end-to-end (chunk validation → MessageSource → UI)

Fixes the biggest Definition-of-Done gap ([issue #13 pre-work](https://github.com/Noro18/EstudIA/issues)): `MessageSource` rows are never written, `Message.supported` is never set, and the UI shows no sources. PRD § 3 must-have 3 + § 5 step 8; honesty rule from `docs/DATABASE.md` § 4.2 step 7. The whole flow runs inside the existing SSE ask pipeline — **no new LLM call, no extra cost, no new endpoints** (the `sources` data ships in the existing `done` SSE event, and per-document sources ride on Sources in `documents/{id}` detail? — no: `GET /documents/{id}/sources/` stays out of scope here, tracked as a follow-up).

## 1. Equipment checklist (what must be true after this lands)

| # | Thing | Outcome |
|---|---|---|
| 1 | Model names the chunks it used | Parsed from the answer text, **validated** against the chunk ids actually sent |
| 2 | Validated citation | One `MessageSource` row per distinct chunk — page + excerpt snapshots from stored chunk metadata |
| 3 | `Message.supported` | Set mechanically (C2) on every assistant row — never null again |
| 4 | SSE | `done` event carries `supported` + `conversation_id` + `sources[]` |
| 5 | UI | Sources listed under the assistant bubble: `Title · p.N`, click → excerpt |
| 6 | Model invents/bad numbers | Invalid numbers silently dropped; zero valid → `supported=False`, warning logged |
| 7 | Zero extra provider cost | Parsing only — no second LLM call, no structured-output round-trip |

## 2. The flow after this spec

```text
ask (already streams):
  answer text accumulates → SSE "message" events (unchanged)
  on stream end:
    1. strip the trailing "Used chunks:" line from the text (D1/D5)
    2. parse chunk numbers → validate ⊆ supplied ids (PRD § 5 step 8)
    3. assistant Message: content WITHOUT the used-chunks line (D5),
       supported = (validated count ≥ 1)   ← mechanical rule, docs/DATABASE.md
    4. MessageSource row per validated chunk (page/excerpt snapshots, display order)
    5. SSE "done" event: {conversation_id, supported, sources[]}
```

Nombre exact of the marker line comes from the prompt in `apps/rag/prompting.py`
("Used chunks: [1, 2].") — the prompt and the parser are pinned to each other in
one place: `parse_used_chunks(answer)` in `apps/qa/services.py`, tested against
the prompt template. If the prompt wording ever changes, the parser test breaks
first — on purpose.

## 3. Named micro-choices (vetoable — approve or replace)

| # | Choice | Options considered | Recommendation + why |
|---|---|---|---|
| C1 | How the model names chunks | (a) trailing `Used chunks: [n, m]` line parsed post-stream; (b) second LLM call after the stream; (c) structured JSON output instead of free-text stream | **(a)** zero cost/latency; (b) doubles cost for every question; (c) breaks live streaming and the markdown re-render contract (PRD § 8). Prompt already instructs (a) — we only never read the line |
| C2 | `supported` rule | mechanical: `validated citations ≥ 1`; LLM-judged | **Mechanical**, already recorded in `DATABASE.md` § 4.2 — no judge call until an eval harness does it offline |
| C3 | Answered-without-grounding case | (a) `supported=False` + warning log; (b) invent citations | **(a)** per `DATABASE.md`; honest answer preferred over forced citations; a model disclaiming ("la hetan…") with citations still wins (any valid citation → True) |
| C4 | Strip marker from stored/displayed answer | keep it / strip | **Strip** — the line is plumbing, not content; `Message.content` and the rendered bubbles stay clean |
| C5 | Numbering edge cases | validate against supplied ids only | **Validate, dedupe, first-appearance order**, drop everything else. Duplicates → one MessageSource. Numbers ≥ 1 already guaranteed by the numbered `[Chunk n]` prompt blocks |
| C6 | SSE shape | (a) extend `done`; (b) new `sources` event | **(a)** one final event, client code reads `sources` once on stream end |
| C7 | UI rendering | (a) `<details>` element per source, CSS only; (b) JS rewrite | **(a)** — no JS surface growth; repo decided HTMX + light vanilla JS only |
| C8 | Sources snapshot | live FK reads vs stored page/excerpt fields | **Stored snapshots** (page, excerpt-280-chars-`…`) exactly as `DATABASE.md` § 3 defines — citations never re-derive from current chunk state |

**Veto button:** any C-row can be overridden — say so before `SPEC_APPROVED` lands.

## 4. Runtime interface

| Signature | Where it lives |
|---|---|
| `parse_used_chunks(answer) -> tuple[int, ...]` | `apps/qa/services.py` |
| `strip_used_chunks(answer) -> str` | `apps/qa/services.py` |
| `finalize_assistant_message(conversation, user, matches, answer, usage) -> Message` | `apps/qa/services.py` — steps 2–5, called by the SSE loop |
| `render_sources(message) -> list[dict]` | `apps/qa/templates context — include tag or view helper` |
| SSE payload | `{conversation_id, supported, sources: [{document, page, excerpt}]}` |

## 5. Tests (red-green, factory-first)

- Parser: happy path, multi-line answers where the marker is the last non-empty line, missing marker, malformed brackets, duplicate numbers, out-of-range numbers, numbers formatted `[1,2]` (no spaces) and `[1, 2]`.
- Strip: content stored on the Message row **never** contains the marker; non-marker trailing text survives untouched.
- `finalize_assistant_message`: writes alternate `seq`s, sets `supported=1|0`, writes MessageSource rows with 280-char excerpt + `…` and correct page from chunk metadata, dedupes.
- No valid numbers → zero MessageSource rows, `supported=False`, warning log.
- SSE: `done` payload carries the sources + supported flag and consumers can rebuild the UI from it alone.
- View-level: a streamed ask over a notebook with 2 ready documents cites chunks across both (document titles joined live through the chunk FK).

## 6. Docs updates (after code green)

- `AGENTS.md` decision ledger: C1–C8 with dates.
- `DATABASE.md` § 4.2 step 7 already matches — no edit unless a choice changes.
- README: one paragraph on how citations appear and how they stay honest.
