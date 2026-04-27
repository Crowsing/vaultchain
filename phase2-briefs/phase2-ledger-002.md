---
ac_count: 9
blocks:
- phase2-balances-001
- phase2-deposit-watcher-001
- phase2-faucet-001
complexity: M
context: ledger
depends_on:
- phase2-ledger-001
- phase2-transactions-001
- phase2-transactions-002
- phase2-deposit-watcher-001
estimated_hours: 4
id: phase2-ledger-002
phase: 2
sdd_mode: strict
state: ready
title: Ledger subscribers (deposit/withdrawal posting handlers)
touches_adrs: []
---

# Brief: phase2-ledger-002 — Ledger subscribers (deposit/withdrawal posting handlers)


## Context

This brief wires the Ledger subscribers that translate domain events into balanced postings. Per architecture Section 3 line 92: "When a Transaction transitions to `confirmed`, it publishes a domain event. The Ledger context subscribes and posts the corresponding entries (debit `external_chain`, credit `user_hot_wallet`). When a withdrawal sits in `awaiting_admin`, the Ledger reserves the funds via a debit on `user_hot_wallet` and credit on `user_pending_withdrawal`, then unreserves on rejection or settles on approval."

For Phase 2 (no admin route, no `awaiting_admin` traffic), the active flows are:

1. **Deposit detected.** `chain.DepositDetected{wallet_id, address, asset, amount, tx_hash, block_number}` arrives from the deposit watcher (`phase2-deposit-watcher-001`). Subscriber posts: debit `external_chain:<chain>:<asset>` amount X, credit `user_hot_wallet:<user_id>:<chain>:<asset>` amount X. `posting_type='deposit'`. `caused_by_event_id = event.id` (from outbox metadata).

2. **Withdrawal confirmed (settled).** `transactions.Confirmed{transaction_id, tx_hash, block_number}` arrives. Subscriber loads the Transaction (read-only via repo), posts: debit `user_hot_wallet:<user>:<chain>:<asset>` amount X, credit `external_chain:<chain>:<asset>` amount X. `posting_type='withdrawal_settled'`.

3. **Withdrawal failed/expired.** `transactions.Failed` or `transactions.Expired` arrives. **Phase 2 has no prior reservation** (because Phase 2 has no `awaiting_admin` flow — all txs go straight to `broadcasting`, no money moves until `confirmed`). So the failure handler is a no-op for Phase 2 — but the handler is wired now so Phase 3's `awaiting_admin` flow can hook in without changing event topology. Phase 3 adds: subscriber to `transactions.RoutedToAdmin` posts `withdrawal_reserved` (debit user_hot, credit user_pending); subscriber to `transactions.Failed` (with `status_reason='admin_rejected'`) posts `withdrawal_unreserved` (debit user_pending, credit user_hot).

The `caused_by_event_id` UNIQUE on postings (per `ledger-001` AC-07) makes all subscribers idempotent — re-delivery from the outbox produces zero side effects after the first commit. This is essential because the outbox guarantees at-least-once.

The faucet flow (`phase2-faucet-001`) publishes `faucet.QuickFundCompleted{user_id, chain, asset, amount}` events; this brief wires a Ledger subscriber for that too: `posting_type='faucet_drip'` with debit `faucet_pool:<chain>:<asset>` and credit `user_hot_wallet:<user>:<chain>:<asset>`.

---

## Architecture pointers

- **Layer:** application (handlers/subscribers).
- **Packages touched:**
  - `ledger/application/handlers/on_deposit_detected.py`
  - `ledger/application/handlers/on_transaction_confirmed.py`
  - `ledger/application/handlers/on_transaction_failed.py` (Phase 2: no-op when no prior reservation; Phase 3 fills in)
  - `ledger/application/handlers/on_transaction_expired.py` (same shape as failed)
  - `ledger/application/handlers/on_faucet_drip.py`
  - Subscriber registration in composition root
- **Reads:** `transactions.transactions` (via a thin port `TransactionsReader` exposing only `get_by_id` and `get_by_tx_hash`).
- **Writes:** `ledger.postings`, `ledger.entries` (via `LedgerPostingService.post()`).
- **Subscribes to events:** `chain.DepositDetected`, `transactions.Confirmed`, `transactions.Failed`, `transactions.Expired`, `faucet.QuickFundCompleted`.
- **Publishes events:** `ledger.PostingCommitted` (already declared in `ledger-001`; fires here on every successful subscriber).
- **Migrations:** none.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase2-ledger-002-01:** Given `chain.DepositDetected{wallet_id, asset='ETH', amount='100000000000000000', tx_hash, block_number, chain='ethereum'}` arrives via outbox, when `on_deposit_detected` fires, then it: (1) loads the Wallet by `wallet_id` to get `user_id`; (2) calls `LedgerPostingService.post(posting_type='deposit', entries=[debit external_chain:ethereum:ETH 1e17, credit user_hot_wallet:<user>:ethereum:ETH 1e17], caused_by_event_id=event.id, metadata={tx_hash, block_number})`; (3) returns. Idempotent on duplicate event delivery via `caused_by_event_id UNIQUE`.

