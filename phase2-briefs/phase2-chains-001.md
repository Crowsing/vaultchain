---
ac_count: 5
blocks:
- phase2-chains-002
- phase2-wallet-001
- phase2-balances-001
- phase2-deposit-watcher-001
complexity: M
context: chains
depends_on:
- phase1-shared-003
- phase1-shared-005
estimated_hours: 4
id: phase2-chains-001
phase: 2
sdd_mode: strict
state: ready
title: Chains context + Ethereum read adapter
touches_adrs:
- ADR-005
---

# Brief: phase2-chains-001 — Chains context + Ethereum read adapter


## Context

The Chains context is domain-agnostic infrastructure: RPC clients, transaction building helpers, fee estimation, broadcast, receipt monitoring. Every chain-specific call from elsewhere in the system goes through a stable port `ChainGateway` so callers (Wallet, Custody, Transactions, Balances, deposit-watcher) never import chain SDKs directly. Per architecture Section 2 + Section 5, Phase 2 implements only the Ethereum adapter; Tron and Solana adapters are Phase 3 with the same port shape.

This brief delivers the **read side**: `ChainGateway` Protocol with read methods, the `EthereumReadAdapter` using `web3.py` AsyncWeb3 + Alchemy/Infura RPC URL (with a free-tier fallback to public RPC), the `Address` value object validation per chain (Ethereum's EIP-55 checksum, Tron's base58check, Solana's base58 — all in shared kernel; this brief tightens the Ethereum implementation), and `BlockReference` value object (`{height: int, hash: str, timestamp: datetime}`). The write side (build/sign/broadcast/monitor) is the next brief `phase2-chains-002`.

The deliberate split between read and write helps testing: the read adapter is exercised heavily by Balances (USD aggregation, balance display) and the deposit watcher (reading logs); the write adapter is exercised by signing + broadcasting flows. Splitting the brief means each PR is reviewable in <30 minutes and the read side is foundationally mergeable before write completes.

The RPC strategy: a primary endpoint (Alchemy free-tier — 300M compute units/month, more than enough for portfolio scale) and a fallback (a public endpoint like `https://ethereum-sepolia-rpc.publicnode.com`). On primary failure (5xx, timeout, rate limit), the adapter falls back, emits a structlog warning, and continues. Both endpoints' URLs are env vars; the operator picks at deploy. In tests, an Anvil testcontainer replaces both — Anvil's RPC is identical-shape to Alchemy's.

---

## Architecture pointers

- **Layer:** application + infra. Domain layer has only value objects and ports.
- **Packages touched:**
  - `chains/domain/value_objects.py` (`BlockReference`, `Receipt`, `RawLog`, `FeeEstimate` types — note: address validation is shared kernel from bootstrap)
  - `chains/domain/ports.py` (`ChainGateway` Protocol — read methods only in this brief)
  - `chains/application/use_cases/get_balance.py`, `get_block.py`, `get_logs.py`
  - `chains/infra/ethereum_read_adapter.py`
  - `chains/infra/ethereum_rpc_client.py` (low-level web3.py wrapper with primary/fallback)
  - `chains/infra/ethereum_constants.py` (chain IDs: 11155111 for Sepolia; ERC-20 ABI snippet for `balanceOf`, `transfer`, `Transfer` event)
  - `docs/decisions/ADR-005-chain-testing-asymmetry.md` (drafted here)
- **Reads:** External RPC only.
- **Writes:** none in this brief.
- **Events:** none new.
- **Ports / adapters:** `ChainGateway` (read methods), `EthereumReadAdapter` (chain='ethereum').
- **Migrations:** none.
- **OpenAPI:** none — Chains has no public API.

---

## Acceptance Criteria

- **AC-phase2-chains-001-01:** Given the `ChainGateway` Protocol, when defined, then it has these read methods: `async get_native_balance(address: Address) -> Money`, `async get_token_balance(address: Address, token_contract: Address, decimals: int) -> Money`, `async get_block_number() -> int`, `async get_block(height: int) -> BlockReference`, `async get_logs(from_block: int, to_block: int, contract: Address | None, event_signature: str | None) -> list[RawLog]`, `async get_transaction(tx_hash: str) -> Receipt | None`. Each method takes / returns plain types — no web3.py types leak.

- **AC-phase2-chains-001-02:** Given the `EthereumReadAdapter` constructed with `(primary_rpc_url, fallback_rpc_url, chain_id=11155111)`, when `get_native_balance(address)` is called, then it: (1) tries primary RPC via `AsyncWeb3.eth.get_balance(address)`; (2) on failure (timeout 10s, 5xx, RPC error), falls back to fallback URL with the same call; (3) returns `Money(amount=balance_wei, currency='ETH', decimals=18)`. The `Money` VO is from shared kernel; `decimals=18` for ETH is hardcoded in adapter.

- **AC-phase2-chains-001-03:** Given `get_token_balance(address, token_contract, decimals=6)` for USDC on Sepolia (contract `0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238`), when called, then it constructs the contract via `web3.eth.contract(address=token_contract, abi=ERC20_ABI)`, calls `contract.functions.balanceOf(address).call()`, and returns `Money(amount=balance, currency='USDC', decimals=6, chain='ethereum')`. Address-checksum normalization happens at adapter boundary.

- **AC-phase2-chains-001-04:** Given `get_block_number()`, when called, then it returns the latest block number on Sepolia. Cached for 5 seconds in Redis (`chains:eth:latest_block`) to absorb burst load from concurrent requests in a single API call. Cache miss → RPC call → write cache → return.

- **AC-phase2-chains-001-05:** Given `get_block(height)`, when called, then it returns `BlockReference(height, block_hash, datetime_from_timestamp)`. Cached indefinitely (block by height is immutable post-finalization) under `chains:eth:block:<height>`.

- **AC-phase2-chains-001-06:** Given `get_logs(from_block=10000, to_block=10100, contract=USDC_addr, event_signature='Transfer(address,address,uint256)')`, when called, then it queries `eth_getLogs` with topic[0] = keccak256 of the signature, returns a list of `RawLog{block_number, tx_hash, address, topics, data, log_index}`. Bounded query — caller must specify a window ≤ 1000 blocks (RPC providers cap at ~1000). Window > 1000 raises `ChainQueryTooBroad`.

- **AC-phase2-chains-001-07:** Given `get_transaction(tx_hash)` for a tx that is mined, when called, then it returns `Receipt{tx_hash, block_number, block_hash, status, gas_used, effective_gas_price, logs, contract_address}`. For a tx that is pending (in mempool but not mined), returns a `Receipt` with `block_number=None, status=None`. For a tx that doesn't exist, returns `None`.

- **AC-phase2-chains-001-08:** Given primary RPC failure, when fallback also fails, then `ChainUnavailable` (DomainError) is raised, mapped to HTTP 503 in callers. The error includes which chain (`details.chain='ethereum'`) so frontend can show a chain-specific banner.

- **AC-phase2-chains-001-09:** Given an Address value object construction `Address.parse('ethereum', '0xinvalidstring')`, when invalid, then raises `InvalidAddress`. **Property test:** for any random 42-char hex string, `Address.parse('ethereum', addr).serialize() == addr.lower()`. The Ethereum branch enforces EIP-55 checksum: input may be all-lowercase, all-uppercase, or mixed-case; if mixed-case, must match EIP-55 checksum or `InvalidAddress` is raised.

- **AC-phase2-chains-001-10:** Given the test environment, when adapter tests run, then a session-scoped Anvil pytest fixture provides a local EVM at `http://127.0.0.1:8545`, chain_id=11155111 (configured via Anvil's `--chain-id`). Tests deploy a tiny ERC-20 mock contract for USDC behavior and exercise `get_native_balance`, `get_token_balance`, `get_logs` against real Anvil RPC.

- **AC-phase2-chains-001-11:** Given ADR-005, when committed, then `docs/decisions/ADR-005-chain-testing-asymmetry.md` exists with sections explaining: Anvil for EVM (real Solidity opcodes, identical RPC interface), deferred plans for Solana (`solana-test-validator`, Phase 3), deferred plans for Tron (vcrpy recording — Tron's testnet has no usable local emulator). Frames the asymmetry as engineering honesty: each chain ecosystem ships different test tooling and the project doesn't pretend otherwise.

---

## Out of Scope

- Tron and Solana adapters: Phase 3.
- Write methods on ChainGateway (build, sign, broadcast, monitor): `phase2-chains-002`.
- WebSocket subscriptions to chain events: not needed — the deposit watcher polls. WebSocket would require additional ops complexity and the polling cost on free-tier RPC is fine.
- Mempool inspection beyond `get_transaction`: V2.
- Custom RPC method extensions (Alchemy's `alchemy_getAssetTransfers`): rejected — vendor lock-in. Plain `eth_getLogs` works.
- Block reorg handling at this layer: deferred to deposit watcher (`phase2-deposit-watcher-001`), which adds confirmation-depth thresholds.

---

## Dependencies

- **Code dependencies:** `phase1-shared-003` (UoW, though minimal use here), `phase1-shared-005` (error envelope for `ChainUnavailable`). Shared kernel `Money`, `Address`, `Chain` already from bootstrap.
- **Data dependencies:** none.
- **External dependencies:** `web3.py` (AsyncWeb3), Alchemy free-tier API key (operator-provisioned, env var `ALCHEMY_API_KEY` or full URL via `ETH_RPC_URL_PRIMARY`), public Sepolia RPC fallback URL via `ETH_RPC_URL_FALLBACK`, Anvil testcontainer (image `ghcr.io/foundry-rs/foundry:latest`).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/chains/domain/test_value_objects.py` — `BlockReference`, `Receipt`, `RawLog`, `FeeEstimate` equality and serialization.
- [ ] **Property tests:** `tests/shared/domain/test_address_ethereum_properties.py` — for any random valid 20-byte address, parse-serialize round-trips per AC-09. **This realizes the architecture-mandated property test for Address VO (Section 5 line 4).**
- [ ] **Application tests:** `tests/chains/application/test_get_balance.py` — uses `FakeChainGateway` (returns scripted Money values), happy path + ChainUnavailable path. Covers usage shape from Wallet/Balances callers.
- [ ] **Adapter tests:** `tests/chains/infra/test_ethereum_read_adapter.py` — Anvil fixture, exercises `get_native_balance`, `get_token_balance` (deploys a mock ERC-20 first), `get_block_number`, `get_block`, `get_logs` (emits a `Transfer` event via the mock contract, then queries it). Covers AC-02 through AC-07, AC-10.
- [ ] **Adapter tests:** `tests/chains/infra/test_ethereum_rpc_failover.py` — uses `respx` to mock httpx-level RPC; primary returns 503 → adapter falls back; both fail → raises `ChainUnavailable`. Covers AC-08.
- [ ] **Contract tests:** none — no public API.
- [ ] **E2E:** none yet.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contract: `chains.domain` may not import web3.py; only `chains.infra` imports it. Enforced.
- [ ] `mypy --strict` passes (web3.py has imperfect type stubs; use targeted `# type: ignore[...]` only where unavoidable, document each).
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (chains/domain 95%, chains/application 90%, chains/infra 80%).
- [ ] No new domain events.
- [ ] One new port `ChainGateway` declared in `chains/domain/ports.py` with a `FakeChainGateway` in `tests/chains/fakes/`.
- [ ] **ADR-005 drafted and committed.**
- [ ] Single PR. Conventional commit: `feat(chains): ethereum read adapter + ChainGateway port + ADR-005 [phase2-chains-001]`.

---

## Implementation Notes

- The Anvil fixture lives in `tests/conftest.py` at the project root and is shared between Custody and Chains tests (they both need it). Session-scoped, instantiated once per test run.
- web3.py's `AsyncWeb3` has improved over the years; use `AsyncWeb3(AsyncHTTPProvider(rpc_url))`. Avoid the older sync `Web3` even in tests — keeps the codebase async-consistent.
- The primary/fallback failover is implemented as a tiny wrapper around two `AsyncHTTPProvider` instances; on failure the wrapper retries on the fallback. NOT a reactive circuit-breaker — keep it simple. A 3-failure-in-1-minute → "primary disabled for 5 minutes" pattern is reasonable; add it if test load reveals flakiness.
- ERC-20 ABI: only need `balanceOf(address) returns (uint256)`, `transfer(address, uint256)`, `Transfer(address indexed, address indexed, uint256)`. Bundle as a constant in `ethereum_constants.py`.
- Don't shell out to `cast` or `forge` from Python — keep the dependency surface to web3.py + boto3 only.
- The `Receipt.status` field uses `1=success, 0=failure, None=pending` per EVM convention. Document inline.

---

## Risk / Friction

- Alchemy free-tier API key requires an Alchemy account. Add this to the deploy runbook checklist. If the operator doesn't have one, the public-RPC fallback works for low traffic but is rate-limited and unreliable.
- web3.py's type stubs are not great. Resist the temptation to write `# type: ignore` everywhere; it defeats `mypy --strict`. Where unavoidable, use `# type: ignore[no-untyped-call]` with a brief comment explaining why. Phase 2/3 cleanup pass can revisit.
- Anvil testcontainer adds ~3 seconds to test startup. For local iteration, allow the developer to set `VAULTCHAIN_USE_HOSTED_ANVIL=1` to use a long-running Anvil from `docker-compose-dev.yml` instead. Document in `web/README.md`.
- The `eth_getLogs` 1000-block cap is provider-dependent; some providers (Alchemy paid tier) allow 10000. The adapter's hardcoded cap is a portable lowest-common-denominator. The deposit watcher (next brief) is the only consumer that needs windowed iteration; document the cap there too.
