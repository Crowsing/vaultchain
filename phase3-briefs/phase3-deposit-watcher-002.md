---
ac_count: 6
blocks: []
complexity: M
context: chains
depends_on:
- phase3-chains-003
- phase3-chains-004
- phase3-wallet-002
- phase2-deposit-watcher-001
- phase2-ledger-002
estimated_hours: 4
id: phase3-deposit-watcher-002
phase: 3
sdd_mode: strict
state: ready
title: Tron deposit watcher (TRC-20 Transfer events + TRX balance diff)
touches_adrs: []
---

# Brief: phase3-deposit-watcher-002 — Tron deposit watcher (TRC-20 Transfer events + TRX balance diff)


## Context

Mirrors the Ethereum deposit watcher (`phase2-deposit-watcher-001`) for Tron. Polls Shasta blocks at the chain's natural interval, detects incoming native TRX transfers (via balance diff) and TRC-20 transfers (via TronGrid contract events), publishes `chain.DepositDetected` events that the Ledger subscriber consumes to post deposits.

Tron-specific differences from Ethereum:

- **Block interval ~3s.** Watcher polls every 3 seconds (matches block production).
- **Confirmation depth 20 blocks (~60s).** Conservative for testnet; matches the receipt monitor's confirmation depth from `phase3-chains-004`.
- **TRC-20 events via TronGrid REST API.** The endpoint `/v1/contracts/{contract}/events?event_name=Transfer&min_block_number={n}&max_block_number={n+1000}` returns events for the contract. Unlike Ethereum's `eth_getLogs` which spans many contracts, Tron requires per-contract queries. **Watcher iterates over the asset catalog's known TRC-20 contracts** (just USDT in Phase 3) per scan window.
- **Native TRX deposits.** No "log" exists for native transfers; watcher detects via balance diff: query `getaccount` for each user's hot address, compare to last-known. If balance increased, scan recent block range for transactions to that address (`/v1/accounts/{addr}/transactions?only_to=true&min_timestamp={last_check}`), filter for `TransferContract` (native), publish events.
- **Watermark in Redis.** Last scanned block per chain: `deposits:tron:last_scanned_block`. Persistent across worker restarts.

The watcher publishes `chain.DepositDetected{wallet_id, address, asset, amount, tx_hash, block_number, chain='tron'}` per detected deposit. The chain-agnostic event shape from `phase2-deposit-watcher-001` works for Tron too.

Reorg handling: Tron's BFT consensus rarely reorgs but the 20-block confirmation depth is the safety net. The watcher only publishes events for deposits that are at depth ≥ 20 from the latest finalized block. A scratchpad table `chains.pending_deposits_tron` (or per-chain Redis hash) tracks not-yet-confirmed deposits between detection and depth-confirmation.

---

## Architecture pointers

- **Layer:** application (worker job + use case) + infra (TronGrid client extension).
- **Packages touched:**
  - `chains/application/jobs/tron_deposit_watcher.py` (arq scheduled job)
  - `chains/application/use_cases/scan_tron_window.py` (per-window scanning logic)
  - `chains/infra/tron_read_adapter.py` (extend with `get_account_transactions` if not in chains-003)
  - `chains/infra/redis_deposit_watermark.py` (already from phase2-deposit-watcher-001; reuse generically)
- **Reads:** TronGrid RPC + REST API; Redis watermark; `wallet.wallets` (to know which addresses to scan).
- **Writes:** Redis watermark + pending-deposits scratch.
- **Publishes events:** `chain.DepositDetected` (already registered in Phase 2).
- **Migrations:** none (Redis-only state).
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase3-deposit-watcher-002-01:** Given the `TronDepositWatcher` arq job, when triggered (cron `*/3 * * * * *` — every 3 seconds), then it: (1) reads the watermark `deposits:tron:last_scanned_block` from Redis (default: latest_block - 100 if missing); (2) computes scan window `(last_scanned + 1, min(last_scanned + 1000, latest - 20))` — the `latest - 20` enforces 20-block confirmation depth; (3) if window is empty (caught up), exits; (4) scans the window for deposits; (5) updates watermark to window's end. Concurrency: single instance via arq's `keep_result=False` and worker's `max_jobs=1` for this specific job (no parallel scans).

