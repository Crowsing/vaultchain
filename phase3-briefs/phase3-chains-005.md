---
ac_count: 7
blocks:
- phase3-chains-006
- phase3-wallet-002
- phase3-deposit-watcher-003
complexity: M
context: chains
depends_on:
- phase2-chains-001
estimated_hours: 4
id: phase3-chains-005
phase: 3
sdd_mode: strict
state: ready
title: Solana read adapter + SPL token reads + ADR-005 update
touches_adrs:
- ADR-005
---

# Brief: phase3-chains-005 — Solana read adapter + SPL token reads + ADR-005 update


## Context

Solana is the third chain. Its programming model differs from EVM and Tron in several places that ripple into the adapter shape: addresses are base58-encoded ed25519 public keys (not secp256k1; not checksummed), there are no smart contracts in the EVM sense — instead there are programs (compiled BPF) and accounts (data the programs read/write), tokens are SPL — implemented by the `spl-token` program rather than per-token contracts. A user's "USDC balance" is actually the balance of an Associated Token Account (ATA) — a deterministic address derived from `(wallet_pubkey, USDC_mint, spl_token_program_id)`. Reading SPL balances requires resolving the ATA first.

This brief delivers the **read side**: extends `Address` VO with `chain='solana'` (base58 + 32-byte ed25519 length validation), implements `SolanaReadAdapter` realizing the existing `ChainGateway` port methods, adds an `Ata` (Associated Token Account) helper utility, and updates ADR-005 with the Solana testing-by-`solana-test-validator` section. The `solana-py` library wraps the JSON-RPC API and is async-native (`AsyncClient`) — no `asyncio.to_thread` wrapping needed.

The RPC strategy: Helius free-tier or QuickNode free-tier as primary (`https://api.devnet.solana.com` is the official Solana Labs public RPC, fine for testnet but rate-limited). Public devnet RPC as fallback. For tests: `solana-test-validator` testcontainer (session-scoped pytest fixture). The validator ships with `solana-cli` and is straightforward to start in a container.

**Commitment level for reads: `confirmed`** (≈400ms, sufficient for display freshness). The deposit watcher (`phase3-deposit-watcher-003`) uses `finalized` (≈13s) for actual balance changes affecting Ledger. Two distinct commitment levels for two distinct purposes — documented in ADR-005 update.

The architecture-mandated property test (Section 5 line 4) extends with a Solana branch: for any random 32-byte ed25519 public key, `Address.parse('solana', encode_base58(pubkey)).serialize() == encode_base58(pubkey)`.

---

## Architecture pointers

- **Layer:** application + infra. Domain only adds Solana branch to `Address` VO.
- **Packages touched:**
  - `shared/domain/address.py` (extend with Solana base58 ed25519 validation)
  - `chains/infra/solana_read_adapter.py` (new)
  - `chains/infra/solana_rpc_client.py` (low-level solana-py wrapper with primary/fallback)
  - `chains/infra/solana_constants.py` (USDC devnet mint `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`, `SPL_TOKEN_PROGRAM_ID`, `ASSOCIATED_TOKEN_PROGRAM_ID`)
  - `chains/infra/solana_ata.py` (deterministic ATA derivation utility)
  - `tests/chains/fixtures/solana_test_validator.py` (pytest fixture for testcontainer)
  - `docs/decisions/ADR-005-chain-testing-asymmetry.md` (update — add Solana section)
- **Reads:** Solana JSON-RPC.
- **Writes:** none.
- **Events:** none new.
- **Ports / adapters:** `SolanaReadAdapter` implements existing `ChainGateway` Protocol. No port changes.
- **Migrations:** none.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase3-chains-005-01:** Given the `Address` VO, when `Address.parse('solana', '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU')` is called, then it: (1) base58-decodes to exactly 32 bytes; (2) returns the Address VO. Lengths ≠ 32 raise `InvalidAddress`. Solana addresses are NOT checksummed — base58 alphabet validation + length is the full check. **Property test:** for any random 32-byte ed25519 pubkey, `Address.parse('solana', base58_encode(pubkey)).serialize() == base58_encode(pubkey)` round-trips. Architecture-mandated extension.

- **AC-phase3-chains-005-02:** Given the `SolanaReadAdapter` constructed with `(primary_rpc_url, fallback_rpc_url, commitment='confirmed')`, when `get_native_balance(address)` is called, then it: (1) calls `solana_client.get_balance(Pubkey.from_string(addr), commitment='confirmed')`; (2) returns `Money(amount=balance_lamports, currency='SOL', decimals=9, chain='solana')`.

