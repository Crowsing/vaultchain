---
ac_count: 12
blocks:
- phase4-ai-004
- phase4-ai-005
- phase4-ai-006
- phase4-ai-007
- phase4-web-008
complexity: M
context: ai
depends_on:
- phase1-shared-003
- phase1-identity-004
estimated_hours: 4
id: phase4-ai-002
phase: 4
sdd_mode: strict
state: ready
title: Chat aggregate + `ai.conversations` / `ai.messages` persistence
touches_adrs: []
---

# Brief: phase4-ai-002 — Chat aggregate + `ai.conversations` / `ai.messages` persistence


## Context

This brief is the persistence-and-aggregate brief for AI chat. It does NOT ship a streaming endpoint, does NOT call the LLM, does NOT execute tools. Those concerns live in `phase4-ai-006` (SSE) and `phase4-ai-004` (executor). What this brief delivers is the **state model** that every later brief writes into and reads from: the `Conversation` aggregate, the `Message` record (Regime C, append-only per architecture-decisions §"Three regimes"), the schema migration, the persistence adapter, the user-scoped use cases, and a tiny REST surface for "list my conversations" / "open conversation" / "archive conversation" — the non-streaming reads of chat history, used by the chat panel in `phase4-web-008` to populate the sidebar.

The split between `Conversation` and `Message` matches the two regimes in the architecture: a `Conversation` has small mutable metadata (title, archived flag, last_message_at, message_count) — Regime A (mutable rows). A `Message` is content-bearing, append-only, never updated, never deleted (until GDPR delete in V2) — Regime C (append-only operational log). Mixing them in one table would force everything into Regime C and we'd lose the convenience of `archived = TRUE` updates; splitting keeps each table honest about what it is.

`MessageContent` is a discriminated union shaped to mirror what Anthropic stores natively: blocks of `text`, `tool_use`, `tool_result`. This means later when `phase4-ai-006` reconstructs an Anthropic API call, the messages are already in the right shape — no translation. The discriminator is `type: "text" | "tool_use" | "tool_result"`. The persisted JSONB is exactly this list-of-blocks. Domain code never imports Anthropic SDK types — these are our own dataclasses (the boundary established in `phase4-ai-001` AC-05).

User-scoping authorization is the single most important behavioural invariant of this brief. **Every read and every write asserts that the conversation belongs to the requesting user.** A mismatch raises `ConversationNotFound` (HTTP 404), never `Unauthorized` (HTTP 403) — the latter would leak the existence of conversations belonging to other users. A property test (AC-12) fuzzes random `(operation, requesting_user_id, conversation_user_id)` combinations and verifies the invariant holds across every use case in this brief.

---

## Architecture pointers

- `architecture-decisions.md` §"Three regimes" (Regime A for `conversations`, Regime C for `messages`), §"AI Assistant" sub-domain catalog, §"Schema-per-context in Postgres", §"UUIDv7 primary keys", §"Pragmatic (reads)" — chat may eventually read from Wallet/Balances/etc. but THIS brief reads only its own schema.
- **Layer:** domain (aggregate + VOs) + application (5 use cases) + infra (SQLAlchemy repo + Alembic migration) + delivery (3 thin REST endpoints).
- **Packages touched:**
  - `ai/chat/domain/conversation.py` (aggregate root)
  - `ai/chat/domain/message.py` (append-only record)
  - `ai/chat/domain/value_objects/message_content.py` (`TextBlock | ToolUseBlock | ToolResultBlock` union)
  - `ai/chat/domain/value_objects/message_role.py` (`MessageRole` enum: `user | assistant | tool | system`)
  - `ai/chat/domain/ports.py` (`ConversationRepository`, `MessageRepository`)
  - `ai/chat/domain/errors.py` (`ConversationNotFound`)
  - `ai/chat/application/use_cases/create_conversation.py`
  - `ai/chat/application/use_cases/append_message.py`
  - `ai/chat/application/use_cases/get_conversation_history.py` (paginated message read)
  - `ai/chat/application/use_cases/list_user_conversations.py`
  - `ai/chat/application/use_cases/archive_conversation.py`
  - `ai/chat/infra/sqlalchemy_conversation_repo.py`
  - `ai/chat/infra/sqlalchemy_message_repo.py`
  - `ai/chat/infra/migrations/002_chat_tables.py` (Alembic; revision after `001_ai_schema`)
  - `ai/chat/delivery/router.py` (REST: `GET /api/v1/ai/conversations`, `GET /api/v1/ai/conversations/{id}`, `POST /api/v1/ai/conversations/{id}/archive`)
