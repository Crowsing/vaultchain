---
ac_count: 7
blocks:
- phase3-admin-007
complexity: M
context: ledger
depends_on:
- phase2-ledger-001
- phase2-ledger-002
- phase3-transactions-003
- phase3-custody-004
- phase3-admin-004
estimated_hours: 4
id: phase3-ledger-003
phase: 3
sdd_mode: strict
state: ready
title: Withdrawal reservation flow + `internal_rebalance` posting type
touches_adrs: []
---

# Brief: phase3-ledger-003 — Withdrawal reservation flow + `internal_rebalance` posting type


## Context

Phase 2's Ledger handled deposits (single posting on `chain.DepositConfirmed`) and direct withdrawals (single posting on `chain.TransactionConfirmed` for the user's hot-signed tx). Phase 3 adds two scenarios that need richer posting flows:

1. **Withdrawal reservation flow.** When a user requests a withdrawal that's routed to admin (`transactions.RoutedToAdmin`), the user's available hot balance must immediately decrement (so they can't double-spend pending admin approval). When admin approves and the tx confirms, the reservation is settled. When admin rejects (or the tx fails), the reservation is released.

2. **Internal rebalance.** The Custody rebalance worker (phase3-custody-004) moves funds hot→cold. From the user's accounting perspective this is a **wash** — total balance unchanged, just internal redistribution. We post a `internal_rebalance` entry that's filtered from the user-facing transaction history but visible in admin views.

This brief introduces 4 new `posting_type` values plus 2 new `account_kind` values (`user_cold_wallet`, `external_withdraw`) and the corresponding subscriber handlers. Account-key form follows the Phase 2 convention from `phase2-ledger-001`: `<account_kind>:<user_id>:<chain>:<asset>` for user-scoped accounts, `<account_kind>:<chain>` for system-scoped accounts.

- **`withdrawal_reserved`** (debit `user_hot_wallet:<user_id>:<chain>:<asset>`, credit `user_pending_withdrawal:<user_id>:<chain>:<asset>`) — fired on `transactions.RoutedToAdmin`.
- **`withdrawal_unreserved`** (debit `user_pending_withdrawal:<user_id>:<chain>:<asset>`, credit `user_hot_wallet:<user_id>:<chain>:<asset>`) — fired on `transactions.Failed{status_reason: 'admin_rejected' | 'broadcast_failed_after_admin' | 'expired_post_admin'}`.
- **`withdrawal_settled`** (debit `user_pending_withdrawal:<user_id>:<chain>:<asset>`, credit `external_withdraw:<chain>`) — fired on `transactions.Confirmed{came_via_admin: True}`. The "came_via_admin" flag distinguishes from the existing direct-withdrawal posting from Phase 2, which fires on `transactions.Confirmed{came_via_admin: False}` and goes from `user_hot_wallet` directly to `external_withdraw`.
- **`internal_rebalance`** (debit `user_hot_wallet:<user_id>:<chain>:<asset>`, credit `user_cold_wallet:<user_id>:<chain>:<asset>`) — fired on `custody.RebalanceSettled`.

The Phase 2 ledger posting already accommodates an `is_user_visible` field (default true). `internal_rebalance` postings set this to `false` — `GET /api/v1/transactions` (user-facing) filters them out; admin views include them.

The "available balance" for withdrawal validation in `phase3-transactions-003` reads from `user_hot_wallet` only (NOT `user_hot_wallet - user_pending_withdrawal` — pending_withdrawal lives in a separate account, so reading just `user_hot_wallet` after a reservation gives the post-reservation balance). The double-entry invariant naturally enforces this: hot decreases by the reserved amount the moment the reservation posts.

---

## Architecture pointers

- **Layer:** application (subscribers, posting logic) + infra (subscriber wiring).
- **Packages touched:**
  - `ledger/domain/value_objects/posting_type.py` (extend enum with 4 new values)
  - `ledger/application/subscribers/on_routed_to_admin.py` (new — posts withdrawal_reserved)
  - `ledger/application/subscribers/on_admin_rejected.py` (new — posts withdrawal_unreserved on `transactions.Failed{status_reason='admin_rejected'}`)
  - `ledger/application/subscribers/on_admin_confirmed.py` (new — posts withdrawal_settled on `transactions.Confirmed{came_via_admin=True}`)
  - `ledger/application/subscribers/on_rebalance_settled.py` (new — posts internal_rebalance on `custody.RebalanceSettled`)
  - `ledger/domain/entities/posting.py` (extend with `is_user_visible: bool` field — default `True`)
  - `ledger/application/queries/list_user_transactions.py` (extend filter `WHERE is_user_visible = TRUE`)
  - `ledger/infra/migrations/<ts>_phase3_postings.py` (adds is_user_visible column + indexes; backfills existing rows to TRUE)
- **Reads:** `ledger.postings`, `ledger.account_balances` (existing).
- **Writes:** `ledger.postings` (new posting types), `ledger.account_balances` (updated by trigger from Phase 2).
- **Publishes events:** none new (Ledger is a sink, not a source for these flows).
- **Migrations:** Yes (column addition + index; trivial backfill).
- **OpenAPI:** `GET /api/v1/transactions` continues to return only user-visible postings — no schema change.

---

## Acceptance Criteria

- **AC-phase3-ledger-003-01:** Given the migration runs, when applied, then `ledger.postings.is_user_visible BOOLEAN NOT NULL DEFAULT TRUE` exists; existing rows are backfilled to `TRUE`. The migration is idempotent (`IF NOT EXISTS`-style guards). Index `idx_postings_user_visible_created_at ON (user_id, is_user_visible, created_at DESC)` added.

- **AC-phase3-ledger-003-02:** Given `transactions.RoutedToAdmin{transaction_id, user_id, chain, asset, amount_chain_units, fee_chain_units}` is published, when the `on_routed_to_admin` subscriber consumes it, then a `withdrawal_reserved` posting is created within a UoW: debit `user_hot_wallet:<user_id>:<chain>:<asset>`, credit `user_pending_withdrawal:<user_id>:<chain>:<asset>`, `amount = amount_chain_units + fee_chain_units` (reserve the gross). `caused_by_event_id = event.id` UNIQUE (idempotent — re-delivery is a no-op).

- **AC-phase3-ledger-003-03:** Given `transactions.Failed{transaction_id, status_reason, ...}` where `status_reason in ['admin_rejected', 'broadcast_failed_after_admin', 'expired_post_admin']`, when the `on_admin_rejected` subscriber consumes, then a `withdrawal_unreserved` posting reverses the reservation: debit `user_pending_withdrawal:<user_id>:<chain>:<asset>`, credit `user_hot_wallet:<user_id>:<chain>:<asset>`, same amount as the reserve. The subscriber looks up the original `withdrawal_reserved` posting via `transaction_id` to get the exact reservation amount (avoids drift if the original tx had different fee estimate).

- **AC-phase3-ledger-003-04:** Given `transactions.Confirmed{transaction_id, came_via_admin: bool, fee_paid_chain_units, ...}`, when the `on_admin_confirmed` subscriber consumes ONLY when `came_via_admin == True`, then a `withdrawal_settled` posting: debit `user_pending_withdrawal:<user_id>:<chain>:<asset>`, credit `external_withdraw:<chain>`, amount = the original reservation. **A second posting "fee_settlement"** posts the actual fee paid (vs the estimate at reservation): if `actual_fee < estimated_fee`, post a small return credit to `user_hot_wallet:<user_id>:<chain>:<asset>` for the difference. If `actual_fee > estimated_fee` (rare, the build path uses `gas_limit * max_fee_per_gas`), the user is undercharged — post the difference as a debit from `user_hot_wallet:<user_id>:<chain>:<asset>` to `external_withdraw:<chain>`. This keeps the ledger accurate to the chain.

- **AC-phase3-ledger-003-05:** Given `custody.RebalanceSettled{tx_hash, user_id, chain, asset, amount_chain_units, hot_address, cold_address}`, when the `on_rebalance_settled` subscriber consumes, then an `internal_rebalance` posting: debit `user_hot_wallet:<user_id>:<chain>:<asset>`, credit `user_cold_wallet:<user_id>:<chain>:<asset>`. **`is_user_visible = FALSE`** (filtered from user history). The `caused_by_event_id` UNIQUE prevents duplicates.

- **AC-phase3-ledger-003-06:** Given the Phase 2 direct-withdrawal flow (no admin involved), when `transactions.Confirmed{came_via_admin: False}` fires, then the existing Phase 2 subscriber posts `withdrawal_direct` (or whatever name Phase 2 chose — verify it differs from `withdrawal_settled`). **No regression to Phase 2 behavior.**

- **AC-phase3-ledger-003-07:** Given `GET /api/v1/transactions` for a user, when listed, then the response excludes postings where `is_user_visible = FALSE`. So `internal_rebalance` postings do NOT appear in user-visible history; `withdrawal_reserved`, `withdrawal_unreserved`, `withdrawal_settled` DO appear (they affect the user's visible balance arc and should be transparent). **Open question on UX:** showing all 3 reservation/unreservation/settle postings creates a noisy history. **Decision:** group them in the API response by `transaction_id` — return one logical "transaction" entity per `transaction_id` with its full posting timeline. The frontend renders this as a single row with a status pill (Pending / Approved / Rejected / Settled). **Implementation:** the API does the GROUP BY at query time; the test asserts a tier_0 user's withdrawal flow produces ONE row in the API list (with multiple sub-postings nested) rather than 3.

- **AC-phase3-ledger-003-08:** Given the property-test invariant from `phase2-ledger-001` (sum of all postings = 0 per asset), when extended for Phase 3, then for any randomly generated sequence of (deposit, withdraw, route-to-admin, approve/reject, rebalance), the property still holds. **Architecture-mandated invariant — extension verified.**

- **AC-phase3-ledger-003-09:** Given the admin user-detail view (`phase3-admin-007`), when querying transactions, then it includes ALL postings including `internal_rebalance` (the admin needs visibility). The query path is via a separate admin-side ledger query that doesn't filter `is_user_visible`. Phase 3 admin-007 brief implements the UI; this brief delivers the underlying query support.

- **AC-phase3-ledger-003-10:** Given the test environment, when the Ledger subscribers are exercised, then a fixture publishes the relevant events synchronously (in-memory event bus mode for tests) and asserts the postings are created with correct shapes and the account_balances rows reflect the sums.

- **AC-phase3-ledger-003-11:** Given the property test on **no negative `user_hot_wallet` after withdrawal_reserved** (`tests/ledger/domain/test_no_negative_balance_properties.py::test_user_hot_never_negative`), when fuzzed via Hypothesis over random sequences of `(deposit, withdrawal_reserved, withdrawal_unreserved, withdrawal_settled, internal_rebalance)` postings for a single `(user_id, chain, asset)` triple — generated such that any reservation respects the available-balance precondition — then at every intermediate state the `SUM(amount)` projected onto `user_hot_wallet:<user_id>:<chain>:<asset>` is non-negative. The property holds because: (a) the policy refuses to enqueue a reservation that would over-draw hot; (b) the `withdrawal_reserved` posting subtracts from `user_hot_wallet`; the property test asserts (a) + (b) compose correctly. **Architecture-mandated property test (PHASE3-SUMMARY property #9).**

---

## Out of Scope

- Settling fee differences via a "fee_adjustment" posting type instead of inline (AC-04): kept inline for simplicity. V2 polish if reviewers want cleaner audit per-fee.
- Per-asset USD denomination of postings: postings are in chain-native units (per architecture invariant); USD shown in API response is computed at read time from PricingPort.
- Account hierarchy / user-level virtual accounts: out of scope. Account names are flat strings (e.g., `user_hot_wallet:<user_uuid>:ethereum:USDC`), per Phase 2 `phase2-ledger-001` convention.
- Trial-balance reports for treasury reconciliation: V2 admin polish.

---

## Dependencies

- **Code dependencies:** `phase2-ledger-001` (Posting + balances), `phase2-ledger-002` (subscriber pattern), `phase3-transactions-003` (publishes RoutedToAdmin), `phase3-custody-004` (publishes RebalanceSettled), `phase3-admin-004` (publishes Confirmed{came_via_admin=True} and Failed{admin_rejected}).
- **Data dependencies:** `ledger.postings` and `ledger.account_balances` exist.
- **External dependencies:** none.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/ledger/domain/test_posting_type.py` — enum exhaustiveness; the 4 new values added.
- [ ] **Application tests:** `tests/ledger/application/test_on_routed_to_admin.py` — happy path, idempotency on re-delivery (caused_by_event_id collision is silent), correct accounts and amounts. Covers AC-02.
- [ ] **Application tests:** `tests/ledger/application/test_on_admin_rejected.py` — rejection unreserves correctly; status_reason variants exercised; finds original reservation by transaction_id. Covers AC-03.
- [ ] **Application tests:** `tests/ledger/application/test_on_admin_confirmed.py` — settle posts correctly; fee adjustment when actual ≠ estimate; came_via_admin=False short-circuits (no Phase 3 posting). Covers AC-04.
- [ ] **Application tests:** `tests/ledger/application/test_on_rebalance_settled.py` — rebalance posts internal_rebalance with is_user_visible=FALSE. Covers AC-05.
- [ ] **Application tests:** `tests/ledger/application/test_list_user_transactions.py` — internal_rebalance excluded; reservation+unreserve+settle grouped by transaction_id. Covers AC-07.
- [ ] **Property tests:** `tests/ledger/domain/test_double_entry_invariant_phase3.py` — extends Phase 2's property test with Phase 3's events; asserts sum=0 per asset. Covers AC-08.
- [ ] **Property tests:** `tests/ledger/domain/test_no_negative_balance_properties.py` — asserts `user_hot_wallet` balance is non-negative across random sequences of (deposit, reserved, unreserved, settled, rebalance). Covers AC-11.
- [ ] **Adapter tests:** `tests/ledger/infra/test_postings_migration_phase3.py` — testcontainer; migration adds column + index, backfills correctly, idempotent.
- [ ] **Contract tests:** `tests/api/test_transactions_endpoint_phase3.py` — admin-routed tx appears as one logical row; rebalance hidden; direct withdrawal appears normally.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] Migration tested: forward + (in test) backward (drop column); idempotent.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] No new domain events.
- [ ] 4 new posting types exhaustively handled in subscribers.
- [ ] Property test extended; double-entry invariant verified.
- [ ] Single PR. Conventional commit: `feat(ledger): withdrawal reservation flow + internal_rebalance [phase3-ledger-003]`.

---

## Implementation Notes

- The grouping in AC-07 — "one logical row per transaction_id with sub-postings" — adds query complexity. Implementation: use a CTE or subquery to get distinct `transaction_id`s ordered by latest posting timestamp; for each, fetch all its postings; assemble into a response row with `status` derived from the latest posting type. Pseudocode:

```sql
WITH user_txs AS (
  SELECT transaction_id, MAX(created_at) AS latest_at
  FROM ledger.postings
  WHERE user_id = ? AND is_user_visible = TRUE
  GROUP BY transaction_id
  ORDER BY latest_at DESC
  LIMIT ? OFFSET ?
)
SELECT p.* FROM ledger.postings p
JOIN user_txs ut ON p.transaction_id = ut.transaction_id
WHERE p.is_user_visible = TRUE
ORDER BY ut.latest_at DESC, p.created_at ASC
```

The application layer assembles the postings-per-tx into response objects.

- The `withdrawal_unreserved` (AC-03) on `expired_post_admin` is the case where admin approved but cold sign or broadcast subsequently failed/timed out. This is a real edge case — distinct status_reason from `broadcast_failed`. Make sure the Transactions context emits this distinct reason in `phase3-admin-006`.
- Fee adjustment (AC-04) is small but important. The estimate at reservation time is `gas_limit_estimate * max_fee_per_gas` (Ethereum) or chain-equivalent. The actual fee in `Confirmed.fee_paid_chain_units` may differ. Phase 3 ships the inline correction; consider a dedicated `fee_adjustment` posting type in V2 if this gets messy.
- The `internal_rebalance` posting affects `user_cold_wallet:*` balance — this is the first time `user_cold_wallet:*` accounts appear. The account_balances trigger from Phase 2 handles the row creation transparently.
- For the property test (AC-08), enumerate scenarios: deposit → direct withdraw, deposit → admin withdraw approved, deposit → admin withdraw rejected, deposit → admin withdraw approved-but-broadcast-fail, deposit → rebalance → withdraw (cold balance is reserved separately if admin chooses cold-source — out of scope here, but the property holds because all postings net to zero).

---

## Risk / Friction

- The "grouping at query time" (AC-07) is more complex than the alternative of computing a `display_status` field on every posting at write time. Trade-off: query is slower (CTE + join), but writes stay simple and correct. For Phase 3 portfolio scale, the query is fine. V2 could add a `display_status` materialized column if the query becomes a bottleneck.
- The `withdrawal_settled` posting fires on confirm — but the user has already seen the "approved" state when `withdrawal_reserved` exists with `transaction.status='broadcasting'`. The lag between admin approve and on-chain confirm is ~1-3 minutes for Ethereum/Solana, ~1 minute for Tron. The dashboard's transaction timeline shows "approved → broadcasting → confirming (X/12)" naturally.
- A subtle rule: `transactions.Confirmed{came_via_admin: False}` triggers Phase 2's direct-withdrawal posting, not Phase 3's. The `came_via_admin` flag must be propagated by Transactions correctly — verify in `phase3-admin-004`'s tests that the approve-and-confirm path sets `came_via_admin=True` on the confirmed event.
- The `caused_by_event_id` UNIQUE on `ledger.postings` (from Phase 2) is the idempotency guarantee. If a subscriber re-runs (handler crash + retry), the second insert hits UNIQUE and is silently absorbed. **Verify this works for all 4 new posting types** — the UNIQUE is on `caused_by_event_id`, so a single event causing multiple postings (like AC-04's settle + fee adjustment) needs distinct event_ids OR a composite UNIQUE `(caused_by_event_id, posting_type)`. Recommend the composite — implement in this brief's migration. Document.
- The `is_user_visible` flag is technically mutable via UPDATE — if ops needs to retroactively hide a posting for audit reasons, they could set it false. Add audit row to `audit.events` whenever this flag is changed (V2 polish; for V1, add a comment "this column should never be UPDATEd in practice"). Phase 3 ships without trigger enforcement.
