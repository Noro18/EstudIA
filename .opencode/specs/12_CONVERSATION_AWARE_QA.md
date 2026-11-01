# Spec 12 — Conversation-aware QA (follow-up handling)

Fixes [GitHub issue #11](https://github.com/Noro18/EstudIA/issues/11). Chosen approach: the user's Option C — history-aware query rewriting plus a fast intent router on a separate small provider. User-approved 2026-10-27 (plan presented before code, per the standing rule). Land before feature freeze (Oct 28): steps 1–2 must land; step 3 may follow post-freeze.

## 1. Equipment checklist

| # | Thing we measured | Outcome |
|---|---|---|
| 1 | History shown in the prompt | Recent turns (user + assistant), newest last, trimmed to `HISTORY_TOKEN_BUDGET` |
| 2 | Follow-up referencing prior context | Rewritten standalone question _before_ retrieval |
| 3 | Meta/conversational message ("why didn't you…") | Router classifies `history` → answered from the conversation only |
| 4 | Router failure of any kind | Hard fallback to today's behavior — retrieve on the raw question |
| 5 | Citation rule | Unchanged — citations still built only from stored chunk metadata |

## 2. The flow after this spec

```text
user message ──> router (small fast model, separate env vars)
   │
   ├─ RETRIEVE ──> rewriter ──> hybrid retrieval (on rewritten question) ──> grounded prompt incl. history ──> answer (as today)
   │
   └─ HISTORY  ──> history-only prompt (no retrieval) ──> Tetum answer, no citations block

any router/rewriter error or timeout ──> jump to the RETRIEVE path with the raw question (never block the answer)
```

## 3. Named micro-choices (vetoable — implemented per the 2026-10-27 approval)

| # | Choice | Decision & extent |
|---|--------|-------------------|
| C1 | Router availability | `off` when `LLM_ROUTER_MODEL` is unset → behavior identical to today (zero regression; safe for demo) |
| C2 | History in the grounded answer prompt | included (trimmed, ...) so replies can naturally reference the conversation |
| C3 | Router/rewriter logging | `logger` lines only — no `UsageRecord` row, no daily-limit consumption (they are internal control calls, not user questions) |
| C4 | Token estimator | `len(text) // 4` heuristic — no tokenizer dependency |
| C5 | Router timeout | separate small `LLM_ROUTER_TIMEOUT_SECONDS` (default 15) — never inherits the 180 s generation timeout |

## 4. Runtime interface

| Signature | Where it lives |
|---|---|
| `build_grounded_messages(question, matches, history=None)` | `apps/rag/prompting.py` — history block inserted before the passages, current question stays last |
| `rewrite_standalone(question, history) -> str` | `apps/rag/router.py` |
| `classify_intent(question, history) -> str` (`"retrieve"` \| `"history"`) | `apps/rag/router.py` |
| `build_history_only_messages(question, history)` | `apps/rag/prompting.py` |
| `estimate_tokens(text) -> int` | `apps/rag/router.py` |

## 5. Tests (red-green, factory-first)

- History block trimmed at the `HISTORY_TOKEN_BUDGET` edge; current question always last in the grounded prompt.
- Empty conversation → no history block in the prompt at all (not an empty placeholder).
- `classify_intent` returns `"history"` for Tetum meta-question fixture, `"retrieve"` for a factual question; malformed router output → `"retrieve"`.
- `rewrite_standalone` resolves a bare follow-up to a standalone question; any exception path returns the original question unchanged.
- View-level: a `HISTORY`-routed follow-up produces an assistant message but zero new retrieval database reads beyond the router; a `RETRIEVE` message keeps chunk metadata intact.
- Router disabled (`LLM_ROUTER_MODEL` unset) → byte-identical prompt to today's grounded path.

## 6. Docs updates (after code green, same session)

- `AGENTS.md` decision ledger: C1–C5 with dates.
- `README.md`/`docs/`: `LLM_ROUTER_MODEL` and `LLM_ROUTER_TIMEOUT_SECONDS` env vars listed; one paragraph on follow-up routing.

## 7. Explicitly unchanged

- PRD § 8 `POST /documents/{id}/ask/` SSE contract — events, order, `data-error-code` values.
- Hybrid retrieval itself (issue #9's multi-pass work stays independent of this spec).
- The adapter module (single adapter rule; the router is a *call* using an adapter, not a second path).
