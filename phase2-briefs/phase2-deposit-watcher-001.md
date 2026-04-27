---
ac_count: 8
blocks:
- phase2-ledger-002
complexity: L
context: chains
depends_on:
- phase2-chains-001
- phase2-wallet-001
estimated_hours: 4
id: phase2-deposit-watcher-001
phase: 2
sdd_mode: strict
state: ready
title: Ethereum block scanner → DepositDetected events
touches_adrs: []
---

# Brief: phase2-deposit-watcher-001 — Ethereum block scanner → DepositDetected events


## Context

This brief delivers the Ethereum deposit watcher: an arq scheduled job that scans new blocks, identifies incoming transfers to user-owned addresses (both native ETH and tracked ERC-20s like USDC), and publishes `chain.DepositDetected` events for the Ledger to translate into postings. Without this, on-chain deposits never reach the user-facing balance.

The strategy: a watermark-based scanner. Redis stores `chains:eth:deposits:last_scanned_block`. Every 12 seconds (one Ethereum block on average), the job: (1) reads the watermark; (2) calls `Chains.get_block_number()` to find the latest finalized block; (3) computes a scan window `[watermark+1, latest - confirmation_depth]` where `confirmation_depth=12`; (4) if window is empty (scanner caught up), exits; (5) otherwise, scans up to 100 blocks per run (cap to bound RPC cost).

For each block in the window, the job runs **two queries**:
1. **Native ETH:** for each user-owned ETH address, query `eth_getBalance(addr, block)` and compare with the previous block's balance. Diff > 0 means an incoming transfer (this is naive but correct for V1 — it ignores fee dust from outgoing txs because outgoing-tx detection is owned by the broadcast path, not this scanner). For Phase 2 with ≤10 demo users, this is ~10 RPC calls per block — well within rate limits.
2. **ERC-20 transfers:** call `eth_getLogs(from_block, to_block, contracts=[USDC_addr], event_signature='Transfer(address,address,uint256)', topic_2_in=user_addresses)` filtering by `topic[2]` = recipient. Returns Transfer events to user addresses. Each event becomes a `DepositDetected` candidate.

For each detected deposit, before publishing `DepositDetected`, the watcher dedupes against in-flight outgoing transactions: if `tx_hash` matches a `transactions.transactions.tx_hash` row owned by the same user (their own outgoing), skip — it's not an incoming deposit, it's a return-to-self or refund (rare). Otherwise publish.

Reorg handling: the `confirmation_depth=12` buffer means we only post deposits that are 12+ blocks deep. Reorgs at that depth are vanishingly rare on Sepolia. The watermark is only advanced after successfully publishing all events from the scanned block; if publishing fails mid-block, the next run re-scans from the same watermark — duplicate events are absorbed by the Ledger's `caused_by_event_id UNIQUE` per `ledger-002` AC-05.

Phase 2 watches only Ethereum. Phase 3 adds Tron and Solana watchers — same pattern, different RPC primitives. The shape of `chain.DepositDetected` is chain-agnostic, so the Ledger subscriber works without modification.

---

## Architecture pointers

- **Layer:** application (the scan use case) + infra (the worker registration). Reads chain state via `ChainGateway` port from `chains-001`.
- **Packages touched:**
  - `chains/application/jobs/deposit_watcher_ethereum.py` (the arq scheduled job)
  - `chains/application/use_cases/scan_blocks_for_deposits.py` (testable use case under the job)
  - `chains/infra/redis_watermark_store.py` (read/write watermark; thin wrapper)
  - `chains/infra/wallet_address_resolver.py` (gets the list of user-owned ETH addresses; reads from `wallet.wallets` via a port)
  - Composition root wiring (cron registration in `arq` worker)
- **Reads:** Chain RPC (`get_block_number`, `eth_getBalance`, `eth_getLogs`); `wallet.wallets` (via `WalletAddressLister` port); Redis (watermark).
- **Writes:** Redis (watermark advance); outbox (publish `chain.DepositDetected`).
- **Publishes events:** `chain.DepositDetected{wallet_id, address, asset, amount, tx_hash, block_number, log_index}` — registered in `shared/events/registry.py`. `log_index` is included so the same tx producing two ERC-20 transfers (rare batch txs) generates two distinct events with distinct `caused_by_event_id`s.
- **Migrations:** none.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase2-deposit-watcher-001-01:** Given the cron-registered arq job `deposit_watcher_ethereum` runs every 12 seconds, when invoked, then it: (1) reads watermark from Redis (`chains:eth:deposits:last_scanned_block`, default 0 if unset); (2) calls `Chains.get_block_number()`; (3) computes scan window `[max(watermark+1, latest-1000), latest-12]` (cap window at 1000 blocks for RPC limits per `chains-001` AC-06); (4) if window is empty, returns immediately; (5) otherwise calls `ScanBlocksForDeposits(start, end)`. Watermark advances ONLY after the use case returns success.

