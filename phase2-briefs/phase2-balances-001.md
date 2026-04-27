---
ac_count: 8
blocks:
- phase2-web-006
complexity: M
context: balances
depends_on:
- phase2-ledger-001
- phase2-ledger-002
- phase2-pricing-001
- phase2-wallet-001
- phase2-chains-001
estimated_hours: 4
id: phase2-balances-001
phase: 2
sdd_mode: strict
state: ready
title: Balances read-projection + GET /portfolio with USD aggregation
touches_adrs: []
---

# Brief: phase2-balances-001 — Balances read-projection + GET /portfolio with USD aggregation


## Context

The Balances context is a thin read-projection over Ledger and the chain RPC. Per architecture Section 2 + Section 3, it owns one job: aggregate per-user, per-wallet, per-asset balances with USD conversion, exposed via `GET /api/v1/portfolio`. It does NOT have its own write side — balances are derived. The two sources are:

1. **Ledger** (the canonical source for held funds): per-account balance via `GetAccountBalance`. This represents what VaultChain's books say the user owns.
2. **Chain RPC** (truth check): `ChainGateway.get_native_balance(address)` and `get_token_balance(address, contract, decimals)` for each user wallet.

These two sources must agree (the daily reconciliation job from `ledger-001` checks). For the user-facing endpoint, **the Ledger is authoritative** — what the books say is what the user sees. On-chain balance is consulted in two cases: (1) deposit detection (handled by `phase2-deposit-watcher-001`, which posts to the Ledger when chain balance increases); (2) the explicit "force-refresh" debug endpoint for admin (introduced in Phase 3).

This brief delivers: the `Portfolio` aggregate (read-only, computed on demand), the `GetPortfolio` use case (composes Wallet list + per-wallet Ledger balances + per-asset USD conversion via Pricing), the `GET /api/v1/portfolio` endpoint, and a `BalanceProjection` Redis cache that stores the last-computed result for 30 seconds (rate limits per architecture Section 4 — the dashboard polls this every 30s, so the cache prevents redundant compute).

The endpoint shape: returns `{wallets: [{wallet_id, chain, address, balances: [{asset, amount: chain_native_string, decimals, usd_value: decimal_string}], total_usd}], total_usd_all_chains}`. Decimals are returned alongside amounts so the frontend can format without hardcoding (`web3.utils.formatUnits` equivalent in TypeScript).

---

## Architecture pointers

- **Layer:** application + delivery. No domain entities — `Portfolio` is a frozen dataclass shaped for the response. No infra adapters new — uses existing Ledger / Pricing / Wallet ports.
- **Packages touched:**
  - `balances/application/use_cases/get_portfolio.py`
  - `balances/application/queries/portfolio_view.py` (the `Portfolio` projection dataclass)
  - `balances/application/handlers/on_posting_committed.py` (subscriber that invalidates the BalanceProjection cache key)
  - `balances/delivery/router.py` (`GET /api/v1/portfolio`)
  - `balances/infra/redis_balance_projection_cache.py`
- **Reads:** Ledger (`GetAccountBalance` per (user_id, chain, asset)), Pricing (`GetQuotesUseCase`), Wallet (`ListUserWallets`).
- **Writes:** none. Cache invalidation only.
- **Subscribes to events:** `ledger.PostingCommitted` — invalidates the BalanceProjection cache for affected users.
- **Migrations:** none.
- **OpenAPI:** new `GET /api/v1/portfolio` endpoint.

---

## Acceptance Criteria

- **AC-phase2-balances-001-01:** Given an authenticated user with one Ethereum wallet (provisioned via `wallet-001`), when `GET /api/v1/portfolio` is called, then the response is a JSON envelope `{portfolio: {wallets: [{wallet_id, chain: 'ethereum', address: '0x...', balances: [{asset: 'ETH', amount: '0', decimals: 18, usd_value: '0.00'}, {asset: 'USDC', amount: '0', decimals: 6, usd_value: '0.00'}], total_usd: '0.00'}], total_usd_all_chains: '0.00', priced_at: '2026-...', stale: false}}`. For Phase 2 (Ethereum only, no incoming deposits yet), all amounts are zero — but the structure is in place.