- **Reads:** `identity.users` (FK only, via repo joins for user-id validation — no use-case-level dep, FK is sufficient).
- **Writes:** `ai.conversations`, `ai.messages`.
- **Publishes events (registered in `shared/events/registry.py`):**
  - `ai.ConversationCreated{conversation_id, user_id, created_at}` — no V1 subscriber, registered for V2 (notifications).
  - `ai.MessageAppended{message_id, conversation_id, user_id, role, has_tool_result: bool, created_at}` — consumed by `phase4-ai-007` memory writer (filters by `role='assistant' AND has_tool_result=True AND tool_result references a `transactions.Confirmed` event`). The event payload deliberately does NOT include message content — subscribers fetch via the repo if they need the body. This keeps the event small and avoids accidentally widening the payload-redaction surface.
- **Subscribes to events:** none.
- **New ports introduced:** `ConversationRepository`, `MessageRepository` (both in `ai/chat/domain/ports.py`).
- **New adapters introduced:** `SqlAlchemyConversationRepository`, `SqlAlchemyMessageRepository`. Plus `FakeConversationRepository`, `FakeMessageRepository` in `tests/ai/fakes/`.
- **DB migrations required:** yes — new Alembic revision `002_chat_tables` creates `ai.conversations` and `ai.messages`.
- **OpenAPI surface change:** yes — three endpoints under `/api/v1/ai/conversations` (the streaming `POST /api/v1/ai/chat` endpoint comes in `phase4-ai-006`, NOT here).

---

## Acceptance Criteria

- **AC-phase4-ai-002-01:** Given migration `002_chat_tables`, when applied, then two tables exist: `ai.conversations(id UUID PK, user_id UUID NOT NULL REFERENCES identity.users(id), title TEXT NULL, archived BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_message_at TIMESTAMPTZ NULL, message_count INTEGER NOT NULL DEFAULT 0, INDEX idx_conv_user_archived ON (user_id, archived, last_message_at DESC NULLS LAST))` and `ai.messages(id UUID PK, conversation_id UUID NOT NULL REFERENCES ai.conversations(id) ON DELETE RESTRICT, role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')), content JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), INDEX idx_msg_conversation_created ON (conversation_id, created_at))`. Migration is idempotent (`IF NOT EXISTS` guards). `ON DELETE RESTRICT` enforces append-only-ness at the FK level — deleting a conversation requires explicit message cleanup (out of V1 scope; V2 GDPR delete brief handles this).

- **AC-phase4-ai-002-02:** Given the `Conversation` aggregate in `ai/chat/domain/conversation.py`, when constructed via `Conversation.create(user_id)`, then it returns a frozen-but-state-bearing instance with: `id` (uuid7), `user_id`, `title=None`, `archived=False`, `created_at` (now), `last_message_at=None`, `message_count=0`, and a pending `ai.ConversationCreated` event in its `events()` collector. Mutating methods: `update_title(title: str)` (validates non-empty, ≤120 chars), `archive()` (idempotent — re-archiving is no-op), `_record_message_appended(message: Message)` (called by `AppendMessage` use case after persisting the message; bumps `message_count`, sets `last_message_at`, collects `ai.MessageAppended` event). Invalid: empty `title`, `title > 120` chars, `archive` then `update_title` (raises `ConversationArchived`).

- **AC-phase4-ai-002-03:** Given the `Message` record in `ai/chat/domain/message.py`, when constructed via `Message.create(conversation_id, role, content)`, then it returns a frozen `(id, conversation_id, role, content, created_at)` tuple-like dataclass. **No mutating methods** — Regime C append-only. Validation: `role` is a `MessageRole` enum; `content` is a non-empty `list[MessageContentBlock]` where every element is one of `TextBlock`, `ToolUseBlock`, `ToolResultBlock`. A `system` message must have only `TextBlock`s (LLM contract). A `user` message has `TextBlock`s and possibly `ToolResultBlock`s (tool outputs returned to assistant). An `assistant` message has `TextBlock`s and `ToolUseBlock`s (tool calls). A `tool` role is reserved (Anthropic style — present for shape compatibility; V1 always uses `user` role for tool results).

- **AC-phase4-ai-002-04:** Given `MessageContentBlock` discriminated union in `ai/chat/domain/value_objects/message_content.py`, when serialised via `to_dict()` and deserialised via `MessageContentBlock.from_dict()`, then round-trip is byte-equal. `TextBlock(text: str)`. `ToolUseBlock(tool_use_id: str, tool_name: str, input: dict[str, Any])`. `ToolResultBlock(tool_use_id: str, output: dict[str, Any], is_error: bool)`. The discriminator field is `"type"` with values `"text" | "tool_use" | "tool_result"`. **Property test:** for any randomly generated `MessageContentBlock` (Hypothesis strategies for each variant), `from_dict(to_dict(b)) == b`.

