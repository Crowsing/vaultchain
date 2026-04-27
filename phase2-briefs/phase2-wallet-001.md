---
ac_count: 6
blocks:
- phase2-balances-001
- phase2-transactions-002
- phase2-faucet-001
- phase2-web-006
- phase2-deposit-watcher-001
complexity: M
context: wallet
depends_on:
- phase2-custody-002
- phase2-chains-001
- phase1-shared-003
- phase1-shared-005
estimated_hours: 4
id: phase2-wallet-001
phase: 2
sdd_mode: strict
state: ready
title: Wallet domain + provision-on-signup + GET /wallets
touches_adrs: []
---

# Brief: phase2-wallet-001 — Wallet domain + provision-on-signup + GET /wallets


## Context

The Wallet context owns the user-facing wallet entity. Per architecture Section 2, "Wallet — user-facing wallets per user (3 fixed: ETH/TRX/SOL), addresses, balance views, total aggregation surface." It's the read surface the SPA queries to render the dashboard. Each user has exactly one wallet per chain — created on first login post-Phase-2-deploy via a subscriber to `identity.UserAuthenticated`. The wallet entity stores: `id, user_id, chain, address, asset_set (the list of native + stable assets shown for this chain), display_order, created_at`. Critically, **Wallet does not own the private key** — that's Custody's `hot_wallets` table. Wallet stores only the public address, and looks up the private key indirectly via `Custody.GenerateHotWallet` at provisioning time.

The provisioning flow: when a user authenticates for the first time after Phase 2 deploy (i.e., they exist in `identity.users` but have no `wallet.wallets` rows), the `ProvisionUserWallets` use case fires. For each chain in the active configuration (`['ethereum']` in Phase 2; `['ethereum', 'tron', 'solana']` in Phase 3), it: (1) calls `Custody.GenerateHotWallet(user_id, chain)` to mint the keypair and store the encrypted private key; (2) inserts a `wallet.wallets` row with the resulting address; (3) publishes `wallet.WalletProvisioned`. All within a single UoW so partial failures don't leave orphan keys.

The trigger: a subscriber `wallet.handlers.on_user_authenticated` listens for `identity.UserAuthenticated` (published in Phase 1) and runs `ProvisionUserWallets` if no wallets exist for the user. This is idempotent — a user who already has wallets is a no-op. The subscriber runs in the outbox publisher worker (the same arq process); it's not on the hot path of login. The dashboard, on first load post-provisioning, sees the wallets via `GET /wallets`. Until provisioning completes (typically <2 seconds), the dashboard shows the `ProvisioningWallets` edge state from `empty-states.jsx`.

The single public endpoint: `GET /api/v1/wallets`. Returns a list of `{id, chain, address, native_asset, stable_assets, display_order}`. No balance — Balances context owns that. The frontend composes wallet + balances in the dashboard.

---

## Architecture pointers

- **Layer:** application + domain + infra + delivery.
- **Packages touched:**
  - `wallet/domain/entities/wallet.py` (Wallet aggregate)
  - `wallet/domain/value_objects/asset.py` (`Asset{symbol, name, decimals, contract_address: Address | None, is_stable: bool}`)
  - `wallet/domain/ports.py` (`WalletRepository`)
  - `wallet/application/use_cases/provision_user_wallets.py`, `list_user_wallets.py`
  - `wallet/application/handlers/on_user_authenticated.py` (subscriber)
  - `wallet/infra/sqlalchemy_wallet_repo.py`
  - `wallet/infra/migrations/<timestamp>_wallet_initial.py`
  - `wallet/delivery/router.py` (`GET /api/v1/wallets`)
  - `wallet/infra/asset_catalog.py` (the static list of supported assets per chain — Phase 2 includes ETH + USDC on Sepolia)
- **Reads:** `wallet.wallets` by `user_id`. Cross-context: calls `Custody.GenerateHotWallet` (via port).
- **Writes:** `wallet.wallets` insert. No updates (Wallet entities are immutable post-creation in V1).
- **Publishes events:**
  - `wallet.WalletProvisioned{wallet_id, user_id, chain, address}` — registered in `shared/events/registry.py`.
- **Ports / adapters:** new `WalletRepository`, plus uses `CustodyGateway` Protocol (a thin port wrapping `Custody.GenerateHotWallet` to enforce the anti-corruption boundary).
- **Migrations:** `wallet.wallets` table.
- **OpenAPI:** new `GET /api/v1/wallets` endpoint.

---

## Acceptance Criteria

