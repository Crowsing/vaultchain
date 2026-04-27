---
ac_count: 7
blocks: []
complexity: M
context: chains
depends_on:
- phase3-chains-005
- phase3-chains-006
- phase3-wallet-002
- phase2-deposit-watcher-001
- phase2-ledger-002
estimated_hours: 4
id: phase3-deposit-watcher-003
phase: 3
sdd_mode: strict
state: ready
title: Solana deposit watcher (logsSubscribe + SPL transfers + finalized commitment)
touches_adrs: []
---

# Brief: phase3-deposit-watcher-003 — Solana deposit watcher (logsSubscribe + SPL transfers + finalized commitment)


## Context

Mirrors the Ethereum and Tron deposit watchers for Solana. Solana-specific differences from EVM-style watching:

- **No EVM logs.** Detection happens via two paths: (a) `accountSubscribe` WebSocket subscription on each user hot address — fires when the account's lamport balance changes (covers native SOL deposits); (b) periodic polling of each user's USDC ATA for SPL token transfers (the SPL-token program emits transfer notifications via account update, but parsing them robustly via WebSocket is brittle in `solana-py`; periodic polling is more reliable).
- **`finalized` commitment.** ~13s confirmation (vs Ethereum's 12 blocks ~150s and Tron's 20 blocks ~60s). Despite the speed advantage, we use `finalized` for ledger-affecting deposits — matches the architectural philosophy of "wait for safety, not speed."
- **Slot-based watermark.** `deposits:solana:last_scanned_slot` in Redis. Solana's slot rate is ~400ms but the watcher polls at 13s intervals (matching `finalized` confirmation latency).
- **No "block by block" scan.** Solana doesn't expose a clean "give me all events in this slot range" API. The watcher uses two complementary strategies: (1) `accountSubscribe` WebSocket for low-latency native deposit detection (best-effort; falls back to periodic polling on disconnect); (2) periodic polling per-user-ATA via `getSignaturesForAddress` to detect SPL transfers (every 13s).

The watcher publishes `chain.DepositDetected` events per detected deposit. The chain-agnostic shape works for Solana too — `wallet_id, address, asset, amount, tx_hash, block_number=slot, chain='solana'`.

The `accountSubscribe` WebSocket approach is the modern best practice for Solana deposit detection — sub-second latency for native deposits. **However, free-tier RPC providers limit WebSocket connections.** Helius free tier: 100 concurrent subscriptions. With 3 chains × 1 hot address per user, the limit binds at ~33 users (only counting Solana). For Phase 3 portfolio scope this is fine. Mainnet would shard or upgrade plan. Document.

The polling-only strategy (no WebSocket) is the safer fallback used in CI tests (where setting up a stable WebSocket against `solana-test-validator` adds complexity). Production may opt for WebSocket-or-polling per env flag `SOLANA_USE_LOGS_SUBSCRIBE`.

---

## Architecture pointers

- **Layer:** application + infra.
- **Packages touched:**
  - `chains/application/jobs/solana_deposit_watcher.py` (arq scheduled job — polling fallback path; runs every 13s)
  - `chains/application/jobs/solana_account_subscriber.py` (long-running WebSocket subscriber, optional via env flag)
  - `chains/application/use_cases/scan_solana_window.py` (per-user-ATA scan logic)
  - `chains/infra/solana_ws_client.py` (long-lived WebSocket connection management, reconnect logic)
- **Reads:** Solana RPC + WebSocket; `wallet.wallets` (user hot addresses on Solana).
- **Writes:** Redis watermarks: `deposits:solana:last_scanned_slot`, `deposits:solana:user_ata_last_sig:<user_id>` (per-user pagination cursor).
- **Publishes events:** `chain.DepositDetected` (already registered in Phase 2).
- **Migrations:** none.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase3-deposit-watcher-003-01:** Given the `SolanaDepositWatcher` arq job, when triggered (cron `*/13 * * * * *` — every 13 seconds), then it: (1) loads all user hot addresses on Solana from `wallet.wallets` (cached 5-min); (2) for each user: derives USDC ATA via `derive_ata(addr, USDC_mint)`; (3) calls `getSignaturesForAddress(ATA, until=<last_sig_for_user>, limit=20, commitment='finalized')`; (4) for each new signature, calls `getTransaction(sig, commitment='finalized')`; (5) parses inner instructions for SPL Transfer to the user's ATA; (6) publishes `DepositDetected` for each match. Updates per-user pagination cursor.

