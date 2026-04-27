---
ac_count: 11
blocks: []
complexity: L
context: ai
depends_on:
- phase1-shared-003
- phase1-shared-004
- phase2-transactions-002
- phase4-ai-001
- phase4-ai-002
- phase4-ai-005
- phase4-ai-006
- phase4-ai-008
estimated_hours: 4
id: phase4-ai-007
phase: 4
sdd_mode: strict
state: ready
title: Memory writer + `ai.tx_memory_embeddings` + ivfflat config + cross-user-leak
  property
touches_adrs: []
---

# Brief: phase4-ai-007 — Memory writer + `ai.tx_memory_embeddings` + ivfflat config + cross-user-leak property


## Context

This brief realises the **memory** sub-domain. The product story: when a user asks the AI assistant "did I send anything to that 0x456… address recently?", the assistant should be able to find a matching transaction even if the user phrases the question differently than the transaction's stored fields. Static SQL keyword search is brittle; vector similarity over LLM-generated transaction summaries is the right tool.

**What ships here:**

1. The `ai.tx_memory_embeddings` table — schema declared in `architecture-decisions.md` §"Vector store" (with `VECTOR(1536)` shown illustratively; ADR-010 from `phase4-ai-001` binds the actual dim to `VECTOR(768)`).
2. The ivfflat index parameters (`lists=100`, `probes=10`), which ADR-010 explicitly deferred to "the brief that creates the table". This brief makes the call.
3. The per-user-scoping enforcement strategy, which ADR-010 also deferred. The strategy: **every read goes through `TxMemoryEmbeddingRepository.search`, which takes `user_id` as a non-Optional argument; raw SQL is forbidden in application code and an import-linter contract enforces it**. Defence-in-depth alongside a property test that fuzzes a wide range of inputs and asserts no cross-user-leak ever occurs.
4. The `MemoryWriter` subscriber. Triggered by `ai.MessageAppended` (where `has_tool_result=True` on the message — set in `phase4-ai-002` AC-04) AND by `transactions.Confirmed` events on transactions whose origin involved an AI prepared action. The two-trigger design is intentional: most memory entries come from the AI flow (a tool call → confirmed → memory), but some arrive when an AI-prepared transaction confirms minutes after the chat turn ended (the user closed the chat panel before the on-chain confirmation). The writer dedupes on `(user_id, tx_id)` UNIQUE.
5. The summary-generation pipeline: a small LLM call (Anthropic Haiku, NOT Sonnet, for cost) produces a 1-2 sentence summary of the transaction. Then the embeddings call produces a 768-dim vector with `task_type='RETRIEVAL_DOCUMENT'`. Persist row. Idempotent on re-fire.
6. The retrieval port `TxMemoryRetriever.search(user_id, query_text, *, limit=5)` — used by `phase4-ai-006` SSE flow (a future memory-aware tool, deferred to V2 but the port ships now) and by `phase4-ai-008`'s consolidated retrieval interface.

**What does NOT ship here:**

