# Spec: Chat stream and answer polish

Status: proposal for review  
Branch: `polish-stream`  
Scope: the notebook chat stream and the rendered LLM answer

## Objective

Make the chat feel responsive, trustworthy, and finished while an answer is
being generated and after it completes. The user should always understand
whether StudIA is waiting, receiving an answer, showing a grounded answer, or
recovering from a failure.

This is a refinement of the existing Django-template/HTMX workspace. It must
preserve the PRD contract: answers are in Tetum, the answer is streamed over
SSE as escaped Markdown rendered to HTML, citations come from validated stored
metadata, and the final result exposes `answer`, `supported`,
`conversation_id`, and `sources`.

## Current branch baseline

The branch currently contains one focused change in commit `b9ba144`:

- The client creates an assistant loading bubble after the user event.
- The bubble contains a spinner, an accessible `role="status"`, and the text
  `thinking…`.
- The status pulses while the answer is pending.
- The first `message` event removes the loading state and replaces the bubble
  with the streamed HTML.

The existing stream also has:

- An SSE `user` event containing `conversation_id` and the user text.
- Re-rendered answer-so-far HTML in each `message` event.
- A `done` event currently carrying only `conversation_id`.
- An `error` event with a message and an error code.
- Server keep-alive comments while the provider is quiet.
- Adapter-side retry before the first byte, no retry after partial output, and
  usage accounting that includes Gemini thinking tokens.
- Markdown escaping through Mistune before the browser assigns `innerHTML`.

The current path is still a stream prototype: the QA view sends conversation
history directly to Gemini and does not yet complete retrieval, citation
validation, `supported` calculation, or final source rendering described by
the PRD/DATABASE flow.

## Product requirements traced to the PRD

This spec implements or refines:

- PRD §3 must-have 2, 6, 7, and 8: Tetum grounded Q&A, follow-ups, honest
  not-found answers, and responsive loading/streaming/error states.
- PRD §5 steps 6–9: stream the answer, validate cited chunk numbers, attach
  stored source metadata, and show sources.
- PRD §7: keep the single adapter boundary, retry/fallback behavior, and
  per-call token, latency, and cost logging.
- PRD §8: keep the existing ask endpoint and its conceptual response fields;
  do not add a second chat endpoint or an undocumented response shape.
- DATABASE.md §4.2: persist the complete assistant answer and validated
  `MessageSource` rows only after the stream finishes successfully.

## Proposed experience

### 1. Before generation

When the user submits a non-empty question:

- Disable Send and prevent a second ask for the same active stream.
- Append the user bubble immediately so the conversation feels acknowledged.
- Append one assistant placeholder with the current spinner and thinking
  status.
- Keep the input text cleared only after the request has been accepted by the
  browser; restore/focus it after a terminal failure so the question is not
  lost.
- Keep the feed scrolled to the newest content unless the user has deliberately
  scrolled upward. If the user is reading older messages, do not force-scroll.

### 2. While the model is quiet

The current `thinking…` treatment is the safe baseline because the existing
contract does not expose retrieval or model-thought progress. The UI may use a
small set of client-only labels, but they must not claim backend work that has
not happened.

Recommended label sequence:

1. `thinking…` immediately after submission.
2. `writing…` after the first answer `message` event.

Do not display the model's hidden chain of thought, raw provider events, or
claims such as “searching 12 passages” unless the backend explicitly sends a
contracted progress event and the team approves that contract change.

### 3. While text streams

For each `message` event:

- Treat the payload as the complete answer-so-far, not a delta.
- Replace the assistant bubble's contents rather than append them.
- Render only the server-produced escaped HTML.
- Preserve readable Markdown structure: paragraphs, lists, headings, code,
  and blockquotes should not visibly jump more than necessary as the answer
  grows.
- Keep the loading spinner out of the answer once the first visible text
  arrives.
- Keep the answer in the normal assistant visual style; the transient state
  should not leave a loading class behind.

The client should tolerate an empty text chunk and keep reading. A heartbeat
comment is not an answer event and must not change the visible answer.

### 4. On successful completion

The final event must complete the existing conceptual response, rendering:

