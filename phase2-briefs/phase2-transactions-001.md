---
ac_count: 9
blocks:
- phase2-transactions-002
- phase2-ledger-002
complexity: L
context: transactions
depends_on:
- phase1-shared-003
- phase1-shared-005
- phase1-shared-006
estimated_hours: 4
id: phase2-transactions-001
phase: 2
sdd_mode: strict
state: ready
title: Transactions domain (8-status state machine + Drafts)
touches_adrs: []
---

# Brief: phase2-transactions-001 — Transactions domain (8-status state machine + Drafts)


## Context

The Transactions context owns user intent for money movement. Per architecture Section 3 lines 244–256, the model is a **state machine aggregate** with 8 statuses: `awaiting_totp, awaiting_admin, broadcasting, pending, confirmed, failed, expired` (the eighth is `awaiting_totp` listed twice in some references — corrected count: 7 active states + the implicit "draft" living in a separate table = 8 distinct conceptual states, of which 7 are statuses on the `transactions.transactions` row). The split between `awaiting_totp` (short, ~30s) and `awaiting_admin` (long, hours) is deliberate. A `status_reason` column disambiguates `failed_chain` from `failed_admin_rejected` for analytics.

Drafts live in a separate table `transactions.drafts` with nullable fields. They have no state machine, no idempotency, no money impact. When a user confirms in the send wizard, a use case `ConfirmDraft` creates a fresh `Transaction` row at `awaiting_totp` and deletes the draft in the same UoW. There is no `from_draft_id` link.

This brief delivers: the `Transaction` aggregate with the state machine, the `Draft` aggregate, all transitions as domain methods (`request_totp_confirmation`, `confirm_with_totp`, `route_to_admin`, `mark_broadcasting`, `mark_pending`, `mark_confirmed`, `mark_failed`, `expire`), the `TransactionRepository` and `DraftRepository` ports, the migrations creating both tables, and the **mandatory property test** per architecture Section 5 line 2: "for any random valid transition, the state machine has no orphan states; all valid transitions are reachable."

The state machine is enforced at the domain layer by guard methods. Each transition method validates the current state — calling `mark_confirmed()` on a `pending` transaction works; calling it on `awaiting_totp` raises `InvalidStateTransition`. The aggregate stores the full history as an internal list (not persisted as separate rows in V1 — just JSONB in `transactions.history`), so the audit trail of state changes is queryable.

Idempotency keys (`X-Idempotency-Key` header per `phase1-shared-006`) are stored alongside the transaction; a retry with the same key returns the existing transaction without creating a duplicate. Per architecture Section 5 line 6, this realizes the architecture-mandated property test: "same idempotency key returns same response."

---

## Architecture pointers

- **Layer:** domain + application (use cases for state transitions) + infra (repos + migration). Delivery comes in `phase2-transactions-002`.
- **Packages touched:**
  - `transactions/domain/entities/transaction.py` (Transaction aggregate)
  - `transactions/domain/entities/draft.py` (Draft aggregate)
  - `transactions/domain/value_objects/status.py` (`TransactionStatus` enum + `StatusReason` enum)
  - `transactions/domain/services/state_machine.py` (transition validity rules)
  - `transactions/domain/ports.py` (`TransactionRepository`, `DraftRepository`)
  - `transactions/domain/errors.py` (`InvalidStateTransition`, `TransactionNotFound`, `DraftNotFound`)
  - `transactions/application/use_cases/confirm_draft.py` (creates a Transaction from a Draft)
  - `transactions/application/use_cases/transition_state.py` (internal: applies a transition + persists)
  - `transactions/infra/sqlalchemy_transaction_repo.py`, `sqlalchemy_draft_repo.py`
  - `transactions/infra/migrations/<timestamp>_transactions_initial.py`