- **AC-phase2-wallet-001-01:** Given the migration runs, when applied, then `wallet.wallets` table exists with columns `id UUID PK, user_id UUID NOT NULL, chain TEXT NOT NULL CHECK (chain IN ('ethereum','tron','solana')), address TEXT NOT NULL, display_order SMALLINT NOT NULL DEFAULT 0, created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(user_id, chain)`. The user_id is NOT a foreign key (cross-schema FKs are avoided per architecture Section 3); referential integrity at the application layer.

- **AC-phase2-wallet-001-02:** Given the `Wallet` aggregate, when constructed via factory `Wallet.create(user_id, chain, address)`, then it: validates `address` via `Address.parse(chain, address)`, sets `display_order` based on chain (`ethereum=0, tron=1, solana=2` — fixed UX order). Returns the aggregate with a fresh UUID. Aggregate is read-only post-construction.

- **AC-phase2-wallet-001-03:** Given the `ProvisionUserWallets` use case is invoked with `user_id` and the active chain set `['ethereum']`, when executed, then within a single UoW: for each chain, (1) checks repo for existing wallet → if exists, skip; (2) calls `CustodyGateway.generate_hot_wallet(user_id, chain) → address`; (3) inserts `Wallet.create(user_id, chain, address)` via repo; (4) publishes `wallet.WalletProvisioned`. Idempotent on re-run (skips existing).