- **AC-phase4-ai-002-05:** Given `CreateConversation(user_id, first_message: MessageContentBlock | None = None)`, when invoked, then within a single UoW: (1) a new `Conversation` is created and persisted; (2) if `first_message` is provided, an `AppendMessage` is performed immediately with `role='user'`, content=`[first_message]` (so the conversation never has `message_count=0` when explicitly seeded); (3) `ai.ConversationCreated` and (if seeded) `ai.MessageAppended` events are committed via the outbox. Returns the persisted `Conversation` (with `id`, `created_at`, populated counters). Failure modes: nonexistent `user_id` → `IdentityUserNotFound` (FK constraint surfaces this).

- **AC-phase4-ai-002-06:** Given `AppendMessage(conversation_id, role, content, *, requesting_user_id)`, when invoked, then within a single UoW: (1) loads the conversation; (2) **asserts `conversation.user_id == requesting_user_id`** — on mismatch, raises `ConversationNotFound` (NOT `Unauthorized`); (3) asserts `not conversation.archived` — raises `ConversationArchived` if so; (4) constructs `Message.create(...)`, persists; (5) calls `conversation._record_message_appended(message)` and persists the updated counters; (6) commits `ai.MessageAppended` event via outbox. Returns the persisted `Message`.

- **AC-phase4-ai-002-07:** Given `GetConversationHistory(conversation_id, *, requesting_user_id, limit=50, before_id: UUID | None = None)`, when invoked, then: (1) authorisation as in AC-06 (`ConversationNotFound` on mismatch); (2) returns `list[Message]` ordered by `created_at ASC` (chronological — for LLM context window construction), capped at `limit` (default 50, max 200); (3) cursor pagination: `before_id` if provided returns messages with `created_at < (lookup of that id's created_at)`; (4) returns empty list, not error, if conversation has zero messages. The repo SQL: `WHERE conversation_id = $1 AND ($2::UUID IS NULL OR created_at < (SELECT created_at FROM ai.messages WHERE id = $2)) ORDER BY created_at ASC LIMIT $3`.

- **AC-phase4-ai-002-08:** Given `ListUserConversations(user_id, *, include_archived=False, limit=20, before_id: UUID | None = None)`, when invoked, then returns `list[ConversationSummary{id, title, archived, last_message_at, message_count, created_at}]` for the user, ordered by `last_message_at DESC NULLS LAST`. Filters: `include_archived=False` returns only `archived=False`. Cursor: `before_id` paginates. Authorisation: implicit — query is scoped to `user_id`, no foreign-conversation leak possible.

- **AC-phase4-ai-002-09:** Given `ArchiveConversation(conversation_id, *, requesting_user_id)`, when invoked, then: (1) authorisation as in AC-06; (2) calls `conversation.archive()` (idempotent — re-archive is no-op, no second event); (3) persists; (4) returns the updated `ConversationSummary`. No domain event is published in V1 (archived state is private; nothing subscribes).

- **AC-phase4-ai-002-10:** Given the three REST endpoints, when called with valid auth (cookie session per `phase1-identity-004`), then: `GET /api/v1/ai/conversations?include_archived=false&limit=20&before=<uuid>` returns `{conversations: [ConversationSummary], next_cursor: <uuid> | null}`; `GET /api/v1/ai/conversations/{id}?limit=50&before=<uuid>` returns `{conversation: ConversationDetail, messages: [Message], next_cursor}` (combines AC-07 with AC-08's per-conversation read); `POST /api/v1/ai/conversations/{id}/archive` returns `{conversation: ConversationSummary}` (200). All three return `404 ai.conversation_not_found` when the user does not own the conversation. **`POST /api/v1/ai/conversations` (create) is NOT in this brief** — conversations are created implicitly by the SSE endpoint in `phase4-ai-006` (the user starts a chat → `phase4-ai-006`'s endpoint calls `CreateConversation` internally on first message).

- **AC-phase4-ai-002-11:** Given the SQLAlchemy repos, when persisting `MessageContentBlock` lists, then the JSONB column round-trips exactly: a message persisted with `[TextBlock("hi"), ToolUseBlock("tu_1", "get_balances", {})]` and read back returns the same list. The mapper between `list[MessageContentBlock]` and JSONB lives in `ai/chat/infra/content_mapper.py` and is unit-tested independently. PostgreSQL JSONB ordering is preserved (PG stores JSONB with explicit array order). No use of `JSONB` operators that would lose ordering.