- **Reads / writes:** `transactions.transactions`, `transactions.drafts`.
- **Publishes events (registered, fired in `transactions-002`):**
  - `transactions.TransactionRequested{transaction_id, user_id, ...}`
  - `transactions.TotpConfirmed{transaction_id}`
  - `transactions.RoutedToAdmin{transaction_id}`
  - `transactions.Broadcasting{transaction_id, tx_hash}`
  - `transactions.Confirmed{transaction_id, tx_hash, block_number}`
  - `transactions.Failed{transaction_id, status_reason}`
  - `transactions.Expired{transaction_id}`
- **Migrations:** `transactions.transactions`, `transactions.drafts`.
- **OpenAPI:** none in this brief — endpoints are in `transactions-002`.

---

## Acceptance Criteria

- **AC-phase2-transactions-001-01:** Given the migration runs, when applied, then `transactions.transactions` exists with columns: `id UUID PK, user_id UUID NOT NULL, idempotency_key TEXT NOT NULL, status TEXT NOT NULL CHECK status IN (...), status_reason TEXT, chain TEXT NOT NULL, asset TEXT NOT NULL, from_address TEXT NOT NULL, to_address TEXT NOT NULL, amount NUMERIC(78,0) NOT NULL, fee_estimate JSONB, tx_hash TEXT, block_number BIGINT, history JSONB NOT NULL DEFAULT '[]', created_at, updated_at, UNIQUE(user_id, idempotency_key)`. Plus `transactions.drafts` with nullable fields: `id UUID PK, user_id UUID NOT NULL, chain TEXT, asset TEXT, to_address TEXT, amount NUMERIC(78,0), memo TEXT, created_at, updated_at`.

- **AC-phase2-transactions-001-02:** Given the `Transaction.create()` factory, when invoked with `(user_id, idempotency_key, chain, asset, from_address, to_address, amount, fee_estimate)`, then it: validates addresses via `Address.parse(chain, ...)`, validates `amount > 0`, sets `status='awaiting_totp'`, appends an initial entry to `history` (`{from: null, to: 'awaiting_totp', timestamp: now}`), and returns the aggregate. Idempotency key is uniqueness-checked at repo level via UNIQUE constraint.

- **AC-phase2-transactions-001-03:** Given a Transaction at status `awaiting_totp`, when `confirm_with_totp()` is called, then it validates the current status (raises `InvalidStateTransition` if not `awaiting_totp`), transitions to `broadcasting` IF the threshold check passes, OR to `awaiting_admin` IF threshold exceeded. **The threshold check itself is NOT in this brief** — `transactions-002` injects a `ThresholdPolicy` port that this method consults. Phase 2's policy implementation always passes (no admin route), so all transitions go to `broadcasting`. The history list gets a new entry.

- **AC-phase2-transactions-001-04:** Given a Transaction at `broadcasting`, when `mark_pending(tx_hash)` is called, then it transitions to `pending`, stores `tx_hash`, appends history. Given `pending`, when `mark_confirmed(block_number)` is called, transitions to `confirmed`, stores `block_number`, appends history. Given `pending`, when `mark_failed(reason)` is called, transitions to `failed` with `status_reason`. Given any non-terminal status, when `expire()` is called, transitions to `expired`. **Terminal states (`confirmed`, `failed`, `expired`) reject all transitions.**

- **AC-phase2-transactions-001-05:** Given the **invalid transitions exhaustive list**, when each is attempted, then `InvalidStateTransition` is raised. **Property test:** Hypothesis enumerates all `(from_status, transition_method)` pairs; for every pair, either the transition is in the valid table or it raises `InvalidStateTransition`. **Architecture-mandated property test (Section 5: state machine has no orphan states, all valid transitions reachable.)**

- **AC-phase2-transactions-001-06:** Given the `Draft.create()` factory, when invoked with `(user_id, chain=None, asset=None, to_address=None, amount=None)`, then it accepts all fields nullable, sets `created_at`, returns the aggregate. The `Draft.update(field, value)` method allows progressive filling: `draft.update('amount', Money(1_000_000_000_000_000_000, 'ETH'))`, etc. No state machine on Draft.