- **AC-phase2-wallet-001-04:** Given the subscriber `on_user_authenticated`, when `identity.UserAuthenticated{user_id, actor_type='user', ...}` arrives in the outbox, then it invokes `ProvisionUserWallets(user_id)`. For `actor_type='admin'`, the subscriber is a no-op (admins don't get wallets). Subscriber acks the event regardless of result; failures retry per outbox semantics (max 5 attempts, then dead-letter).

- **AC-phase2-wallet-001-05:** Given `GET /api/v1/wallets` is called by an authenticated user, when handled, then the response is `{wallets: [{id, chain, address, native_asset: {symbol, name, decimals, is_stable}, stable_assets: [...], display_order}]}` sorted by `display_order`. For Phase 2 (Ethereum only, ETH + USDC), a fully-provisioned user sees one wallet with native=ETH + stable_assets=[USDC]. The endpoint is rate-limited per architecture (60/min/user).

- **AC-phase2-wallet-001-06:** Given a user authenticated for the first time post-Phase-2-deploy, when they hit `GET /api/v1/wallets` before provisioning has completed (race window typically <2s), then the endpoint returns `{wallets: [], provisioning: true}`. The `provisioning: true` flag tells the frontend to keep polling every 1s, max 30 attempts. Once provisioning completes and the next call returns wallets, the flag is `false`.

- **AC-phase2-wallet-001-07:** Given the `CustodyGateway` Protocol, when defined in `wallet/domain/ports.py`, then it exposes only the methods Wallet needs: `async generate_hot_wallet(user_id: UUID, chain: Chain) -> Address`. **Wallet does NOT see `EncryptedPayload`, `HotWallet`, or any Custody internal type.** This enforces the anti-corruption layer per architecture Section 2 ("Custody never sees Transaction... AI never sees Transaction"). The adapter implementation in `wallet/infra/custody_gateway_adapter.py` calls `Custody.GenerateHotWallet` and returns only the address.

- **AC-phase2-wallet-001-08:** Given the asset catalog in `wallet/infra/asset_catalog.py`, when consulted, then it provides for `chain='ethereum'`: native `Asset(symbol='ETH', name='Ether', decimals=18, contract_address=None, is_stable=False)` and stable `Asset(symbol='USDC', name='USD Coin', decimals=6, contract_address=Address('ethereum', '0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238'), is_stable=True)` — the canonical Sepolia USDC contract per Circle's docs. For `chain='tron'` and `chain='solana'`, the catalog has placeholder entries that will be filled in Phase 3.

- **AC-phase2-wallet-001-09:** Given a user has wallets, when `GET /api/v1/wallets` is repeatedly called, then the response is cached on the client side (TanStack Query default 5min stale time) but the backend has no caching — the query is cheap (a single SELECT by user_id with LIMIT 3). Backend response includes `Cache-Control: private, max-age=60` to nudge browser caching.

- **AC-phase2-wallet-001-10:** Given a `WalletProvisioned` event is published, when downstream subscribers (Balances, Notifications) come online in subsequent briefs, then they can replay from the outbox. The event payload is stable: `{wallet_id, user_id, chain, address, provisioned_at}`. No coupling to entity internals.

---

## Out of Scope

- Tron and Solana wallet provisioning: Phase 3 (just unlock chains in the active set; the code path already supports it).
- Wallet rename / custom labels: V2.
- Multiple wallets per chain per user: V2 (the schema's UNIQUE constraint enforces 1:1 in V1).
- Wallet archival / deletion: V2.
- Delegated signing / multi-sig: V2.
- The actual balance fetching: `phase2-balances-001`.
- The deposit watcher for incoming txs: `phase2-deposit-watcher-001`.

---

## Dependencies

- **Code dependencies:** `phase2-custody-002` (Custody.GenerateHotWallet via port), `phase2-chains-001` (Address VO refinements), `phase1-shared-003` (UoW + outbox subscriber pattern).
- **Data dependencies:** `custody.hot_wallets` migration applied; `identity.users` schema applied; outbox publisher running.
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/wallet/domain/test_wallet_entity.py` — covers AC-02 (factory, address validation, display_order assignment).
- [ ] **Application tests:** `tests/wallet/application/test_provision_user_wallets.py` — happy path (one chain), idempotency on re-run, partial failure (Custody returns error → UoW rollback). Uses `FakeWalletRepository` and `FakeCustodyGateway`. Covers AC-03.
- [ ] **Application tests:** `tests/wallet/application/test_on_user_authenticated.py` — fires the handler with a `UserAuthenticated` event, asserts `ProvisionUserWallets` invoked exactly once; with admin actor, asserts no-op. Covers AC-04.
- [ ] **Application tests:** `tests/wallet/application/test_list_user_wallets.py` — happy path, empty (provisioning in flight) returns `provisioning=true`. Covers AC-05, AC-06.
- [ ] **Adapter tests:** `tests/wallet/infra/test_sqlalchemy_wallet_repo.py` — testcontainer Postgres, asserts INSERT with UNIQUE(user_id, chain) constraint, list_by_user returns ordered by display_order.
- [ ] **Adapter tests:** `tests/wallet/infra/test_custody_gateway_adapter.py` — wires the real Custody use case via the gateway adapter, end-to-end (LocalStack KMS) provisions a wallet and returns the address. This is also a small integration test for the cross-context pattern.
- [ ] **Contract tests:** `tests/api/test_wallets_endpoint.py` — TestClient hits `GET /api/v1/wallets`; before provisioning, asserts `provisioning: true`; after, asserts wallet list. Covers AC-05, AC-06, AC-09.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass: `wallet.application` may not import `custody.application` or `custody.infra` directly — only the `CustodyGateway` Protocol from `wallet.domain.ports`.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] OpenAPI schema diff: 1 new endpoint documented; `docs/api-contract.yaml` committed.
- [ ] One new domain event registered.
- [ ] Two new ports declared (`WalletRepository`, `CustodyGateway`) with fakes in `tests/wallet/fakes/`.
- [ ] Single PR. Conventional commit: `feat(wallet): domain + provision-on-signup + GET /wallets [phase2-wallet-001]`.

---

## Implementation Notes

- The "no cross-schema FK" rule is per architecture Section 3 ("Each bounded context owns a Postgres schema"). The Wallet's `user_id` is just a UUID column with no FK; the application layer trusts that the Identity context generated it. This is a deliberate trade-off: stronger context isolation, slightly weaker referential integrity.
- The `provisioning: true` UX in AC-06 is a small but important detail — without it, a fresh user sees an empty wallet list and concludes the system is broken. The frontend's polling logic (web-006) leans on this flag.
- The asset catalog is a static module, not a DB table. This is intentional: the supported asset set is a deploy-time decision, not a runtime one. Adding a new asset means a code change + ADR (small one). DB-driven asset config is V2 if the product justifies it.
- The subscriber `on_user_authenticated` receives all UserAuthenticated events including admin logins. Filter at the top: `if event.actor_type != 'user': return`. Cleaner than filtering at outbox-subscriber registration time.
- `GET /wallets` doesn't need pagination — V1 max is 3 wallets per user.

---

## Risk / Friction

- The first-login race window where the SPA might query `/wallets` before provisioning completes is the kind of timing bug that's invisible until a real deploy. Test it explicitly: a contract test that simulates the race (provisioning is mid-flight when the request arrives) and asserts the `provisioning: true` flag flips correctly.
- Cross-schema "soft FK" for `user_id` is a pattern reviewers may push back on. The defense is in architecture-decisions Section 3 — cite it. If they still don't like it, point out that surgical schema dumps (`pg_dump --schema=wallet`) work cleanly because of this.
- The asset catalog has placeholder entries for Tron and Solana; ensure those are truly placeholder (return empty stable_assets) and not active in Phase 2's chain set. Otherwise the dashboard renders broken cards.
- Provisioning failures retry up to 5 times via outbox. After 5, the event lands in dead-letter. The frontend's polling will give up at 30s. There's a gap: the user sees a permanent "still provisioning..." state without remediation. Document this in the runbook: "if a user is stuck in provisioning, check `event_log.dead_letter` and re-publish manually." V2 adds an admin re-trigger button.
