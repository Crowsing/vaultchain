---
ac_count: 8
blocks:
- phase2-transactions-002
- phase2-faucet-001
complexity: L
context: chains
depends_on:
- phase2-chains-001
- phase2-custody-002
estimated_hours: 4
id: phase2-chains-002
phase: 2
sdd_mode: strict
state: ready
title: Ethereum write path (build, fee, broadcast, receipt monitor)
touches_adrs: []
---

# Brief: phase2-chains-002 — Ethereum write path (build, fee, broadcast, receipt monitor)


## Context

This brief completes the `ChainGateway` port with the write methods and ships a worker that monitors broadcast transactions to terminal status. Specifically it adds: `build_send_tx` (constructs an EIP-1559 unsigned transaction for native-or-ERC20 sends, fills nonce, gas estimate, fee parameters), `estimate_fee` (returns a `FeeEstimate{base_fee, priority_fee, gas_limit, max_total}`), `broadcast` (submits a signed tx via `eth_sendRawTransaction`), and the `ReceiptMonitor` worker that polls `eth_getTransactionReceipt` for in-flight txs and publishes `chain.TransactionConfirmed` / `chain.TransactionFailed` events when they reach a target confirmation depth.

EIP-1559 fee strategy: `base_fee = block.base_fee_per_gas * 1.125` (the next-block estimate per spec), `priority_fee = max(2 gwei, fee_history.recent_avg_priority_fee)`, `max_fee_per_gas = base_fee * 2 + priority_fee` (room for two doublings before re-broadcast). Gas limit: `eth_estimateGas` + 20% buffer. The result is conservative — txs land reliably without overpaying egregiously. The fee estimate is exposed to the user in the Send screen review card so they see exactly what they'll pay.

The `ReceiptMonitor` worker is an arq job spawned per-broadcast (architecture pattern: `Transactions.execute` enqueues `monitor_receipt(tx_hash)` after successful broadcast). The job polls every 3 seconds for up to 5 minutes; on first receipt seen, switches to a "confirmation depth" mode polling every 5 seconds until depth ≥ 12 blocks (Ethereum finality buffer for portfolio purposes — mainnet would target 32 for safety). On confirmed depth, publishes `chain.TransactionConfirmed`. On status=0 (failed on-chain), publishes `chain.TransactionFailed` with the revert reason if available. On 5-minute timeout without seeing the receipt at all, publishes `chain.TransactionExpired` (Transactions context handles the state transition to `expired`).

Reorg handling: between "first receipt seen" and "depth ≥ 12 confirmed", a reorg can move the tx to a different block. The monitor re-queries each poll and accepts the new block as the canonical home; if the tx disappears from chain entirely (uncle / dropped), it falls back to mempool check for 30 seconds before declaring expired. Documented limitation: deeper reorgs (12+ blocks) are not handled — they require a full reconciliation job, which is V2.

---

## Architecture pointers

- **Layer:** application + infra. Domain has only the new value objects.
- **Packages touched:**
  - `chains/domain/value_objects.py` (extend with `UnsignedTx`, `FeeEstimate`)
  - `chains/domain/ports.py` (extend `ChainGateway` Protocol with write methods)
  - `chains/application/use_cases/build_send_tx.py`, `estimate_fee.py`, `broadcast_tx.py`
  - `chains/infra/ethereum_write_adapter.py` (or extend `ethereum_read_adapter.py` — recommended: rename to `ethereum_adapter.py` covering both)
  - `chains/infra/workers/receipt_monitor.py` (arq job)
  - Composition root wiring for the worker
- **Reads:** Chain RPC (nonce, fee history, gas estimate, receipts).
- **Writes:** RPC `eth_sendRawTransaction` for broadcast.
- **Publishes events:**
  - `chain.TransactionConfirmed{tx_hash, chain, block_number, gas_used, effective_gas_price}` — terminal happy path
  - `chain.TransactionFailed{tx_hash, chain, block_number, revert_reason}` — terminal failure (on-chain failure with status=0)
  - `chain.TransactionExpired{tx_hash, chain, last_seen_block}` — terminal timeout
  - All registered in `shared/events/registry.py`.