- **AC-phase2-deposit-watcher-001-02:** Given the `ScanBlocksForDeposits(start_block, end_block)` use case, when invoked, then for each block in range: (1) fetches all user ETH addresses via `WalletAddressLister.list_addresses_by_chain('ethereum')`; (2) for each address, computes native ETH balance diff `eth_getBalance(addr, block) - eth_getBalance(addr, block-1)`; if diff > 0, identifies the incoming tx via `eth_getBlockReceipts(block)` and matches by `to_address` and `value`; publishes `DepositDetected{wallet_id, address, asset='ETH', amount=diff, tx_hash, block_number}`. (3) calls `eth_getLogs(block, block, USDC_addr, Transfer_signature, topic_2_in=user_addresses)`; for each log, publishes `DepositDetected` with `asset='USDC'`, `amount=log.data` decoded as uint256.

- **AC-phase2-deposit-watcher-001-03:** Given a deposit's `tx_hash` matches an existing `transactions.transactions` row owned by the same user (it's the user's own outgoing transaction landing), when checked, then **skip** — do not publish `DepositDetected`. The dedupe check is a SELECT on `transactions.transactions WHERE tx_hash=$1 AND user_id=$2`. **Property test:** for any random sequence of (user-sends-tx, scan-detects-tx), the scanner does not double-count outgoing as incoming.

- **AC-phase2-deposit-watcher-001-04:** Given the watcher publishes a `DepositDetected` event, when constructed, then `caused_by_event_id` (the outbox event_id) is a deterministic function of `(tx_hash, log_index, recipient_address)` — concretely, `uuid.uuid5(NAMESPACE_OID, f'{tx_hash}:{log_index}:{address}')`. **Re-scanning the same block produces the same event_id**, so the Ledger's UNIQUE constraint absorbs duplicates without further work.

- **AC-phase2-deposit-watcher-001-05:** Given a scan-window batch of 100 blocks, when processed, then the use case scans them sequentially; if any block fails (RPC timeout, parse error), the watermark is NOT advanced past the failed block — the next run retries from the same start. Failure escalates to Sentry after 3 consecutive failures.

- **AC-phase2-deposit-watcher-001-06:** Given the first run after a deploy (watermark unset → defaults to 0), when invoked, then the watcher does NOT scan from genesis — instead initializes the watermark to `latest - 12` (the current finalized tip) so first-deploy doesn't drown in historical scanning. Operator can manually set a different watermark via runbook for backfill scenarios.

- **AC-phase2-deposit-watcher-001-07:** Given the watcher detects a `DepositDetected` for an address that doesn't map to a known wallet (race: user deletes wallet, but watcher still has it cached), when checked, then it logs WARN, skips, advances watermark normally. This is a defensive guard — should never fire in V1 (wallets are immutable).

- **AC-phase2-deposit-watcher-001-08:** Given the test environment, when adapter tests run, then Anvil testcontainer (shared from `chains-001`) seeds a known account, broadcasts a transfer to a user-owned address, advances blocks past confirmation depth, runs the scanner, asserts `DepositDetected` event was published with correct fields. ERC-20 path: deploys mock USDC, mints to faucet, transfers to user, scans, asserts USDC `DepositDetected`.

- **AC-phase2-deposit-watcher-001-09:** Given the rate-limit profile, when at steady state with no new deposits, then the worker does ≤2 RPC calls per 12s tick (`get_block_number` + watermark check). On a tick with new blocks, ~3 RPC calls per block scanned (native balance, prev block, getLogs). With 10 user addresses and 100 blocks/run worst-case, that's ~3000 RPC calls per minute peak — within Alchemy free tier (300M CU/month → ~6000 CU/min sustained for 30 days).

- **AC-phase2-deposit-watcher-001-10:** Given the runbook documentation, when committed, then `docs/runbook.md` has a section "Backfilling deposits" describing how to manually set the watermark via Redis CLI (`SET chains:eth:deposits:last_scanned_block <block>`) to force re-scan of a range. Also documents the manual command `arq tasks deposit_watcher_ethereum:trigger` to fire the job out-of-cron.

---

## Out of Scope

- Tron and Solana deposit watchers: Phase 3.
- WebSocket-based block subscriptions (`eth_subscribe('newHeads')`): rejected — adds connection management complexity, polling is fine at portfolio scale.
- Mempool-level deposit detection (showing "incoming, unconfirmed"): V2. The 12-block delay (~3 minutes) is acceptable for Phase 2 demo.
- Cross-chain bridges / wrapped tokens: out of scope.
- Per-user notification on deposit detection (the user sees the balance update via SSE+polling, but no toast): `phase2-notifications-001` adds the toast.
- Reorg handling beyond 12-block depth (deeper reorgs require reconciliation): V2.

---

## Dependencies

