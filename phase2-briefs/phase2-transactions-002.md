---
ac_count: 10
blocks:
- phase2-ledger-002
- phase2-notifications-001
- phase2-web-006
- phase2-web-007
complexity: M
context: transactions
depends_on:
- phase2-transactions-001
- phase2-chains-002
- phase2-custody-002
- phase2-pricing-001
- phase2-wallet-001
- phase1-identity-003
- phase1-shared-006
estimated_hours: 4
id: phase2-transactions-002
phase: 2
sdd_mode: strict
state: ready
title: PrepareSendTransaction + ConfirmWithTotp + ExecuteTransaction + API
touches_adrs: []
---

# Brief: phase2-transactions-002 — PrepareSendTransaction + ConfirmWithTotp + ExecuteTransaction + API


## Context

This brief delivers the user-facing send flow as three orchestration use cases plus their HTTP endpoints. Per architecture Section 2 (the dependency graph) and architecture Section 4, the flow is:

1. **`PrepareSendTransaction`** — user types recipient + amount, frontend calls `POST /api/v1/transactions/prepare`. Backend validates address, checks Wallet ownership, fetches fee estimate via Chains, fetches USD value via Pricing, returns a Draft (or updates one) with all fields filled. Status: this is the **Drafts** flow from architecture Section 3 line 252. The user reviews on the "review card" UI.

2. **`ConfirmWithTotp`** — user enters TOTP. Frontend calls `POST /api/v1/transactions/confirm` with `(draft_id, totp_code, idempotency_key)`. Backend: (a) verifies TOTP via `identity-003` use case, (b) calls `ConfirmDraft` from `transactions-001` to materialize a Transaction at `awaiting_totp`, (c) immediately calls the threshold policy — Phase 2's policy is "always pass to broadcasting" (no admin route); Phase 3 introduces the real threshold, (d) transitions the Transaction to `broadcasting`, (e) enqueues `ExecuteTransaction` arq job, (f) returns the Transaction id + status. Synchronous user-facing latency is ~200ms (TOTP verify + draft confirm + outbox write).

3. **`ExecuteTransaction`** (arq job, NOT user-facing endpoint) — pulls the Transaction, calls Custody.SignTransaction → ApprovedTx, calls Chains.broadcast → tx_hash, transitions Transaction to `pending` with `tx_hash`, enqueues `ReceiptMonitor` (from chains-002). On any error, transitions Transaction to `failed` with appropriate `status_reason`, publishes `TransactionFailed` event.

The endpoints exposed: `POST /api/v1/drafts` (create draft), `PATCH /api/v1/drafts/{id}` (update field), `DELETE /api/v1/drafts/{id}`, `GET /api/v1/drafts/{id}` (read), `POST /api/v1/transactions/prepare` (alias for create-or-update draft + return enriched view with fee + USD value), `POST /api/v1/transactions/confirm`, `GET /api/v1/transactions/{id}`, `GET /api/v1/transactions` (list, paginated).

The `ThresholdPolicy` port is introduced here. Phase 2 adapter: `AlwaysPassThresholdPolicy`. Phase 3 replaces it with the real per-chain threshold from architecture Section 1: e.g., 0.1 ETH on testnet, 1000 USDC equivalent. The port keeps Custody and Transactions cleanly separated.

---

## Architecture pointers

- **Layer:** application + delivery + minimal infra (the policy adapter).
- **Packages touched:**
  - `transactions/application/use_cases/prepare_send_transaction.py`
  - `transactions/application/use_cases/confirm_with_totp.py`
  - `transactions/application/jobs/execute_transaction.py` (arq)
  - `transactions/application/handlers/on_transaction_confirmed.py` (subscribes to chain.TransactionConfirmed → updates Transaction status)
  - `transactions/application/handlers/on_transaction_failed.py` / `on_transaction_expired.py`
  - `transactions/domain/services/threshold_policy.py` (Protocol)
  - `transactions/infra/always_pass_threshold_policy.py` (Phase 2 adapter)
  - `transactions/delivery/router.py` (drafts CRUD + transactions endpoints)
  - `transactions/delivery/schemas.py` (Pydantic request/response models)
