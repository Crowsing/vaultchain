---
ac_count: 14
blocks:
- phase4-ai-002
- phase4-ai-007
- phase4-evals-001
- phase4-web-008
complexity: L
context: ai
depends_on:
- phase4-ai-001
- phase4-ai-003
- phase4-ai-004
- phase1-identity-004
- phase1-shared-005
- phase2-notifications-001
estimated_hours: 4
id: phase4-ai-006
phase: 4
sdd_mode: strict
state: ready
title: Chat SSE endpoint + custom event protocol + ADR-012
touches_adrs:
- ADR-012
---

# Brief: phase4-ai-006 — Chat SSE endpoint + custom event protocol + ADR-012


## Context

This brief is the integration brief for Phase 4. Everything before it (ai-001..005) is plumbing; this is where the plumbing carries water. The endpoint is `POST /api/v1/ai/chat` with content negotiation:

- `Accept: text/event-stream` returns SSE — the live streaming path (production default).
- `Accept: application/json` returns a blocking response with the full assembled assistant message — used by Tier-1 and integration tests, and by reconnect-fallback clients per the architecture's hybrid-SSE-plus-polling discipline.

Both paths exercise the same use case (`StreamChatTurn`), differing only in how output is delivered.

The flow for one chat turn:

1. **Connection open.** Auth dependency validates session. Connection-limit guard (5 concurrent per user, per architecture §"Rate limit") via Redis-tracked counter — exceeds → 429 `ai.events_too_many_connections`. Conversation-load step: if request body has `conversation_id`, load + authorise (`ConversationNotFound` on mismatch — 404 close); if absent, lazily create one via `CreateConversation` (the AC-10 placeholder from `phase4-ai-002`'s out-of-scope list — this brief implements that lazy-create entrypoint).
2. **User message persistence.** Append the user's text as a `Message{role='user', content=[TextBlock(text=request.text)]}` via `AppendMessage` (`phase4-ai-002`). On `ConversationArchived`, immediately send an `error` event and close.
3. **History + system + tools assembly.** Load history via `GetConversationHistory(limit=50)` — chronological order. Build the system prompt (a static prompt template living in `ai/chat/application/system_prompt.py`, hash-versioned for ADR-006 Tier-2 cache invalidation). Pass `ToolCatalog.definitions()` as `tools`.
4. **LLM stream.** Open the SSE response (`text/event-stream`). Send `message_start` event with `{message_id, conversation_id}` (where `message_id` is pre-allocated UUIDv7 — pre-allocation lets the frontend correlate events). Call `LlmClient.stream_message(system, messages=[...history, user_msg], tools, max_tokens)`. Translate each domain `StreamEvent` from `phase4-ai-001` into a frontend SSE event per the protocol below.
5. **Tool dispatch.** When the assistant's stream emits a `tool_use` block (signalled by domain `ToolUseStop` after a sequence of `ToolUseStart` + `ToolUseInputDelta`s assembling the input JSON): (a) emit `tool_use_start` event to frontend; (b) await `ExecuteToolUse(tool_use_block, conversation_id, message_id, requesting_user_id)` from `phase4-ai-004`; (c) on completion, emit `tool_use_result` event; (d) **if** the tool was `prepare_send_transaction` and the result is success, the executor's UoW collected an `ai.PreparedActionCreated` event — the in-memory event bus (per `phase4-ai-005`'s pattern) delivers it to this stream, which emits `prepared_action` event with the full preview payload; (e) supersession events from `phase4-ai-005` similarly emit `prepared_action_superseded`. Tool execution can run in parallel for multi-tool turns — the executor's AC-09 design accommodates `asyncio.gather`.
6. **Continuation.** After tool results are returned to Anthropic (the next stream call's input includes the tool_use + tool_result blocks), continue streaming. The architecture's invariant: at most one assistant message per turn, even when tools are called — Anthropic's API handles this; we just keep streaming the same logical message.
7. **Persistence + close.** When `MessageStop` arrives with `stop_reason ∈ {'end_turn', 'tool_use', 'max_tokens', 'stop_sequence'}`, persist the assistant message via `AppendMessage(role='assistant', content=<assembled blocks>)`. Emit `message_complete{message_id, stop_reason, usage: {input_tokens, output_tokens}}`. Close the SSE stream cleanly.
8. **Error paths.** Network drops → SSE connection closes; the partial assistant message is **not** persisted (Regime C invariant: messages persist only on stream completion; mid-stream state is ephemeral). LLM errors map to `error` SSE events with the `LlmUnavailableError` envelope from `phase4-ai-001`. Tool internal errors are already handled at the executor layer; they appear as `tool_use_result` events with `is_error=true` data and the assistant continues streaming.

Reconnect / resume: the architecture's pattern is graceful-degradation via blocking-mode + polling, NOT mid-message resume. If the SSE connection drops at second 5 of a 30-second turn, the frontend doesn't try to resume the same turn — it falls back to `GET /api/v1/ai/conversations/{id}` polling (from `phase4-ai-002`'s read endpoints) to discover whether the assistant message landed. The architecture documents this; ADR-012 confirms it as a deliberate non-feature.

ADR-012 codifies the SSE event protocol as a contract that has its own versioning, frontend-binding shape, and Tier-2 testing strategy. The architecture-decisions doc lists the seven event types prosaically (line 481–489); ADR-012 makes them a frozen schema, with payload shapes, ordering invariants, and explicit non-goals (no resume, no per-event-kind subscription filtering, no compression).

---

## Architecture pointers

- `architecture-decisions.md` §"AI streaming via SSE" (Section 4 lines 477–489 — the seven event types), §"AI Assistant" sub-domain catalog, §"Tx status updates: hybrid SSE + polling" (the broader SSE discipline this endpoint follows), §"Rate limit policy" (5 SSE connections concurrent, 20 messages/hour per user), §"AI testing — three tiers" (ADR-006 — Tier-2 recorded-conversation tests live here in massive numbers).
- **Layer:** application (use case + system prompt module) + delivery (FastAPI router + SSE adapter).
- **Packages touched:**
  - `ai/chat/application/use_cases/stream_chat_turn.py` (the orchestrator — content-negotiation-agnostic; produces an async iterator of frontend events; the delivery layer formats them as SSE or assembles into JSON)
  - `ai/chat/application/system_prompt.py` (static prompt template + version hash)
  - `ai/chat/application/value_objects/frontend_event.py` (the seven event types as a discriminated union — these are domain-side representations of the protocol; the delivery layer serialises to wire format)
  - `ai/chat/delivery/router.py` (extended from `phase4-ai-002`'s file with `POST /api/v1/ai/chat`)
  - `ai/chat/delivery/sse_writer.py` (translates `FrontendEvent`s to wire-format `event: ... data: ... id: ...` strings; reuses `sse_starlette` package already pinned by `phase2-notifications-001`)
  - `ai/chat/infra/connection_limit.py` (Redis-backed counter for the 5-concurrent-AI-SSE rule; pattern lifted from `phase2-notifications-001` AC-12 but with separate Redis namespace `ai_chat:conn:<user_id>` because the limits are different — 5 here vs 3 there)
  - `tests/ai/conversations/fixtures/conv_*.jsonl` (Tier-2 recorded conversation traces — at least 6 baseline fixtures, listed in AC-10)
- **Reads:** `ai.conversations`, `ai.messages` (via use cases from `phase4-ai-002`).
- **Writes:** `ai.conversations` (lazy create on missing `conversation_id`), `ai.messages` (user msg + assistant msg), `ai.tool_calls` (via `phase4-ai-004` executor), `ai.prepared_actions` (via `phase4-ai-005` tool path).
- **Publishes events:** `ai.ChatTurnStarted{conversation_id, user_id, message_id}` (informational; no V1 subscriber, registered for future analytics), `ai.ChatTurnCompleted{conversation_id, user_id, message_id, stop_reason, total_tool_calls, duration_ms}` (no V1 subscriber). The `ai.MessageAppended` / `ai.PreparedActionCreated` / `ai.PreparedActionSuperseded` events are emitted by the use cases this endpoint calls; this endpoint does not double-publish them but DOES surface them as frontend SSE events via the in-memory bus pattern from `phase4-ai-005`.
- **Subscribes to events (in-memory, scoped to the active stream):** `ai.PreparedActionCreated` and `ai.PreparedActionSuperseded` — the in-memory bus from `phase4-ai-005` delivers these to the active SSE handler so it can emit `prepared_action` / `prepared_action_superseded` events to the frontend within the same turn.
- **New ports introduced:** `ConnectionLimiter` (Protocol with `async acquire(user_id) -> AcquireResult`, `async release(user_id)`).
- **New adapters introduced:** `RedisConnectionLimiter`. Plus `FakeConnectionLimiter` in `tests/ai/fakes/`.
- **DB migrations required:** no.
- **OpenAPI surface change:** yes — one new endpoint `POST /api/v1/ai/chat` with both content negotiations documented; payload shapes for all eight wire events (the seven from architecture + `prepared_action_superseded`) committed as JSON Schema in `docs/api/ai-sse-events.schema.json` and referenced from the OpenAPI doc.

---

## Acceptance Criteria

- **AC-phase4-ai-006-01:** Given the endpoint `POST /api/v1/ai/chat` with body `{conversation_id?: UUID, text: string (1..8000)}`, when called with `Accept: text/event-stream` and a valid session, then the response is `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` (Nginx hint), `Connection: keep-alive`. The handler is async-streaming via `sse_starlette.EventSourceResponse`. Auth dependency reuses the session-cookie pattern from `phase1-identity-004`. Rate-limit headers (`RateLimit-Limit`, `RateLimit-Remaining` from architecture's middleware) reflect the AI-chat-specific 20-msgs/hour bucket.

- **AC-phase4-ai-006-02:** Given a user already holding 5 active SSE connections to `/api/v1/ai/chat`, when they open a 6th, then the response is `429 ai.events_too_many_connections` with `Retry-After: 5` and an SSE error event before close. The Redis-tracked counter at `ai_chat:conn:<user_id>` is incremented on stream open, decremented on stream close (including network-drop close — wired via `EventSourceResponse`'s background callback). The TTL on the counter key is 10 min as a safety net against missed decrements (tests verify TTL set on first increment).

- **AC-phase4-ai-006-03:** Given a request without `conversation_id`, when `StreamChatTurn` runs, then it lazily creates a new `Conversation` for the user via `CreateConversation` (without `first_message` parameter — the user's text is appended in step 4). The lazy-create path is the V1 entry point for fresh chats; the architecture's "user starts a chat → SSE endpoint" is realised here. The created `conversation_id` is included in the first `message_start` event so the frontend can store it and use on next turn. **A new conversation is created exactly once per turn** — re-issuing the same request without `conversation_id` produces a SECOND conversation (not idempotent by design; idempotency is a per-message concept and would require an idempotency-key header which V1 omits for chat — documented in OpenAPI).

- **AC-phase4-ai-006-04:** Given history reconstruction, when `StreamChatTurn` builds the message list to send Anthropic, then it loads `messages` via `GetConversationHistory(conversation_id, limit=50)` (chronological order), then appends the new user message; the resulting list is `[<system message constructed separately>, msg_1, msg_2, ..., msg_n, new_user_msg]`. Anthropic API receives `system` as a top-level parameter and `messages` as the array (correct API shape — verified by recorded smoke test fixture). **History truncation:** if the assembled message-list exceeds `MAX_HISTORY_TOKENS=80_000` tokens (estimated via `len(json.dumps(...)) // 4` as a cheap heuristic), the OLDEST messages are dropped one-pair-at-a-time (user+assistant pair) until under the cap. Truncation is logged at `info`. The first turn after truncation includes a system-prompt addendum: `"<note: earlier conversation truncated for context window>"`. **Property test** in AC-13 covers truncation.

- **AC-phase4-ai-006-05:** Given the `FrontendEvent` discriminated union in `ai/chat/application/value_objects/frontend_event.py`, when defined, then it has eight variants: `MessageStart{message_id, conversation_id}`, `ContentDelta{text}`, `ToolUseStart{tool_use_id, tool_name, input_partial?: str}`, `ToolUseResult{tool_use_id, output, is_error}`, `PreparedAction{prepared_action_id, kind, expires_at, preview}`, `PreparedActionSuperseded{prepared_action_id, superseded_by_id}`, `MessageComplete{message_id, stop_reason, usage: {input_tokens, output_tokens}}`, `ErrorEvent{code, message}`. Each has a `to_wire_dict()` returning the JSON object that lands in the SSE `data:` line, and a `wire_event_name()` returning the SSE `event:` line value (snake_case: `message_start`, `content_delta`, etc.). The discriminator field on the wire is the `event:` line — clients use `EventSource.addEventListener('content_delta', ...)`.

- **AC-phase4-ai-006-06:** Given an Anthropic stream with text-only output (no tool calls), when `StreamChatTurn` runs, then the SSE output is exactly: `1 message_start`, `N content_delta` (one per text chunk from Anthropic — the adapter passes through verbatim, no buffering), `1 message_complete`. No spurious events; no double-emit; ordering deterministic. Tested via Tier-2 fixture `tests/ai/conversations/fixtures/conv_text_only_simple.jsonl`. The fixture is a JSONL of recorded Anthropic stream events; the test stubs `LlmClient` to replay it; asserts exact-sequence equality on the frontend events (a list, ordering matters).

- **AC-phase4-ai-006-07:** Given an Anthropic stream that uses one tool (e.g., `get_balances`), when `StreamChatTurn` runs, then SSE output is: `message_start`, optional `content_delta`s (assistant's preamble), `tool_use_start{tool_name='get_balances'}`, [tool execution happens server-side], `tool_use_result{output: {wallets:[...], total_usd:'...', stale:false}, is_error: false}`, more `content_delta`s (assistant's response after seeing tool result), `message_complete{stop_reason: 'end_turn'}`. The order is strict: the `tool_use_result` event appears AFTER `tool_use_start` AND BEFORE the post-tool-result `content_delta`s. Tested via fixture `conv_one_tool_get_balances.jsonl`.

- **AC-phase4-ai-006-08:** Given an Anthropic stream that uses `prepare_send_transaction` (mutating tool from `phase4-ai-005`), when the tool succeeds, then SSE output includes: `tool_use_start{tool_name='prepare_send_transaction'}`, `prepared_action{prepared_action_id, kind: 'send_transaction', expires_at, preview: {chain, asset, amount_human, value_usd, fee_usd, to_address_short, requires_admin}}`, `tool_use_result{output: {prepared_action_id, summary, ...}, is_error: false}`, then the assistant's natural-language follow-up via `content_delta`s. The `prepared_action` event arrives BEFORE `tool_use_result` (the in-memory event bus delivers it as part of the executor's UoW commit, which precedes the executor returning the ToolResult to the LLM stream). The frontend renders the prep card on `prepared_action`; the `tool_use_result` is mostly informational. Tested via fixture `conv_prepare_send_happy.jsonl` AND `conv_prepare_send_route_to_admin.jsonl`.

- **AC-phase4-ai-006-09:** Given a turn that calls `prepare_send_transaction` twice in the same conversation (the user changed their mind), when the second prepare runs, then SSE output for the second turn includes: a `prepared_action_superseded{prepared_action_id: <prior>, superseded_by_id: <new>}` event followed by the new `prepared_action{...new...}`. The supersession event is delivered via the in-memory event bus from `phase4-ai-005`; the two events arrive in order (supersede-then-create). Tested via fixture `conv_prepare_send_supersede.jsonl` simulating the LLM-driven retry pattern.

- **AC-phase4-ai-006-10:** Given the Tier-2 recorded-conversation fixtures, when collected, then at least the following six baseline fixtures exist in `tests/ai/conversations/fixtures/` and each has a corresponding test in `tests/ai/conversations/test_protocol_<name>.py`: `conv_text_only_simple.jsonl` (greeting + reply), `conv_one_tool_get_balances.jsonl` (single read tool), `conv_one_tool_get_kyc_status.jsonl`, `conv_two_tools_parallel.jsonl` (Anthropic emits two `tool_use` blocks concurrently — verifies parallel dispatch from `phase4-ai-004` AC-09), `conv_prepare_send_happy.jsonl`, `conv_prepare_send_route_to_admin.jsonl`. Each fixture is a JSONL of recorded Anthropic stream events with a header line documenting `{anthropic_model, recorded_at, prompt_template_hash}`. The test runner stubs `LlmClient` to replay; asserts the resulting frontend-event sequence matches a committed expected-trace file (`tests/ai/conversations/expected/<name>.json`). When any fixture's `prompt_template_hash` mismatches the current `system_prompt.py` hash, the test fails with a clear "re-record" message — protects against silent prompt drift.

- **AC-phase4-ai-006-11:** Given an `LlmClient.stream_message` raises `LlmUnavailableError` mid-stream, when handled, then: (1) any partially-streamed content is **not** persisted (no truncated `Message` row); (2) an `error` SSE event is emitted with `{code: 'llm.unavailable', message: 'AI assistant temporarily unavailable, please retry in a moment.'}`; (3) the SSE stream closes cleanly; (4) the Redis connection-limit counter is decremented; (5) Sentry breadcrumb fires with `{conversation_id, user_id, error_class}` (no message contents). If the failure happens BEFORE any text is streamed (e.g., immediate 503), the `message_start` event may not have been sent — in that case the response degrades to a 503 HTTP status with the standard JSON error envelope (the `Accept: text/event-stream` mode upgrades only after the first event).

- **AC-phase4-ai-006-12:** Given the blocking JSON mode (`Accept: application/json`), when the same `StreamChatTurn` runs, then the response is a single JSON envelope `{message_id, conversation_id, content: [<assembled MessageContentBlocks>], stop_reason, usage, prepared_actions: [...]}` — the same logical content as the SSE stream, collected synchronously. The `prepared_actions` array surfaces any prepared actions created during the turn (so the JSON-mode client can render confirmation cards too). Latency is bounded by the LLM turn's full duration (no streaming benefit) — used for tests + reconnect-fallback. Tested by replaying the same fixtures from AC-10 in JSON mode and asserting the assembled response matches.

- **AC-phase4-ai-006-13:** Given the property test on **SSE event ordering invariants** (`tests/ai/conversations/test_protocol_ordering_properties.py::test_event_ordering_invariants`), when fuzzed via Hypothesis over randomly generated stream-event sequences (drawing from a small grammar that produces valid Anthropic-shaped sequences with random tool-use placements), then for any generated sequence, the resulting `FrontendEvent` list satisfies: (a) **first event is `MessageStart`** OR an immediate `ErrorEvent` (no other start); (b) **last event is `MessageComplete` or `ErrorEvent`** — never a `ContentDelta` or `ToolUseStart` last (mid-stream truncation is not a valid completion); (c) for every `ToolUseStart{tool_use_id=k}` that has a corresponding result, there is exactly one matching `ToolUseResult{tool_use_id=k}` AFTER it in the sequence; (d) each `PreparedAction` event is preceded by some `ToolUseStart{tool_name='prepare_send_transaction'}` in the same turn; (e) `MessageStart.message_id` and `MessageComplete.message_id` are equal; (f) no event references a `tool_use_id` not introduced by a prior `ToolUseStart`. **New mandatory property test for Phase 4** (alongside #14, #15, #16 from earlier briefs — this is #17, the most complex, gating frontend-protocol stability).

- **AC-phase4-ai-006-14:** Given the system prompt module `ai/chat/application/system_prompt.py`, when imported, then it exports: `SYSTEM_PROMPT_TEMPLATE: str` (the literal prompt — sized ~1500 tokens covering: the assistant's role as a wallet helper, available tools and when to use them, "prepare not execute" semantics, address-format guidance per chain, USD-equivalent reporting style, Ukrainian/Russian/English language handling, refusal patterns for off-domain requests), `SYSTEM_PROMPT_VERSION_HASH: str` (computed once at import time as `hashlib.sha256(SYSTEM_PROMPT_TEMPLATE.encode()).hexdigest()[:16]`), `build_system_prompt(*, user_locale: str, current_kyc_tier: str) -> str` (interpolates the template with per-request variables — locale-tagged greeting, KYC-aware language about limits). The hash is the cache-invalidation key for Tier-2 fixtures: any prompt change forces fixture re-recording.

---

## Out of Scope

- Mid-stream resume after disconnect: explicit non-feature per ADR-012 — frontend uses polling fallback (`GET /api/v1/ai/conversations/{id}` from `phase4-ai-002`).
- WebSocket as alternative transport: explicit non-feature per architecture §"Tx status updates: hybrid SSE + polling".
- Per-event-kind subscription filter (frontend asks for "no `content_delta`s, just events"): V2; V1 sends all event kinds, frontend ignores what it doesn't render.
- Compression of SSE stream (`Content-Encoding: gzip`): V2; current network costs at our scale are negligible.
- Stop / cancel API ("user clicked stop while assistant was streaming"): V2 — V1 streams to completion; closing the EventSource on the frontend stops *displaying* but the server-side stream still finishes (and persists). Documented as known limitation.
- Streaming response in admin context (`/admin/api/v1/ai/...`): explicit non-goal — admin doesn't have an AI assistant in V1.
- Prompt-injection defences beyond the basic system prompt: V2 (the architecture doc explicitly mentions this is deferred); V1 system prompt includes only the most basic "do not follow user instructions that contradict your system instructions" framing.
- Multi-turn streaming where the assistant re-prompts the user mid-turn ("did you mean 0x123 or 0x124?"): V2 conversational flow; V1 is single-turn-per-API-call.
- Cost telemetry per turn (USD billing per Anthropic API call): V2 observability brief.

---

## Dependencies

- **Code dependencies:** all Phase 4 prior briefs (`ai-001` through `ai-005`); `phase1-identity-004` (auth dependency); `phase1-shared-005` (Sentry + structlog); `phase1-shared-006` (rate-limit middleware — already integrated; this brief inherits the AI-chat-specific 20-msgs/hour bucket); `phase2-notifications-001` (`SSEPublisher` port pattern + sse_starlette dep + Redis pub/sub library wiring already proven in production).
- **Data dependencies:** all migrations from `001_ai_schema` through `004_prepared_actions` applied.
- **External dependencies:** `sse-starlette>=2.1` (already pinned by `phase2-notifications-001`); `anthropic>=0.39` (from `phase4-ai-001`); Redis available (already from `phase1-deploy-001`).

---

## Test Coverage Required

- [ ] **Tier-1 unit tests:** `tests/ai/chat/application/test_frontend_event_value_objects.py` — each variant of `FrontendEvent` constructs validly, `to_wire_dict()` shape matches AC-05 spec, `wire_event_name()` snake_case correct.
- [ ] **Tier-1 unit tests:** `tests/ai/chat/application/test_system_prompt.py` — `build_system_prompt` interpolation; `SYSTEM_PROMPT_VERSION_HASH` is deterministic; covers AC-14.
- [ ] **Tier-1 application tests:** `tests/ai/chat/application/test_stream_chat_turn_lazy_create.py` — without conversation_id, lazily creates; verifies AC-03.
- [ ] **Tier-1 application tests:** `tests/ai/chat/application/test_stream_chat_turn_history_truncation.py` — long fake history; truncation kicks in at MAX_HISTORY_TOKENS; covers AC-04.
- [ ] **Tier-1 application tests:** `tests/ai/chat/application/test_stream_chat_turn_llm_failure.py` — `LlmClient` raises mid-stream; partial assistant message NOT persisted; covers AC-11.
- [ ] **Tier-2 SSE protocol tests** (per ADR-006): `tests/ai/conversations/test_protocol_text_only.py`, `test_protocol_one_tool_get_balances.py`, `test_protocol_one_tool_get_kyc_status.py`, `test_protocol_two_tools_parallel.py`, `test_protocol_prepare_send_happy.py`, `test_protocol_prepare_send_route_to_admin.py`, `test_protocol_prepare_send_supersede.py` — covers AC-06, AC-07, AC-08, AC-09, AC-10.
- [ ] **Tier-2 fixtures:** `tests/ai/conversations/fixtures/conv_*.jsonl` — six baseline fixtures, recorded against real Anthropic, committed.
- [ ] **Tier-2 expected traces:** `tests/ai/conversations/expected/<name>.json` — six expected `FrontendEvent` sequences.
- [ ] **Property tests:** `tests/ai/conversations/test_protocol_ordering_properties.py` — covers AC-13 (mandatory).
- [ ] **Adapter tests:** `tests/ai/chat/infra/test_redis_connection_limiter.py` — 5-connection limit, decrement on close, TTL safety net. Covers AC-02.
- [ ] **Contract tests:** `tests/api/test_ai_chat_endpoint.py` — `Accept` negotiation works for both modes; auth required (401 unauthenticated); rate limit hit returns 429; covers AC-01, AC-02, AC-12.
- [ ] **JSON-mode tests:** `tests/ai/chat/delivery/test_json_mode_assembly.py` — replay each fixture from AC-10 in JSON mode; assert assembled response matches; covers AC-12.
- [ ] **Wire-format tests:** `tests/ai/chat/delivery/test_sse_writer.py` — for each `FrontendEvent`, `sse_writer.write(event)` produces the correct `event: ... \n data: ... \n id: ... \n\n` bytes per the SSE spec (`text/event-stream`). UTF-8 safe; embedded newlines in text deltas are SSE-escaped (`\n` in JSON; SSE concatenates).

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] At least 6 Tier-2 fixtures recorded against real Anthropic, committed; `record-trace` skill documented in `docs/runbook.md`.
- [ ] `import-linter` contracts pass (chat application doesn't import `ai.infra` directly; uses ports from `ai.shared.domain`).
- [ ] `mypy --strict` passes for `vaultchain.ai.chat.*`.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (`ai/chat/application/` ≥ 90%, `ai/chat/delivery/` ≥ 85%).
- [ ] OpenAPI schema diff reviewed: `POST /api/v1/ai/chat` with both content-negotiations, examples for both modes; the eight-event JSON Schema referenced from OpenAPI doc.
- [ ] One new error code (`ai.events_too_many_connections`) registered.
- [ ] Two new domain events (`ai.ChatTurnStarted`, `ai.ChatTurnCompleted`) registered.
- [ ] One new port (`ConnectionLimiter`) declared with fake.
- [ ] **ADR-012 drafted and committed.**
- [ ] `docs/runbook.md` updated with: how to re-record fixtures (`pytest -m record_trace --record-against-real-anthropic`), what the system-prompt-hash drift error means, how to inspect a stalled SSE stream in production (`redis-cli KEYS 'ai_chat:conn:*'`).
- [ ] `pyproject.toml`: `sse-starlette>=2.1` confirmed pinned; if `phase2-notifications-001` pinned a different version, reconcile.
- [ ] Single PR. Conventional commit: `feat(ai/chat): SSE chat endpoint + protocol + ADR-012 [phase4-ai-006]`.
- [ ] PR description: a sequence diagram of one tool-use turn with `prepare_send_transaction` (user submits text → connection acquire → user msg appended → LLM stream open → content_delta → tool_use_start → tool execute → prepared_action event → tool_use_result event → content_delta → message_complete → assistant msg persisted → connection release) plus a one-page diagram of the eight wire events.

---

## Implementation Notes

- **The orchestrator is content-negotiation-agnostic.** `StreamChatTurn` returns `AsyncIterator[FrontendEvent]`. The SSE delivery layer iterates and writes wire format. The JSON delivery layer iterates and assembles into a single response. This separation keeps the use case testable without spinning up SSE.
- **In-memory event bus for `prepared_action*` events.** `phase4-ai-005`'s repo, when persisting a PreparedAction inside the executor's UoW, ALSO publishes via an in-memory `asyncio.Queue` scoped to the active SSE handler (request-scoped DI). The handler's iteration loop drains that queue between LLM stream events. This is the pattern that makes `prepared_action` arrive between `tool_use_start` and `tool_use_result` without the executor needing to know about the SSE handler. Keep this scope tight: the queue is created per-request, garbage-collected when the request ends.
- **History token estimate is intentionally cheap.** `len(json.dumps(...)) // 4` is wrong by a factor of ~1.3-1.5 (UTF-8 vs tokenisation), but it's stable and cheap. Real tokenisation via `tiktoken` would be 50ms per call — too slow on every turn. The 80k token cap has plenty of slack against Sonnet's 200k window.
- **The `ToolUseInputDelta` event from `phase4-ai-001`'s domain stream is NOT emitted to the frontend.** It's an internal assembly step; the frontend only sees `tool_use_start` (with the assembled input once known) and `tool_use_result`. Anthropic's stream sends input as JSON deltas; we wait for `RawContentBlockStop` on the tool_use block before emitting `tool_use_start`. This trades a small latency (the user sees the tool invocation only when the input is fully received, ~50-200ms) for protocol simplicity. Documented in ADR-012.
- **`MessageStart` is sent eagerly** (before LLM responds) so the frontend can show "Assistant is thinking..." immediately. The `message_id` is pre-allocated UUIDv7. If the LLM call subsequently fails, `error` event closes; the message_id is unreferenced (no DB row). Acceptable garbage.
- **Don't import `anthropic.types.*` here.** `LlmClient` returns domain `StreamEvent`s; this brief consumes those, not Anthropic SDK types. The translation lives in `phase4-ai-001`'s adapter.
- **Error-event close timing.** When `ErrorEvent` is emitted, give the network ~50ms before closing the response (`asyncio.sleep(0.05)`). Without this, some browsers don't deliver the final SSE event before the EventSource's `error` callback fires. Cite the relevant browser-bug discussion in a comment.
- **JSON-mode reconnect-fallback caveat.** The architecture mentions JSON mode for tests + reconnect-fallback. "Reconnect-fallback" means: SSE drops, frontend polls `GET /conversations/{id}` to discover the assistant's response landed, then renders. NOT: frontend immediately re-issues `POST /api/v1/ai/chat` in JSON mode to retry. Documented.

---

## Risk / Friction

- **Tier-2 fixture re-recording is operationally expensive.** Six fixtures × Anthropic API calls × any prompt change = $$$. Mitigation: prompt-hash drift detection (AC-10) makes drift visible immediately; fixtures only re-record when hash changes; engineers know not to fiddle with the system prompt casually. ADR-012 documents the discipline.
- **The in-memory `asyncio.Queue` for `prepared_action` events** is a request-scoped pattern that's easy to misuse (e.g., if a future brief uses module-level globals). Document the scope explicitly in the implementation file's docstring; consider a small `RequestScopedEventBus` wrapper class to make the scoping syntactically obvious.
- **Reviewer concern: "shouldn't we resume mid-stream?"** ADR-012 must answer this directly. The answer: SSE resume requires server-side stream replay buffer (RAM) and Last-Event-ID coordination — meaningful complexity for a marginal UX gain. The polling fallback is universally compatible and tested. WebSocket would solve resume but the architecture rules it out for separate reasons.
- **Connection limiter race.** If `acquire` succeeds and the request handler crashes before establishing the stream, the counter doesn't decrement. The 10-min TTL is the safety net but a determined-but-flaky user could chew through their slot budget. Mitigation: `try/finally` around the entire handler ensures `release` runs on any exit path. The TTL is belt-and-suspenders.
- **Anthropic SDK stream API specifics.** The `async with client.messages.stream(...)` context manager handles cleanup. Don't manually iterate the stream object outside the `async with`; resource leaks happen subtly (open HTTPX connections lingering). The adapter from `phase4-ai-001` AC-06 is the only place this is touched correctly.
- **Testing parallel tool dispatch (AC-10's `conv_two_tools_parallel.jsonl`).** Recording this requires a real conversation where the LLM emits two `tool_use` blocks in one assistant message. Anthropic does this rarely in practice — to record, craft a prompt that strongly suggests two independent reads. Documented in `record-trace` skill.
- **The `prepared_action_superseded` event is not in the architecture's seven-event list** — it's the eighth, introduced here. ADR-012 explicitly notes this addition (the architecture doc enumerates seven; this brief, drafting ADR-012, frames the eighth as a refinement). Architecture-decisions doc is NOT touched (per the SSoT discipline); the ADR supersedes for the protocol-contract level.
- **`Accept: text/event-stream` content negotiation** edge cases: a client sending `Accept: */*` defaults to SSE per `EventSource` browser-default behaviour; a client sending neither defaults to JSON. Document in OpenAPI; test both.