- **AC-phase3-deposit-watcher-003-02:** Given the SPL Transfer detection, when parsing a transaction, then: (1) iterate `transaction.meta.innerInstructions` and `transaction.transaction.message.instructions`; (2) match `program_id == SPL_TOKEN_PROGRAM_ID`; (3) decode the instruction's first byte (3 = Transfer, 12 = TransferChecked); (4) extract source ATA, destination ATA, amount; (5) match destination ATA to known user ATA. **Property test:** for any synthesized SPL Transfer instruction, the parser correctly extracts (src, dest, amount).

- **AC-phase3-deposit-watcher-003-03:** Given native SOL deposit detection via polling fallback, when each cycle runs, then: (1) for each user hot address, calls `get_balance(addr, commitment='finalized')`; (2) compares to `deposits:solana:balance:<addr>` cached value; (3) on increase, queries `getSignaturesForAddress(addr, until=<last_native_sig>, limit=10)` for recent txs; (4) for each, calls `getTransaction` and identifies the SystemProgram::transfer instruction with `to == user_addr`; (5) publishes `DepositDetected{asset='SOL', amount=lamports_in}`.

- **AC-phase3-deposit-watcher-003-04:** Given the optional WebSocket path (`SOLANA_USE_LOGS_SUBSCRIBE=true`), when enabled, then a long-running `SolanaAccountSubscriber` task: (1) opens WebSocket connection to RPC's `accountSubscribe`; (2) for each user hot Solana address, sends a subscribe request; (3) on `accountNotification` callback, computes balance diff vs cache, if increase → queries recent signatures → publishes `DepositDetected`. On disconnect, exponential-backoff reconnect (5s, 10s, 20s up to 60s). On reconnect, resubscribes all addresses. **Polling fallback (`scan_solana_window`) keeps running concurrently** as a safety net even with WebSocket enabled — the LedgerPostingService's idempotency (`caused_by_event_id` UNIQUE) handles dual delivery.

- **AC-phase3-deposit-watcher-003-05:** Given a deposit event published, when emitted, then it includes `chain='solana', block_number=slot_at_finalization, tx_hash=signature_base58`. The `request_id` for the event is `f"solana-deposit-{signature}"` for idempotency.

- **AC-phase3-deposit-watcher-003-06:** Given the WebSocket connection limit (Helius free tier: 100 concurrent subs), when more users exist than the limit, then: (1) the subscriber subscribes only the most-recently-active N-10 addresses (leaving headroom); (2) inactive addresses fall back to polling-only; (3) a hourly job re-evaluates and rotates subscriptions. **Phase 3 portfolio scope (≤30 demo users) doesn't hit the limit** — but the rotation logic is documented for future scale.

- **AC-phase3-deposit-watcher-003-07:** Given a Solana RPC endpoint fails or returns a non-finalized response, when caught, then the watcher logs the issue but proceeds to next cycle. The `finalized` commitment level is enforced — `confirmed`-only responses are not treated as deposits.

- **AC-phase3-deposit-watcher-003-08:** Given the test environment, when adapter tests run, then `solana-test-validator` fixture (from chains-005) provides the local network. Tests: deposit SOL via `airdrop` to user hot address → trigger polling watcher → assert `DepositDetected` event. Mint SPL USDC → transfer to user ATA → trigger watcher → assert event. Cover the WebSocket path with a mock subscriber to avoid maintaining a real WebSocket against test-validator. Polling path is the canonical CI path.

- **AC-phase3-deposit-watcher-003-09:** Given the worker is configured with env `SOLANA_DEPOSIT_WATCHER_ENABLED=true`, when arq scheduler boots, then the polling cron registers and (if `SOLANA_USE_LOGS_SUBSCRIBE=true`) the WebSocket task spawns. In tests, both default to `false` and tests invoke handlers directly.

- **AC-phase3-deposit-watcher-003-10:** Given an SPL transfer where the source ATA balance is INSUFFICIENT to make the transfer (i.e., the on-chain tx reverts), when scanned, then `getTransaction.meta.err` is non-null. The watcher skips this event entirely — only deposits with `err=None` are published. Documented to prevent confusion: a "failed transfer attempt" doesn't credit the user.

---

## Out of Scope

- Subscribe via Geyser plugin (advanced Solana streaming): V2.
- Compressed token deposits: out of scope.
- Devnet airdrop event tracking (filtering airdrops differently from real deposits): not necessary; airdrops are deposits.
- Stake account rewards: out of scope.