- **AC-phase2-transactions-001-07:** Given the `ConfirmDraft` use case, when invoked with `(draft_id, user_id, idempotency_key, fee_estimate)`, then within a single UoW: (1) loads draft, validates ownership; (2) validates draft has all required fields filled (chain, asset, to_address, amount); (3) creates `Transaction.create(...)` with the draft's data; (4) DELETEs the draft; (5) inserts the transaction; (6) returns the transaction. On idempotency replay (same `idempotency_key`), returns the existing Transaction without creating duplicate.

- **AC-phase2-transactions-001-08:** Given the `TransactionRepository` Protocol, when defined, then methods: `async insert(tx) -> None`, `async get_by_id(tx_id) -> Transaction | None`, `async get_by_idempotency_key(user_id, key) -> Transaction | None`, `async list_by_user(user_id, status=None, limit=50, offset=0) -> list[Transaction]`, `async update(tx) -> None` (UPDATEs the row to reflect new status / fields). The `update` method uses optimistic locking via `updated_at` (raises `ConcurrentModification` on stale write).

- **AC-phase2-transactions-001-09:** Given the idempotency replay test, when the same `(user_id, idempotency_key)` is used in two `Transaction.create()` calls, then the repo's UNIQUE constraint blocks the second; the use case catches it and returns the first transaction. **Property test:** for the same idempotency key invoked N times, exactly one transaction exists, all callers receive the same `transaction_id`. (Architecture-mandated property test, Section 5 line 6.)

- **AC-phase2-transactions-001-10:** Given the `transactions.drafts` cleanup job, when the daily cron fires, then it `DELETE FROM transactions.drafts WHERE updated_at < NOW() - INTERVAL '30 days'`. Stub registered in arq scheduler with cron `0 5 * * *`. Phase 2 doesn't have many drafts; tests verify cleanup removes old rows correctly.

- **AC-phase2-transactions-001-11:** Given the state machine, when a transaction's history is inspected, then `history` is a JSONB array of `{from_status: str | null, to_status: str, timestamp: ISO8601, status_reason: str | null}`. The list is append-only — entries are never modified. Useful for debugging and admin visibility (Phase 3).

---

## Out of Scope

- The actual API endpoints for send / draft CRUD: `phase2-transactions-002`.
- The threshold policy real implementation: Phase 3 (Phase 2 has a stub-pass-through).
- The admin approval queue: Phase 3.
- Cancel / replace transaction (speed up / cancel UI): V2.
- Multi-chain transactions in one operation: out of scope.
- Send to internal-VaultChain-user (off-chain transfer): V2.

---

## Dependencies

