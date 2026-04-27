---
ac_count: 12
blocks:
- phase4-ai-006
complexity: M
context: ai
depends_on:
- phase4-ai-002
- phase4-ai-003
estimated_hours: 4
id: phase4-ai-004
phase: 4
sdd_mode: strict
state: ready
title: Tool executor + `ai.tool_calls` audit + structured error mapping
touches_adrs: []
---

# Brief: phase4-ai-004 — Tool executor + `ai.tool_calls` audit + structured error mapping


## Context

This brief is the dispatch + audit layer between the LLM stream and the tool catalog from `phase4-ai-003`. Anthropic's stream returns `tool_use` blocks with shape `{tool_use_id, tool_name, input}`. The executor:

1. Looks up the tool in `ToolCatalog` (404-equivalent error if unknown — programmer-error case, returns to LLM as a structured `tool_result_block.is_error=True`).
2. Validates the `input` against the tool's JSON schema. Schema violations are LLM errors, surfaced back to the model as `is_error=True` so it can self-correct (Anthropic's published guidance for tool-using agents).
3. Invokes `tool.execute(input, user_id=user_id)` with a wall-clock measurement.
4. Persists a row in `ai.tool_calls` — small audit/observability record, NOT a content store. The full tool output is stored in `ai.messages.content` (Regime C, persisted by `phase4-ai-002`'s `AppendMessage`); duplicating it here would widen the redaction surface and waste storage.
5. Returns a `ToolResultBlock` ready to be appended as the user-role response to Anthropic in the next message.

The audit table answers operationally important questions: "which tools is the LLM picking?", "how long is `get_recent_transactions` taking?", "what's the failure rate of `prepare_send_transaction` per chain?". For privacy and storage efficiency, only metadata + a tiny result summary go here; full inputs and outputs ride the `ai.messages` table.

The boundary between "programmer error" and "tool error" matters here. Per `phase4-ai-003` AC-08, tools raise `ToolInputInvalid` on bad inputs (programmer-error case). The executor catches this, logs to Sentry, and surfaces a `ToolResultBlock(is_error=True, output={"code": "tool_input_invalid", "message": "..."})` so the LLM sees the failure and can react — but the executor also captures the violation details server-side because schema mismatches indicate a prompt-engineering or tool-description bug worth investigating. Runtime errors that the tool wraps as `ToolResult.failure` (e.g., `balances_unavailable` when the upstream service is down) flow through unmodified and are surfaced as `is_error=True` `ToolResultBlock`s — same on-the-wire shape, different server-side log severity.

The executor itself has no LLM dependency. It receives a `ToolUseBlock` (our domain VO from `phase4-ai-002`), returns a `ToolResultBlock`. The SSE handler in `phase4-ai-006` is the only caller, but the boundary is testable in isolation with synthetic inputs.

---

## Architecture pointers

- `architecture-decisions.md` §"Three regimes" (Regime C for `ai.tool_calls`), §"AI Assistant" sub-domain catalog, §"Vector store" closing paragraph re: PII column-level encryption deferred to V2 — the audit row stores no message content, side-stepping that concern, but the comment in the schema migration documents it.
- **Layer:** application (executor use case) + infra (SQLAlchemy repo + Alembic migration).
- **Packages touched:**
  - `ai/tools/application/use_cases/execute_tool_use.py` (the executor)
  - `ai/tools/domain/ports.py` (extends with `ToolCallRepository`)
  - `ai/tools/domain/tool_call.py` (the audit aggregate — small)
  - `ai/tools/domain/value_objects/tool_use_block.py` (already declared in `phase4-ai-002`'s `MessageContentBlock` — re-uses the same VO)
  - `ai/tools/infra/sqlalchemy_tool_call_repo.py`
  - `ai/tools/infra/migrations/003_tool_calls.py` (Alembic; revision after `002_chat_tables`)
  - `ai/tools/infra/composition.py` (extends `configure_tools` to wire the executor)
- **Reads:** `ai.conversations`, `ai.messages` (FK validation only — repo joins for parent integrity).
- **Writes:** `ai.tool_calls` (single INSERT per tool execution, no UPDATE).
- **Publishes events:** `ai.ToolCallExecuted{tool_call_id, conversation_id, user_id, tool_name, success, duration_ms, error_code | null}` — registered for V2 observability subscribers (e.g., a future analytics worker that pre-computes "most-used tools per user"); no V1 subscriber.
- **Subscribes to events:** none.
- **New ports introduced:** `ToolCallRepository`.
- **New adapters introduced:** `SqlAlchemyToolCallRepository`. Plus `FakeToolCallRepository` in `tests/ai/fakes/`.
- **DB migrations required:** yes — `003_tool_calls`.
- **OpenAPI surface change:** no (the executor is not exposed as an HTTP endpoint; the SSE handler in `phase4-ai-006` calls it internally).

---

## Acceptance Criteria

- **AC-phase4-ai-004-01:** Given migration `003_tool_calls`, when applied, then table `ai.tool_calls(id UUID PK, conversation_id UUID NOT NULL REFERENCES ai.conversations(id) ON DELETE RESTRICT, message_id UUID NOT NULL REFERENCES ai.messages(id) ON DELETE RESTRICT, tool_use_id TEXT NOT NULL, tool_name TEXT NOT NULL, input JSONB NOT NULL, result_summary JSONB NOT NULL, duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (message_id, tool_use_id), INDEX idx_tc_conv_created ON (conversation_id, created_at DESC), INDEX idx_tc_name_created ON (tool_name, created_at DESC))` exists. The `UNIQUE (message_id, tool_use_id)` is the idempotency guard — re-executing the same tool call (e.g., on stream retry) does not produce a second audit row. Migration is idempotent (`IF NOT EXISTS` guards). `ON DELETE RESTRICT` matches the append-only Regime C discipline.

- **AC-phase4-ai-004-02:** Given the `ToolCall` aggregate in `ai/tools/domain/tool_call.py`, when constructed via `ToolCall.create(conversation_id, message_id, tool_use_id, tool_name, input)`, then it returns a frozen `(id, conversation_id, message_id, tool_use_id, tool_name, input, result_summary=None, duration_ms=None, created_at)` dataclass with two terminal-mutating methods: `_record_completion(result: ToolResult, duration_ms: int)` (sets `result_summary` and `duration_ms`, collects an `ai.ToolCallExecuted` domain event) and `_record_input_invalid(violations: list[str], duration_ms: int)` (sets `result_summary={"success": False, "error_code": "tool_input_invalid", "violations_count": len(violations), "output_size_bytes": 0}`, collects the same event with `success=False`). Once recorded, calling `_record_*` again raises `ToolCallAlreadyRecorded`. The mutating methods are underscore-prefixed (only the executor calls them).

- **AC-phase4-ai-004-03:** Given the `result_summary` JSONB shape, when constructed from a `ToolResult.ok(data)`, then it equals `{"success": True, "error_code": None, "output_size_bytes": <len of json.dumps(data)>, "output_keys": [<top-level keys of data>]}`. From a `ToolResult.failure(error)`: `{"success": False, "error_code": error.code, "output_size_bytes": <len of json.dumps({"code": error.code, "message": error.message})>, "output_keys": []}`. **The summary deliberately excludes the actual output values** — this is the privacy boundary; the full output lives in `ai.messages.content[*].output` only. The `output_keys` array is small and helps observability ("get_balances returned `wallets, total_usd, stale`").

- **AC-phase4-ai-004-04:** Given the `ExecuteToolUse` use case in `ai/tools/application/use_cases/execute_tool_use.py`, when invoked with `(tool_use_block: ToolUseBlock, *, conversation_id: UUID, message_id: UUID, requesting_user_id: UUID)`, then within a single UoW: (1) authorisation — load the conversation, assert `conversation.user_id == requesting_user_id` else raise `ConversationNotFound` (re-uses `phase4-ai-002`'s discipline); (2) lookup tool via `ToolCatalog.find(tool_use_block.tool_name)`; on miss, short-circuit to step 6 with a synthetic `ToolError(code="tool_unknown", message=f"No tool named {tool_name} is available.")` — log a Sentry warning (this means our advertised catalog and Anthropic's pick disagree, a possible drift); (3) validate `tool_use_block.input` against `tool.input_schema` via `jsonschema.Draft7Validator`; on validation error, short-circuit to step 6 with `ToolInputInvalid` semantics (synthetic `ToolError(code="tool_input_invalid", message=<truncated jsonschema error>)`, plus full violations list logged to Sentry); (4) measure wall clock; await `tool.execute(input, user_id=requesting_user_id)`; record duration; (5) catch any uncaught exception from the tool body — synthetic `ToolError(code="tool_internal_error", message="An internal error occurred. The team has been notified.")`, exception captured to Sentry with full traceback; (6) construct `ToolCall.create(...)`, persist, call `_record_completion` or `_record_input_invalid`, persist, commit `ai.ToolCallExecuted` via outbox; (7) return `ToolResultBlock(tool_use_id=<original>, output=<dict>, is_error=<not result.success>)`. The whole sequence is single-UoW: a tool that hit step 5 with an exception still produces a clean audit row + ToolResultBlock; we never lose the audit.

- **AC-phase4-ai-004-05:** Given the idempotency guard from AC-01 (`UNIQUE (message_id, tool_use_id)`), when `ExecuteToolUse` is invoked twice with the same `(message_id, tool_use_id)` pair, then the second call SHORT-CIRCUITS: it loads the existing `ToolCall`, reads `result_summary`, and returns the same `ToolResultBlock` shape (reconstructed from `result_summary` plus a re-fetch of the original output if needed — but here's the subtlety: since `result_summary` deliberately excludes the actual output, we cannot fully reconstruct. **Resolution:** the second-call path returns a `ToolResultBlock` whose `output` is `{"replayed": True, "tool_call_id": <id>}` — this informs the LLM/SSE handler that the tool was already executed and the original result is in the prior `ai.messages` row; in practice this happens only on stream-retry within the same SSE connection, so the LLM-facing path doesn't hit this branch). Tested by simulating a duplicate call in adapter tests.

- **AC-phase4-ai-004-06:** Given the `output_size_bytes > 50_000` case, when `ToolResult.ok(data)` exceeds 50KB after `json.dumps`, then the executor TRUNCATES: replaces `data` with `{"truncated": True, "original_size_bytes": N, "preview": <first 1000 chars of json.dumps(data)>}` BEFORE constructing the `ToolResultBlock` AND before computing `result_summary`. The Sentry breadcrumb logs `{tool_name, original_size_bytes}`. Reason: large tool outputs (e.g., a 1000-tx history dump) bloat the conversation context window and inflate the next LLM call's token cost. Documented limit per `phase4-ai-002` Implementation Notes; this AC is the enforcement.

- **AC-phase4-ai-004-07:** Given the `ToolResultBlock.is_error` field, when constructed from a `ToolResult.ok(...)`, then `is_error=False`; from `ToolResult.failure(...)` or any short-circuit error path (unknown tool, input invalid, internal error), `is_error=True`. The `output` dict in the `is_error=True` case follows the shape `{"code": <error_code>, "message": <human readable>}` — Anthropic's published guidance for tool-using agents: errors-as-data with structured codes lets the LLM react meaningfully. Verified by parametrised test across all five error paths (success, tool_unknown, tool_input_invalid, tool_internal_error, tool runtime failure via `ToolResult.failure`).

- **AC-phase4-ai-004-08:** Given a Sentry breadcrumb is captured at every tool execution, when fired, then it carries `{tool_name, conversation_id, user_id, success: bool, duration_ms, error_code: <or null>}` — **NEVER** the input dict, NEVER the output dict, NEVER message contents. Privacy invariant from `phase4-ai-001` carried forward. A test case `tests/ai/tools/application/test_sentry_redaction.py` runs the executor against a tool whose input contains `{"secret": "TOPSECRET"}` and asserts the captured Sentry payload string does NOT contain `TOPSECRET`.

- **AC-phase4-ai-004-09:** Given concurrent tool executions for the same conversation (e.g., the LLM emits two `tool_use` blocks in one assistant message — Anthropic supports parallel tool use), when both run concurrently against the same conversation, then: (1) each gets its own `ai.tool_calls` row (the `(message_id, tool_use_id)` pair is unique per call); (2) no UoW lock contention — each execution opens its own UoW; (3) total wall-clock is bounded by `max(t1, t2)` not `t1 + t2` (asserted by adapter test that runs two slow fake tools in parallel and times the total). Architecture support: each UoW is independent; no `SELECT FOR UPDATE` on conversation. The audit rows are independent inserts; PG MVCC handles them cleanly.

- **AC-phase4-ai-004-10:** Given the `ToolCallRepository` SQL adapter, when implementing the idempotent-load-or-create path used by AC-05, then the SQL is: `INSERT INTO ai.tool_calls (...) VALUES (...) ON CONFLICT (message_id, tool_use_id) DO NOTHING RETURNING id`. If `RETURNING` returns zero rows, follow-up SELECT fetches the existing row. This is the canonical PG idempotent-insert pattern; `caused_by_event_id` is not used here because tool calls aren't event-sourced — they're LLM-call-sourced, and the natural key is `(message_id, tool_use_id)`.

- **AC-phase4-ai-004-11:** Given the executor's behavior on a `ConversationArchived` exception from AC-04 step (1), when the LLM tries to invoke a tool against an archived conversation, then: (1) NO `ai.tool_calls` row is inserted (we don't audit failed-authorization attempts at this layer — those should never happen in V1's flow because the SSE handler in `phase4-ai-006` checks archived state at stream open); (2) the exception propagates to the SSE handler. This is intentional asymmetry vs the other error paths: tool-internal errors are LLM-visible (it can react); authorization failures are caller-visible (the SSE handler closes the stream with an error event).

- **AC-phase4-ai-004-12:** Given the property test on **executor result equivalence under truncation** (`tests/ai/tools/application/test_executor_truncation_properties.py::test_truncated_output_still_valid`), when fuzzed via Hypothesis over `ToolResult.ok(data)` where `data` is a randomly generated dict of varying sizes (1B to 200KB after JSON encoding), then: (a) for `output_size_bytes <= 50_000`, the returned `ToolResultBlock.output == data` exactly; (b) for `output_size_bytes > 50_000`, the returned output has keys `{"truncated", "original_size_bytes", "preview"}`, `truncated == True`, `original_size_bytes` matches the actual size, and `len(preview) <= 1000`; (c) the `result_summary.output_size_bytes` always equals the size AFTER truncation, never the original. **New property test for Phase 4** (added to PHASE4-SUMMARY mandatory list alongside `phase4-ai-002` AC-12's authorization invariant).

---

## Out of Scope

- Mutating tools (`prepare_send_transaction` and `PreparedAction`): `phase4-ai-005`. (The executor is shape-agnostic — it dispatches whatever's in the catalog. ai-005 just adds another tool.)
- SSE handler that orchestrates the LLM stream and calls this executor: `phase4-ai-006`.
- Per-tool rate limiting (e.g., "no more than 5 `prepare_send_transaction` calls per minute"): documented as V2; the architecture's rate-limit section already caps AI chat at 20 messages/hour, indirectly capping tool calls.
- A user-facing "tool history" view ("show me what AI did in this conversation"): V2; admin can query `ai.tool_calls` directly via psql for debugging.
- Capturing tool-call traces for OpenTelemetry / observability vendor: V2; structlog-only in V1.
- Truncation strategy for VERY large outputs (>10MB): explicit non-goal — anything that big is a tool bug; the 50KB threshold is well below any reasonable tool output and a reviewer asking "why not 100KB?" gets the answer in this brief's Implementation Notes.

---

## Dependencies

- **Code dependencies:** `phase4-ai-001` (port infra, error registry, Sentry hook); `phase4-ai-002` (`Conversation`/`Message` aggregates, the FK targets); `phase4-ai-003` (`ToolCatalog`, `Tool` Protocol, `ToolResult`, `ToolInputInvalid`); `phase1-shared-003` (UoW, outbox); `phase1-shared-005` (Sentry).
- **Data dependencies:** migrations `001_ai_schema` (extension), `002_chat_tables` (FK targets) applied.
- **External dependencies:** `jsonschema>=4.21` already pinned in `phase4-ai-003`.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/ai/tools/domain/test_tool_call.py` — `create`, `_record_completion` (success + failure shapes of `result_summary`), `_record_input_invalid`, double-record raises. Covers AC-02 + AC-03.
- [ ] **Application tests:** `tests/ai/tools/application/test_execute_tool_use_happy.py` — fake tool returns `ToolResult.ok({"x": 1})`; assert audit row written, ToolResultBlock shape correct, event collected. Covers AC-04 success branch.
- [ ] **Application tests:** `tests/ai/tools/application/test_execute_tool_use_unknown.py` — catalog returns None; assert short-circuit path produces `tool_unknown` error and audit row. Covers AC-04 step (2).
- [ ] **Application tests:** `tests/ai/tools/application/test_execute_tool_use_invalid_input.py` — fake tool with strict schema; pass non-conforming input; assert `tool_input_invalid` error, audit row records via `_record_input_invalid`. Covers AC-04 step (3).
- [ ] **Application tests:** `tests/ai/tools/application/test_execute_tool_use_runtime_failure.py` — fake tool returns `ToolResult.failure(...)`; assert audit row written with `error_code` populated, `is_error=True` on the block. Covers AC-04 step (5) success-with-failure, AC-07.
- [ ] **Application tests:** `tests/ai/tools/application/test_execute_tool_use_internal_exception.py` — fake tool raises `RuntimeError`; assert `tool_internal_error` synthesised, exception captured to Sentry. Covers AC-04 step (5) exception branch.
- [ ] **Application tests:** `tests/ai/tools/application/test_execute_tool_use_authorization.py` — wrong user → `ConversationNotFound`, no audit row inserted. Covers AC-11.
- [ ] **Application tests:** `tests/ai/tools/application/test_execute_tool_use_idempotent.py` — invoke twice with same `(message_id, tool_use_id)`, assert one audit row total, second call returns `replayed=True` shape. Covers AC-05.
- [ ] **Application tests:** `tests/ai/tools/application/test_executor_truncation.py` — fake tool returns 60KB dict; assert truncation kicks in. Covers AC-06.
- [ ] **Property tests:** `tests/ai/tools/application/test_executor_truncation_properties.py` — covers AC-12 (mandatory).
- [ ] **Concurrency tests:** `tests/ai/tools/application/test_executor_concurrent.py` — two slow fake tools in parallel via `asyncio.gather`; assert both audit rows present, total time bounded by max not sum. Covers AC-09.
- [ ] **Privacy tests:** `tests/ai/tools/application/test_sentry_redaction.py` — covers AC-08.
- [ ] **Adapter tests:** `tests/ai/tools/infra/test_sqlalchemy_tool_call_repo.py` (testcontainers Postgres) — JSONB round-trip, idempotent insert (`ON CONFLICT DO NOTHING`), index usage on `(conversation_id, created_at DESC)` via EXPLAIN. Covers AC-10.
- [ ] **Migration tests:** `tests/ai/tools/infra/test_migration_003_tool_calls.py` — apply + rollback, idempotency, FK integrity. Covers AC-01.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass — executor lives in `ai/tools/application/`, imports `ai/tools/domain/*` only; no leakage into `ai/infra` directly.
- [ ] `mypy --strict` passes for `vaultchain.ai.tools.*`.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (`ai/tools/application/` ≥ 90%, `ai/tools/domain/` ≥ 95%).
- [ ] OpenAPI schema unchanged.
- [ ] One new error code (`ai.tool_call_already_recorded` for `ToolCallAlreadyRecorded`, programmer-error class) registered in `errors-reference.md`.
- [ ] One new port (`ToolCallRepository`) declared with fake.
- [ ] One new Alembic revision (`003_tool_calls`) committed + applied + rolled-back tested.
- [ ] One new domain event (`ai.ToolCallExecuted`) registered with payload schema.
- [ ] Single PR. Conventional commit: `feat(ai/tools): executor + audit + truncation [phase4-ai-004]`.
- [ ] PR description: a sequence diagram of one execute (lookup tool → validate input → wall-clock measure → execute → truncate-if-needed → audit insert → return block) plus a small ER diagram showing `ai.tool_calls` ↔ `ai.messages` ↔ `ai.conversations`.

---

## Implementation Notes

- The `ToolUseBlock` and `ToolResultBlock` types are already declared in `phase4-ai-002` `ai/chat/domain/value_objects/message_content.py`. Re-use; do not redeclare in `ai/tools/`.
- `jsonschema.Draft7Validator` is the canonical validator. Lazy-instantiate per tool (`tool_name → validator` cache in the executor instance) — schema compilation isn't free, the cache pays for itself within a single SSE stream that calls the same tool multiple times.
- The `result_summary.output_keys` field is computed via `list(data.keys())` if `data` is a dict, else `[]`. Don't recurse — top-level keys are enough for observability.
- The truncation `preview` string is the first 1000 chars of `json.dumps(data, ensure_ascii=False, default=str)`. Wraps Decimals/UUIDs/datetimes safely via `default=str`.
- Use `time.perf_counter_ns()` for duration measurement; convert to ms via `// 1_000_000`. `monotonic_ns` would also work; `perf_counter_ns` is explicit about high-resolution.
- Sentry breadcrumb categories: `category="ai.tool"`, `level="info"` for success, `"warning"` for `tool_input_invalid` / `tool_unknown`, `"error"` for `tool_internal_error`. Severity drives alert routing.
- Don't add a `SELECT FOR UPDATE` on the conversation — the architecture's "no fancy locking" stance applies. Concurrent tool execution is a desired feature (Anthropic's parallel tool use), not a race to defend against.
- `ai.ToolCallExecuted` event is registered but has no V1 subscriber. Documented in the registry; future analytics worker can subscribe.

---

## Risk / Friction

- **Replay semantics under stream retry.** The architecture's hybrid SSE+polling design means a flaky network can cause the SSE client to reconnect; if Anthropic's stream resumes, the same `tool_use_id` may arrive twice. AC-05's idempotent path handles this. The "replayed" sentinel is unusual but well-defined; the LLM never sees this branch in V1 because Anthropic's resume API replays the prior assistant message verbatim including the tool_result already present — the executor branch only fires from server-side retries internal to `phase4-ai-006`.
- **The 50KB threshold is judgement-call territory.** A reviewer might prefer 100KB or argue for chain-aware sizing (a Solana getRecentBlockhash result is tiny; a transaction-list result is bigger). 50KB is a defensible round number that's well below typical context-window-bloat concerns; document the rationale and accept that V2 might tune this per-tool.
- **`output_keys` reveals high-level shape.** A reviewer concerned with privacy might ask "is it OK to log that `get_balances` returned `wallets, total_usd, stale`?" — yes; the keys themselves are not PII, and they help debugging when paired with the user_id-scoped query against `ai.messages`. Document in Implementation Notes.
- **No retry inside the executor.** If a tool's `execute` raises a transient error (e.g., DB blip), the executor surfaces it as `tool_internal_error` and the LLM sees the failure. The LLM may decide to retry by issuing another tool_use in the next turn. Resist adding executor-level retry: it complicates idempotency (the audit row is written before the retry attempt, so the second attempt would need to update — violates Regime C). Documented as deliberate.
- **`ConversationArchived` causes an audit gap.** A determined operator inspecting `ai.tool_calls` will not see "user tried to invoke tool against archived conv" — but in V1 this can't happen via the SSE handler (which guards), so the gap is theoretical. If future code paths bypass the SSE handler, add the audit at this layer; flag in Risk/Friction so a reviewer notices.