---

## Dependencies

- **Code dependencies:** `phase3-chains-005` (SolanaReadAdapter, ATA derivation), `phase3-wallet-002` (Solana wallets in `wallet.wallets`), `phase2-deposit-watcher-001` (watermark Redis utility), `phase2-ledger-002` (subscriber).
- **Data dependencies:** wallet.wallets populated with Solana addresses.
- **External dependencies:** Solana RPC URL (Helius/QuickNode optional but recommended), `websockets` library (bundled with `solana-py`).

---

## Test Coverage Required

- [ ] **Property tests:** `tests/chains/infra/test_spl_transfer_parser_properties.py` — for any synthesized SPL Transfer/TransferChecked instruction, parser correctly extracts (src, dest, amount). Covers AC-02.
- [ ] **Application tests:** `tests/chains/application/test_scan_solana_window.py` — empty signatures list, one SPL transfer to user ATA, multiple SPL transfers, transfer with err=non-null (skipped), native SOL detection via balance diff. Covers AC-01, AC-03, AC-10.
- [ ] **Application tests:** `tests/chains/application/test_solana_account_subscriber.py` — WebSocket connection mock, balance-change notification triggers detection, reconnect logic on disconnect. Covers AC-04, AC-06.
- [ ] **Adapter tests:** `tests/chains/integration/test_solana_deposit_e2e.py` — solana-test-validator fixture; airdrop SOL to user address → trigger watcher → assert `DepositDetected{asset='SOL'}`. Mint USDC → transfer to user ATA → trigger watcher → assert `DepositDetected{asset='USDC'}`. Covers AC-08.
- [ ] **Contract tests:** none.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] No new domain events.
- [ ] `docs/runbook.md` updated: WebSocket vs polling tradeoffs, how to disable, how to inspect watermarks/cursors.
- [ ] Single PR. Conventional commit: `feat(chains): solana deposit watcher [phase3-deposit-watcher-003]`.

---

## Implementation Notes

- The `getSignaturesForAddress(addr, until=<last_seen>, limit=20)` returns signatures NEWER than `until`. Use this for incremental scanning. Initial cursor (no last_seen) starts at the latest signature minus a reasonable backfill window.
- Solana's `inner_instructions` in `getTransaction` response include the "real" transfers when the user-facing instruction is a CPI (cross-program invocation) — e.g., a router calling `spl-token::transfer`. Parse both top-level and inner instructions.
- The `derive_ata` function from `chains-005` is called per user per cycle. Cache results in worker memory (5-min TTL) to avoid re-derivation costs.
- WebSocket reconnect logic: use `websockets` library's `reconnect=True` parameter where supported, else implement explicit backoff loop. Don't use `solana-py`'s built-in WebSocket if it doesn't expose reconnect — fall through to raw `websockets` for control.
- Native SOL transfer detection via balance diff is the same trick as Tron native. The signature-search step (AC-03) ensures we capture the actual tx_hash and block_number.

---

## Risk / Friction

- The "polling every 13s + WebSocket-when-available" hybrid is more complex than a pure-polling design. Resist the urge to remove polling once WebSocket works — WebSocket is unreliable on free tier under network jitter. Polling is the safety net.
- Free-tier RPC quotas: Helius free is 1M req/month. Polling 30 users every 13s × 2 calls per scan = ~6.7M req/month. Either: (a) reduce poll frequency to 30s; (b) batch user-ATA queries (Helius supports batch `getMultipleAccounts`); (c) accept that mainnet would need paid tier. Phase 3 portfolio scope (≤5 demo users) is well under quota even at 13s polling.
- The signature-pagination cursor (`deposits:solana:user_ata_last_sig:<user_id>`) is per-user state. On worker restart, all per-user cursors are valid (they're in Redis, not memory). On Redis flush (rare), the watcher backfills from the latest signature with a small backfill window — could miss deposits older than the window. Document and add a runbook note: "if Redis is flushed, run the SDK's manual reconciliation via `scan_solana_window --backfill-slots=10000` once."
- WebSocket subscription drift: Helius/Solana endpoints occasionally drop subscriptions silently. The polling fallback covers this. Don't over-invest in WebSocket reliability — it's the bonus path.
- Native SOL detection misses if a user receives + sends in same window (same gotcha as Tron). Documented.
