---
ac_count: 5
blocks:
- phase3-chains-004
- phase3-wallet-002
- phase3-deposit-watcher-002
complexity: L
context: chains
depends_on:
- phase2-chains-001
estimated_hours: 4
id: phase3-chains-003
phase: 3
sdd_mode: strict
state: ready
title: Tron read adapter + Address VO + ADR-005 update
touches_adrs:
- ADR-005
---

# Brief: phase3-chains-003 — Tron read adapter + Address VO + ADR-005 update


## Context

Tron is the second chain integrated. Its programming model differs from EVM in several places that affect adapter shape: addresses are base58check (not hex), the JSON-RPC API has Tron-specific shapes (`/wallet/getaccount`, `/wallet/triggerconstantcontract`), block intervals are 3 seconds (vs 12 on Ethereum), TRC-20 contracts mirror ERC-20 closely (same `balanceOf` / `Transfer` event signatures) but are invoked through different RPC endpoints. The `tronpy` Python library wraps this and is the canonical adapter target.

This brief delivers the **read side**: extends the `Address` value object with chain='tron' branch (base58check validation per Tron spec — first byte `0x41`, then 20-byte payload, then 4-byte checksum), implements `TronReadAdapter` in `chains/infra/tron_read_adapter.py` realizing the existing `ChainGateway` port methods (no port changes), and updates ADR-005 with the Tron testing-by-vcrpy section. The `tronpy` library is sync-only — adapter wraps every call in `asyncio.to_thread()` per architecture Section 4 line 202.

The RPC strategy: TronGrid is the primary endpoint (`https://api.shasta.trongrid.io` for Shasta testnet, requires API key for higher rate limits — operator provisions). Public fallback (`https://api.shasta.trongrid.io` no-key, low rate limit) and a third option Nile testnet RPC are documented in runbook but only TronGrid+key is wired for prod. Tests use vcrpy cassettes — no live network required for unit/CI runs.

The architecture-mandated property test (Section 5 line 4: address VO round-trip per chain) is extended here with a Tron branch: for any random valid 21-byte raw address, `Address.parse('tron', encode_base58check(addr)).serialize() == encode_base58check(addr)`.

---

## Architecture pointers

- **Layer:** application + infra. Domain only adds Tron branch to the existing `Address` VO in `shared/domain/`.
- **Packages touched:**
  - `shared/domain/address.py` (extend with Tron base58check parsing/validation)
  - `chains/domain/value_objects.py` (no changes — `BlockReference`, `RawLog`, etc. stay generic)
  - `chains/infra/tron_read_adapter.py` (new)
  - `chains/infra/tron_rpc_client.py` (low-level tronpy wrapper with primary/fallback)
  - `chains/infra/tron_constants.py` (chain id config; `TRC20_TRANSFER_TOPIC = keccak256("Transfer(address,address,uint256)")` — same as ERC-20; Shasta USDT contract `TG3XXyExBkPp9nzdajDZsozEu4BkaSJozs` placeholder pending operator decision)
  - `tests/chains/cassettes/tron/` (vcrpy cassette directory)
  - `docs/decisions/ADR-005-chain-testing-asymmetry.md` (update — add Tron section)
- **Reads:** TronGrid RPC only.
- **Writes:** none.
- **Events:** none new.
- **Ports / adapters:** `TronReadAdapter` implements existing `ChainGateway` Protocol from `phase2-chains-001`. No port changes.
- **Migrations:** none.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase3-chains-003-01:** Given the `Address` VO, when `Address.parse('tron', 'TG3XXyExBkPp9nzdajDZsozEu4BkaSJozs')` is called, then it: (1) base58-decodes to 25 bytes; (2) verifies first byte is `0x41` (Tron mainnet/testnet prefix); (3) verifies last 4 bytes match `sha256(sha256(first_21_bytes))[:4]`; (4) returns the Address VO. On any check failure, raises `InvalidAddress`. The `serialize()` method returns the canonical base58check string.

- **AC-phase3-chains-003-02:** Given the `Address` VO with a hex-encoded Tron address as input (`'410000000000...'`), when `Address.parse('tron', hex_str)` is called, then the adapter decodes hex and produces the same `Address` value as the base58check input form for the same underlying 20-byte payload. **Property test:** for any random 20-byte payload, `Address.parse('tron', base58check) == Address.parse('tron', hex_with_41_prefix)` and round-trip via `serialize()` produces the canonical base58check form. Architecture-mandated property test extension.