- **AC-phase2-ledger-002-02:** Given `transactions.Confirmed{transaction_id, tx_hash, block_number}` arrives, when `on_transaction_confirmed` fires, then it: (1) loads Transaction via `TransactionsReader.get_by_id`; (2) extracts `(user_id, chain, asset, from_address, to_address, amount)`; (3) **In Phase 2, since no prior `withdrawal_reserved` posting exists** (no admin route), posts `posting_type='withdrawal_settled'` with debit `user_hot_wallet:<user>:<chain>:<asset>` amount X, credit `external_chain:<chain>:<asset>` amount X. `caused_by_event_id=event.id`. Phase 3 extension: if `withdrawal_reserved` exists for this transaction, post `withdrawal_settled` debits `user_pending_withdrawal` instead — but Phase 2 doesn't see this branch.

- **AC-phase2-ledger-002-03:** Given `transactions.Failed{transaction_id, status_reason}` or `transactions.Expired{transaction_id}` arrives, when the handler fires, then it: (1) loads the Transaction; (2) checks if a `withdrawal_reserved` posting exists for this transaction (Phase 2: never; Phase 3: maybe); (3) **Phase 2 path**: no posting needed (no money was moved before broadcast); the handler returns successfully. (4) **Phase 3 path** (documented but not implemented): post `withdrawal_unreserved` (debit user_pending, credit user_hot). Phase 2 unit-tests assert the no-op behavior; Phase 3 tests will add the populated path.

- **AC-phase2-ledger-002-04:** Given `faucet.QuickFundCompleted{user_id, chain, asset, amount, tx_hash}` arrives, when `on_faucet_drip` fires, then it posts: debit `faucet_pool:<chain>:<asset>` amount X, credit `user_hot_wallet:<user>:<chain>:<asset>` amount X, `posting_type='faucet_drip'`, metadata={tx_hash}. The `faucet_pool` account is auto-created by `Account.upsert` in `LedgerPostingService` if missing.

- **AC-phase2-ledger-002-05:** Given a duplicate event delivery (same `event_id` arrives twice from outbox), when subscribers fire, then the second invocation hits UNIQUE on `caused_by_event_id`, the `LedgerPostingService` catches the violation, returns the existing Posting, and the subscriber returns success. **No double-posting.** Asserted in property test that re-fires same event N times → exactly one posting row exists.