- **AC-phase3-deposit-watcher-002-02:** Given the scan finds a TRC-20 USDT transfer to a user's hot address, when processed, then it: (1) queries TronGrid `/v1/contracts/{USDT_contract}/events?event_name=Transfer&min_block_number={from}&max_block_number={to}` — returns events with `result.to`, `result.value`, `transaction_id`, `block_number`; (2) filters events where `result.to` matches a known user hot address (loaded from `wallet.wallets` for chain='tron', cached in worker memory with 5-minute TTL); (3) for each match, publishes `chain.DepositDetected{wallet_id, address, asset='USDT', amount=int(value), tx_hash=transaction_id, block_number, chain='tron'}`.

- **AC-phase3-deposit-watcher-002-03:** Given the scan checks for native TRX deposits, when processed, then for each user hot address on Tron: (1) calls `tron.get_account_balance(addr)` — current balance; (2) compares to last-known balance from Redis cache `deposits:tron:balance:<addr>`; (3) if `current > last_known`, scans `/v1/accounts/{addr}/transactions?only_to=true&min_timestamp={last_check_ms}` for incoming TransferContract; (4) for each, publishes `DepositDetected{...asset='TRX'...}`. Updates the last-known balance cache. **Critically: the balance-diff method can miss simultaneous outgoing+incoming if both happen in the same window** — accept this as a known limitation; the once-per-3s polling makes it rare.

- **AC-phase3-deposit-watcher-002-04:** Given the watcher publishes a deposit, when emitted, then the event is signed with the same `request_id` pattern as Phase 2 — uniquely identifiable. **The `caused_by_event_id` UNIQUE constraint on Ledger postings is the idempotency guarantee** — if the watcher republishes a deposit (e.g., on restart), the Ledger subscriber's `caused_by_event_id` collision short-circuits.

- **AC-phase3-deposit-watcher-002-05:** Given a TronGrid query returns 0 events for a window, when processed, then the watcher proceeds normally (advances watermark, no events published). No retries beyond the standard adapter-level fallback (chains-003).

- **AC-phase3-deposit-watcher-002-06:** Given TronGrid is unreachable for >5 minutes, when monitored, then a Sentry alert fires (existing infra). The watermark stays put; on recovery, the watcher catches up by scanning the missed window. A 1000-block scan window cap prevents runaway scans on extended outages — the watcher logs `tron_deposit_watcher.lag` if `latest_block - watermark > 5000` (~4 hours), flagging operator attention.

- **AC-phase3-deposit-watcher-002-07:** Given the user's wallet was provisioned only seconds before a deposit, when the watcher's address-cache is stale (5-minute TTL), then the deposit is missed in the current cycle but caught in the next (within 5 minutes worst case). **Acceptable** for testnet; documented as a known small-latency-on-fresh-wallets behavior.

- **AC-phase3-deposit-watcher-002-08:** Given the test environment, when adapter tests run, then vcrpy cassettes provide deterministic TronGrid responses. Tests cover: empty window, one TRC-20 event, multiple events in one window, native TRX detection via balance diff, address-cache staleness behavior, watermark advancement.

- **AC-phase3-deposit-watcher-002-09:** Given the worker is configured with env `TRON_DEPOSIT_WATCHER_ENABLED=true`, when arq scheduler boots, then the cron registers. In tests, the env is `false` and the cron doesn't auto-fire; tests invoke `scan_tron_window` directly.

---

## Out of Scope

- WebSocket-based event streaming: TronGrid free tier doesn't expose this reliably; polling is fine.
- TRC-10 token deposits: out of scope (not in asset catalog).
- Smart contract deposit destinations (deposits to a contract our user owns via TVM proxy): out of scope.
- Cross-shard awareness: Tron isn't sharded.

---

## Dependencies