- the final assistant answer,
- `supported`,
- `conversation_id`, and
- the validated `sources` list containing `chunk_id`, `document`, `page`, and
  `excerpt`.

The client should then:

- remove all transient loading state;
- re-enable Send and focus the question field;
- retain the conversation id for the next follow-up;
- show a compact grounded-answer/source treatment when `supported` is true;
- show an honest Tetum not-found treatment when `supported` is false;
- render sources from the final event only, never from model text;
- keep source excerpts collapsed by default on small screens and make the
  document/page reference easy to scan.

The source presentation is intentionally left as an approval choice:

- Recommended: a compact “Sources” disclosure below the answer, with one row
  per validated source and document + page + excerpt.
- Alternative: inline numbered source markers in the answer.

Inline markers would require a stable mapping from answer text to source rows
and should not be inferred from free-form model output, so the disclosure is
the lower-risk option for the current contract.

### 5. Honest unsupported answers

If `supported` is false:

- Do not present the answer as a normal confident answer.
- Use a visually distinct but non-alarming state with Tetum copy explaining
  that the uploaded documents do not contain enough information.
- Do not show invented citations or an empty “Sources” heading.
- Keep the answer in conversation history so the user can ask a better
  follow-up.

The UI must trust the backend's mechanically calculated `supported` value. It
must not decide support by searching answer text for phrases.

### 6. Errors and interrupted streams

For a terminal SSE `error` event:

- Replace the loading placeholder with the standard error fragment/style.
- Preserve the user's question in the visible conversation.
- Re-enable Send and focus the input.
- Keep the returned PRD error code in `data-error-code` for tests.
- Use a short, actionable message for `document_not_ready`,
  `document_failed`, `rate_limited`, and `llm_unavailable`; do not expose raw
  provider payloads.

For a network failure, malformed SSE payload, or connection ending before a
terminal event:

- Mark the assistant bubble as interrupted rather than silently treating it as
  a successful answer.
- Preserve any partial text, but label it as incomplete and do not create a
  successful-looking sources section.
- Re-enable Send and offer a retry action only if the retry semantics are
  approved; the retry must not duplicate persisted user messages or charge an
  unintended extra LLM call.

### 7. Accessibility and responsive behavior

- Keep a single live status region for the active stream; avoid announcing
  every re-rendered token to screen readers.
- The spinner is decorative when the text status is present and should not
  create duplicate announcements.
- Respect `prefers-reduced-motion` by disabling the spinner/pulse animation
  while preserving the text status.
- Maintain keyboard submission behavior already present: Enter submits, and
  Ctrl/Cmd/Shift+Enter inserts a newline.
- Keep the active assistant bubble and source disclosure usable at narrow
  widths without horizontal overflow.
- Ensure focus is visible after completion and error recovery.

## LLM answer quality polish

The stream UI cannot compensate for an unclear or weak answer. Once the real
RAG path is connected, the answer contract should enforce:

- short, simple Tetum unless a technical term needs the original spelling;
- Markdown suitable for progressive rendering;
- answer only from the supplied numbered passages;
- explicit Tetum not-found wording when passages are insufficient;
- chunk numbers used only as internal grounding signals, never as trusted
  citation metadata;
- no raw HTML, provider traces, hidden thinking text, or JSON leakage in the
  visible answer;
- final source rows assembled from stored chunk metadata after validation.

The first visible answer bytes should be useful prose, not a preamble such as
“Sure, I can help.” The prompt should prefer a direct answer followed by a
brief explanation and source disclosure handled by the application.

## Proposed SSE behavior

This keeps the PRD's existing event model and does not add an endpoint.

| Event | Required payload | Client behavior |
|---|---|---|
| `user` | `conversation_id`, `text` | Append the user bubble and create the assistant placeholder. |
| `message` | whole answer-so-far as escaped rendered HTML | Replace the assistant answer contents. |
| `done` | final `supported`, `conversation_id`, and `sources`; final answer remains the rendered answer | Remove transient state and render support/source treatment. |
| `error` | `code`, `message` | Render the standard error state and stop the active stream. |
| keep-alive comment | no data payload | Keep the connection alive; change nothing visually. |