- A "memory tool" the LLM can invoke (`search_my_transaction_history`): explicit V2 — the architecture mentions transaction memory as RAG-context, not as a tool. V1's flow is "LLM doesn't actively query memory; the SSE handler will inject relevant memories into the prompt context" — but injecting context is also V2 (the architecture's V1 RAG focus is product-doc retrieval in `phase4-ai-008`, with tx-memory laid down as infrastructure for V2 surface). This brief delivers the substrate without an active V1 consumer of the retrieval port.
- Re-embedding migration when the embedding model changes (ADR-010 documents this as V2 backlog).
- GDPR delete cascade on memory rows: V2 (with the rest of GDPR delete plumbing).
- Encryption of the `summary` column: V2 (architecture's PII pin); the summary is LLM-generated and contains addresses + amounts but not user PII per se.

The cross-user-leak property test (AC-12) is the most important deliverable. Vector search is a category of bug where it is genuinely easy to ship a `WHERE` clause that misses a filter, and the failure mode is silent — wrong rows return, no exception, no log. The Hypothesis test fuzzes randomly generated `(victim_user_id, attacker_user_id, query_text, victim_corpus, attacker_corpus)` configurations and asserts every search executed under `attacker_user_id` returns ZERO rows belonging to `victim_user_id`, regardless of how textually similar the corpora are. This is the canary; if it ever fails, the production deployment must roll back.

---

## Architecture pointers

- `architecture-decisions.md` §"Three regimes" (Regime C for `tx_memory_embeddings` — append-only), §"Vector store" (the table shape, with the note that VECTOR(1536) is illustrative — ADR-010 binds VECTOR(768)), §"AI Assistant" sub-domain catalog (memory), §"Pragmatic (reads)" (the writer reads `transactions.transactions` via `GET` query — direct cross-context import allowed).
- **Layer:** application (subscriber + writer use case + retrieval use case) + domain (`TxMemoryEntry` value object, ports) + infra (SQLAlchemy repo + Alembic migration).
- **Packages touched:**
  - `ai/memory/domain/tx_memory_entry.py` (`TxMemoryEntry` — read-side projection; the writer constructs and inserts but doesn't model an aggregate with a state machine — Regime C means INSERT-only; no mutations to model)
  - `ai/memory/domain/value_objects/memory_metadata.py` (`MemoryMetadata{chain, asset, value_usd, came_via_admin, was_ai_prepared}` — JSONB shape used for filterable narrowing post-search)
  - `ai/memory/domain/ports.py` (`TxMemoryEmbeddingRepository`, `TxMemoryRetriever`)
  - `ai/memory/domain/errors.py` (`MemoryWriterFailed` — wrapped non-fatal failure for subscriber retry semantics)
  - `ai/memory/application/use_cases/write_tx_memory.py` (the writer use case — fetches tx view, calls LLM for summary, calls embeddings, persists)
  - `ai/memory/application/use_cases/search_tx_memory.py` (the retrieval use case — wraps repo.search with port discipline)
  - `ai/memory/application/handlers/on_message_appended.py` (subscribes to `ai.MessageAppended` with `has_tool_result=True`; identifies tool_result blocks referencing a confirmed-transaction id; enqueues writer)
  - `ai/memory/application/handlers/on_transaction_confirmed.py` (subscribes to `transactions.Confirmed`; checks if tx originated from an AI prepared action; enqueues writer)
  - `ai/memory/infra/sqlalchemy_tx_memory_repo.py`
  - `ai/memory/infra/migrations/005_tx_memory_embeddings.py` (Alembic; revision after `004_prepared_actions`)
  - `ai/memory/infra/composition.py`
- **Reads:** `transactions.application.queries.get_transaction_view` (for fetching full tx details — chain, asset, amount, to_address, value_usd, etc.; this is the read-side query backing `GET /api/v1/transactions/{id}`); `ai.prepared_actions` (read via `PreparedActionRepository.find_by_confirmed_transaction_id` — small lookup helper added to the existing repo from `phase4-ai-005`).
- **Writes:** `ai.tx_memory_embeddings` (INSERT only).
- **Publishes events:** `ai.TxMemoryWritten{memory_id, user_id, tx_id, summary_token_count, vector_dim}` — informational; no V1 subscriber.
- **Subscribes to events:** `ai.MessageAppended` (filtered by `has_tool_result=True` at handler level), `transactions.Confirmed` (filtered to AI-originated by checking `prepared_actions.confirmed_transaction_id`).
- **New ports introduced:** `TxMemoryEmbeddingRepository` (write + raw search), `TxMemoryRetriever` (high-level user-scoped search). `LlmClient` (existing) used for summary generation.
- **New adapters introduced:** `SqlAlchemyTxMemoryEmbeddingRepository`. `TxMemoryRetriever` is implemented as a thin application-layer class wrapping the repo (no separate adapter — the discipline IS the implementation). Plus `FakeTxMemoryEmbeddingRepository` and `FakeTxMemoryRetriever` in `tests/ai/fakes/`.
- **DB migrations required:** yes — `005_tx_memory_embeddings`.
- **OpenAPI surface change:** no.
- **Import-linter contract added:** `name = "ai.memory raw SQL banned in application"; type = "forbidden"; source_modules = ["vaultchain.ai.memory.application"]; forbidden_modules = ["sqlalchemy"]` — application code uses repo ports only; only `ai.memory.infra` may import sqlalchemy. This is the mechanical safeguard against the cross-user-leak class of bug.

---

## Acceptance Criteria

- **AC-phase4-ai-007-01:** Given migration `005_tx_memory_embeddings`, when applied, then table `ai.tx_memory_embeddings(id UUID PK, user_id UUID NOT NULL REFERENCES identity.users(id), tx_id UUID NOT NULL REFERENCES transactions.transactions(id) ON DELETE RESTRICT, summary TEXT NOT NULL CHECK (length(summary) BETWEEN 10 AND 1000), embedding VECTOR(768) NOT NULL, metadata JSONB NOT NULL, came_via_ai BOOLEAN NOT NULL, embedding_model TEXT NOT NULL, embedding_dim INTEGER NOT NULL CHECK (embedding_dim = 768), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (user_id, tx_id))` exists with: ivfflat index `idx_tx_emb_vector USING ivfflat (embedding vector_cosine_ops) WITH (lists=100)` (the lists=100 binding ADR-010 deferred), b-tree index `idx_tx_emb_user_created ON (user_id, created_at DESC)` (for non-vector listing queries by recency), partial index `idx_tx_emb_user_came_via_ai ON (user_id) WHERE came_via_ai = TRUE` (for the V1 "AI-touched only" filter, useful for evals). The `embedding_model` column captures the model used (`gemini-embedding-001`) for forward-compat with V2 re-embed migration. The `embedding_dim` CHECK (= 768) is belt-and-suspenders against accidental dim drift — if ADR-010 is ever revised, the check tells us. Migration is idempotent.

- **AC-phase4-ai-007-02:** Given the `TxMemoryEmbeddingRepository` Protocol in `ai/memory/domain/ports.py`, when defined, then it declares: `async def insert(entry: TxMemoryEntry) -> None` (idempotent on `(user_id, tx_id)` UNIQUE — `INSERT ... ON CONFLICT DO NOTHING`); `async def search(user_id: UUID, query_vector: list[float], *, limit: int, ef_search_probes: int = 10) -> list[TxMemorySearchResult]` (the user-scoped search — `user_id` is a NON-OPTIONAL POSITIONAL kwarg, no default, no `None` allowed; **this is the structural enforcement of the user-scoping invariant**; passing `None` raises `TypeError` at call time); `async def list_by_user(user_id: UUID, *, limit: int, came_via_ai_only: bool = False) -> list[TxMemoryEntry]` (non-vector recency listing). No method that takes anything other than a concrete `user_id: UUID` exists — no `search_all`, no `search_unscoped`, no debug method. The Protocol is `runtime_checkable`.

- **AC-phase4-ai-007-03:** Given the `TxMemoryRetriever` use case in `ai/memory/application/use_cases/search_tx_memory.py`, when invoked via `await retriever.search(user_id, query_text, *, limit=5)`, then it: (1) asserts `user_id is not None` and `isinstance(user_id, UUID)`; (2) calls `EmbeddingsClient.embed_one(query_text, task_type=TaskType.RETRIEVAL_QUERY)` — task_type matches the read-side per Gemini's contract from `phase4-ai-001` AC-07; (3) calls `repo.search(user_id, query_vector, limit=limit)`; (4) returns the result list (already user-scoped by the repo). On `EmbeddingsUnavailableError`, the use case surfaces it (caller handles); does NOT silently return empty (silent-empty would mask outages from the LLM-using caller). Tests verify `user_id is None` raises `ValueError("user_id is required")` immediately, before any external call.

- **AC-phase4-ai-007-04:** Given the `WriteTxMemory` use case in `ai/memory/application/use_cases/write_tx_memory.py`, when invoked via `await writer.execute(user_id, tx_id, *, came_via_ai: bool)`, then within a single UoW: (1) idempotency check — `repo.list_by_user` filtered to this `tx_id` returns non-empty → short-circuit, return existing entry id (ON CONFLICT DO NOTHING also catches concurrent-double-insert at SQL level); (2) fetches transaction view via `transactions.application.queries.get_transaction_view(tx_id, requesting_user_id=user_id)` — the requesting_user_id arg ensures cross-user fetch is impossible; (3) constructs LLM summary prompt: a 200-token instruction asking for a 1-2 sentence factual summary mentioning chain, asset, amount, direction, and counterparty (truncated address); (4) calls `LlmClient.complete(system=SUMMARY_SYSTEM_PROMPT, messages=[user_msg], tools=[], max_tokens=120)` using **Haiku** model (`claude-haiku-4-5-20251001`) NOT Sonnet — ~3× cheaper per token at current Anthropic pricing ($1/$5 per MTok vs Sonnet's $3/$15), sufficient quality for short factual summaries; (5) extracts the summary text, validates length 10–1000 chars; on failure (truncated, refused, gibberish), retries once with stricter system prompt; on second failure, persists a fallback summary `"<chain> <direction> of <amount> <asset> to <to_address[:10]>… on <date>"` constructed deterministically; (6) calls `EmbeddingsClient.embed_one(summary, task_type=TaskType.RETRIEVAL_DOCUMENT)`; (7) builds `MemoryMetadata{chain, asset, value_usd, came_via_admin, was_ai_prepared: came_via_ai}`; (8) constructs `TxMemoryEntry`, calls `repo.insert(entry)`; (9) commits `ai.TxMemoryWritten` event via outbox.

- **AC-phase4-ai-007-05:** Given the LLM summary system prompt in `ai/memory/application/summary_prompt.py`, when imported, then it exports `SUMMARY_SYSTEM_PROMPT: str` (~150 tokens; instructs: "Write a one or two sentence factual summary of this transaction. Mention the chain, the asset, the amount, the direction (sent/received), and the counterparty as the first 10 chars of their address. Do not editorialize. Do not speculate about purpose. Reply with summary text only — no preamble, no closing."), `SUMMARY_SYSTEM_PROMPT_HASH: str` (sha256[:16] for cache-invalidation parity with `phase4-ai-006`'s system prompt). The hash is logged at writer startup for ops visibility.

- **AC-phase4-ai-007-06:** Given the `OnMessageAppended` handler in `ai/memory/application/handlers/`, when an `ai.MessageAppended` event arrives with `has_tool_result=True`, then: (1) loads the message via `MessageRepository.get_by_id(message_id)` from `phase4-ai-002`; (2) iterates `content` looking for `ToolResultBlock`s; (3) for each tool result whose tool_use_id maps to a `prepare_send_transaction` call (cross-reference via `ai.tool_calls` → `ai.prepared_actions`), checks if the prepared_action is `confirmed` AND has `confirmed_transaction_id` set; (4) if yes, enqueues `WriteTxMemory.execute(user_id, tx_id, came_via_ai=True)` via the arq queue (NOT direct invocation — the writer involves an LLM call + embedding call, taking ~2-5 seconds, must not block the subscriber thread). The arq job key is `tx_memory:<tx_id>` — natural idempotency. The handler is itself idempotent (re-firing the same `MessageAppended` event re-enqueues the same arq key, which the worker dedupes).

- **AC-phase4-ai-007-07:** Given the `OnTransactionConfirmed` handler, when `transactions.Confirmed{transaction_id, tx_hash, block_number}` arrives, then: (1) calls `PreparedActionRepository.find_by_confirmed_transaction_id(transaction_id)` (small new helper on the existing repo from `phase4-ai-005`); (2) if a matching PreparedAction exists, this transaction was AI-originated → enqueues `WriteTxMemory.execute(user_id, tx_id, came_via_ai=True)`; (3) if NOT matching (regular wizard-confirmed transaction), enqueues with `came_via_ai=False`. **The choice to memorise non-AI transactions too** is justified: the architecture's V2 "memory-aware tool" will benefit from a corpus that covers all transactions, not just AI-touched ones; deferred to V2 as a cost decision but the writer is built for it. **However**, in V1, non-AI transactions ARE NOT memorised by default — a feature flag `MEMORY_WRITE_NON_AI_TRANSACTIONS` defaults to FALSE, gating step (3); the handler still subscribes (so flipping the flag in V2 doesn't require a new deploy). The flag gates writer execution, not subscription.

- **AC-phase4-ai-007-08:** Given the writer's idempotency guard (`UNIQUE (user_id, tx_id)` + `ON CONFLICT DO NOTHING`), when two arq jobs for the same `(user_id, tx_id)` run concurrently (rare but possible if both subscribers fire near-simultaneously: `ai.MessageAppended` + `transactions.Confirmed`), then: (1) one INSERT succeeds; (2) the other INSERT returns `RETURNING id` empty; (3) the second job's use case detects empty return, fetches the existing row, treats as success, no event re-published. Adapter test simulates this via concurrent `asyncio.gather`. The redundant LLM/embedding calls in the second job are accepted as wasted-but-correct (the logical-correctness invariant trumps the small cost); a future optimisation could check repo before calling LLM, but adds complexity for marginal savings.

- **AC-phase4-ai-007-09:** Given the ivfflat parameters from AC-01 (`lists=100, probes=10`), when the system has ~10k tx_memory rows (V1 realistic upper bound), then: (1) `repo.search(user_id, vector, limit=5)` returns top-5 results in <50ms p95 (measured by an adapter benchmark — single-threaded, after `VACUUM ANALYZE`); (2) recall vs exact-knn baseline is ≥95% on a synthetic-but-realistic corpus (10k rows, 768-dim Gemini-embedded summaries) — a one-shot benchmark in `tests/ai/memory/infra/test_ivfflat_recall.py` builds the corpus, computes exact-knn ground truth via brute-force `ORDER BY embedding <=> $1 LIMIT 5` over a test partition, then runs the indexed query and asserts overlap. **Why these parameters:** with N=10k rows, the rule of thumb `lists ≈ √N → 100` balances index-build time, query speed, and recall; `probes=10` (the canonical default) maintains the 95% recall target. ADR-010 deferred this; documented inline in the migration with rationale.

- **AC-phase4-ai-007-10:** Given the `came_via_admin` flag persisted in `MemoryMetadata`, when a memory entry is constructed and the source transaction had `transactions.transactions.came_via_admin = TRUE` (from `phase3-admin-004` AC-12), then `MemoryMetadata.came_via_admin = True`. This is captured at write-time, not at search-time — the projection is denormalised by design (Regime C). The metadata supports a future "filter to admin-approved only" search (V2), wired into the JSONB column not as a separate column to keep the table narrow.

- **AC-phase4-ai-007-11:** Given the import-linter contract "ai.memory raw SQL banned in application" from the Architecture pointers section, when a synthesised test introduces `from sqlalchemy import select` inside `ai/memory/application/`, then `lint-imports` reports a violation and exits non-zero. A regression test runs `lint-imports` programmatically against a temp-copy with the violation injected. The legitimate sqlalchemy imports remain in `ai/memory/infra/sqlalchemy_tx_memory_repo.py` and pass.

- **AC-phase4-ai-007-12:** Given the property test on **cross-user-leak prevention** (`tests/ai/memory/test_cross_user_leak_properties.py::test_search_never_returns_other_users_rows`), when fuzzed via Hypothesis: for each random configuration `(num_users ∈ [2, 8], rows_per_user ∈ [1, 50], query_text: str)`: (a) seed the in-memory fake repo (or a testcontainers Postgres for a higher-fidelity variant — both modes covered) with `num_users * rows_per_user` rows, splitting users; (b) for each user `u`, call `retriever.search(u, query_text, limit=20)`; (c) assert ALL returned `TxMemorySearchResult.user_id == u`; (d) assert NO returned id appears in other users' corpora; (e) repeat with adversarial query texts that closely resemble other users' summaries (Hypothesis can generate strings near each user's corpus to maximize embedding similarity). Property holds across all 100 generated examples (`@settings(max_examples=100)`). **New mandatory property test #18 for Phase 4** — the most security-critical property test in the entire codebase. **Failure mode**: if this test ever fails on `main`, deployment is rolled back immediately — production data already exposed in the failing branch is grounds for incident response.

- **AC-phase4-ai-007-13:** Given a writer execution that fails at the LLM step (network blip), when retried by arq (default 3 retries with exponential backoff), then: (1) first failure logs warning, retry; (2) second failure ditto; (3) third failure: writer falls back to the deterministic summary (per AC-04 step 5) AND persists with metadata `summary_source: "fallback"`. The row IS persisted (we don't lose the memory entry due to LLM outages — degraded summary is acceptable). Sentry breadcrumb captures `{tx_id, user_id, retry_count, error_class}`. No PII / no summary content in breadcrumb (privacy invariant carried from `phase4-ai-001`).

---

## Out of Scope

- A user-invokable "memory tool" (`search_my_transaction_history`): V2 surface extension; this brief delivers the substrate.
- RAG injection of relevant memories into the chat context window: V2; the architecture mentions this but V1 ships memory as RAG infrastructure, not as a chat-context augmenter.
- `ai.kb_embeddings` (parallel table for product-doc RAG): `phase4-ai-008`.
- Re-embedding migration on model change: V2 backlog (per ADR-010).
- GDPR delete cascade on memory rows: V2.
- Encryption-at-rest of the `summary` column: V2 (architecture's PII pin).
- Per-user opt-out of memory recording: V2 privacy feature; V1 records for all users with no UI surface to control.
- Memorising deposit transactions (received funds): V2 — V1 only memorises confirmed sends. Deposits don't surface through `prepare_send_transaction` and don't trigger this brief's handlers naturally.
- Memorising failed/expired transactions: explicit no — only `transactions.Confirmed` triggers the writer; failed sends are noise.
- A "delete my memory" endpoint: V2.

---

## Dependencies

- **Code dependencies:** `phase4-ai-001` (EmbeddingsClient + LlmClient + ADR-010); `phase4-ai-002` (`Conversation`/`Message` aggregates + `ai.MessageAppended` event); `phase4-ai-003` (cross-context query pattern reference); `phase4-ai-005` (`PreparedAction` repo + `ai.PreparedActionConfirmed` event + `find_by_confirmed_transaction_id` helper); `phase2-transactions-002` (`transactions.Confirmed` event + `get_transaction_view` query — must be exposed as an importable use case in `transactions.application.queries.get_transaction_view`; if currently inlined in router, lift as a small refactor included in this PR — same pattern as `phase4-ai-003`'s `ListUserTransactions` lift).
- **Data dependencies:** migrations 001–004 applied. `transactions.transactions` table has `came_via_admin` column from `phase3-admin-004` AC-12.
- **External dependencies:** `pgvector>=0.3` (Python client) — already pinned by `phase4-ai-001`. `arq>=0.25` for the queue (already pinned by `phase1-shared-004`).
- **Configuration:** new env var `MEMORY_WRITE_NON_AI_TRANSACTIONS` (default `false`; documented in runbook).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/ai/memory/domain/test_tx_memory_entry.py` — construction, summary length validation (10–1000), embedding dim validation (= 768), JSONB metadata round-trip.
- [ ] **Domain unit tests:** `tests/ai/memory/domain/test_memory_metadata.py` — happy construction, JSONB serialisation.
- [ ] **Application tests:** `tests/ai/memory/application/test_search_tx_memory.py` — `user_id is None` raises ValueError; happy path calls embed_one with task_type=RETRIEVAL_QUERY; result list user-scoped. Covers AC-03.
- [ ] **Application tests:** `tests/ai/memory/application/test_write_tx_memory.py` — happy path (LLM summary success, embed, persist, event); LLM-fail-once-then-success retry; LLM-fail-twice fallback to deterministic summary; idempotency on second invocation. Covers AC-04, AC-05, AC-13.
- [ ] **Application tests:** `tests/ai/memory/application/handlers/test_on_message_appended.py` — event with `has_tool_result=False` → no enqueue; with `has_tool_result=True` but no `prepare_send_transaction` tool_use → no enqueue; with confirmed PreparedAction → enqueue with came_via_ai=True. Covers AC-06.
- [ ] **Application tests:** `tests/ai/memory/application/handlers/test_on_transaction_confirmed.py` — AI-originated confirmed → enqueue with came_via_ai=True; wizard-confirmed → no-op when flag off; wizard-confirmed → enqueue with came_via_ai=False when flag on. Covers AC-07.
- [ ] **Concurrency tests:** `tests/ai/memory/application/test_writer_concurrent.py` — two writer jobs racing on same (user_id, tx_id), only one row inserted, both report success. Covers AC-08.
- [ ] **Property tests:** `tests/ai/memory/test_cross_user_leak_properties.py` — covers AC-12 (mandatory).
- [ ] **Adapter tests (testcontainers Postgres + pgvector):** `tests/ai/memory/infra/test_sqlalchemy_tx_memory_repo.py` — INSERT round-trip, ON CONFLICT idempotency, `search(user_id, vector, limit)` returns user-scoped rows in cosine-distance order, `list_by_user` ordering, EXPLAIN shows ivfflat usage.
- [ ] **Adapter benchmarks:** `tests/ai/memory/infra/test_ivfflat_recall.py` — 10k synthetic rows, recall ≥95% vs exact knn, p95 latency <50ms. Covers AC-09.
- [ ] **Architecture tests:** `tests/architecture/test_memory_imports.py` — synthesises `from sqlalchemy import select` in `ai/memory/application/` and asserts `lint-imports` fails. Covers AC-11.
- [ ] **Migration tests:** `tests/ai/memory/infra/test_migration_005_tx_memory_embeddings.py` — apply + rollback, idempotency, ivfflat index present, dim CHECK constraint enforced. Covers AC-01.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass — including the new "ai.memory raw SQL banned in application" contract.
- [ ] `mypy --strict` passes for `vaultchain.ai.memory.*`.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (`ai/memory/domain/` ≥ 95%, `ai/memory/application/` ≥ 90%, `ai/memory/infra/` ≥ 85%).
- [ ] OpenAPI schema unchanged (no API surface in this brief).
- [ ] One new error code (`ai.memory_writer_failed`) registered in `errors-reference.md`.
- [ ] Two new ports declared (`TxMemoryEmbeddingRepository`, `TxMemoryRetriever`) with fakes.
- [ ] One new Alembic revision (`005_tx_memory_embeddings`) committed + applied + rolled-back tested.
- [ ] One new domain event (`ai.TxMemoryWritten`) registered.
- [ ] If `get_transaction_view` was previously inlined in `transactions/delivery/router.py`, it is lifted into `transactions/application/queries/get_transaction_view.py` as part of this PR (small refactor; documented in commit body — same pattern as `phase4-ai-003`).
- [ ] `docs/runbook.md` updated with: `MEMORY_WRITE_NON_AI_TRANSACTIONS` flag default, how to inspect ivfflat performance (`SET ivfflat.probes = N` per-session for tuning), how to interpret cross-user-leak property test failures (rollback procedure).
- [ ] Single PR. Conventional commit: `feat(ai/memory): writer + tx_memory_embeddings + ivfflat config + cross-user-leak property [phase4-ai-007]`.
- [ ] PR description: a sequence diagram of one writer turn (event arrives → handler filters → arq enqueue → worker fetches tx view → LLM Haiku summary → Gemini embed → repo insert with ON CONFLICT) plus a small ER diagram showing `ai.tx_memory_embeddings` ↔ `transactions.transactions` ↔ `identity.users`. Include the cross-user-leak property test as a code block in the PR description.

---

## Implementation Notes

- **Use Haiku, not Sonnet, for summary generation.** Cost: Haiku is ~3× cheaper per token at current Anthropic pricing ($1/$5 per MTok vs Sonnet's $3/$15); output quality for "1-2 sentence factual summary of structured data" is more than sufficient. Reserve Sonnet (or whichever current-generation chat model is configured via `AI_MODEL_CHAT`) for the chat path (`phase4-ai-006`).
- **The `task_type='RETRIEVAL_DOCUMENT'` on writes and `'RETRIEVAL_QUERY'` on reads is the central Gemini-quality optimization** from ADR-010. Both are documented in `phase4-ai-001` AC-07. Tests assert the correct task_type per code path.
- **`SET LOCAL ivfflat.probes = 10`** at the start of search transactions (per-transaction). Document in the repo's `search` method as a comment; the default Postgres probes value is 1, which catastrophically tanks recall (~30% in a 100-list index). The repo opens an explicit transaction for search, sets the GUC, runs the query, returns. Don't rely on session-level config.
- **Don't use SQLAlchemy's `relationship()` between `TxMemoryEntry` and `Transaction`** — they live in different schemas and bounded contexts. Cross-context FKs are declared at the migration level only. Application code joins via explicit queries when needed.
- **The `summary` field is the indexed text**, not the embedding vector. Embedding similarity is over the LLM-generated summary semantics. A direct embedding of e.g. tx_hash would be useless (high-entropy, no semantic structure). Document inline in the migration.
- **Fallback summary format** (AC-04 step 5): `f"{chain.title()} {direction} of {amount} {asset} to {to_address[:10]}… on {created_at:%Y-%m-%d}"`. Deterministic; produced when LLM repeatedly fails. The summary still gets embedded (deterministic strings still produce reasonable vectors) — search still works in degraded mode.
- **Idempotency on the writer is doubled-up**: pre-check via `list_by_user` lookup AND `INSERT ... ON CONFLICT DO NOTHING`. The pre-check saves the LLM/embedding API costs in the common case; the SQL-level ON CONFLICT guards against the race window between check and insert.
- **The `find_by_confirmed_transaction_id` helper on `PreparedActionRepository`** is a one-line addition to `phase4-ai-005`'s repo (technically belonging there but introduced by this brief's needs). PR includes the small helper; tests cover it. Document in commit body.

---

## Risk / Friction

- **The cross-user-leak property test (AC-12) is the most important test in the codebase**, and Hypothesis-driven tests can sometimes find configurations where they're slow. Setting `@settings(max_examples=100, deadline=timedelta(seconds=30))` keeps the budget bounded; document in test file. If the test ever flakes due to timing, *that is a signal*, not a flake — investigate immediately.
- **ivfflat parameters are corpus-size-dependent.** `lists=100` is right for ~10k rows; at 100k rows it should be ~316 (`√N`). The migration captures the V1-realistic value; runbook documents the formula and how to ALTER INDEX in V2 (without downtime: `CREATE INDEX CONCURRENTLY ... new`, swap, drop old). A reviewer asking "what about scale?" gets that answer.
- **Cost of summary generation.** Per-confirmed-AI-tx: ~150 input tokens + ~50 output tokens with Haiku ≈ $0.0001. At 1000 AI-confirmed tx/day in V1: ~$0.10/day. Negligible. At V2 scale (say 10k/day) still under $1/day. Documented in ADR-010's "embedding cost" rationale extension.
- **The handler-fires-twice case** (AC-06 + AC-07 both fire for an AI-confirmed tx — one from the chat message, one from the chain confirmation) costs ~one wasted LLM+embed call (the second writer job's pre-check sees the row, short-circuits but still consumed the arq slot). Acceptable; the alternative (deduplicating subscribers) increases architectural complexity. Document.
- **`came_via_ai=True` for both AC-06 and AC-07's matching path:** important, because if `transactions.Confirmed` arrives before `ai.MessageAppended` (race in the outbox publisher), the handler from AC-07 still correctly identifies the AI origin via `find_by_confirmed_transaction_id`. Tested.
- **Embedding model swap is hostile.** ADR-010 documents this; this brief captures the model in `embedding_model` column for V2 audit. A future re-embed migration: read all rows, batch through new embeddings client, write to a parallel table, atomic rename. Out of V1 scope but the column makes it sane.
- **The `MEMORY_WRITE_NON_AI_TRANSACTIONS` flag is a footgun** — if accidentally flipped to TRUE in V1 production, suddenly every wizard-confirmed transaction generates an LLM call + embed call, ~10× write volume. Default explicitly false; runbook flags this. Consider adding a smoke test that asserts the default at startup (one-line CI check).
- **Reviewer concern: "the writer takes 2-5 seconds per call — what if 1000 transactions confirm at once?"** The arq queue absorbs the load; workers process at their own pace. Backed by `phase1-shared-004`'s outbox publisher pattern, which is durable. The writer can fall behind by an hour without losing data; product impact is "memory-aware features may show stale results during a flood" — V1-acceptable. Documented.
