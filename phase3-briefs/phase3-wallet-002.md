---
ac_count: 10
blocks:
- phase3-deposit-watcher-002
- phase3-deposit-watcher-003
- phase3-admin-007
complexity: M
context: wallet
depends_on:
- phase2-wallet-001
- phase3-custody-003
- phase3-chains-003
- phase3-chains-004
- phase3-chains-005
- phase3-chains-006
estimated_hours: 4
id: phase3-wallet-002
phase: 3
sdd_mode: strict
state: ready
title: Multi-chain provisioning (Tron+Solana+cold) + asset catalog finalization
touches_adrs: []
---

# Brief: phase3-wallet-002 — Multi-chain provisioning (Tron+Solana+cold) + asset catalog finalization


## Context

Phase 2 provisioned a single Ethereum hot wallet per user. Phase 3 expands provisioning to: **all 3 chains × hot+cold = 6 wallets per user**. The user-facing endpoint stays the same shape (`GET /api/v1/wallets`), but now returns 3 entries (Ethereum, Tron, Solana — only hot addresses). Cold addresses are admin-only (visible in `phase3-admin-007`'s user-detail view).

This brief delivers: extension of `ProvisionUserWallets` to all 3 chains, **dual provisioning** (each chain triggers both `Custody.GenerateHotWallet` AND `Custody.GenerateColdWallet`), asset catalog finalization (TRX+USDT, SOL+USDC additions to the catalog from `phase2-wallet-001`), and a **backfill mechanism** for Phase 2 users (who have only ETH hot — they need Tron hot, Solana hot, and all-3 cold).

The asset catalog (already in `wallet/infra/asset_catalog.py` from Phase 2) gets its placeholder Tron and Solana entries filled in:

- **Tron:** native `TRX` (decimals=6, contract=None, is_stable=False); stable `USDT` on Shasta (`TG3XXyExBkPp9nzdajDZsozEu4BkaSJozs` placeholder — operator confirms at deploy, decimals=6, is_stable=True).
- **Solana:** native `SOL` (decimals=9); stable `USDC` on Devnet (`4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`, decimals=6, is_stable=True).

The backfill: a one-shot job `backfill_phase3_wallets` iterates `identity.users`, for each: (1) ensures hot wallets for all 3 chains (skip existing); (2) ensures cold wallets for all 3 chains (calls `phase3-custody-003`'s GenerateColdWallet). Idempotent. Triggered via admin endpoint AND CLI.

The `provisioning: true` UX flag from Phase 2 carries over — the dashboard polls until provisioning completes. With 6 wallets × ~500ms KMS calls each = ~3 seconds total provisioning time. Acceptable.

---

## Architecture pointers

- **Layer:** application (extension of existing use case + new backfill) + infra (asset catalog rows).
- **Packages touched:**
  - `wallet/application/use_cases/provision_user_wallets.py` (extend; loop over `ACTIVE_CHAINS = ['ethereum', 'tron', 'solana']`)
  - `wallet/application/use_cases/provision_cold_wallets.py` (new; calls Custody.GenerateColdWallet per chain)
  - `wallet/application/handlers/on_user_authenticated.py` (extend; calls both provision use cases)
  - `wallet/application/jobs/backfill_phase3_wallets.py` (one-shot)
  - `wallet/domain/ports.py` (extend `CustodyGateway` Protocol with `generate_cold_wallet(user_id, chain) -> Address`)
  - `wallet/infra/custody_gateway_adapter.py` (extend; wraps Custody.GenerateColdWallet)
  - `wallet/infra/asset_catalog.py` (finalize Tron + Solana asset entries)
- **Reads:** `wallet.wallets`, `custody.cold_wallets` (via gateway).
- **Writes:** `wallet.wallets` insert (one row per user-chain hot pair; same as Phase 2). **Cold wallet entries are NOT in `wallet.wallets`** — they live only in `custody.cold_wallets`. The Wallet context's table is for user-visible addresses.
- **Publishes events:** `wallet.WalletProvisioned` (already from Phase 2 — fires once per chain hot wallet). New: `wallet.AllWalletsProvisioned{user_id, hot_addresses, cold_addresses}` — fires once per user when all 6 are provisioned. Useful for Notifications.
- **Migrations:** none new.
- **OpenAPI:** `GET /api/v1/wallets` response shape unchanged from Phase 2 — just returns 3 entries instead of 1 once provisioning completes.

---

## Acceptance Criteria

- **AC-phase3-wallet-002-01:** Given the `ACTIVE_CHAINS` constant, when set to `['ethereum', 'tron', 'solana']` (Phase 3 default; Phase 2 was `['ethereum']`), when `ProvisionUserWallets(user_id)` runs, then it iterates all 3 chains and provisions hot wallets for each. Idempotent — existing wallets are skipped.

- **AC-phase3-wallet-002-02:** Given the new `ProvisionColdWallets(user_id)` use case, when invoked, then it iterates `ACTIVE_CHAINS` and calls `CustodyGateway.generate_cold_wallet(user_id, chain)` for each. Idempotent — existing cold wallets are skipped (Custody-side enforcement). Does NOT insert into `wallet.wallets` (cold isn't user-facing).

- **AC-phase3-wallet-002-03:** Given the subscriber `on_user_authenticated` (extended), when `identity.UserAuthenticated{actor_type='user'}` fires, then it invokes `ProvisionUserWallets(user_id)` THEN `ProvisionColdWallets(user_id)`, both in sequence within the same outbox handler. After both succeed, publishes `wallet.AllWalletsProvisioned`.

- **AC-phase3-wallet-002-04:** Given the asset catalog, when consulted for chain='tron', then native is `Asset(symbol='TRX', name='Tron', decimals=6, contract_address=None, is_stable=False)`, stable is `Asset(symbol='USDT', name='Tether', decimals=6, contract_address=Address('tron', '<SHASTA_USDT>'), is_stable=True)`. The contract address is read from env `SHASTA_USDT_CONTRACT` (deploy-time configurable for ops flexibility).

- **AC-phase3-wallet-002-05:** Given the asset catalog for chain='solana', then native is `Asset(symbol='SOL', name='Solana', decimals=9, contract_address=None, is_stable=False)`, stable is `Asset(symbol='USDC', name='USD Coin', decimals=6, contract_address=Address('solana', '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU'), is_stable=True)`. Same env-driven mint address pattern as Tron.

- **AC-phase3-wallet-002-06:** Given a Phase 3 user with all 6 wallets provisioned, when `GET /api/v1/wallets` is called, then the response contains 3 wallet entries sorted by `display_order` (ethereum=0, tron=1, solana=2). Each entry includes the wallet's hot address ONLY; cold addresses are not in this endpoint's response.

- **AC-phase3-wallet-002-07:** Given the `backfill_phase3_wallets` job, when triggered (admin endpoint or CLI), then: (1) loads all users from `identity.users`; (2) for each, runs `ProvisionUserWallets` + `ProvisionColdWallets`; (3) emits progress logs every 10 users; (4) on completion, logs `wallet.backfill_phase3.complete` with counts. **Critical:** the backfill must complete BEFORE the rebalance worker starts firing — runbook documents the deploy sequence (deploy code → run backfill → enable rebalance worker).

- **AC-phase3-wallet-002-08:** Given the extended `CustodyGateway` Protocol, when defined, then it has both methods: `async generate_hot_wallet(user_id, chain) -> Address` (existing from Phase 2) and `async generate_cold_wallet(user_id, chain) -> Address` (new). The implementation in `wallet/infra/custody_gateway_adapter.py` calls the corresponding Custody use cases. **Wallet still does NOT see `EncryptedPayload`, `HotWallet`, or `ColdWallet` types** — only `Address`. Anti-corruption layer preserved.

- **AC-phase3-wallet-002-09:** Given the `provisioning: true` UX flag for first-load polling (from Phase 2 AC-06), when applied to Phase 3, then the flag remains `true` until ALL 3 hot wallets exist (cold provisioning happens "behind the scenes" — the user doesn't wait for it). Cold provisioning failure does NOT keep the user blocked; the admin can re-trigger backfill if needed.

- **AC-phase3-wallet-002-10:** Given the import-linter contracts, when run, then `wallet.application` may not import `custody.application.use_cases.generate_cold_wallet` directly — only the `CustodyGateway` Protocol from `wallet.domain.ports`. Same anti-corruption invariant as Phase 2.

---

## Out of Scope

- Per-user wallet customization (renaming, archiving): V2.
- Multi-account per user (multiple addresses on the same chain): V2.
- Cold wallet visibility in user dashboard: never (it's a security model — cold is admin-only).
- Asset additions beyond TRX/USDT and SOL/USDC: V2.

---

## Dependencies

- **Code dependencies:** `phase2-wallet-001`, `phase3-custody-003`, all 4 chain expansion briefs (`chains-003` through `chains-006`).
- **Data dependencies:** `wallet.wallets` schema (Phase 2), `custody.cold_wallets` schema (Phase 2).
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Application tests:** `tests/wallet/application/test_provision_user_wallets_phase3.py` — happy path with 3 chains, idempotency on partial state (1 of 3 already provisioned). Uses Fakes. Covers AC-01.
- [ ] **Application tests:** `tests/wallet/application/test_provision_cold_wallets.py` — happy path 3 chains, idempotency, partial failure. Covers AC-02.
- [ ] **Application tests:** `tests/wallet/application/test_on_user_authenticated_phase3.py` — handler runs both provision use cases sequentially, publishes `AllWalletsProvisioned`. Covers AC-03.
- [ ] **Application tests:** `tests/wallet/application/test_backfill_phase3_wallets.py` — seeds Phase-2-style users (ethereum hot only), runs backfill, asserts all 6 wallets per user post-backfill. Covers AC-07.
- [ ] **Adapter tests:** `tests/wallet/infra/test_asset_catalog.py` — assert Tron and Solana entries shape. Covers AC-04, AC-05.
- [ ] **Adapter tests:** `tests/wallet/infra/test_custody_gateway_adapter.py` — extended; asserts both methods route correctly. Covers AC-08.
- [ ] **Contract tests:** `tests/api/test_wallets_endpoint_phase3.py` — fully provisioned user returns 3 wallet entries. Covers AC-06, AC-09.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] `import-linter` contracts pass — Wallet does not see Custody internals. Covers AC-10.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] One new domain event registered (`AllWalletsProvisioned`).
- [ ] CustodyGateway Protocol extended; fakes updated.
- [ ] Asset catalog entries finalized for Tron and Solana.
- [ ] `docs/runbook.md` updated with: deploy sequence (code → backfill → rebalance), backfill CLI command.
- [ ] Single PR. Conventional commit: `feat(wallet): multi-chain provisioning + cold + asset catalog [phase3-wallet-002]`.

---

## Implementation Notes

- The `ACTIVE_CHAINS` constant is in `wallet/domain/value_objects.py` (or `shared/domain/chains.py`) — single source of truth. Phase 4 leaves it unchanged.
- The "provision hot then cold sequentially" (AC-03) is conservative — could be parallel via `asyncio.gather`. Phase 3 ships sequential for simpler error handling; if startup latency is problematic, switch to parallel (KMS handles concurrent calls fine). Document.
- The cold wallet doesn't get a `wallet.wallets` row, but admin's user-detail view (`phase3-admin-007`) needs to read both hot AND cold. The admin's pattern: `SELECT * FROM wallet.wallets WHERE user_id = ?` for hot + `SELECT * FROM custody.cold_wallets WHERE user_id = ?` for cold (cross-schema read with appropriate role). Documented in admin-007.
- The asset catalog placeholder addresses (Shasta USDT, Devnet USDC) are testnet contracts. Document in catalog comments which contract is canonical and where to verify (Circle for USDC mint; Tether for USDT — but USDT on Shasta is community-deployed, not Tether-canonical, so document this caveat).
- Solana SPL contract address is technically a "mint" not a contract; the Address VO doesn't distinguish, but the catalog comment should note "this is the SPL mint address" for clarity.

---

## Risk / Friction

- 6 wallets × ~500ms each = 3 seconds first-login provisioning. The dashboard's `provisioning: true` poll loop is set to 30 max attempts × 1s = 30s ceiling. 3s is comfortable but if KMS latency spikes, the user could see provisioning take 10-15s. Consider a "provisioning takes a moment for first-time users..." subtitle in the dashboard's loading state — the design system from `phase1-web-004` already has it.
- The deploy sequence "backfill before enabling rebalance" (AC-07) is operationally critical. If rebalance fires before backfill completes, it tries to send to non-existent cold addresses and fails (gracefully — RebalanceFailed event). Document. The runbook step is essential.
- The Phase 2 → Phase 3 user migration: a user who logged in during Phase 2 has only ETH hot. They won't auto-trigger provisioning on next login because `wallet.wallets` is non-empty (the existing AC-03 from Phase 2 wallet-001 short-circuits if any wallet exists). The backfill is the migration path. Verify by: deploy Phase 3, run backfill, log in as a Phase 2 user, see 3 hot wallets. Test this in the integration test suite.
- The `display_order` constants (ethereum=0, tron=1, solana=2) are UX choices — Ethereum first because it's the most familiar to crypto-aware reviewers. If a reviewer prefers a different order, change the constants. Cosmetic.