The exact final-event rendering may be an HTML fragment or serialized data
inside the already agreed SSE response, but the conceptual fields must remain
the PRD fields. No new public response field should be added without a team
decision and a PRD/API-contract update.

## Implementation boundaries

### Always do

- Keep Django templates + HTMX/SSE; do not introduce React, npm, or a new
  client framework.
- Keep provider-specific code inside the one LLM adapter.
- Escape model Markdown before assigning `innerHTML`.
- Validate model chunk references before creating `MessageSource` rows.
- Persist the complete answer and usage data at stream completion.
- Test both the browser event state machine and the Python stream/service
  contract.
- Respect `prefers-reduced-motion`, keyboard use, and mobile layout.

### Ask first

- Adding new SSE event names or payload fields.
- Adding stop-generation/cancel semantics.
- Adding automatic retry from the browser.
- Choosing inline citations instead of a source disclosure.
- Adding a database field for stream status, interruption reason, or partial
  answers.
- Adding a frontend dependency or changing the current HTML-over-the-wire
  approach.

### Never do

- Display hidden chain-of-thought or provider debug payloads.
- Invent citations from model prose.
- Mark an answer supported without at least one validated source.
- Treat a dropped connection as a successful completed answer.
- silently retry a request in a way that duplicates messages or usage charges.
- Commit secrets, generated artifacts, or the untracked `.vscode/` directory
  unless the team explicitly wants it tracked.

## Testing strategy

### Python/service tests

- Stream success persists one assistant message, one usage record, and the
  final response data.
- Final supported answers persist only validated source rows.
- Unsupported answers persist `supported=False` and no source rows.
- Provider failure emits `llm_unavailable` or `rate_limited` with a safe
  message.
- Partial stream interruption is not reported as success.
- Usage includes provider, model, prompt tokens, completion tokens including
  billable thinking tokens, latency, and estimated cost.
- Follow-up requests retain the existing conversation id and do not duplicate
  sequence numbers.

### Browser/interaction tests

- `user → thinking → message → done` produces one user bubble and one finished
  assistant bubble.
- Multiple `message` events replace the same assistant bubble.
- `user → thinking → error` leaves the question visible and restores input
  availability.
- Missing `done` is shown as interrupted, not successful.
- Sources appear only after `done` and are absent for unsupported answers.
- Empty chunks and keep-alive comments do not break the stream.
- Reduced-motion mode removes animation without removing status text.
- Mobile layout has no horizontal overflow and source excerpts remain usable.

### Manual acceptance pass

Run the workspace with:

```text
uv run pytest
uv run python manage.py runserver
```

Check one short answer, one answer with Markdown structure, one follow-up,
one unsupported question, one provider error, one interrupted connection,
one narrow viewport, and one reduced-motion setting.

## Success criteria

- A user always sees a clear state from submission to completion or failure.
- The assistant bubble never shows raw model HTML or hidden thinking text.
- The stream remains readable while Markdown grows and does not duplicate text.
- Successful answers end with the correct conversation id, support state, and
  stored-metadata sources.
- Unsupported answers are visibly honest and have no fake citations.
- Failures are recoverable without losing the question or creating a false
  successful answer.
- Existing PRD endpoint, adapter, storage, privacy, and cost rules remain
  intact.

## Open decisions for approval

1. Should the first polish slice stay client-only (`thinking…` then
   `writing…`), or should the backend expose additional progress events for
   retrieval/generation phases? **Recommendation:** client-only for this
   branch; it preserves the current contract and avoids implying unsupported
   backend progress.
2. Should sources use a disclosure below the answer or inline markers?
   **Recommendation:** disclosure below the answer.
3. Should stop-generation be in this slice? **Recommendation:** defer until
   cancellation and persistence semantics are specified, because the current
   contract has no cancel endpoint or interrupted-message state.
4. Should the visible UI copy be Tetum now, or remain English while the core
   stream stabilizes? **Recommendation:** keep transient technical labels
   minimal and move user-facing answer/error copy to Tetum as part of the
   contract-complete answer slice; the PRD requires answers in Tetum but does
   not require an entirely Tetum interface.

## Decision ledger

No new product decisions are recorded by this proposal. The recommendations
above require explicit approval before implementation or before changing the
PRD/API contract.