- **AC-phase3-chains-003-03:** Given `TronReadAdapter` constructed with `(primary_rpc_url='https://api.shasta.trongrid.io', api_key, fallback_rpc_url, network='shasta')`, when `get_native_balance(address)` is called, then it: (1) calls `tronpy.AsyncTron(provider=HTTPProvider(...)).get_account_balance(address)` (the address as base58check string); (2) returns `Money(amount=balance_in_sun, currency='TRX', decimals=6, chain='tron')`. The TRX-to-sun conversion is identity inside tronpy (it returns sun); decimals=6 is enforced at adapter boundary.

- **AC-phase3-chains-003-04:** Given `get_token_balance(address, token_contract, decimals=6)` for USDT on Shasta, when called, then it: (1) constructs the contract via `tron.get_contract(token_contract)`; (2) calls `contract.functions.balanceOf(address)` (sync, wrapped in `asyncio.to_thread`); (3) returns `Money(amount=balance, currency='USDT', decimals=6, chain='tron')`.

- **AC-phase3-chains-003-05:** Given `get_block_number()`, when called, then it returns `tron.get_latest_block_number()` (sync, wrapped). Cached for 3 seconds in Redis (`chains:tron:latest_block`) — matches Tron block interval. Cache miss → RPC → write cache → return.

- **AC-phase3-chains-003-06:** Given `get_block(height)`, when called, then it returns `BlockReference(height, block_id_hex, datetime_from_timestamp_ms)`. Tron block IDs are 32-byte hashes; serialize as hex string with `0x` prefix for cross-chain consistency. Cached indefinitely.

- **AC-phase3-chains-003-07:** Given `get_logs(from_block, to_block, contract_address, event_signature='Transfer(address,address,uint256)')` for a TRC-20 contract, when called, then it queries the TronGrid REST endpoint `/v1/contracts/{contract_address}/events?event_name=Transfer&min_block_number={from}&max_block_number={to}` (tronpy's `get_contract_events`), maps the response into `RawLog` objects with `tx_hash`, `block_number`, `address` (the contract), `topics` (synthesized from event signature + indexed args), `data` (the unindexed `value`). Window cap: 1000 blocks (TronGrid hard limit at free tier). Larger window raises `ChainQueryTooBroad`.

- **AC-phase3-chains-003-08:** Given `get_transaction(tx_hash)` for a confirmed Tron tx, when called, then returns `Receipt{tx_hash, block_number, block_hash, status, gas_used (= tronpy's energy_usage_total), effective_gas_price (None for Tron — energy model differs), logs}`. For pending tx returns Receipt with `block_number=None`. For non-existent returns None. **Tron's energy/bandwidth model is mapped to the EVM-shaped `Receipt`** with energy in `gas_used` and a comment noting the Tron-specific semantic; the user-facing display shows energy units distinctly per chain. The `effective_gas_price=None` is a deliberate signal that fee model doesn't translate.

- **AC-phase3-chains-003-09:** Given primary TronGrid fails (5xx, timeout 10s, rate-limit 429), when fallback also fails, then `ChainUnavailable` is raised with `details.chain='tron'`.

- **AC-phase3-chains-003-10:** Given the test environment, when adapter tests run, then vcrpy fixture is configured with cassette directory `tests/chains/cassettes/tron/`; new tests record live Shasta responses (one-time, requires `TRONGRID_API_KEY` env var) and replay deterministically afterwards. Cassettes filter the `TRON-PRO-API-KEY` header from recordings. Re-recording procedure documented in ADR-005 update and `tests/chains/cassettes/tron/README.md`.

- **AC-phase3-chains-003-11:** Given ADR-005 update, when committed, then `docs/decisions/ADR-005-chain-testing-asymmetry.md` gains a "Tron section": testing via vcrpy with rationale ("no production-grade local Tron emulator; Shasta is the closest to mainnet semantics; recorded responses provide deterministic CI"), cassette refresh procedure (delete cassette → run test against live Shasta with API key → review diff → commit), and the limitation acknowledgement (cassettes drift when Tron upgrades; CI doesn't catch upstream API changes between refreshes).

---

## Out of Scope

- Tron write path (build / sign / broadcast / monitor): `phase3-chains-004`.
- Tron-specific fee abstraction (energy + bandwidth model proper): documented as Tron quirk; full UX modeling deferred to `phase3-chains-004`'s build path.
- TRC-10 token support: never (TRC-10 is legacy; only TRC-20 stables in scope).
- Multi-signature accounts: V2.
- Frozen TRX (resource freezing for energy): out of scope.

---

## Dependencies

- **Code dependencies:** `phase2-chains-001` (ChainGateway port).
- **Data dependencies:** none.
- **External dependencies:** `tronpy` library, `base58` library (for the Address VO branch — tronpy bundles it but explicit dep is cleaner), TronGrid Shasta API key (operator-provisioned, env var `TRONGRID_API_KEY`), vcrpy for tests.

---

## Test Coverage Required

- [ ] **Property tests:** `tests/shared/domain/test_address_tron_properties.py` — for any random 20-byte payload, parse-serialize via base58check round-trips. Hex-form vs base58check-form parse to the same Address. Covers AC-01, AC-02. **Architecture-mandated property test extension.**
- [ ] **Domain unit tests:** `tests/shared/domain/test_address_tron.py` — known-good Tron addresses (TG3XX..., operator-provided test set) parse correctly; malformed (wrong prefix, bad checksum, too short) raise `InvalidAddress`.
- [ ] **Application tests:** `tests/chains/application/test_get_balance_tron.py` — uses `FakeChainGateway` returning Tron-shaped Money; validates the Money carries `chain='tron', decimals=6, currency='TRX'`.
- [ ] **Adapter tests:** `tests/chains/infra/test_tron_read_adapter.py` — vcrpy cassettes; exercises `get_native_balance`, `get_token_balance` (USDT contract), `get_block_number`, `get_block`, `get_logs` (TRC-20 Transfer event), `get_transaction`. Covers AC-03 through AC-08.
- [ ] **Adapter tests:** `tests/chains/infra/test_tron_rpc_failover.py` — uses `respx` to mock httpx for primary failure; asserts fallback attempt and final `ChainUnavailable` raise. Covers AC-09.
- [ ] **Contract tests:** none — no public API change.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] vcrpy cassettes committed under `tests/chains/cassettes/tron/`; cassette files do not contain API keys (assert via grep in CI).
- [ ] `import-linter` contract: `chains.domain` and `shared.domain` may not import tronpy.
- [ ] `mypy --strict` passes (tronpy has minimal type stubs; targeted `# type: ignore[no-untyped-call]` allowed with comments).
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] No new ports; no new domain events.
- [ ] **ADR-005 updated** with Tron section.
- [ ] Single PR. Conventional commit: `feat(chains): tron read adapter + Address VO base58check + ADR-005 update [phase3-chains-003]`.