- **Reads:** Wallet (validate ownership of from_address), Chains (fee estimate via `EstimateFee`, build via `BuildSendTx`), Pricing (USD), Identity (TOTP verify port).
- **Writes:** `transactions.transactions`, `transactions.drafts`, outbox events.
- **Publishes events:** the seven from `transactions-001` (now actually fire here).
- **Subscribes to events:** `chain.TransactionConfirmed`, `chain.TransactionFailed`, `chain.TransactionExpired` (handlers update Transaction status, publish corresponding `transactions.*` events).
- **Migrations:** none new.
- **OpenAPI:** ~7 new endpoints documented.

---

## Acceptance Criteria

- **AC-phase2-transactions-002-01:** Given an authenticated user, when `POST /api/v1/transactions/prepare` is called with `{from_wallet_id, to_address, asset: 'ETH', amount: '50000000000000000'}` (0.05 ETH in wei), then within a single UoW: (1) validate user owns `from_wallet_id`; (2) validate `to_address` via `Address.parse('ethereum', to_address)`; (3) validate `amount > 0`; (4) call `Chains.estimate_fee(chain='ethereum')` for fee data; (5) call `Pricing.GetQuotes(['ETH'])` for USD; (6) create or update the user's draft for this wallet (one draft per wallet — the next call replaces); (7) return `{draft_id, chain, asset, from_address, to_address, amount, fee_estimate, amount_usd, fee_usd, total_usd}`. Idempotent on subsequent calls with same payload.

- **AC-phase2-transactions-002-02:** Given the prepare response returns insufficient balance (current balance < amount + fee), when checked, then the response includes `validation: {sufficient_balance: false, current_balance, required}`. The transaction is NOT blocked at this stage — the frontend renders a warning. Final block happens at confirm time. (This is intentional: the user sees the issue and can adjust without an error toast.)

- **AC-phase2-transactions-002-03:** Given the user enters TOTP, when `POST /api/v1/transactions/confirm` is called with `{draft_id, totp_code: '123456', idempotency_key: '<UUIDv4>'}`, then: (1) TOTP verified via `identity.application.use_cases.verify_totp` (port-injected); on failure, `403 identity.totp_invalid`. (2) Idempotency middleware (shared-006) intercepts duplicate-key — replay returns existing tx. (3) `ConfirmDraft` materializes Transaction at `awaiting_totp`. (4) Inside `confirm_with_totp` domain method, threshold policy is consulted — `AlwaysPassThresholdPolicy` returns `pass`, so transaction transitions `awaiting_totp → broadcasting`. (5) `TransactionRequested` and `Broadcasting` events published. (6) `ExecuteTransaction` arq job enqueued. (7) Response: `{transaction_id, status: 'broadcasting'}` with HTTP 202. Total latency target: <500ms.

- **AC-phase2-transactions-002-04:** Given the `ExecuteTransaction` job runs, when invoked with `transaction_id`, then: (1) load Transaction (must be `broadcasting`); (2) call `Chains.build_send_tx(...)` to construct UnsignedTx; (3) call `Custody.SignTransaction(unsigned_tx, user_id, transaction_id, request_id)` → ApprovedTx; (4) call `Chains.broadcast(approved_tx)` → tx_hash; (5) call `Transaction.mark_pending(tx_hash)` — DB UPDATE — and persist; (6) enqueue `ChainGateway.ReceiptMonitor` for `tx_hash`. On any failure between steps 2 and 5, transition to `failed` with appropriate `status_reason` (`signing_failed`, `broadcast_failed`, etc.) and publish `TransactionFailed` event.

- **AC-phase2-transactions-002-05:** Given a chain monitor publishes `chain.TransactionConfirmed{tx_hash}`, when the subscriber `on_transaction_confirmed` fires, then it: (1) loads Transaction by `tx_hash`; (2) calls `Transaction.mark_confirmed(block_number)` — domain method validates current state is `pending`; (3) persists; (4) publishes `transactions.Confirmed`. Same shape for `Failed` and `Expired` subscribers.