- **AC-phase2-balances-001-02:** Given the same user after a deposit was posted to Ledger (e.g., 0.1 ETH credited to `user_hot_wallet:<uuid>:ethereum:ETH`), when `GET /portfolio` is called, then the ETH balance row reflects `amount: '100000000000000000'` (0.1 ETH in wei), `decimals: 18`, `usd_value` computed as `(amount / 10^18) * price_per_eth_usd` rounded to 2 decimals (e.g., `'284.05'` if ETH is $2840.50).

- **AC-phase2-balances-001-03:** Given Pricing returns `stale: true` for one or more assets (e.g., CoinGecko outage and 24h fallback active), when the portfolio is computed, then the response's `stale` field is `true` and a `stale_assets: ['ETH', 'USDC']` array lists which. The frontend uses this to show a tiny "prices may be outdated" banner.

- **AC-phase2-balances-001-04:** Given a portfolio query is in flight, when a second concurrent query for the same user arrives, then the cache key `balances:portfolio:<user_id>` resolves the second call from cache (30s TTL). The cache stores the full envelope, NOT a per-asset breakdown — simplest invalidation.

- **AC-phase2-balances-001-05:** Given a `ledger.PostingCommitted` event arrives via outbox affecting `user_hot_wallet:<uuid>:*` accounts, when the subscriber processes it, then it DELs the cache key `balances:portfolio:<user_id>`. Next portfolio query recomputes. **No fancy "incremental update" — invalidation + recompute is simple and correct.**

- **AC-phase2-balances-001-06:** Given Ledger returns 503 (database issue), when `GetPortfolio` runs, then the use case raises `LedgerUnavailable` mapped to HTTP 503. Given Pricing returns 503 (no last-known cache, complete failure), when `GetPortfolio` runs, then the use case STILL returns balance data — but with `usd_value: null` for the affected assets, `priced_at: null`, and `stale: true`. Balance display should not be blocked by USD pricing failure (degraded UX > broken UX).

- **AC-phase2-balances-001-07:** Given the `Portfolio` projection dataclass, when serialized to JSON, then all `amount` fields are strings (avoiding JS BigInt loss of precision for wei values), all `usd_value` fields are strings (Decimal precision preserved), `priced_at` is ISO8601 with timezone. Schema validated by Pydantic at the delivery layer.

- **AC-phase2-balances-001-08:** Given an authenticated user with no wallets yet (provisioning in flight, per `wallet-001` AC-06), when `GET /portfolio` is called, then it returns `{portfolio: {wallets: [], total_usd_all_chains: '0.00', priced_at: ..., stale: false, provisioning: true}}`. The `provisioning: true` flag mirrors the Wallet endpoint's flag.

- **AC-phase2-balances-001-09:** Given the endpoint is rate-limited, when called more than 60 times per minute per user, then the 61st request returns 429 with `Retry-After: <seconds>`. The 30s cache makes hitting this limit unusual — but it caps abuse.

- **AC-phase2-balances-001-10:** Given a user has an Ethereum wallet but no Tron/Solana wallets (Phase 2 only provisions Ethereum), when the portfolio is composed, then only the Ethereum wallet appears. The endpoint does NOT return placeholder Tron/Solana entries. (Frontend's `EmptyDashboard` per `web-004` already handles "expected wallets vs actual" — but that's a frontend concern.)

---

## Out of Scope

- Per-historical-period charts (24h change, 7d change): Phase 4 polish.
- Per-transaction line items in portfolio response: that's the Activity endpoint, separate.
- Tron and Solana balances: Phase 3.
- Reading on-chain balance directly for display (bypassing Ledger): never (the Ledger is the authoritative source; bypassing it is what the reconciliation job watches for).
- Caching strategy beyond 30s: V2 — could go to push-based via SSE if scale demands.
- USD prices in non-USD currencies: V2.

