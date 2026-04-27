---
ac_count: 9
blocks:
- phase3-deposit-watcher-003
- phase3-wallet-002
- phase3-transactions-003
- phase3-custody-004
complexity: L
context: chains
depends_on:
- phase3-chains-005
- phase2-custody-002
- phase2-chains-002
estimated_hours: 4
id: phase3-chains-006
phase: 3
sdd_mode: strict
state: ready
title: Solana write path (solana-py signer + broadcast + receipt monitor)
touches_adrs: []
---

# Brief: phase3-chains-006 — Solana write path (solana-py signer + broadcast + receipt monitor)


## Context

This brief completes Solana support: build, fee estimation, broadcast, and the `SolanaReceiptMonitor`. Key Solana specifics that affect the adapter shape:

- **No nonces.** Replay protection via the recent blockhash. Each tx must reference a blockhash less than ~150 slots (≈60s) old or it's rejected.
- **No "gas".** Compute Units (CU) bound execution, fee is fixed-per-signature (~5000 lamports) plus optional priority fee per CU. For a simple SPL transfer, priority fees are usually 0 lamports per CU. We include priority fee = 0 in V1 (testnet has zero contention); the build path accepts a parameter for future flexibility.
- **Signing.** ed25519, fundamentally different from secp256k1. The `SolanaSigner` uses `solders.keypair.Keypair.from_bytes(private_key)` to load + sign. Key generation in `phase3-wallet-002` calls `Keypair()` to mint a fresh keypair (32-byte secret expanding to 64-byte secret+public via ed25519-dalek).
- **Confirmation. `finalized` vs `confirmed`.** This brief's monitor uses `finalized` (≈13s) for the terminal confirmation event — matches the Ethereum 12-block-depth philosophy of "wait for safety." Frontend shows progressive confirmation feedback. Documented in chains-005's ADR-005 update.

The receipt monitor follows the same arq pattern as Ethereum and Tron monitors. Polls `get_signature_statuses` every 1 second initially; on first non-null status with `confirmation_status='confirmed'`, switches to polling for `finalized`. Average wall time: 13–20 seconds for SPL transfers on Devnet.

The `SolanaSigner` registers with `signer_registry` from `phase2-custody-002`. No changes to `Custody.SignTransaction` use case code.

---

## Architecture pointers

- **Layer:** application + infra. Domain unchanged — `UnsignedTx` accommodates Solana with `chain='solana'`, nullable EVM-specific fields.
- **Packages touched:**
  - `chains/infra/solana_write_adapter.py` (or merge with read adapter)
  - `chains/infra/workers/solana_receipt_monitor.py` (arq job)
  - `custody/infra/signers/solana_signer.py` (new, registered in registry)
  - `chains/infra/solana_constants.py` extend with: `SYSTEM_PROGRAM_ID`, transfer instruction discriminators
  - Composition root wires `SolanaSigner`
- **Reads / writes:** RPC.
- **Publishes events:** `chain.TransactionConfirmed{tx_hash, chain='solana', block_number=slot, gas_used=fee_lamports, effective_gas_price=None}`, `chain.TransactionFailed`, `chain.TransactionExpired`. No new events.
- **Migrations:** none.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase3-chains-006-01:** Given `build_send_tx(from_address, to_address, value: Money(SOL), chain='solana')` for native SOL transfer, when invoked, then it: (1) fetches recent blockhash via `get_latest_blockhash(commitment='finalized')`; (2) constructs a `Transaction` with one `transfer` instruction from the system program (`solders.system_program.transfer({from_pubkey, to_pubkey, lamports: amount})`); (3) sets `recent_blockhash` and `fee_payer=from_pubkey`; (4) serializes the unsigned message via `tx.message.serialize()`; (5) returns `UnsignedTx{chain='solana', from, to, value, gas_limit=None, max_fee_per_gas=None, nonce=None, chain_id=None, data=serialized_message_bytes, expiration_slot=current_slot+150}`. The blockhash is captured implicitly in `data`.