- **Migrations:** none — no DB schema needed for monitoring (state lives in arq's Redis queue).
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase2-chains-002-01:** Given `build_send_tx(from_address, to_address, value: Money, asset: Asset, chain='ethereum')` for native ETH send, when invoked, then it: (1) fetches nonce via `eth_getTransactionCount(from, 'pending')`; (2) calls `estimate_fee(chain)`; (3) constructs `UnsignedTx{chain='ethereum', from, to, value, gas_limit=21000, max_fee_per_gas, max_priority_fee_per_gas, nonce, chain_id=11155111, data=b''}`; (4) returns it. The Money is passed in `wei` per architecture Section 3 (`NUMERIC(78,0)` chain-native units).

- **AC-phase2-chains-002-02:** Given `build_send_tx(...)` for ERC-20 transfer (e.g., USDC), when invoked, then: (1) `to` field of the tx is the token contract address, (2) `value` field is 0, (3) `data` field is `transfer(recipient, amount)` ABI-encoded calldata, (4) `gas_limit` is `eth_estimateGas` + 20% buffer (typical: ~65000-75000 for USDC transfer), (5) the rest mirrors AC-01.

- **AC-phase2-chains-002-03:** Given `estimate_fee(chain='ethereum')`, when called, then: (1) calls `eth_feeHistory(blocks=4, newest='pending', reward_percentiles=[50])` getting recent base fees and priority fees; (2) `priority_fee = max(2_000_000_000 wei, percentile_50_of_recent_priority_fees)` — the 2 gwei floor protects against testnet's occasional 0-priority-fee blocks; (3) `base_fee_next = pending_block.base_fee_per_gas * 9 / 8` (1.125× ceiling per spec); (4) `max_fee_per_gas = base_fee_next * 2 + priority_fee`; (5) returns `FeeEstimate{base_fee, priority_fee, gas_limit_estimate, max_total_wei}`. Cached for 12 seconds (one block on Ethereum).

- **AC-phase2-chains-002-04:** Given an `ApprovedTx` from Custody (with `signed_bytes`), when `broadcast(approved_tx)` is called, then: (1) RPC `eth_sendRawTransaction(0x<hex>)` is invoked; (2) on success returns `{tx_hash}` (the same hash the signer computed; cross-checks for sanity); (3) on RPC error mapping: `nonce too low` → `NonceConflict` (caller decides retry strategy), `insufficient funds for gas` → `InsufficientGas`, `replacement transaction underpriced` → `ReplacementUnderpriced`, anything else → `ChainUnavailable`. **Critically: the broadcast log entry does NOT include `signed_bytes` content** — only `tx_hash`. (Audit log of the sign event in Custody already covered the hash; this brief just extends the no-leakage pattern.)

- **AC-phase2-chains-002-05:** Given the `ReceiptMonitor.monitor_receipt(tx_hash, chain)` arq job is invoked, when running, then: (1) polls `get_transaction(tx_hash)` every 3 seconds; (2) on first receipt seen with `block_number != None`, captures `seen_at_block`; (3) switches to 5-second polling, comparing `current_block - seen_at_block`; (4) on `confirmation_depth >= 12`, publishes `chain.TransactionConfirmed` and exits; (5) on receipt with `status=0`, fetches revert reason via `debug_traceTransaction` (best-effort — public RPC may not support it; fallback to "execution reverted") and publishes `chain.TransactionFailed`, exits.

- **AC-phase2-chains-002-06:** Given `monitor_receipt` runs longer than 300 seconds without seeing the receipt at all (tx never mined, perhaps due to insufficient gas or replaced), when timeout fires, then it publishes `chain.TransactionExpired{last_seen_block: current_block}` and exits. The Transactions context's `expired` state handler unreserves the ledger withdrawal-pending posting and notifies the user.

- **AC-phase2-chains-002-07:** Given a tx is reorged out of one block and into another between polls (within depth-12 confirmation window), when the monitor detects the new `block_number` differs from `seen_at_block`, then it logs the reorg at WARN level, updates `seen_at_block` to the new block, and continues counting confirmations from the new block. **No special domain event for reorgs at this depth** — they are routine on testnets; deep-reorg handling is out of scope.

- **AC-phase2-chains-002-08:** Given the `UnsignedTx` value object, when constructed, then it validates: `gas_limit > 0`, `max_fee_per_gas >= max_priority_fee_per_gas`, `value >= 0`, `chain_id == 11155111` for ethereum (Phase 2 single-chain). Mismatches raise `InvalidTransaction` (DomainError, mapped to 422).

- **AC-phase2-chains-002-09:** Given the EIP-1559 transaction structure, when serialized for hashing (the input to `pre_hash` in Custody's audit log), then it follows EIP-1559's RLP encoding: `[chain_id, nonce, max_priority_fee_per_gas, max_fee_per_gas, gas_limit, to, value, data, access_list]` prefixed with `0x02`. The serialization function lives in `chains/domain/value_objects.py` so Custody can call it without importing chains/infra.

- **AC-phase2-chains-002-10:** Given the test environment, when `broadcast` and `receipt_monitor` tests run, then the Anvil testcontainer is used (same instance from `chains-001`). Anvil's `evm_mine` and `anvil_setNextBlockBaseFeePerGas` cheats let tests deterministically advance blocks and simulate reorgs (via `anvil_dropTransaction` + remine).

---

## Out of Scope

- Tron and Solana write paths: Phase 3.
- "Speed up" / "cancel" tx UX: V2 (would require nonce-replacement mechanic; expensive to implement well).
- Reorg handling deeper than 12 blocks: V2 reconciliation pipeline.
- Mempool propagation tracking (which nodes have seen the tx): not useful for portfolio scope.
- MEV protection / private mempools (Flashbots): not testnet-relevant.
- Custom RPC providers beyond Alchemy + public: V2.

---

## Dependencies

- **Code dependencies:** `phase2-chains-001` (read adapter, port, value objects), `phase2-custody-002` (`ApprovedTx` type).
- **Data dependencies:** none.
- **External dependencies:** arq for the worker (already in the bootstrap), web3.py, the same Alchemy + public RPC URLs from chains-001.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/chains/domain/test_unsigned_tx.py` covers AC-08 (validation rules).
- [ ] **Property tests:** `tests/chains/domain/test_eip1559_serialization_properties.py` — for any random valid `UnsignedTx`, `serialize_for_hash(tx)` is deterministic byte-for-byte, and `keccak256(serialize_for_hash(tx))` equals `eth_account.Account.sign_transaction(...).hash` for the same inputs (cross-checks our serialization against the canonical library). Covers AC-09.
- [ ] **Application tests:** `tests/chains/application/test_build_send_tx.py` covers AC-01, AC-02 (native vs ERC-20). Uses `FakeChainGateway` returning scripted nonce + fee.
- [ ] **Application tests:** `tests/chains/application/test_estimate_fee.py` covers AC-03 (priority floor enforcement, base_fee multiplier).
- [ ] **Adapter tests:** `tests/chains/infra/test_ethereum_write_adapter.py` — Anvil fixture; build → sign (via custody-002 adapter) → broadcast → assert tx hash matches → mine block → assert receipt available. Covers AC-01 through AC-05.
- [ ] **Adapter tests:** `tests/chains/infra/test_receipt_monitor.py` — Anvil fixture, broadcast a tx, run monitor in a task, advance Anvil blocks via cheat, assert `TransactionConfirmed` event published. Variants: tx reverts (advance block with failing tx) → `TransactionFailed`; never mine the tx for 300s simulated → `TransactionExpired`. Covers AC-05, AC-06, AC-07.
- [ ] **Contract tests:** none.
- [ ] **E2E:** none yet.
- [ ] **Locust:** none.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] Three new domain events registered in `shared/events/registry.py` with payload schemas inline.
- [ ] `ChainGateway` port extended; the new write methods are added to the existing `FakeChainGateway`.
- [ ] Single PR. Conventional commit: `feat(chains): ethereum write path + receipt monitor [phase2-chains-002]`.
- [ ] PR description: a sequence diagram of the broadcast → monitor → terminal-event flow.

---

## Implementation Notes

- The `monitor_receipt` arq job's polling intervals (3s mempool, 5s confirmation) are configured via env `RECEIPT_MONITOR_POLL_INTERVAL_MEMPOOL` and `_CONFIRMATION` so testnet vs mainnet can tune separately. Test override is via fixture (5ms poll for fast tests).
- Confirmation depth target: 12 blocks (Sepolia). On mainnet the architecture would target 32. Phase 4 polish brief revisits if portfolio includes mainnet bridging — not in scope for V1.
- The revert-reason fetch via `debug_traceTransaction` is best-effort. Free-tier RPCs (public, Alchemy free) often don't support it. Adapter handles `MethodNotFound` gracefully and falls back to `failure_reason="execution reverted"`. Document inline.
- Don't try to detect `replacement underpriced` in build-time; let the broadcast catch it and surface to caller. The Transactions context decides whether to retry with a higher fee.
- The arq job for receipt-monitor needs access to the same EventBus (outbox publisher) that other contexts use. Ensure the worker's composition root wires it.

---

## Risk / Friction

- Sepolia base fees are sometimes 0 wei (empty blocks). The "max(2 gwei, ...)" priority floor is what keeps txs landing in those conditions. Don't lower it; testnet looks "free" but txs sit forever without priority.
- Receipt monitor running as arq job means each in-flight tx holds a worker slot for up to 5 minutes. With 1 worker process and concurrency=10, that's a 10-tx ceiling on simultaneous in-flight monitors. Phase 2 portfolio scale (≤5 demo users sending occasional txs) is comfortable; if reviewers stress-test, increase `worker.max_jobs` in `arq.toml`. Document.
- Reorg behavior on Sepolia is more aggressive than mainnet. The 12-block depth is conservative for testnet; reviewers may notice the 2-3 minute confirmation wait. Frontend (web-007) shows progressive confirmation count to manage expectations. Document the rationale in PR.
- The EIP-1559 serialization property test (AC-09 cross-check against eth_account) is critical — getting it wrong silently breaks signing. If the test ever turns flaky, treat it as a code bug, not a test bug.
- Public RPC (publicnode.com or similar) has uptime ~99% which means ~7h/month of blackout. Alchemy free-tier is ~99.9%. With both as fallback, effective uptime > 99.99% — fine.