- **Code dependencies:** `phase3-chains-003` (TronReadAdapter), `phase3-wallet-002` (asset catalog finalized), `phase2-deposit-watcher-001` (Redis watermark utility), `phase2-ledger-002` (the Ledger subscriber that consumes `DepositDetected`).
- **Data dependencies:** `wallet.wallets` populated with Tron hot addresses; `custody.rebalance_config` for Tron exists (deposits trigger rebalance eventually).
- **External dependencies:** TronGrid REST API access (`TRONGRID_API_KEY`).

---

## Test Coverage Required

- [ ] **Application tests:** `tests/chains/application/test_scan_tron_window.py` — empty window, one TRC-20 deposit, multiple deposits, balance diff for native TRX, no-match (transfer to non-user address), address cache hit/miss. Uses Fakes. Covers AC-02, AC-03.
- [ ] **Application tests:** `tests/chains/application/test_tron_deposit_watcher_orchestration.py` — watermark advancement, depth=20 enforcement, lag detection. Covers AC-01, AC-06.
- [ ] **Adapter tests:** `tests/chains/infra/test_tron_account_transactions.py` — vcrpy cassette, queries `/v1/accounts/.../transactions?only_to=true`, parses TransferContract entries. (Mostly extends chains-003's adapter tests.)
- [ ] **Adapter tests:** `tests/chains/integration/test_tron_deposit_e2e.py` — vcrpy fixture; deposit a known TRX amount + USDT amount to a test address; trigger watcher; assert two `DepositDetected` events emitted with correct shapes. Covers AC-04, AC-08.
- [ ] **Contract tests:** none.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] vcrpy cassettes committed.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] No new domain events (reuses `chain.DepositDetected`).
- [ ] `docs/runbook.md` updated: how to disable Tron deposit watcher, watermark inspection commands.
- [ ] Single PR. Conventional commit: `feat(chains): tron deposit watcher [phase3-deposit-watcher-002]`.

---

## Implementation Notes

- The address-cache reload (5-min TTL) reads `wallet.wallets WHERE chain='tron'`. Keep the query lightweight — single SELECT, projection of `address, id`.
- TronGrid's `/v1/contracts/{contract}/events` endpoint pagination uses `min_block_number` + `max_block_number`. Capped at 200 events per call (free tier). Implement pagination via `fingerprint` cursor.
- Native TRX detection via balance diff is unusual but Tron's lack of native-transfer logs forces it. The alternative (scanning every block's full transaction list) is far more expensive in API quota. Document.
- The `request_id` for published `DepositDetected` events is generated as `f"tron-deposit-{tx_hash}"` — deterministic, so re-publication produces the same id, helping the Ledger subscriber's idempotency.
- Handle TronGrid's 429 rate-limit responses with exponential backoff (already in chains-003's adapter); the watcher inherits this naturally.

---

## Risk / Friction

- TronGrid API quotas at free tier: ~100k requests/day. Watcher polls every 3s = 28800/day per chain just for `get_block_number`. Plus per-window contract event queries (~10/day). Plus per-user balance checks (depends on user count × every cycle = 28800 × N). At N=100 users this is 3M requests/day — exceeds free tier. **Mitigations:** (a) reduce balance-check frequency to once per 30s instead of once per 3s; (b) only check users with non-zero last-known balance + recently-active users; (c) operator upgrades to paid tier ($30/month for 1M req/day at TronGrid). Document.
- The native-transfer "balance diff" misses out-then-in patterns within one window. For testnet portfolio this is acceptable; mainnet would use a more robust solution (full block parsing). Documented limitation.
- vcrpy cassettes for the watcher have lots of moving parts (block numbers advance). Re-recording requires a funded test account on Shasta; document the cassette refresh procedure.
- The 1000-block window cap is TronGrid's. If the watcher falls 1000+ blocks behind, it takes multiple cycles to catch up — at 3 seconds per cycle and 1000 blocks per cycle, recovery from a 5000-block lag is 5 cycles = 15 seconds. Comfortable for testnet outages of <1 hour. Larger gaps need manual intervention.