- **AC-phase3-chains-006-02:** Given `build_send_tx(...)` for SPL token transfer (USDC), when invoked, then it: (1) derives source ATA `derive_ata(from, USDC_mint)`; (2) derives destination ATA `derive_ata(to, USDC_mint)`; (3) **checks if destination ATA exists** via `get_account_info(dest_ata)` — if not, prepends a `create_associated_token_account` instruction (the *fee payer* — i.e., the sender — pays for the destination's ATA creation, ~0.002 SOL rent); (4) appends the SPL transfer instruction `spl_token.transfer(source=src_ata, dest=dest_ata, owner=from, amount=value.amount)`; (5) builds the message with both instructions, returns the same `UnsignedTx` shape as native. The "create ATA on demand" is critical — without it, sends to fresh recipients fail.

- **AC-phase3-chains-006-03:** Given `estimate_fee(chain='solana', for_tx_type='spl_transfer_with_create_ata')`, when called, then it returns `FeeEstimate{base_fee=5000 (lamports per signature), priority_fee=0, gas_limit_estimate=None, max_total_wei=2_039_280 + 5000 (rent for a new token account + signature fee)}`. For a transfer without ATA creation, `max_total_wei=5000`. Live estimation via `get_fee_for_message` is best-effort and falls back to defaults on RPC error. Cached for 30 seconds.

- **AC-phase3-chains-006-04:** Given an `ApprovedTx` from Custody (signed serialized transaction bytes), when `broadcast(approved_tx)` is called, then: (1) calls `solana_client.send_raw_transaction(signed_bytes, opts={'skip_preflight': false, 'preflight_commitment': 'confirmed'})`; (2) returns `{tx_hash: signature_base58_str}`. On RPC errors: `'BlockhashNotFound'` → `TransactionExpired` (the blockhash referenced is too old; caller decides retry strategy with fresh blockhash); `'InsufficientFundsForRent'` → `InsufficientGas`; preflight simulation failure → `BroadcastFailed` with the simulation logs in `details`.

- **AC-phase3-chains-006-05:** Given the `SolanaSigner.sign(unsigned_tx, private_key)`, when invoked, then it: (1) deserializes `unsigned_tx.data` (the message bytes) into `solders.message.Message`; (2) creates `Keypair.from_bytes(private_key)` (private_key here is the 64-byte ed25519 expanded form, matching what custody-003 stores); (3) signs the message via `Transaction.new_unsigned(message)` then `tx.sign([keypair], recent_blockhash)`; (4) returns `(signed_bytes=bytes(tx), tx_hash=str(tx.signatures[0]))`. The Solana tx_hash is the first signature (base58-encoded). Pre/post hashes for audit follow the SHA-256 pattern.

- **AC-phase3-chains-006-06:** Given the `SolanaReceiptMonitor.monitor_receipt(tx_hash, chain='solana')` arq job, when running, then: (1) polls `solana_client.get_signature_statuses([tx_hash])` every 1 second; (2) on first non-null status with `confirmation_status in ['confirmed', 'finalized']`, captures the slot; (3) if status is `confirmed` (not yet finalized), continues polling at 2-second intervals waiting for `finalized`; (4) on `finalized` AND `err == None`, fetches `get_transaction(sig)` to extract slot/fee/logs, publishes `chain.TransactionConfirmed`, exits; (5) on `err != None`, publishes `chain.TransactionFailed` with the err details, exits.

- **AC-phase3-chains-006-07:** Given the monitor runs longer than 60 seconds without seeing `finalized`, when timeout fires, then it publishes `chain.TransactionExpired{last_seen_slot}`. If the tx was seen at `confirmed` but never `finalized` in 60s (rare), this still triggers expired — caller handles. Note: 60s exceeds Solana's blockhash expiry (~60s), so an expired-from-monitor often coincides with the network having dropped the tx.

- **AC-phase3-chains-006-08:** Given the `signer_registry` from `phase2-custody-002`, when wired, then `SolanaSigner` is registered for `chain='solana'`. **No changes to Custody.SignTransaction code.** Same dynamic dispatch pattern as Tron.

- **AC-phase3-chains-006-09:** Given the test environment, when adapter tests run, then `solana-test-validator` (from chains-005) provides the local network. Tests fund accounts via airdrop, build → sign (via SolanaSigner) → broadcast → wait for finalized → assert events. Validator cheats: the test fixture exposes a helper `advance_slots(n)` via the validator's `--ticks-per-slot` config to speed up confirmation tests. (If not feasible, real-time waits up to ~5 seconds are acceptable for adapter tests — they're not domain tests.)

- **AC-phase3-chains-006-10:** Given the property test for serialization (mirrors `phase2-chains-002` AC-09 and `phase3-chains-004` AC-11), when `serialize_for_hash_solana` is exercised, then the `data` field byte-for-byte matches `solders.message.Message.serialize()` for an equivalent message. Cross-checks our build path doesn't drift.

- **AC-phase3-chains-006-11:** Given a Solana tx where preflight simulation succeeds but the actual block execution fails (e.g., source ATA balance changed in flight), when broadcast returns the signature but monitor sees `err != None`, then the failure is treated as terminal `failed` — no automatic retry. Caller (Transactions context) decides. Document inline.

---

## Out of Scope