- **AC-phase2-ledger-002-06:** Given a `chain.DepositDetected` event references an unknown `wallet_id` (e.g., wallet was deleted between detection and processing — shouldn't happen in V1 since wallets are immutable, but defensive), when `on_deposit_detected` fires, then it logs WARN `ledger.deposit.unknown_wallet`, drops the event with a successful ack (no retry — the data is bad). Sentry alert fires.

- **AC-phase2-ledger-002-07:** Given the `TransactionsReader` Protocol, when defined, then it has methods: `async get_by_id(tx_id) -> TransactionView | None`, `async get_by_tx_hash(tx_hash, chain) -> TransactionView | None`. Returns a read-only `TransactionView` dataclass — NOT the full `Transaction` aggregate. **Ledger never sees the state machine internals**, only the fields it needs (`user_id, chain, asset, from_address, to_address, amount`). Anti-corruption boundary preserved per architecture Section 2.

- **AC-phase2-ledger-002-08:** Given the subscriber outbox processing, when an event fails (e.g., DB unavailable mid-handler), then the outbox retries up to 5 times with exponential backoff (5s, 25s, 125s, 625s, 1h). After 5 attempts, dead-letters the event with full payload + last-error and emits a Sentry alert `ledger.handler.dead_letter`. Operator can re-publish manually via runbook procedure.

- **AC-phase2-ledger-002-09:** Given concurrent deposits to the same user wallet (e.g., two separate ERC-20 transfers detected in the same block), when both arrive as separate events, then both subscribers process independently — each gets its own UoW + posting + UNIQUE check. Race-free because PostgreSQL row-level locks (from `ledger-001` AC-05's `SELECT FOR UPDATE`) serialize within the per-user balance check.

- **AC-phase2-ledger-002-10:** Given the runbook documentation, when committed, then `docs/runbook.md` has a new section "Re-publishing dead-lettered ledger events" describing the procedure: query `event_log.dead_letter` for the event, inspect payload, decide whether the underlying issue is fixed, then `INSERT INTO event_log.outbox (...)` to re-queue. Phase 3 adds an admin button for this; Phase 2 is operator-only.

---

## Out of Scope

- Cold tier withdrawal flows (`withdrawal_reserved`, `withdrawal_unreserved`): Phase 3.
- Real-time reconciliation between Ledger and chain (the daily job stub from `ledger-001` stays a stub): Phase 3.
- Per-event metrics / dashboards: V2.
- Manual re-post / correction admin UI: V2.
- Cross-chain swaps (would need `swap_pool` accounts): V2.

---

## Dependencies

- **Code dependencies:** `phase2-ledger-001` (`LedgerPostingService`, `Account`, `Posting`), `phase2-transactions-001` (events declared), `phase2-transactions-002` (events fire), `phase2-wallet-001` (`WalletRepository.get_by_id`).
- **Data dependencies:** all prior migrations applied; outbox publisher running.
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Application tests:** `tests/ledger/application/test_on_deposit_detected.py` — happy path (ETH deposit posts correctly), USDC deposit posts correctly (different asset), unknown wallet → warn + drop, idempotent re-delivery. Covers AC-01, AC-05, AC-06.
- [ ] **Application tests:** `tests/ledger/application/test_on_transaction_confirmed.py` — happy path posts `withdrawal_settled`, idempotent re-delivery. Covers AC-02.
- [ ] **Application tests:** `tests/ledger/application/test_on_transaction_failed.py` — Phase 2 no-op assertion, no posting created. Covers AC-03.
- [ ] **Application tests:** `tests/ledger/application/test_on_faucet_drip.py` — posts `faucet_drip` with correct accounts. Covers AC-04.
- [ ] **Property tests:** `tests/ledger/application/test_subscriber_idempotency.py` — for any random valid event, firing it N times produces exactly one posting; the user balance after N fires equals the balance after one fire. Covers AC-05, AC-09. Builds on `transactions-001`'s idempotency property.
- [ ] **Adapter tests:** none new — uses `LedgerPostingService` already tested in `ledger-001`.
- [ ] **Contract tests:** none — no API.
- [ ] **E2E:** indirect via `phase2-web-006` and `phase2-web-007` flows.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass: `ledger.application` may import `transactions` only via `TransactionsReader` port; no direct entity imports.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gate passes (ledger/application 90%).
- [ ] No new domain events (reuses `PostingCommitted`).
- [ ] One new port `TransactionsReader` declared in `ledger/domain/ports.py`. Phase 2 adapter wraps `TransactionRepository.get_by_id` returning the projection.
- [ ] Single PR. Conventional commit: `feat(ledger): subscribers for deposit/withdrawal/faucet events [phase2-ledger-002]`.

---

## Implementation Notes

- Each subscriber is a small async function: `async def on_X(event: EventEnvelope) -> None`. Registered in composition root via the outbox subscriber registry pattern from `phase1-shared-003`.
- The `TransactionsReader` adapter lives in `ledger/infra/transactions_reader_adapter.py` — it wraps the existing `TransactionRepository` and projects the result. Importing across context schemas is allowed for read-only ports per architecture Section 2.
- For `on_transaction_confirmed`, the handler posts immediately. There's no waiting for receipt monitor — the receipt monitor publishes `chain.TransactionConfirmed`, transactions-002 subscribes and publishes `transactions.Confirmed`, this handler subscribes to `transactions.Confirmed`. Two-hop propagation, but each step is independent and idempotent.
- The metadata JSONB on postings is a stable contract: `{tx_hash: str, block_number: int}` for deposits and withdrawals; `{tx_hash: str}` for faucet drips. Useful for future admin views and debugging.
- Don't try to "optimize" by skipping the `LedgerPostingService.post()` call when the math is trivial — the service enforces the invariants. Always go through it.

---

## Risk / Friction

- The "Phase 2 no-op for failed/expired" pattern is intentional but unusual — reviewers may ask "why subscribe just to no-op?" The answer: registering the handler now means Phase 3 just adds the populated branch without wiring changes. Document inline in the handler.
- Subscriber failures lead to dead-letter; without monitoring, this silently degrades correctness (user's deposit doesn't show on dashboard). The Sentry alert in AC-08 is essential — confirm the alert routing in the runbook.
- Concurrent deposits to the same user (AC-09) are rare on testnet but possible. The row-lock-based serialization is correct; if performance ever matters, consider per-user posting queues. Phase 2 scale doesn't need it.
- `TransactionsReader` is a slight DDD compromise — Ledger reads from another context's table. Pure DDD would suggest event-sourcing the transaction projection inside Ledger. The pragmatic compromise (read-only port, projection dataclass, no entity import) preserves the boundary without the projection-table overhead. Document the rationale once in `architecture-decisions.md` line 90 area if reviewers push back; otherwise, leave it.