- **AC-phase2-transactions-002-06:** Given the Drafts CRUD endpoints `POST /api/v1/drafts`, `GET /api/v1/drafts/{id}`, `PATCH /api/v1/drafts/{id}`, `DELETE /api/v1/drafts/{id}`, when each is called, then they enforce ownership (user can only see/modify own drafts), return 404 on missing, return 422 on invalid field names. PATCH accepts partial updates `{to_address: "0x..."}` or `{amount: "..."}`.

- **AC-phase2-transactions-002-07:** Given `GET /api/v1/transactions/{id}`, when called by the owner, then returns the full transaction view: `{id, status, status_reason, chain, asset, from_address, to_address, amount, amount_usd, fee_actual_usd, tx_hash, block_number, history, created_at, confirmed_at}`. Status-aware fields: `tx_hash` is null until `pending`, `block_number` until `confirmed`. The `history` is the JSONB array.

- **AC-phase2-transactions-002-08:** Given `GET /api/v1/transactions?status=confirmed&limit=20&offset=0`, when called, then returns paginated list ordered by `created_at DESC`. Filters: `status` (one or more, comma-separated), `chain`, `asset`. Offset-based pagination is sufficient for V1 — cursor pagination is V2 if list grows.

- **AC-phase2-transactions-002-09:** Given a request to `POST /api/v1/transactions/confirm` arrives without the `X-Idempotency-Key` header, when validated, then returns `400 idempotency.key_required`. The middleware from `phase1-shared-006` enforces this for all state-changing endpoints; documented in OpenAPI per architecture Section 4.

- **AC-phase2-transactions-002-10:** Given a malicious user attempts to confirm someone else's draft (passes a `draft_id` they don't own), when validated, then returns `403 transactions.draft_ownership` without leaking whether the draft exists. Same pattern for transactions: foreign tx access returns 404 (not 403, to avoid existence leakage).

- **AC-phase2-transactions-002-11:** Given the `ThresholdPolicy` Protocol, when defined, then it has one method: `async check(transaction: Transaction) -> ThresholdResult` where `ThresholdResult = Literal['pass', 'route_to_admin']`. The `AlwaysPassThresholdPolicy` (Phase 2 adapter) returns `'pass'` unconditionally. Phase 3 brief replaces with `ChainAwareThresholdPolicy` reading from a config table.

---

## Out of Scope

- The threshold policy real implementation: Phase 3.
- Send to internal user (off-chain): V2.
- Multi-asset / batched sends: V2.
- Smart contract interaction beyond ERC-20 transfer: V2.
- Refund / reverse posting on tx failure: V2 (Phase 2 just marks Transaction failed; no Ledger reversal because no money moved yet — withdrawal only posts on `confirmed`).
- The actual deposit handling (incoming transactions): `phase2-deposit-watcher-001`.

---

## Dependencies