- **AC-phase3-chains-005-03:** Given `get_token_balance(address, token_mint, decimals=6)` for USDC on Devnet, when called, then it: (1) derives the ATA via `derive_ata(wallet=address, mint=token_mint)` (deterministic via `Pubkey.find_program_address` with seeds `[wallet, SPL_TOKEN_PROGRAM_ID, mint]`); (2) calls `solana_client.get_token_account_balance(ata, commitment='confirmed')`; (3) returns `Money(amount=int(balance.value.amount), currency='USDC', decimals=6, chain='solana')`. **If the ATA doesn't exist** (user has never received the token), the RPC returns an account-not-found error; adapter returns `Money(amount=0, ...)` rather than raising. This handles the common case of a user with a wallet but no SPL accounts yet.

- **AC-phase3-chains-005-04:** Given the `Ata` derivation utility, when called with `derive_ata(wallet, mint)`, then it returns the deterministic 32-byte ATA pubkey using `Pubkey.find_program_address(seeds=[bytes(wallet), bytes(SPL_TOKEN_PROGRAM_ID), bytes(mint)], program_id=ASSOCIATED_TOKEN_PROGRAM_ID)`. **Property test:** for any random `(wallet, mint)`, derivation is deterministic — same inputs produce same ATA pubkey across calls. Plus a known-good fixture: VaultChain's faucet wallet's USDC ATA derives to a documented address (verified manually once, then asserted in test).

- **AC-phase3-chains-005-05:** Given `get_block_number()`, when called, then it returns `solana_client.get_slot(commitment='confirmed').value`. Solana uses "slots" not blocks (slots increment every 400ms; not every slot has a block). Cached for 1 second in Redis. The `BlockReference.height` field stores the slot number — semantically correct for Solana even if naming is EVM-flavored.

- **AC-phase3-chains-005-06:** Given `get_block(slot)`, when called, then it returns `BlockReference(height=slot, hash=blockhash, timestamp=block_time)`. Calls `solana_client.get_block(slot, commitment='confirmed', max_supported_transaction_version=0)`. **Important:** Solana skips slots when leaders fail; `get_block(skipped_slot)` returns null. Adapter handles by raising `BlockNotProduced` (DomainError, mapped to 404 in callers — only callers that strictly need a specific slot see this).

- **AC-phase3-chains-005-07:** Given `get_logs(from_slot, to_slot, contract=USDC_mint, event_signature=None)` — Solana doesn't have EVM-style logs/events. The adapter implementation: queries `get_signatures_for_address(USDC_mint, before, until)` returning tx signatures touching the mint, then for each signature calls `get_transaction(sig)` to extract the inner instructions, filters for SPL Transfer instruction shape, and synthesizes `RawLog` objects with `tx_hash=signature, block_number=slot, address=mint, topics=[]`, `data=bytes(transfer_amount + from + to)`. **The deposit watcher is the primary consumer** and uses this to detect incoming USDC transfers. Window cap: 1000 slots (Helius/public RPC limit at signature pagination). The implementation is genuinely complex — encapsulate in a dedicated `_resolve_spl_transfers` helper.

- **AC-phase3-chains-005-08:** Given `get_transaction(tx_signature)`, when called for a confirmed Solana tx, then returns `Receipt{tx_hash=signature, block_number=slot, block_hash=blockhash, status (1=success | 0=failed), gas_used (=fee_paid_lamports), effective_gas_price=None (Solana fees are per-tx not per-CU on the user-facing model), logs (parsed inner instructions)}`. For pending: `block_number=None`. For non-existent: `None`.

- **AC-phase3-chains-005-09:** Given primary RPC failure (5xx, timeout 10s, rate-limit 429), when fallback also fails, then `ChainUnavailable` raised with `details.chain='solana'`.

- **AC-phase3-chains-005-10:** Given the `solana-test-validator` testcontainer fixture, when adapter tests run, then a session-scoped fixture starts the validator (`solana-test-validator --reset --quiet`), waits for RPC ready (poll `getHealth` until OK), exposes the local RPC URL to tests. Tests can fund accounts via `solana airdrop` (validator allows unlimited devnet drops), deploy SPL token (USDC mint setup once at fixture init), exercise read paths against real SPL state.

- **AC-phase3-chains-005-11:** Given ADR-005 update, when committed, then the existing ADR-005 markdown gains a "Solana section": testing via `solana-test-validator` (real validator, real BPF, real ed25519 signing semantics), commitment level discipline (`confirmed` for reads display, `finalized` for ledger-affecting deposit detection), the SPL ATA derivation as a concept (vs the EVM "balanceOf at contract" pattern). Also documents the limitation: SPL token program version mismatches between testcontainer and devnet are rare but possible; pin a known-good `solana-test-validator` version in `docker-compose-dev.yml`.

---

## Out of Scope

