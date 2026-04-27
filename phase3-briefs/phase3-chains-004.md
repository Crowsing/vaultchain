---
ac_count: 9
blocks:
- phase3-deposit-watcher-002
- phase3-wallet-002
- phase3-transactions-003
- phase3-custody-004
complexity: L
context: chains
depends_on:
- phase3-chains-003
- phase2-custody-002
- phase2-chains-002
estimated_hours: 4
id: phase3-chains-004
phase: 3
sdd_mode: strict
state: ready
title: Tron write path (tronpy signer + broadcast + receipt monitor)
touches_adrs: []
---

# Brief: phase3-chains-004 — Tron write path (tronpy signer + broadcast + receipt monitor)


## Context

This brief completes Tron support with the write side: `build_send_tx` for native TRX and TRC-20 transfers, `estimate_fee` (energy + bandwidth model), `broadcast`, and the `TronReceiptMonitor` running as an arq job. It also delivers the `TronSigner` (`custody/infra/signers/tron_signer.py`) registered in the `signer_registry` from `phase2-custody-002`. The `Custody.SignTransaction` use case routes to the Tron signer when `unsigned_tx.chain == 'tron'` — no changes to Custody application code needed; just one new entry in the registry's chain→signer dict.

Tron's transaction model differs meaningfully from Ethereum:

- **No gas, two resource types.** Bandwidth (BPN per byte of tx) and Energy (for smart contract calls). Each account gets a small free daily allotment of bandwidth (1500 BPN) and pays in TRX (burned) for the rest. TRC-20 transfer typically uses ~14k energy + ~345 bandwidth = ~5 TRX burned at testnet rates. Native TRX transfer uses bandwidth only.
- **No nonce.** Tron uses `ref_block_bytes` and `ref_block_hash` (referencing a recent block) for replay protection. tronpy fills these automatically.
- **Signing.** Same elliptic curve as Ethereum (secp256k1), same private key bytes can be reused conceptually, but the signed payload structure is Tron-specific (protobuf-encoded). tronpy's `tron.trx.sign(transaction, priv_key)` handles this. The signing service in Custody calls the Tron signer adapter; pre/post hashes for audit log are SHA-256 of the protobuf bytes.

Receipt monitoring: same arq pattern as `phase2-chains-002`'s Ethereum monitor. Tron blocks are 3 seconds; confirmation depth target is **20 blocks** (≈60 seconds — Tron's BFT-like consensus finalizes faster than PoS Ethereum, so 20 blocks is conservative-and-quick for testnet). Reorg behavior on Shasta is rare; same handling pattern as Ethereum (re-query each poll, accept new block as canonical).

---

## Architecture pointers