- **Code dependencies:** `phase2-transactions-001` (entity + state machine), `phase2-chains-002` (build, broadcast, fee, monitor), `phase2-custody-002` (sign), `phase2-pricing-001` (USD), `phase2-wallet-001` (ownership check), `phase1-identity-003` (TOTP verify port — exposes its use case for cross-context call), `phase1-shared-006` (idempotency middleware).
- **Data dependencies:** all prior migrations applied.
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Application tests:** `tests/transactions/application/test_prepare_send_transaction.py` — happy path, address validation, ownership check, insufficient balance warning. Uses Fakes. Covers AC-01, AC-02.
- [ ] **Application tests:** `tests/transactions/application/test_confirm_with_totp.py` — happy path (threshold passes → broadcasting), TOTP-fail (403), draft-not-owned (403), idempotency replay returns existing tx, threshold route_to_admin (mocked policy returning route_to_admin → asserts transaction status awaiting_admin). Covers AC-03, AC-09, AC-10, AC-11.
- [ ] **Application tests:** `tests/transactions/application/test_execute_transaction.py` — happy path (sign → broadcast → mark_pending → enqueue monitor), signing-failure transitions to `failed`, broadcast-failure transitions to `failed`. Uses Fakes for Chains, Custody. Covers AC-04.
- [ ] **Application tests:** `tests/transactions/application/test_chain_event_handlers.py` — `on_transaction_confirmed` updates status correctly; same for failed/expired. Covers AC-05.
- [ ] **Contract tests:** `tests/api/test_drafts_endpoints.py` — POST/GET/PATCH/DELETE drafts; ownership enforcement; AC-06.
- [ ] **Contract tests:** `tests/api/test_transactions_prepare_confirm.py` — full prepare → confirm flow, idempotency replay, TOTP failure path. Covers AC-01, AC-03, AC-09.
- [ ] **Contract tests:** `tests/api/test_transactions_list.py` — paginated, filtered. Covers AC-08.
- [ ] **E2E:** included in `phase2-web-007`'s Playwright spec for the full send flow.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass: `transactions.application` accesses Custody and Chains via ports only; cross-context invariant ("Custody only sees ApprovedTx, not Transaction") is enforced.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] OpenAPI schema diff: ~7 new endpoints documented; `docs/api-contract.yaml` committed.
- [ ] Seven domain events from `transactions-001` are now actually published in this brief.
- [ ] One new port `ThresholdPolicy` declared in `transactions/domain/services/`. Phase 2 adapter `AlwaysPassThresholdPolicy`.
- [ ] Single PR. Conventional commit: `feat(transactions): prepare/confirm/execute use cases + API [phase2-transactions-002]`.
- [ ] PR description: an end-to-end timing diagram of the user clicking "Confirm" through the SSE confirmation event arriving.

---

## Implementation Notes

- The `ExecuteTransaction` job is the most complex orchestration in Phase 2. Use a small saga-like pattern: each step is a function returning success/failure; on any step failure, transition to failed with a step-specific reason. Unit-test each step individually.
- The TOTP verify port is exposed by Identity as `IdentityTotpVerifier` Protocol with method `verify(user_id, code) -> bool`. Don't import `identity.application.use_cases.verify_totp` directly — go through the port.
- Drafts have one-per-wallet semantics in Phase 2 — calling prepare for the same `from_wallet_id` updates the existing draft. Document inline; users shouldn't see "drafts piling up."
- The history JSONB updates use SQL `UPDATE ... SET history = history || $new_entry::jsonb` — atomic, no read-modify-write.
- For the "ownership check returns 404 on foreign access" pattern, return `404 transactions.not_found` (same code as truly missing). The tradeoff: marginally more confusing for legitimate developers, much harder to enumerate/probe. Document the decision inline in the router.

---

## Risk / Friction

- The end-to-end flow (prepare → confirm → execute → broadcast → monitor → confirm) crosses 5 contexts and 2 worker boundaries. Wiring it up is straightforward; debugging it is hard. Add structured logging at every transition with the `request_id` and `transaction_id` so a single failure can be traced through Sentry.
- The 200ms target latency for `confirm` depends on TOTP verify being cheap (it is — pyotp is microsecond-fast) and the outbox write being fast (it is — single INSERT). If observed latency drifts, profile the UoW to see where time is going.
- The "always pass" threshold policy in Phase 2 means there's no admin route at all — every transaction goes straight to broadcasting. Reviewers may ask "what about the admin queue?" — point to Phase 3 brief which introduces the real policy. Don't preemptively add a stub route_to_admin path; YAGNI.
- The idempotency replay test in this brief is happy-path only (same key returns same response). The deeper property test was in `transactions-001`. Cross-reference in PR.
- Subscribing to chain events here AND having the receipt monitor itself running in chains-002 creates a slight coupling: if the chain monitor publishes events but transactions-002's subscriber crashes mid-processing, the event re-delivers via outbox. Handler must be idempotent — `mark_confirmed` raises `InvalidStateTransition` on already-confirmed tx, which the handler catches and treats as success. Document this pattern.
