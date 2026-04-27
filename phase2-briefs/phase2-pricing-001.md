---
ac_count: 7
blocks:
- phase2-balances-001
- phase2-transactions-002
complexity: S
context: pricing
depends_on:
- phase1-shared-003
- phase1-shared-005
estimated_hours: 4
id: phase2-pricing-001
phase: 2
sdd_mode: strict
state: ready
title: Pricing context with CoinGecko adapter
touches_adrs: []
---

# Brief: phase2-pricing-001 — Pricing context with CoinGecko adapter


## Context

The Pricing context owns one job: convert chain-native amounts (wei, sun, lamports, plus stable tokens at unit price) into USD for display purposes. It is deliberately small — its single port `PriceProvider` returns `Decimal` USD-per-unit for an asset symbol, with a 60-second cache and a fallback to last-known-price on API failure. Per architecture Section 4, the V1 adapter is `CoinGeckoPriceAdapter`, with a `StaticPriceAdapter` retained for tests where reproducibility matters.

Pricing data is **never** persisted as money. Per architecture Section 3, Money lives in chain-native units (`NUMERIC(78,0)`, no float). USD is a read-time derived value. The Balances context (next brief) is the only place that calls Pricing in production code paths; the AI assistant context calls Pricing in Phase 4 for embedding metadata. This brief delivers the port + adapter + cache + fallback wiring, plus a `GET /api/v1/pricing/quote?symbols=ETH,USDC` endpoint used by both the user SPA (header total animation) and Balances internally.

The fallback strategy is layered: (1) Redis cache hit → return immediately; (2) CoinGecko API call → cache 60s, persist last-known with 24h TTL; (3) API failure → return last-known with a `stale: true` flag; (4) no last-known either → raise `PricingUnavailable` domain error mapped to HTTP 503. Reviewers spot the production-discipline of the layering — it's a small context with grown-up engineering inside.

---

## Architecture pointers

- **Layer:** delivery + application + domain + infra. Bounded context `pricing/`.
- **Packages touched:** `pricing/domain/` (`PriceQuote` VO, `PricingUnavailable` error, `PriceProvider` Protocol), `pricing/application/` (`GetQuotesUseCase`), `pricing/infra/` (`coingecko_adapter.py`, `redis_cache.py`, `static_adapter.py`), `pricing/delivery/` (`router.py`).
- **Reads:** Redis `pricing:quote:<symbol>` (60s TTL), `pricing:last_known:<symbol>` (24h TTL).
- **Writes:** Same keys (write-through cache).
- **Events:** none.
- **Ports / adapters:** new `PriceProvider` port. Adapters: `CoinGeckoPriceAdapter`, `StaticPriceAdapter` (test).
- **Migrations:** none.
- **OpenAPI:** new `GET /api/v1/pricing/quote?symbols=...` endpoint.

---

## Acceptance Criteria

- **AC-phase2-pricing-001-01:** Given the `GetQuotesUseCase` is invoked with a list of symbols (`["ETH", "USDC", "TRX", "SOL", "USDT"]`), when the cache is warm, then it returns `dict[symbol → PriceQuote]` immediately from Redis without hitting CoinGecko. `PriceQuote` is `{symbol: str, usd: Decimal, fetched_at: datetime, stale: bool}`.

- **AC-phase2-pricing-001-02:** Given the cache is cold, when `GetQuotesUseCase` is invoked, then `CoinGeckoPriceAdapter.fetch_prices(symbols)` is called. On 200, the adapter parses the CoinGecko `/simple/price?ids=ethereum,usd-coin,...&vs_currencies=usd` response into `Decimal` USD values, writes both the 60s cache and the 24h last-known cache, and returns the quotes. The adapter maps internal symbols (`ETH`) to CoinGecko ids (`ethereum`) via a single static `SYMBOL_TO_COINGECKO_ID` dict.

- **AC-phase2-pricing-001-03:** Given CoinGecko returns a 5xx or times out (5s timeout per request), when `CoinGeckoPriceAdapter.fetch_prices` is called, then it falls back to the 24h last-known cache, returns those values with `stale=true`, and emits a structlog warning `pricing.fallback.last_known`. No exception is raised in this path. CoinGecko's `429 Too Many Requests` is treated identically (free-tier rate limits).

- **AC-phase2-pricing-001-04:** Given both the live API fails AND the last-known cache is empty (cold start, no historical data), when called, then `PricingUnavailable` is raised, mapped to HTTP 503 with `code: pricing.unavailable` per `phase1-shared-005`'s error envelope. The response includes `Retry-After: 60` header.

- **AC-phase2-pricing-001-05:** Given a stablecoin (USDC, USDT) is requested, when the adapter resolves it, then it returns exactly `1.0` USD without hitting CoinGecko (a `STABLECOINS = {"USDC", "USDT"}` constant short-circuits). This is technically unfaithful to mainnet (USDC has depegged in the past) but acceptable for testnet portfolio scope; document the simplification in code comment.