- **Layer:** application + infra. Domain unchanged — `UnsignedTx` value object from `phase2-chains-002` accommodates Tron with `chain='tron'`, `chain_id=null` (Tron doesn't use chain_id like EIP-1559), `data=encoded_protobuf_extra_for_TRC20_or_empty`.
- **Packages touched:**
  - `chains/infra/tron_write_adapter.py` (or merge into `tron_adapter.py` per chains-001 pattern)
  - `chains/infra/workers/tron_receipt_monitor.py` (arq job)
  - `custody/infra/signers/tron_signer.py` (new)
  - `chains/infra/tron_constants.py` (add: `TRC20_TRANSFER_METHOD_ID`, energy cost defaults, default tx expiration window 60s)
  - Composition root wires `TronSigner` into `signer_registry`
  - `tests/chains/cassettes/tron/` (extend with write-path cassettes)
- **Reads / writes:** RPC (broadcast via `/wallet/broadcasttransaction`).
- **Publishes events:** `chain.TransactionConfirmed{tx_hash, chain='tron', block_number, gas_used (=energy), effective_gas_price=None, fee_paid_trx}`, `chain.TransactionFailed{tx_hash, chain='tron', block_number, revert_reason}`, `chain.TransactionExpired{tx_hash, chain='tron', last_seen_block}`. Same event names as Ethereum — chain field disambiguates. No new events.
- **Migrations:** none.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase3-chains-004-01:** Given `build_send_tx(from_address, to_address, value: Money(TRX), chain='tron')` for native TRX send, when invoked, then it: (1) calls `tron.trx.transfer(from, to, amount=value.amount).build()` (sync, wrapped); (2) returns `UnsignedTx{chain='tron', from, to, value=Money(TRX), gas_limit=None, max_fee_per_gas=None, max_priority_fee_per_gas=None, nonce=None, chain_id=None, data=protobuf_serialized_tx_bytes, expiration_seconds=60}`. The `data` field carries the Tron-specific tx bytes ready for signing. The `Money` is in sun.

- **AC-phase3-chains-004-02:** Given `build_send_tx(...)` for TRC-20 (USDT) transfer, when invoked, then: (1) gets the contract via `tron.get_contract(token)`; (2) builds via `contract.functions.transfer(to, amount).with_owner(from).build()`; (3) returns `UnsignedTx` with `data` carrying the protobuf tx bytes that include the `TriggerSmartContract` payload. Energy estimate is included via `estimate_fee` (next AC).

- **AC-phase3-chains-004-03:** Given `estimate_fee(chain='tron', for_tx_type='trc20_transfer')`, when called, then it returns `FeeEstimate{base_fee=None, priority_fee=None, gas_limit_estimate=14_000_000 (sun-equivalent of typical TRC-20 energy cost), max_total_wei=5_000_000 (≈5 TRX in sun), bandwidth_estimate=345}`. Defaults conservative — the user pays a slight overestimate but txs land. Live energy estimation via `tron.trigger_constant_contract(...)` is best-effort and falls back to defaults on RPC error. Cached for 30 seconds in Redis.

- **AC-phase3-chains-004-04:** Given an `ApprovedTx` from Custody (signed Tron tx bytes), when `broadcast(approved_tx)` is called, then: (1) deserializes the protobuf bytes to a tronpy `Transaction`; (2) calls `tron.broadcast(tx)` which returns `{result: True, txid}`; (3) returns `{tx_hash: txid}`. On `result: False`, maps tronpy's error code to: `'BANDWITH_ERROR'/'OUT_OF_ENERGY'` → `InsufficientGas`, `'TRANSACTION_EXPIRATION_ERROR'` → `TransactionExpired` (handled differently — see AC-08), `'TAPOS_ERROR'` (ref block out of range) → retried once with fresh ref_block, then `ChainUnavailable`, anything else → `ChainUnavailable`.

- **AC-phase3-chains-004-05:** Given the `TronSigner.sign(unsigned_tx, private_key)`, when invoked, then it: (1) deserializes the `unsigned_tx.data` into a tronpy `Transaction` object; (2) calls `tx.sign(PrivateKey(private_key))`; (3) returns `(signed_bytes, tx_hash)` where `signed_bytes = tx.SerializeToString()` and `tx_hash = tx.txid`. The pre_hash for audit is SHA-256 of `unsigned_tx.data`; post_hash is SHA-256 of `signed_bytes`. Same audit-log shape as Ethereum signer.

- **AC-phase3-chains-004-06:** Given the `TronReceiptMonitor.monitor_receipt(tx_hash, chain='tron')` arq job runs, when invoked, then: (1) polls `tron.get_transaction_info(tx_hash)` every 3 seconds; (2) on first non-empty result with `blockNumber`, captures `seen_at_block`; (3) switches to 5-second polling, comparing `current_block - seen_at_block`; (4) on `confirmation_depth >= 20` AND `info.receipt.result == 'SUCCESS'`, publishes `chain.TransactionConfirmed` and exits; (5) on `info.receipt.result == 'FAILED'` or non-success, publishes `chain.TransactionFailed` with `revert_reason` parsed from `info.contractResult` if available, exits.

- **AC-phase3-chains-004-07:** Given the monitor runs longer than 90 seconds without seeing the receipt, when timeout fires, then it publishes `chain.TransactionExpired{last_seen_block}` and exits. Tron txs have a built-in 60s expiration; after that the tx is dropped from mempool and won't land. The 90s monitor timeout gives a small grace window past expiration before declaring expired.

- **AC-phase3-chains-004-08:** Given a Tron tx where `tron.broadcast` returned success but the tx doesn't appear in any block (Shasta dropped it under load), when monitor times out at 90s, then it publishes `TransactionExpired`. The Transactions context's expired handler unreserves the ledger withdrawal-pending posting and notifies the user. **No automatic retry at this layer** — caller decides retry strategy.

- **AC-phase3-chains-004-09:** Given the test environment, when adapter tests run, then vcrpy cassettes provide deterministic responses for: build (`/wallet/createtransaction`, `/wallet/triggersmartcontract`), broadcast (`/wallet/broadcasttransaction`), get_transaction_info, get_block_number progression. Tests cover happy path, energy-insufficient, tapos-retry, expired-timeout. Cassette refresh procedure: run `pytest --vcr-record=new_episodes` against live Shasta with `TRONGRID_API_KEY`, review diff, commit.

- **AC-phase3-chains-004-10:** Given the `signer_registry` from `phase2-custody-002`, when wired in composition root, then `TronSigner` is registered for `chain='tron'`. **No changes to `Custody.SignTransaction` use case code** — the registry resolves the signer dynamically. This is the strict-DDD pattern: the use case is chain-agnostic; chain-awareness lives in the registry + signers.

- **AC-phase3-chains-004-11:** Given the property test for EIP-1559 serialization from `phase2-chains-002` (AC-09), when extended for Tron, then a parallel `serialize_for_hash_tron` property test validates: for any random valid Tron `UnsignedTx`, the `data` field byte-for-byte equals tronpy's canonical serialization of an equivalent transaction. Cross-checks our build path doesn't accidentally diverge from tronpy's output.

---

## Out of Scope

- Resource staking / freezing TRX for energy: V2.
- Multi-signature accounts: V2.
- TRC-721 / TRC-1155 (NFTs): never.
- Real-time energy estimation accuracy beyond ±20%: best-effort.
- Custom RPC providers beyond TronGrid: V2.

---

## Dependencies

- **Code dependencies:** `phase3-chains-003`, `phase2-custody-002`, `phase2-chains-002`.
- **Data dependencies:** none.
- **External dependencies:** `tronpy` (already pulled in chains-003), arq (already configured).

---

## Test Coverage Required

- [ ] **Application tests:** `tests/chains/application/test_build_send_tx_tron.py` — happy path native, happy path TRC-20. Uses `FakeChainGateway`. Covers AC-01, AC-02.
- [ ] **Application tests:** `tests/chains/application/test_estimate_fee_tron.py` — defaults applied when live estimation fails. Covers AC-03.
- [ ] **Property tests:** `tests/chains/domain/test_tron_serialization_properties.py` — cross-check our `data` bytes vs tronpy's. Covers AC-11.
- [ ] **Adapter tests:** `tests/chains/infra/test_tron_write_adapter.py` — vcrpy cassettes; build → sign → broadcast → assert tx_hash matches → get_transaction_info → assert SUCCESS. Variants: insufficient energy, tapos retry, expired. Covers AC-01–AC-09.
- [ ] **Adapter tests:** `tests/chains/infra/test_tron_signer.py` — cross-check signed bytes match `tron.trx.sign(...)` output for the same private key + unsigned tx. Recovery: assert the tx_hash returned by signer matches what tronpy computes independently.
- [ ] **Adapter tests:** `tests/chains/infra/test_tron_receipt_monitor.py` — vcrpy cassettes for block progression; monitor advances states correctly. Covers AC-06, AC-07, AC-08.
- [ ] **Contract tests:** none.
- [ ] **E2E:** none yet.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] All test categories above implemented and passing locally.
- [ ] vcrpy cassettes committed; no secrets in cassettes (CI grep check).
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes (tronpy stubs limited; targeted ignores allowed).
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] No new domain events.
- [ ] `signer_registry` composition wired with TronSigner.
- [ ] Single PR. Conventional commit: `feat(chains): tron write path + signer + receipt monitor [phase3-chains-004]`.