---

## Implementation Notes

- The `Address` VO branch for Tron decodes via `base58.b58decode_check` (which validates checksum implicitly). If the input is hex, normalize first to base58check via `base58.b58encode_check(unhex(input))`. Centralize in `Address.parse` so callers don't worry about input form.
- tronpy's `AsyncTron` exists but is shallow — most methods still wrap sync calls. Use `asyncio.to_thread()` consistently to keep the `ChainGateway` async contract honest.
- The TronGrid free tier is generous (~50 req/sec) but the API key adds 100k req/day quota; document that Shasta-without-key works for low-volume CI but prod must use key.
- Tron timestamps are milliseconds (not seconds like Ethereum). Convert to `datetime` correctly: `datetime.fromtimestamp(block.timestamp / 1000, tz=UTC)`.
- The Shasta USDT contract address is operator-decided at deploy. Treat the constant `SHASTA_USDT_CONTRACT` in `tron_constants.py` as a deploy-time config; tests use a mock/fixture address.

---

## Risk / Friction

- vcrpy cassettes drift silently when Tron upgrades the API. Document in ADR-005: re-recording is a quarterly hygiene task. Set a calendar reminder; alternatively, a CI job once per week against live Shasta with `--vcr-record=new_episodes` catches drift early but costs API quota. Phase 3 ships the conservative version (CI uses cassettes only); a "weekly drift check" is V2 ops polish.
- TronGrid testnet sometimes returns stale blocks (5-10 second lag). Adapter doesn't compensate; the deposit watcher (`phase3-deposit-watcher-002`) handles it via confirmation depth.
- The Tron energy/bandwidth model is genuinely different from EVM gas. Folding it into the same `Receipt` shape with `effective_gas_price=None` is a shortcut. A reviewer who knows Tron may push back. Defense: this is a portfolio testnet wallet; full energy/bandwidth UI (resource freezing, energy estimation) is a Tron-specialist product. Document inline in `Receipt`'s docstring.
- `Address.parse('tron', ...)` accepting BOTH base58check AND hex is a small UX win (the user pasted from explorer-A which uses one, explorer-B which uses other). Test both paths explicitly.