- **AC-phase4-ai-002-12:** Given the property test on **per-user authorisation invariant** (`tests/ai/chat/application/test_authorization_properties.py::test_cross_user_access_raises_not_found`), when fuzzed via Hypothesis over `(operation ∈ {AppendMessage, GetConversationHistory, ArchiveConversation}, owner_user_id, requester_user_id)` with `owner != requester`, then **every** operation raises `ConversationNotFound` and **never** raises `Unauthorized` or returns content. The property holds because each use case performs the same `assert conversation.user_id == requesting_user_id` check before any content-returning code path. **New mandatory property test for Phase 4** — to be added to PHASE4-SUMMARY's mandatory list.

---

## Out of Scope

- Streaming chat endpoint (`POST /api/v1/ai/chat` SSE): `phase4-ai-006`.
- LLM invocation, tool execution, prep cards: `phase4-ai-004`/`phase4-ai-005`/`phase4-ai-006`.
- Auto-generated conversation titles (a small LLM job that summarises the first message): documented as V2 — `title` stays NULL until the user sets it manually OR until V2's title-summary worker.
- Message editing / deletion: V2 (Regime C invariant).
- GDPR delete (cascade-delete a user's conversations): V2 brief, requires `ON DELETE CASCADE` migration plus an audit trail of what was deleted.
- Memory write (turning confirmed-tx-result tool messages into embeddings): `phase4-ai-007`.
- Frontend chat panel rendering: `phase4-web-008`.
- Notifications on `ai.ConversationCreated` (e.g., "you started a new chat"): V2.

---

## Dependencies

- **Code dependencies:** `phase4-ai-001` (the `ai` schema and `pgvector` extension are already installed; `ai/shared/domain/value_objects/` exists; ports infrastructure exists), `phase1-shared-003` (UoW, outbox, domain-event registry), `phase1-shared-005` (error envelope mapper for `ConversationNotFound` → 404), `phase1-identity-004` (auth dependency on user-cookie session for the three REST endpoints).
- **Data dependencies:** migration `001_ai_schema` already applied (creates `ai` schema + pgvector — pgvector unused here but the schema is the prerequisite).
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/ai/chat/domain/test_conversation.py` — `create`, `update_title` (valid + invalid), `archive` (idempotent), `_record_message_appended` (counter bump + event collected), `update_title_after_archive` (raises). Covers AC-02.
- [ ] **Domain unit tests:** `tests/ai/chat/domain/test_message.py` — `create` valid; invalid: empty `content`, wrong-typed block list, `system` role with `ToolUseBlock` (raises). Covers AC-03.
- [ ] **Property tests:** `tests/ai/chat/domain/test_message_content_properties.py` — Hypothesis on each block variant; `from_dict(to_dict(b)) == b` for all. Covers AC-04.
- [ ] **Application tests:** `tests/ai/chat/application/test_create_conversation.py` — happy path (with and without `first_message`), unknown user, events committed via fake outbox. Covers AC-05.
- [ ] **Application tests:** `tests/ai/chat/application/test_append_message.py` — happy path (3 messages — counter bump, last_message_at advances), wrong user (`ConversationNotFound`), archived conversation (`ConversationArchived`). Covers AC-06.
- [ ] **Application tests:** `tests/ai/chat/application/test_get_conversation_history.py` — empty, paginated forward (cursor advances), wrong user. Covers AC-07.
- [ ] **Application tests:** `tests/ai/chat/application/test_list_user_conversations.py` — ordering by `last_message_at DESC NULLS LAST`, archived filter, paginated. Covers AC-08.
- [ ] **Application tests:** `tests/ai/chat/application/test_archive_conversation.py` — happy path, idempotency, wrong user. Covers AC-09.
- [ ] **Property tests:** `tests/ai/chat/application/test_authorization_properties.py` — covers AC-12 (mandatory).
- [ ] **Adapter tests:** `tests/ai/chat/infra/test_sqlalchemy_repos.py` (testcontainers Postgres + migration applied) — round-trip persistence, JSONB content preservation (covers AC-11), index usage on the `(user_id, archived, last_message_at)` index via EXPLAIN.
- [ ] **Migration tests:** `tests/ai/chat/infra/test_migration_002_chat_tables.py` — applies + rolls back; idempotency. Covers AC-01.
- [ ] **Contract tests:** `tests/api/test_ai_conversations_routes.py` — happy paths and 404 on cross-user access for all three endpoints. Covers AC-10.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass (the three contracts from `phase4-ai-001` continue to pass — chat does NOT import `ai.infra` directly, only domain ports).
- [ ] `mypy --strict` passes for `vaultchain.ai.chat.*`.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (`ai/chat/domain/` ≥ 95%, `ai/chat/application/` ≥ 90%).
- [ ] OpenAPI schema diff reviewed: three new endpoints under `/api/v1/ai/conversations`. Examples committed for all response shapes.
- [ ] `ConversationNotFound`, `ConversationArchived` registered in `shared/domain/errors.py` + visible in `errors-reference.md`.
- [ ] Two new ports declared (`ConversationRepository`, `MessageRepository`) with fakes in `tests/ai/fakes/`.
- [ ] One new Alembic revision committed + applied + rolled-back tested.
- [ ] Two new domain events registered (`ai.ConversationCreated`, `ai.MessageAppended`) with payload schemas in `shared/events/registry.py`.
- [ ] Single PR. Conventional commit: `feat(ai/chat): conversation aggregate + persistence + REST reads [phase4-ai-002]`.
- [ ] PR description: a small ER diagram of the two tables + the FK to `identity.users`, and a sequence diagram showing one `AppendMessage` UoW (load conv → check user → persist message → bump counters → commit event).

---

## Implementation Notes

- The aggregate boundary is `Conversation`. `Message` rows are accessed via `MessageRepository` directly (not through `Conversation.messages`) because Phase 1's UoW pattern keeps aggregates small and avoids loading collections eagerly. The `_record_message_appended` method on `Conversation` is the *only* coupling — it bumps counters, doesn't load messages.
- `ConversationSummary` and `ConversationDetail` are `application/queries/` projections (frozen dataclasses), separate from the `Conversation` aggregate. Use cases return projections for reads, aggregates for writes.
- The `MessageContentBlock` shape mirrors Anthropic's `MessageParam.content` list-of-blocks format. This is deliberate: when `phase4-ai-006`'s SSE handler builds the message list to send to Anthropic, it can `[m.content for m in messages]` and pass directly. No translation layer needed.
- `ai.MessageAppended.has_tool_result` is a derived flag computed in the use case: `any(isinstance(b, ToolResultBlock) for b in content)`. The memory writer in `phase4-ai-007` filters on this to avoid re-embedding plain chit-chat messages.
- Don't use SQLAlchemy's `relationship()` between `Conversation` and `Message`. Keep the repos independent; aggregate boundaries are clearer that way and N+1 risks are eliminated by construction.
- `update_title` validation (≤120 chars) matches what V2's auto-title summary worker is expected to produce. If a user sets a longer title via UI, frontend trims; backend rejects.
- The `(user_id, archived, last_message_at DESC NULLS LAST)` index supports the `ListUserConversations` query directly. Verify via `EXPLAIN` in adapter tests.
- Counter denormalisation (`message_count`, `last_message_at`) is acceptable Regime A drift risk — the property test in AC-12 doesn't cover counter accuracy, but a separate adapter-level test asserts the counter matches `SELECT COUNT(*) FROM ai.messages WHERE conversation_id = ?` after a sequence of appends.

---

## Risk / Friction

- **Counter drift.** If `_record_message_appended` is bypassed (e.g., a future direct `INSERT INTO ai.messages` from a script), counters diverge. Mitigation: only the application use cases write — adapter is private to repo. A daily reconciliation check is V2-deferrable.
- **JSONB content size.** A long assistant message could embed a large tool result. Postgres has no hard limit on JSONB column size below 1GB, but practical limit is single-row ~100KB before query slowdown. Document in runbook that tool results > 50KB should be truncated by the executor (`phase4-ai-004`) before being appended as `ToolResultBlock`.
- **Authorization-by-`ConversationNotFound` semantic.** A reviewer might object: "shouldn't this be 403?" The standard answer (cite RFC 7235 commentary) is that 404 prevents a timing oracle for conversation existence — important when conversation IDs are UUIDv7 (time-ordered) and could otherwise leak the order in which conversations were created. Document in `errors-reference.md` for the `ai.conversation_not_found` entry.
- **Event payload deliberately small.** Some reviewers might want `ai.MessageAppended` to carry the full content (so subscribers don't need to query). Resist: the smaller payload is harder to accidentally mis-redact. Subscribers that need content fetch via repo.
- **`tool` role is reserved but unused in V1.** Document as "future-shape compatibility — Anthropic's API has `role: tool` but our convention follows the `user`/`assistant` discipline; tool results ride on `user`-role messages."
