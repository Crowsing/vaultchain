---
ac_count: 10
blocks:
- phase3-admin-006
- phase3-ledger-003
- phase3-admin-007
- phase3-admin-008
complexity: M
context: transactions
depends_on:
- phase2-transactions-002
- phase3-transactions-003
- phase3-custody-003
- phase1-admin-002
estimated_hours: 4
id: phase3-admin-004
phase: 3
sdd_mode: strict
state: ready
title: Withdrawal approval queue endpoints + state machine progression
touches_adrs: []
---

# Brief: phase3-admin-004 — Withdrawal approval queue endpoints + state machine progression


## Context

This brief delivers the **server-side admin approval flow** for withdrawals routed by `phase3-transactions-003`. The endpoints live under `/admin/api/v1/withdrawals/*` and are protected by admin auth + TOTP 2FA from Phase 1's admin-002. The flow:

1. **GET `/admin/api/v1/withdrawals?status=awaiting_admin`** — paginated list of pending withdrawals. Filters: `status, chain, asset, min_amount_usd, max_amount_usd, user_email, age_min`. Sort: `created_at DESC` default; `value_usd DESC` available. Returns transaction details + user info (email, KYC tier) + the routing decision row that landed it here (decision_reason).

2. **GET `/admin/api/v1/withdrawals/{id}`** — single withdrawal detail. Includes everything needed for the admin to make the call: tx info, user info (email, KYC tier, account age, recent activity summary), source hot wallet, destination address (if user provided one — flag if it's a fresh address never seen before), USD value at routing time, routing decision row, current hot+cold balance.

3. **POST `/admin/api/v1/withdrawals/{id}/approve`** — admin approves. Body `{totp_code: "123456"}`. The endpoint: (a) verifies admin TOTP via `phase1-admin-002`'s code; (b) loads the transaction, asserts status==`awaiting_admin`; (c) enqueues `ExecuteApprovedTransaction(transaction_id, admin_id, request_id)` arq job; (d) updates transaction status to `approved` (intermediate); (e) returns `202 Accepted`. The arq worker calls `Custody.SignColdTransaction` → `Chains.broadcast` → publishes events. State transitions: `awaiting_admin → approved → broadcasting → confirmed | failed`.

4. **POST `/admin/api/v1/withdrawals/{id}/reject`** — admin rejects. Body `{reason: "<text>", totp_code: "123456"}`. The endpoint: (a) verifies TOTP; (b) loads the tx, asserts status==`awaiting_admin`; (c) calls `Transaction.mark_failed(status_reason='admin_rejected', failure_message=reason, actor_admin_id=admin_id)`; (d) publishes `transactions.Failed{...}`; (e) returns `200 OK`. The Ledger subscriber unreserves on Failed.

State machine progression (extends Phase 2's `phase2-transactions-002` state machine):

```
draft → awaiting_admin → approved → broadcasting → confirmed
                       → rejected (terminal, status=failed, status_reason='admin_rejected')

broadcasting → confirmed | failed (status_reason='broadcast_failed_after_admin' | 'expired_post_admin')
```

Critical invariants:
- `approved → broadcasting` is the only path that uses cold signing.
- A transaction in `awaiting_admin` cannot be modified by the user (no cancel endpoint in V1; admin can reject on user's behalf).
- TOTP is verified per-action — replay-resistant via the existing TOTP-step-counter from admin-002.
- Concurrent approve attempts (two admins click approve simultaneously): the DB row's status check `WHERE status = 'awaiting_admin'` in the UPDATE statement makes the operation atomic; the second admin gets `409 Conflict`.

The `ExecuteApprovedTransaction` arq job is the orchestrator. It's enqueued (not run inline) for two reasons: (a) cold signing involves STS assume-role + KMS calls that may take 1-3 seconds; the API responds quickly; (b) failures during cold sign / broadcast become Sentry-tracked job failures rather than synchronous 500s. The job pattern mirrors `phase2-chains-002`'s receipt monitor.

---

## Architecture pointers

- **Layer:** application (use cases + state machine extension) + presentation (HTTP endpoints).
- **Packages touched:**
  - `transactions/domain/entities/transaction.py` (extend state machine: `approved`, `rejected` states)
  - `transactions/application/use_cases/admin_approve_withdrawal.py`
  - `transactions/application/use_cases/admin_reject_withdrawal.py`
  - `transactions/application/jobs/execute_approved_transaction.py` (arq job orchestrator)
  - `transactions/application/queries/list_admin_withdrawals.py`
  - `transactions/application/queries/get_admin_withdrawal_detail.py`
  - `transactions/web/admin_routes.py` (FastAPI router under `/admin/api/v1/withdrawals`)
  - `docs/openapi/transactions-admin.yaml` (new — the admin endpoints OpenAPI spec)
- **Reads:** `transactions.transactions`, `transactions.routing_decisions`, `identity.users`, `kyc.applicants`, `wallet.wallets`, `custody.cold_wallets` (for balance preview).
- **Writes:** `transactions.transactions` (status transitions), publishes `transactions.AdminApproved`, `transactions.AdminRejected`, `transactions.Failed{status_reason='admin_rejected'}`, `transactions.Confirmed{came_via_admin=True}`.
- **Publishes events:** `transactions.AdminApproved{transaction_id, admin_id, request_id}`, `transactions.AdminRejected{transaction_id, admin_id, reason, request_id}`. Plus the existing `transactions.Failed` and `transactions.Confirmed` (with `came_via_admin` flag).
- **Migrations:** adds `transactions.transactions.came_via_admin BOOLEAN NOT NULL DEFAULT FALSE` column (per AC-12). The status enum extension to add `'approved'` is in the same migration. No new tables.
- **OpenAPI:** new admin spec under `docs/openapi/transactions-admin.yaml`.

---

## Acceptance Criteria

- **AC-phase3-admin-004-01:** Given `GET /admin/api/v1/withdrawals?status=awaiting_admin&page=1&per_page=20`, when called with valid admin auth, then returns `200` with paginated list. Each item: `{id, user: {email, kyc_tier}, chain, asset, amount_chain_units, amount_human, value_usd_at_routing, decision_reason, destination_address, destination_is_fresh: bool, created_at, age_seconds}`. Total count + page metadata included.

- **AC-phase3-admin-004-02:** Given `GET /admin/api/v1/withdrawals/{id}`, when called for an awaiting_admin tx, then returns `200` with full detail: includes user activity summary (last 10 txs, account age, hot/cold balance preview after the proposed withdrawal), destination address history (`destination_seen_count`: how many times this user has sent to this destination), the routing_decisions row that produced this routing.

- **AC-phase3-admin-004-03:** Given `POST /admin/api/v1/withdrawals/{id}/approve` with `{totp_code: "123456"}`, when admin auth is valid AND TOTP code verifies AND transaction status is `awaiting_admin`, then: (1) updates `transactions.transactions.status = 'approved'` atomically (`UPDATE ... WHERE status = 'awaiting_admin'`); (2) records audit row `(admin_id, action='approve_withdrawal', transaction_id, totp_verified=true)`; (3) publishes `transactions.AdminApproved{...}`; (4) enqueues `ExecuteApprovedTransaction(transaction_id, admin_id, request_id)` job; (5) returns `202 Accepted` with `{transaction_id, status: 'approved', queued_at}`.

- **AC-phase3-admin-004-04:** Given `POST /.../approve` where another admin already approved (race), when atomic UPDATE finds 0 rows affected, then returns `409 Conflict` with `{error: 'already_processed', current_status: <whatever>}`. No audit row, no event, no enqueue.

- **AC-phase3-admin-004-05:** Given `POST /.../approve` with invalid TOTP, when verification fails, then returns `401 Unauthorized` with `{error: 'invalid_totp'}`. Audit row recorded with `totp_verified=false`. No state change. **Repeated TOTP failures (>3 in 5 min)** trigger admin lockout per existing admin-002 rate limiter.

- **AC-phase3-admin-004-06:** Given `POST /admin/api/v1/withdrawals/{id}/reject` with `{reason: "Suspicious destination", totp_code: "123456"}`, when valid, then: (1) calls `Transaction.mark_failed(status_reason='admin_rejected', failure_message=reason, actor_admin_id=admin_id)`; (2) records audit row; (3) publishes `transactions.Failed{...}` and `transactions.AdminRejected{...}`; (4) returns `200 OK`. Reason is stored in `transactions.transactions.failure_message`.

- **AC-phase3-admin-004-07:** Given the `ExecuteApprovedTransaction(transaction_id, admin_id, request_id)` arq job runs, when invoked, then: (1) loads the transaction and asserts status=='approved' (defensive check); (2) loads the cold wallet for `(user_id, chain)`; (3) calls `Custody.SignColdTransaction(unsigned_tx_from_transaction, user_id, transaction_id, admin_id, request_id)` → returns `ApprovedTx`; (4) updates status to `broadcasting`; (5) calls `Chains.broadcast(approved_tx)` → returns `tx_hash`; (6) updates `transactions.transactions.tx_hash`; (7) enqueues `ChainGateway.ReceiptMonitor(tx_hash, chain)`. On exception during signing or broadcast, calls `Transaction.mark_failed(status_reason='broadcast_failed_after_admin', failure_message=<exception>)` and publishes `transactions.Failed`.

- **AC-phase3-admin-004-08:** Given a tx in status `broadcasting` (post admin), when receipt monitor publishes `chain.TransactionConfirmed`, then the existing Phase 2 subscriber maps to `Transaction.mark_confirmed(...)` AND **publishes `transactions.Confirmed{came_via_admin=True, ...}`** — the `came_via_admin` flag is set by checking whether the transaction has a `transactions.AdminApproved` event in its history (or simpler: a `came_via_admin` column added to `transactions.transactions` set at approve time). Recommend the column for clean reads.

- **AC-phase3-admin-004-09:** Given the `transactions.transactions.status` field, when migrated for Phase 3, then values are `awaiting_totp, awaiting_admin, approved, broadcasting, pending, confirmed, failed, expired`. **`rejected` is NOT a separate status** — it's `failed` with `status_reason='admin_rejected'` for queryability. **`draft` is NOT a status** — drafts live in a separate `transactions.drafts` table per architecture-decisions.md §"Drafts as separate aggregate". Phase 2 had `awaiting_totp, awaiting_admin, broadcasting, pending, confirmed, failed, expired` (per architecture-decisions.md §"Transaction state machine"); Phase 3 adds `approved`. The state machine in `Transaction` aggregate enforces transitions; e.g., `awaiting_totp → awaiting_admin → (approved | failed[admin_rejected]) → broadcasting → (confirmed | failed[broadcast_failed_after_admin] | expired[expired_post_admin])`. Mypy enum exhaustiveness verifies all transitions are handled.

- **AC-phase3-admin-004-10:** Given the OpenAPI spec for admin endpoints, when `docs/openapi/transactions-admin.yaml` is committed, then it includes 4 endpoints (GET list, GET detail, POST approve, POST reject) with full schemas. The Spectral lint passes (extends from Phase 1's lint config). Schemathesis fuzzes the spec against a running server in CI.

- **AC-phase3-admin-004-11:** Given the admin's permissions (from `phase1-admin-002`), when ANY admin role is sufficient for V1 (no role separation between "approver" and "viewer"), then this brief documents the simplification. V2 introduces "approval-allowed" sub-role.

- **AC-phase3-admin-004-12:** Given the migration adding `transactions.transactions.came_via_admin BOOLEAN NOT NULL DEFAULT FALSE`, when applied, then: (1) all existing rows default to `FALSE` (Phase 2 direct-withdrawal path); (2) `AdminApproveWithdrawal` sets it to `TRUE` in the same UPDATE that transitions status `awaiting_admin → approved`; (3) `transactions.Confirmed` and `transactions.Failed` events read this column to populate the `came_via_admin` event field consumed by ledger-003 subscribers. Migration is idempotent (`IF NOT EXISTS`-style guards).

---

## Out of Scope

- Admin role separation (approver vs viewer): V1 = all admins can approve.
- Multi-signer approval (require 2 admins for txs >$10k): V2.
- Email notification to admins on new pending withdrawals: V2 (notifications context could subscribe to `transactions.RoutedToAdmin` and email the admin team — small extension, deferred for scope).
- Bulk approve/reject: V2.
- Admin override of KYC tier or threshold for a specific tx: V2.

---

## Dependencies

- **Code dependencies:** `phase2-transactions-001/002` (Transaction aggregate + state machine), `phase3-transactions-003` (RoutedToAdmin produces queue entries), `phase3-custody-003` (SignColdTransaction), `phase1-admin-002` (admin auth + TOTP).
- **Data dependencies:** `transactions.transactions` and `transactions.routing_decisions` populated.
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/transactions/domain/test_transaction_state_machine_phase3.py` — extends Phase 2's state machine tests with new transitions (awaiting_admin → approved, awaiting_admin → failed[admin_rejected], approved → broadcasting). All invalid transitions raise.
- [ ] **Application tests:** `tests/transactions/application/test_admin_approve_withdrawal.py` — happy path, idempotency on retry (already-approved 409), TOTP failure path. Covers AC-03, AC-04, AC-05.
- [ ] **Application tests:** `tests/transactions/application/test_admin_reject_withdrawal.py` — happy path, reason persisted, status transitions correctly. Covers AC-06.
- [ ] **Application tests:** `tests/transactions/application/test_execute_approved_transaction.py` — happy path (cold sign + broadcast → status=broadcasting + tx_hash set), signing failure → Failed event, broadcast failure → Failed event. Covers AC-07.
- [ ] **Application tests:** `tests/transactions/application/test_came_via_admin_propagation.py` — verify the came_via_admin flag flows from approve to Confirmed. Covers AC-08.
- [ ] **Contract tests:** `tests/api/test_admin_withdrawals_endpoints.py` — Schemathesis-driven fuzz against the OpenAPI spec; spec validates with Spectral. Covers AC-01, AC-02, AC-10.
- [ ] **Integration tests:** `tests/integration/test_admin_approval_e2e.py` — full flow: user requests withdrawal → routes to admin → admin approves with TOTP → tx broadcasts → confirms → ledger settles correctly. Uses Anvil for Ethereum, in-memory event bus. Covers the full happy path.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] OpenAPI spec lints clean; Schemathesis fuzz passes.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes; Transaction state machine enum exhaustively handled.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] Two new domain events registered (`AdminApproved`, `AdminRejected`).
- [ ] Migration adds `transactions.transactions.came_via_admin BOOLEAN DEFAULT FALSE` column.
- [ ] State machine extended; all transitions are enum-exhaustive.
- [ ] Single PR. Conventional commit: `feat(transactions): admin withdrawal approval queue endpoints [phase3-admin-004]`.

---

## Implementation Notes

- The `destination_is_fresh: bool` flag in AC-01: query `transactions.transactions WHERE user_id = ? AND destination_address = ? AND status = 'confirmed'` — if count is 0, this is a fresh destination. Helps the admin make the call.
- The "admin" user_id (in `audit.events.actor_id` or similar) is the authenticated admin's ID from the admin-002 session. The user-side `audit.events` table from Phase 1's audit context handles cross-context audit; admin actions on behalf of users are recorded with `actor_type='admin'`.
- The arq job `ExecuteApprovedTransaction` could be enqueued with `defer_until=now()` for immediate execution — equivalent to inline-but-async. The latency from approve click to broadcast is ~3-5 seconds: STS assume role (~500ms) + KMS decrypt (~300ms) + sign (~100ms) + broadcast (~500ms) + chain confirmation update. Document.
- The intermediate `approved` status is a brief window (sub-second to a few seconds). If the worker crashes mid-execution, the tx is stuck in `approved`. Recovery: a janitor job (V2 polish, not Phase 3) catches `approved` rows older than 5 minutes and either retries or fails them. Phase 3 acceptable — admin can manually retry by re-approving (which is idempotent at the row-status check level — but the `approved → approved` UPDATE matches 0 rows and 409s; admin would need a "retry stuck tx" button in V2). Document the gap.
- The TOTP-per-action pattern is annoying for admins doing many approvals in a row. V2 polish: a "verified within last 5 minutes" caching window. Phase 3 ships per-action TOTP — security > convenience for portfolio.
- Audit rows: every approve/reject/failed-totp creates a row. The audit-writer is the existing `phase2-audit-001` cross-cutting service.

---

## Risk / Friction

- The "approved" intermediate status that requires a janitor job for stuck txs is a real operational gap. Phase 3 portfolio scope can ship with the documented gap; if a reviewer asks, the answer is "5-minute janitor with auto-retry is V2; manual recovery via direct SQL is current."
- The `came_via_admin` column adds a denormalization. Trade-off: simpler ledger subscriber logic vs an extra column. The alternative (query `transactions.AdminApproved` event for each Confirmed) is more expensive at query time. Column wins.
- TOTP code rotation: admin's TOTP secret was set at admin-002 enrollment. If lost, admin recovery is via the support flow (out of scope here). For portfolio scope, a single hardcoded admin user with known TOTP secret in deploy env is fine — document.
- The state machine has 7 states in Phase 3 (was 6 in Phase 2: draft, pending, broadcasting, confirmed, failed, awaiting_admin). Adding `approved` makes 7. Mypy's `Literal` types catch any unhandled state in match statements. The risk is a developer adding state #8 in V2 without updating all matches — `mypy --strict` + the architecture's exhaustive-state-machine pattern (each transition method enumerates allowed source states) catches this.
- A user could in theory cancel their own withdrawal while it's `awaiting_admin` — but Phase 3 doesn't expose a user-cancel endpoint. The admin "reject" serves as the cancel mechanism. Document.