- Versioned transactions (v0): not used; documented.
- Address Lookup Tables (ALTs): out of scope.
- Priority fees auto-tuning: returns 0; V2 if mainnet pursued.
- Compute budget instructions: V2.
- Cross-program invocation depth tracking: out of scope.
- Account rent collection on long-dormant accounts: never (testnet doesn't enforce rent collection on devnet).

---

## Dependencies

- **Code dependencies:** `phase3-chains-005`, `phase2-custody-002`, `phase2-chains-002`.
- **Data dependencies:** none.
- **External dependencies:** `solana-py`, `solders` (rust-bound primitives for solana-py), arq.

---

## Test Coverage Required

- [ ] **Application tests:** `tests/chains/application/test_build_send_tx_solana.py` — happy path native, happy path SPL with ATA creation, happy path SPL without ATA creation (recipient already has ATA). Uses Fakes. Covers AC-01, AC-02.
- [ ] **Application tests:** `tests/chains/application/test_estimate_fee_solana.py` — defaults applied, with/without ATA creation. Covers AC-03.
- [ ] **Property tests:** `tests/chains/domain/test_solana_serialization_properties.py` — cross-check `data` bytes vs solders' canonical. Covers AC-10.
- [ ] **Adapter tests:** `tests/chains/infra/test_solana_write_adapter.py` — `solana-test-validator` fixture; build → sign → broadcast → finalized → assert. Variants: `BlockhashNotFound` retry path, ATA creation path, simulation failure. Covers AC-01–AC-04, AC-09, AC-11.
- [ ] **Adapter tests:** `tests/chains/infra/test_solana_signer.py` — sign and recover signature; cross-check with `solders.transaction.VersionedTransaction.populate(...)` independently signed.
- [ ] **Adapter tests:** `tests/chains/infra/test_solana_receipt_monitor.py` — monitor advances states correctly; expired path. Covers AC-06, AC-07.
- [ ] **Contract tests:** none.
- [ ] **E2E:** none yet.

---

## Done Definition

- [ ] All ACs verified.
- [ ] All test categories above implemented and passing locally.
- [ ] `solana-test-validator` fixture works in CI.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] No new domain events.
- [ ] `signer_registry` wired with SolanaSigner.
- [ ] Single PR. Conventional commit: `feat(chains): solana write path + signer + receipt monitor [phase3-chains-006]`.

---

## Implementation Notes

- The "create destination ATA on demand" pattern (AC-02) is the MOST common SPL UX gotcha. It's the kind of detail reviewers value: "this person knows Solana, not just generic crypto." Be sure the test for this path exists and PR description highlights it.
- `solders.keypair.Keypair.from_bytes()` expects 64 bytes (the expanded ed25519 secret). If `phase3-wallet-002` and `phase3-custody-003` store a 32-byte seed instead, derive at sign time. Coordinate the format choice across briefs — recommend storing the 64-byte expanded form encrypted by KMS, since deriving on every sign costs CPU.
- Solana's `recent_blockhash` is fetched at build time but the tx is signed later. If signing takes >60s (TOTP wait), the blockhash expires and broadcast fails with `BlockhashNotFound`. The build path captures `built_at_slot`; the broadcast path checks `current_slot - built_at_slot > 100` and triggers re-build. This brief's broadcast does NOT auto-rebuild; it raises `TransactionExpired` and caller decides. Document.
- The `SolanaReceiptMonitor` poll interval (1s mempool, 2s confirmation) is shorter than Ethereum because Solana is faster. Configurable via env.
- Signature computation: `tx.signatures[0]` is the fee payer's signature, which is the canonical tx_hash on Solana. Encode as base58 for display + storage.

---

## Risk / Friction

- The `BlockhashNotFound` failure mode is real and will hit users who hesitate at TOTP. Phase 3's experience: `Transactions.PrepareSendTransaction` calls build at confirm-time (not prepare-time) — the build is cheap and the blockhash is fresh. Verify this is the actual flow in `phase3-transactions-003`.
- Solana fees are fixed (5000 lamports per signature) but rent for a new ATA is ~0.002 SOL = ~$0.20 at $100 SOL. On testnet free, on mainnet noticeable for sub-dollar transfers. Document in the user-facing send review card (web-006/007 from Phase 2 already shows fee separately; Solana fee shows clearly).
- `solana-test-validator` is genuinely a separate process; flaky CI can leak validator processes. Add cleanup in fixture teardown (`SIGKILL` if `SIGTERM` doesn't return in 5s).
- The lack of priority fees is testnet-correct but mainnet-naive. If portfolio reviewers ask "what about priority fees during congestion?", answer: "Priority fee parameter is wired, defaults to 0 on Devnet, V2 mainnet would use `getRecentPrioritizationFees` to compute live estimates." Document.