- **Code dependencies:** `phase2-chains-001` (`get_block_number`, `get_logs`, `Address`), `phase2-wallet-001` (`WalletAddressLister` port), `phase2-ledger-002` (subscribes to events from this brief).
- **Data dependencies:** wallets provisioned (else nothing to scan for); Redis available.
- **External dependencies:** none new (uses existing chain RPC).

---

## Test Coverage Required

- [ ] **Application tests:** `tests/chains/application/test_scan_blocks_for_deposits.py` — happy path (1 ETH transfer to user → 1 event published), happy path USDC, dedupe with own outgoing tx (no event published), unknown-wallet skip, multi-block batch with mixed events. Uses `FakeChainGateway`, `FakeWalletAddressLister`, `FakeOutbox`. Covers AC-02, AC-03, AC-07.
- [ ] **Application tests:** `tests/chains/application/test_deposit_watcher_orchestration.py` — first-run initializes watermark to tip, subsequent runs advance, failed run does not advance, 1000-block cap respected. Covers AC-01, AC-05, AC-06.
- [ ] **Property tests:** `tests/chains/application/test_deposit_dedupe_properties.py` — for any random sequence of `(user_sends_tx, scanner_runs)` interleaved, no `tx_hash` produces both an outgoing-tx posting AND an incoming-deposit event. Covers AC-03.
- [ ] **Property tests:** `tests/chains/application/test_event_id_determinism.py` — for any `(tx_hash, log_index, address)`, two calls produce the same event_id. Re-scanning same block produces identical event payloads. Covers AC-04.
- [ ] **Adapter tests:** `tests/chains/infra/test_deposit_watcher_anvil.py` — Anvil fixture, full flow: seed account → transfer to user → mine past depth → run scanner → assert event in outbox. Repeats for USDC mock. Covers AC-08.
- [ ] **Adapter tests:** `tests/chains/infra/test_redis_watermark_store.py` — Redis testcontainer, get/set/default-on-missing.
- [ ] **Contract tests:** none — no API.
- [ ] **E2E:** indirect via `phase2-web-006` (faucet flow → deposit detected → balance updates).

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (chains/application 90%, chains/infra 80%).
- [ ] One new domain event registered (`chain.DepositDetected`).
- [ ] One new port `WalletAddressLister` declared in `chains/domain/ports.py` (Wallet exposes the corresponding adapter).
- [ ] Single PR. Conventional commit: `feat(chains): ethereum deposit watcher [phase2-deposit-watcher-001]`.
- [ ] Manual smoke-test step in `docs/runbook.md`: "After first prod deploy, send 0.001 ETH from a personal wallet to a test user's address; within ~3 min, dashboard balance should reflect."

---

## Implementation Notes

- The native ETH balance-diff approach is intentionally simple. Alternative: parse every block's transactions and filter `to_address ∈ user_addresses`. Balance-diff is fewer RPC calls (1 per address per block vs 1 per tx in block × ~100 txs per block). Trade-off: balance-diff misses zero-value transfers (but those aren't deposits anyway).
- For the `eth_getBlockReceipts` lookup to attribute the diff to a specific tx_hash: this RPC method is supported on Alchemy and most full nodes but not all public RPCs. Fallback: iterate `block.transactions` and find the matching `to_address + value`. Document the fallback.
- The `WalletAddressLister` port returns addresses, not wallet entities, to keep the interface narrow. The adapter in `wallet/infra/` implements it as a simple SELECT.
- Watermark in Redis is a single integer. Don't over-engineer with sorted sets or per-block-success markers. Single integer + retry-from-watermark on failure is correct and simple.
- The arq cron registration: `cron(deposit_watcher_ethereum, second={0, 12, 24, 36, 48})`. Five fires per minute, every 12 seconds. Document in worker config.

---

## Risk / Friction

- The dedupe check (own outgoing vs incoming) is the single most error-prone part. If it misses, the user sees their own outgoing tx as a "deposit" — embarrassing. Property test (AC-03) is the safety net.
- Alchemy free tier has hard rate limits. Worst-case scan-100-blocks-with-10-users ~3000 RPC calls in one tick. If a long pause makes the watermark fall behind by 10000 blocks, recovery takes ~100 ticks (~20 minutes). Acceptable, but document the recovery time.
- The 12-second cron interval matches Ethereum's ~12s block time. On slow tick days (worker lag), the watcher may miss its window and double-fire on the next tick — that's fine, watermark is idempotent.
- Phase 2 native-ETH balance-diff approach has a subtle bug surface: if the user sends a tx in the same block they receive one, balance-diff conflates them. Minor issue (the user will see the net effect on dashboard correctly); cite as known limitation in runbook. Phase 3 may switch to per-tx parsing if it matters.
- LocalStack has no equivalent for deposit-watcher tests — Anvil is the only viable target. Document that `solana-test-validator` (Phase 3) plays the same role.