- **Code dependencies:** `phase1-shared-003` (UoW, DomainEvent), `phase1-shared-005` (errors), `phase1-shared-006` (idempotency middleware integrates with the UNIQUE constraint here).
- **Data dependencies:** none new.
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/transactions/domain/test_transaction_entity.py` — covers AC-02, AC-03, AC-04 (factory, all valid transitions one-by-one).
- [ ] **Domain unit tests:** `tests/transactions/domain/test_draft_entity.py` — covers AC-06 (factory with nullable fields, update method, validation on partial state).
- [ ] **Property tests:** `tests/transactions/domain/test_state_machine_properties.py` — for every `(status, transition_method)` pair, transition either succeeds (valid) or raises `InvalidStateTransition` (invalid). No orphan states. All valid transitions reachable from `awaiting_totp` through some sequence. Covers AC-05. **Architecture-mandated.**
- [ ] **Property tests:** `tests/transactions/domain/test_idempotency_replay_properties.py` — for the same `(user_id, idempotency_key)`, N concurrent Transaction.create calls produce exactly one row, all return the same id. Uses testcontainer Postgres. Covers AC-09. **Architecture-mandated.**
- [ ] **Application tests:** `tests/transactions/application/test_confirm_draft.py` — happy path, draft missing required fields, ownership mismatch, idempotency replay. Uses Fakes. Covers AC-07.
- [ ] **Adapter tests:** `tests/transactions/infra/test_sqlalchemy_transaction_repo.py` — testcontainer Postgres; INSERT, get_by_id, get_by_idempotency_key, list_by_user, update with optimistic locking (concurrent update raises). Covers AC-08.
- [ ] **Adapter tests:** `tests/transactions/infra/test_drafts_cleanup.py` — seeds drafts with `updated_at` past 30 days, runs cleanup, asserts row count. Covers AC-10.
- [ ] **Contract tests:** none — no API in this brief.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] Both architecture-mandated property tests (state machine, idempotency replay) implemented with ≥200 hypothesis runs in CI.
- [ ] `import-linter` contracts pass: `transactions.domain` may not import `chains`, `custody`, or any non-shared package.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (transactions/domain 95%, transactions/application 90%, transactions/infra 80%).
- [ ] Seven new domain events registered (events fire in `transactions-002`; they're declared here so subscribers in `ledger-002` can compile).
- [ ] Two new ports declared with fakes.
- [ ] Single PR. Conventional commit: `feat(transactions): domain state machine + drafts [phase2-transactions-001]`.
- [ ] PR description: a state-machine diagram (mermaid stateDiagram-v2 with all 7 statuses and valid transitions).

---

## Implementation Notes

- The valid-transitions table is canonical:
  ```
  awaiting_totp     → broadcasting (via confirm_with_totp, threshold pass)
  awaiting_totp     → awaiting_admin (via confirm_with_totp, threshold exceeded)
  awaiting_totp     → expired (via expire)
  awaiting_admin    → broadcasting (via approve, Phase 3)
  awaiting_admin    → failed (via reject, Phase 3, status_reason='admin_rejected')
  awaiting_admin    → expired (via expire)
  broadcasting      → pending (via mark_pending, when tx_hash visible)
  broadcasting      → failed (via mark_failed, status_reason='broadcast_failed')
  pending           → confirmed (via mark_confirmed)
  pending           → failed (via mark_failed, status_reason='failed_chain')
  pending           → expired (via expire, after 5min monitor timeout)
  ```
  Document this in the state-machine diagram in the PR.
- The history JSONB pattern is "append-only list of state changes." A future migration could move this to a separate `transactions.transaction_history` table if querying becomes important. V1 keeps it inline for simplicity.
- Optimistic locking via `updated_at`: every update SET `updated_at = NOW() WHERE updated_at = <prev_updated_at>`. If 0 rows affected, raise `ConcurrentModification`. This is the standard pattern; document inline.
- For the idempotency property test, use `asyncio.gather` with N=10 concurrent calls of `Transaction.create()` with the same key. Assert exactly one row exists in the DB and all callers received the same id (the existing one).

---

## Risk / Friction

- The state-machine property test will catch most bugs. But invalid transitions in the UI (e.g., the user clicking "Cancel" on a `confirmed` tx) need explicit handling at the API layer; the domain just refuses to do invalid work. Document the API behavior plan for `transactions-002`.
- The idempotency UNIQUE constraint is per-user. If a user re-uses the same key for a different intent (different recipient + amount), they get back the OLD tx — not what they expected. The proper handling: idempotency keys are short-lived (5min TTL recommended); the frontend generates a new UUIDv4 per send-attempt. Phase 1's idempotency middleware already enforces TTL; document the contract.
- The 7-status / 8-state-with-Drafts split is a minor naming inconsistency. Use 7-status throughout the code and "8 distinct conceptual states" only when explicitly mentioning Drafts as a state. Avoid drift in error messages and docs.
- Drafts cleanup at 30 days is generous; some users may abandon drafts and return after 60 days expecting them. Document in the user-facing UI's empty state (web-007 brief): "Drafts are cleaned up after 30 days of inactivity."