- Solana write path (build / sign / broadcast / monitor): `phase3-chains-006`.
- Versioned transactions (v0): not needed for simple SPL transfers; documented as out-of-scope simplification.
- Address Lookup Tables (ALTs): out of scope.
- Compute budget instructions (priority fees): added in `phase3-chains-006`'s build path.
- Stake account / vote account reads: out of scope.

---

## Dependencies

- **Code dependencies:** `phase2-chains-001`.
- **Data dependencies:** none.
- **External dependencies:** `solana-py` (provides `AsyncClient`, `Pubkey`), Solana Devnet RPC URL (Helius/QuickNode key optional but recommended; env `SOLANA_RPC_URL_PRIMARY`), `solana-test-validator` testcontainer (image typically built from `solana-cli` or use `anza-xyz/solana` Docker tags).

---

## Test Coverage Required

- [ ] **Property tests:** `tests/shared/domain/test_address_solana_properties.py` — for any random 32-byte ed25519 pubkey, parse-serialize round-trips. Covers AC-01.
- [ ] **Property tests:** `tests/chains/infra/test_solana_ata_properties.py` — for any random `(wallet, mint)` pair, derivation is deterministic; known-good fixture matches manually-verified ATA. Covers AC-04.
- [ ] **Adapter tests:** `tests/chains/infra/test_solana_read_adapter.py` — uses `solana-test-validator` fixture; airdrops SOL, creates a USDC mint, mints to user ATA, exercises `get_native_balance`, `get_token_balance` (with and without ATA existing), `get_block_number` (slot), `get_block` (skipped slot raises `BlockNotProduced`). Covers AC-02 through AC-06.
- [ ] **Adapter tests:** `tests/chains/infra/test_solana_get_logs.py` — issues SPL Transfer instructions, then queries `get_logs` against the mint, asserts the synthesized `RawLog` rows match the issued transfers. Covers AC-07.
- [ ] **Adapter tests:** `tests/chains/infra/test_solana_failover.py` — primary RPC mocked to fail via httpx mocking; asserts fallback retried; both fail raises `ChainUnavailable`. Covers AC-09.
- [ ] **Contract tests:** none.
- [ ] **E2E:** none yet.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] All test categories above implemented and passing locally.
- [ ] `solana-test-validator` testcontainer fixture works in CI (verify in PR by running the tests in GitHub Actions).
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes (solana-py has decent stubs in 2026; minimal ignores expected).
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] No new ports; no new domain events.
- [ ] **ADR-005 updated** with Solana section.
- [ ] Single PR. Conventional commit: `feat(chains): solana read adapter + SPL + ATA + ADR-005 update [phase3-chains-005]`.

---

## Implementation Notes

- The `Address.parse('solana', ...)` should accept `solders.pubkey.Pubkey` instances natively too (just call `str(pubkey)`). Keeps interop with solana-py's typed API smoother.
- `AsyncClient` from solana-py is genuinely async — don't wrap. The adapter is cleaner than tronpy.
- The "ATA might not exist" case (AC-03) is the most common gotcha for Solana newcomers. Handling it as `Money(0, ...)` rather than an error is the right UX — user sees zero balance, not a 503.
- Slot vs block confusion: every block belongs to a slot, but not every slot has a block. The `BlockReference.height` field stores slot. Document inline in the value object.
- The `_resolve_spl_transfers` helper for `get_logs` (AC-07) is the most code in this brief. Test it with multiple txs touching the same mint, including: token mint (different from transfer), token burn, ATA close. Filter only `Transfer` instruction discriminator (the first byte of instruction data is 3 for SPL Transfer).

---

## Risk / Friction

- `solana-test-validator` startup is ~5 seconds. Session-scoped fixture amortizes the cost. If CI is slow, use a long-running container in the CI workflow file (not pytest fixture) and pass URL via env. Trade-off: less hermetic, faster.
- Helius / QuickNode rate limits at free tier are generous but not unlimited. Cassette-style recording for Solana exists (vcrpy + httpx) but the mix of sync/async + WebSocket would complicate. Stick with `solana-test-validator` for tests; live RPC only at deploy.
- The "no logs" reality of Solana (vs EVM events) is the biggest model mismatch. The synthesized-from-signatures approach (AC-07) works but is slower per-block than EVM's `eth_getLogs`. For a deposit watcher polling every 13 seconds (`finalized`), the cost is acceptable. Document the latency expectation.
- ATA derivation via `Pubkey.find_program_address` is conceptually right but expensive (~1ms per call on a fast machine due to the BPF PDA loop). For a hot path checking many users, cache derivations. Phase 3 portfolio scale doesn't need this — but document the optimization for V2.
- Skipped slots on Devnet are uncommon but not zero. The `BlockNotProduced` error path (AC-06) needs to be exercised; if the deposit watcher hits this in production, it should skip-and-continue, not fail. Document for `phase3-deposit-watcher-003`.