---

## Implementation Notes

- The `UnsignedTx.data` field is overloaded across chains: for EVM it's call data (transfer ABI bytes); for Tron it's the entire serialized protobuf transaction. This is acceptable — the signer is chain-aware and knows how to interpret it. Document inline.
- tronpy's `tx.update()` after fee adjustment requires re-fetching `ref_block` if the block expired. The build function captures `built_at_block_number` and the broadcast retry-on-tapos path re-builds with a fresh ref_block.
- Tron's "energy cost" maps to `gas_used` in `Receipt` to keep the cross-chain shape uniform. The user-facing UI in `phase2-web-006` already showed gas distinctly per chain via the `Receipt.chain` field; Tron's display reads "Energy used: 14,235" instead of "Gas used: 21,000". Confirm the frontend handles this in `phase3-admin-008` brief.
- Don't try to estimate bandwidth precisely — it depends on tx size in bytes which depends on built-tx variables (memo length, etc.). The default 345 BPN covers TRC-20 transfers comfortably.
- Tron txs include an `expiration` field set when built. Default 60 seconds. The expired-tx behavior (AC-07) is correct: build → broadcast → if not in block by ~60s, the network drops it. Monitor's 90s gives the network time to confirm-or-drop.

---

## Risk / Friction

- The `UnsignedTx.data` overloading (EVM call data vs Tron full-tx) is a small abstraction smell that reviewers may flag. Defenses: (1) the `chain` field disambiguates; (2) signers route correctly; (3) auditing pre/post hashes is consistent (SHA-256 of `data` either way). If a future chain (Solana with versioned tx) doesn't fit this pattern, refactor — but not preemptively.
- vcrpy cassettes for write path are larger and more brittle than read-path cassettes. Re-recording requires a funded Shasta wallet (operator's faucet account). Document the wallet's address + funding procedure in `tests/chains/cassettes/tron/README.md`.
- Tron's "TAPOS_ERROR" (ref block out of range) happens occasionally on testnet under chain reorg or network delay. The single-retry strategy in AC-04 is enough for testnet; mainnet would want exponential backoff with up to 3 retries. Document.
- Energy cost defaults (5 TRX = 5,000,000 sun) might be conservative-to-the-point-of-wasteful as Tron's network conditions evolve. The CoinGecko Pricing context provides USD value; if 5 TRX exceeds $1 testnet UX-wise, lower the default. No test enforces this — manual tuning per network state.