- **AC-phase2-pricing-001-06:** Given `GET /api/v1/pricing/quote?symbols=ETH,USDC` is called by an authenticated user, when the response returns, then it is `{quotes: {ETH: {usd: "2840.50", fetched_at: "...", stale: false}, USDC: {usd: "1.00", ...}}}`. Cache headers: `Cache-Control: max-age=60, public`. The endpoint is rate-limited to 60 req/min/user (per architecture Section 4).

- **AC-phase2-pricing-001-07:** Given the `StaticPriceAdapter` is configured (in test composition root), when used, then it returns deterministic prices from `tests/pricing/fixtures/static_prices.json` without any network. Used in all property/contract tests downstream (Balances, Transactions) so test runs are reproducible.

- **AC-phase2-pricing-001-08:** Given a request for an unknown symbol (e.g., `?symbols=DOGE`), when processed, then the response includes the known symbols and a `unknown: ["DOGE"]` field listing the unrecognized ones. No 4xx error — partial-data is acceptable here per the CoinGecko free-tier philosophy.

---

## Out of Scope

- Multi-currency support (EUR, GBP): V2.
- Per-user-preferred display currency: V2.
- Historical price queries (charts): V2 — Phase 4 may add a stub.
- WebSocket price streaming: never (over-engineered for the use case).
- Mainnet stablecoin depeg detection: out of testnet scope.

---

## Dependencies

- **Code dependencies:** `phase1-shared-003` (for any UoW orchestration; this brief is mostly stateless), `phase1-shared-005` (error envelope mapping for `PricingUnavailable`).
- **Data dependencies:** Redis available (already provisioned in deploy-001).
- **External dependencies:** `httpx` for async HTTP, CoinGecko free-tier API (no API key needed for `/simple/price`).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/pricing/domain/test_price_quote.py` — VO equality, Decimal precision, datetime serialization. Covers AC-01 (data shape).
- [ ] **Property tests:** `tests/pricing/domain/test_price_quote_properties.py` — `PriceQuote` round-trips through `to_dict()` / `from_dict()` for any random Decimal in [0.0001, 1_000_000].
- [ ] **Application tests:** `tests/pricing/application/test_get_quotes.py` — happy path (warm cache, cold cache hits API, cold cache fallback to last-known, complete failure raises `PricingUnavailable`). Uses `FakePriceProvider` and `FakeRedis`. Covers AC-01 through AC-04, AC-08.
- [ ] **Adapter tests:** `tests/pricing/infra/test_coingecko_adapter.py` — uses `respx` to mock httpx; asserts request URL shape, parses response, handles 5xx/429/timeout. Covers AC-02, AC-03. Uses real Redis via testcontainer for cache assertions.
- [ ] **Adapter tests:** `tests/pricing/infra/test_static_adapter.py` — loads fixture JSON, returns deterministic values. Covers AC-07.
- [ ] **Contract tests:** `tests/api/test_pricing_quote.py` — TestClient hits `GET /api/v1/pricing/quote?symbols=...`, asserts response shape, Cache-Control header, partial-data behavior with unknown symbol. Covers AC-06, AC-08.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass — Pricing has no inbound dependencies from Wallet/Custody/Chains; only Balances imports it.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gate passes (Pricing target: 90% — small context, easy to hit).
- [ ] OpenAPI schema diff: 1 new endpoint documented; `docs/api-contract.yaml` committed.
- [ ] No new domain events.
- [ ] New port `PriceProvider` declared in `pricing/domain/ports.py` with at least one fake in `tests/pricing/fakes/`.
- [ ] Single PR. Conventional commit: `feat(pricing): coingecko price adapter with cache + fallback [phase2-pricing-001]`.

---

## Implementation Notes

- The `PriceProvider` Protocol has one method: `async fetch_prices(symbols: list[str]) -> dict[str, PriceQuote]`. Stablecoin short-circuit happens INSIDE the adapter, not the use case — the use case is symbol-agnostic.
- CoinGecko free-tier rate limit is ~30 calls/min as of 2026. The 60s cache makes this trivially safe even with steady traffic.
- The fallback to last-known is critical: a CoinGecko outage should NOT take down the dashboard. The `stale: true` flag lets the frontend show a tiny "prices may be outdated" tooltip without breaking the layout.
- For tests, use `pyproject.toml`'s test composition root to wire `StaticPriceAdapter` automatically when `PYTEST_CURRENT_TEST` is set. Avoids per-test boilerplate.
- The 5s timeout per request is per-call; the use case fetches all symbols in one CoinGecko call (their API supports comma-separated ids), so the total wall time for a cold-cache miss is ≤5s.

---

## Risk / Friction

- CoinGecko free-tier API stability is not contractual. The 24h last-known fallback is the safety net. If the fallback gets stale beyond 24h, the user sees `stale: true` indefinitely until either the API recovers or the last-known TTL expires (then service returns 503). This is acceptable — better stale than wrong.
- The CoinGecko symbol mapping (`ETH → ethereum`, `USDC → usd-coin`) is the most error-prone part. Add a CI check that round-trips every symbol through the adapter once at build time, surfaces mismatches early.
- The stablecoin short-circuit is not strictly correct (USDC depegged to $0.87 in March 2023). For a testnet portfolio it's fine; if a reviewer questions it, the answer is "deliberate testnet simplification, mainnet would use the live oracle for stables too." Document inline.