---

## Dependencies

- **Code dependencies:** `phase2-ledger-001` (`GetAccountBalance` query), `phase2-pricing-001` (`GetQuotesUseCase`), `phase2-wallet-001` (`ListUserWallets`), `phase2-chains-001` (Address VO).
- **Data dependencies:** Ledger schema applied; wallets provisioned for the test user (or graceful empty-portfolio handling).
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Application tests:** `tests/balances/application/test_get_portfolio.py` — empty wallets (`provisioning: true`), populated wallets with mixed balances, Pricing returning stale, Pricing failing entirely (degraded mode), Ledger 503 raises. Uses `FakeLedgerQuery`, `FakePriceProvider`, `FakeWalletRepository`. Covers AC-01 through AC-08.
- [ ] **Application tests:** `tests/balances/application/test_on_posting_committed.py` — fires the subscriber with a `PostingCommitted` event, asserts the cache key for the affected user is DELeted. Covers AC-05.
- [ ] **Adapter tests:** `tests/balances/infra/test_redis_balance_projection_cache.py` — uses Redis testcontainer; SET → GET round-trip with TTL=30, DEL invalidation, GET on missing key returns None.
- [ ] **Contract tests:** `tests/api/test_portfolio_endpoint.py` — TestClient hits `GET /api/v1/portfolio`, asserts response shape per AC-07, asserts Cache-Control header, asserts rate-limit header. Uses fixtures to seed a user with wallets and ledger postings. Covers AC-01, AC-02, AC-03, AC-09.
- [ ] **E2E:** none yet.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (balances/application 90%, balances/infra 80%).
- [ ] OpenAPI schema diff: 1 new endpoint documented; `docs/api-contract.yaml` committed.
- [ ] No new domain events; subscribes to `ledger.PostingCommitted`.
- [ ] No new ports — uses existing ones.
- [ ] Single PR. Conventional commit: `feat(balances): GET /portfolio with USD aggregation [phase2-balances-001]`.

---

## Implementation Notes

- The "amount as string" rule (AC-07) is non-negotiable for crypto. JavaScript's `Number` can't represent wei values losslessly; using strings everywhere on the wire is the canonical pattern. Frontend uses `bigint` or formatted strings; never raw `Number`.
- The cache invalidation pattern is naïve: on any posting touching a user, blow the cache. For Phase 2 scale this is correct. Phase 4 may revisit if the dashboard polls heavily; even then, "compute on miss" is cheap (one Ledger SELECT + one Pricing call per asset).
- USD computation: `usd_value = (amount * price) / (10 ** decimals)` with all arithmetic in `Decimal`, not float. Round to 2 decimal places at serialization boundary only.
- Total computation: `total_usd_all_chains = sum(wallet.total_usd for wallet in wallets)`. Stable; no special edge cases.
- For the `provisioning: true` flag, just check if `wallets == []`. The frontend treats both flags (this one + the wallet endpoint's) consistently.

---

## Risk / Friction

- The "Pricing failure → degraded UX" path (AC-06) is the kind of detail reviewers respect. Without it, a CoinGecko outage would 503 the dashboard. With it, the user still sees "0.05 ETH (price unavailable)". Worth the extra branch.
- 30s cache TTL × 60 req/min rate limit interaction: a determined client can theoretically hit the cache 60 times in 30s and only force ~2 actual computes. That's the expected behavior. If a load test reveals abuse, lower the rate limit before lowering the cache TTL.
- Decimal arithmetic in Python is slow vs float. For Phase 2 scale (≤3 wallets per user, ≤2 assets per wallet) this is invisible. If profiling later shows it as hot, switch the inner USD math to `Decimal` only for serialization, keep amounts as `int` everywhere else.
- The "Ledger is authoritative" stance is a strong claim that depends on the deposit watcher (`phase2-deposit-watcher-001`) actually keeping Ledger in sync with chain. Until that brief lands, the dashboard shows zeros even after on-chain deposits. Document this clearly so reviewers don't think the dashboard is broken.
