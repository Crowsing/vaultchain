---
ac_count: 8
blocks:
- phase3-transactions-003
complexity: S
context: kyc
depends_on:
- phase3-kyc-001
- phase3-kyc-002
estimated_hours: 4
id: phase3-kyc-003
phase: 3
sdd_mode: strict
state: ready
title: KYC tier enforcement port (KycTierGateway consumed by Transactions)
touches_adrs:
- ADR-009
---

# Brief: phase3-kyc-003 — KYC tier enforcement port (KycTierGateway consumed by Transactions)


## Context

The Transactions context's `ChainAwareThresholdPolicy` (phase3-transactions-003) needs to read a user's KYC tier and the per-tier limits to make routing decisions. Two cross-context concerns:

1. **What's the user's current tier?** Owned by KYC; consumed by Transactions.
2. **What are the limits per tier?** Conceptually a policy/configuration question that could live in either context.

This brief delivers the cross-context boundary as a **port owned by the consumer** (Transactions): `KycTierGateway` is a Protocol declared in `transactions/domain/ports.py`. The implementation is an adapter in `kyc/infra/transactions_kyc_tier_gateway.py` that reads from `kyc.applicants` directly (Transactions-owned port, KYC-owned data — read-only access via the adapter is the pattern).

This pattern is per the architecture's anti-corruption-layer (Section 4.4): consumer owns the port; producer provides the adapter. The producer doesn't expose its domain types — only DTOs. The Transactions context never imports `kyc.domain.entities.applicant.Applicant`.

**Tier limits** are kept as **constants in code** (V1):

```python
# transactions/domain/value_objects/tier_limits.py
TIER_LIMITS: Mapping[KycTier, TierLimits] = {
    KycTier.TIER_0: TierLimits(per_tx_max_usd=Decimal("0"), daily_max_usd=Decimal("0")),
    KycTier.TIER_0_REJECTED: TierLimits(per_tx_max_usd=Decimal("0"), daily_max_usd=Decimal("0")),
    KycTier.TIER_1: TierLimits(per_tx_max_usd=Decimal("5000"), daily_max_usd=Decimal("10000")),
    KycTier.TIER_2: TierLimits(per_tx_max_usd=Decimal("25000"), daily_max_usd=Decimal("50000")),
}
```

`TIER_0` and `TIER_0_REJECTED` have $0 limits — the policy treats this as "always route to admin" (per phase3-transactions-003 AC-01, the tier_0 check happens before limit evaluation, but $0 limits would also force routing for any non-zero amount; both paths converge correctly).

The decision to keep limits as **constants** rather than a config table:
- **Limits are policy decisions, not operational config.** Changing them requires legal/compliance review, not ops tweaking.
- **Code review is the change-control process.** A PR-bound change to limits is auditable.
- **No admin UI complexity.** No "I accidentally set the daily limit to $1,000,000" runtime risk.
- **Trade-off:** changing limits requires a deploy. Acceptable — this isn't a frequently-tweaked knob.

ADR-009 captures this decision so reviewers see it as deliberate.

The KycTierGateway has 2 methods:

```python
class KycTierGateway(Protocol):
    async def get_tier(self, user_id: UUID) -> KycTier: ...
    def get_tier_limits(self, tier: KycTier) -> TierLimits: ...
```

`get_tier` is async (DB lookup); `get_tier_limits` is sync (constant lookup). The split is honest — limits don't depend on per-user state.

The `get_tier` adapter caches with a 60s TTL keyed by `user_id` in Redis, invalidated on `kyc.TierChanged` event. The `KycTierChangeListener` (in transactions context) subscribes to `TierChanged` events and clears the user's cache. Stale cache for up to 60s is acceptable (a freshly-tier_1 user might see one more route_to_admin in the worst case; the dashboard polls `/kyc/status` with fresh data).

---

## Architecture pointers

- **Layer:** application (port + cache logic) + infra (adapter + cache invalidation listener).
- **Packages touched:**
  - `transactions/domain/ports.py` (extend with `KycTierGateway` Protocol)
  - `transactions/domain/value_objects/kyc_tier.py` (KycTier enum — duplicated from KYC's domain to maintain ACL)
  - `transactions/domain/value_objects/tier_limits.py` (TierLimits VO + constants)
  - `transactions/infra/cached_kyc_tier_gateway.py` (cache wrapper; delegates to underlying adapter)
  - `transactions/application/handlers/on_tier_changed.py` (cache invalidation handler)
  - `kyc/infra/transactions_kyc_tier_gateway_adapter.py` (the actual adapter implementing the Protocol; reads `kyc.applicants`)
  - `tests/_fakes/fake_kyc_tier_gateway.py` (shared test fake)
  - `docs/decisions/ADR-009-kyc-tier-enforcement-boundary.md` (drafted)
- **Reads:** `kyc.applicants` (via adapter); Redis cache.
- **Writes:** Redis cache (set/del).
- **Publishes events:** none. **Events consumed:** `kyc.TierChanged` (for cache invalidation).
- **Migrations:** none.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase3-kyc-003-01:** Given the `KycTierGateway` Protocol, when defined in `transactions/domain/ports.py`, then it has `async def get_tier(user_id: UUID) -> KycTier` and `def get_tier_limits(tier: KycTier) -> TierLimits`. The Protocol uses `transactions/`-owned `KycTier` enum (not imported from `kyc.domain`).

- **AC-phase3-kyc-003-02:** Given the `TierLimits` VO, when defined, then it's a frozen dataclass `TierLimits(per_tx_max_usd: Decimal, daily_max_usd: Decimal)`. `Decimal` for monetary precision (no float). Equality and hashable. The constants `TIER_LIMITS` map exhaustively covers all `KycTier` enum values (mypy `assert_never`-style exhaustiveness).

- **AC-phase3-kyc-003-03:** Given the adapter `TransactionsKycTierGatewayAdapter.get_tier(user_id)`, when called, then: (1) checks Redis cache `kyc_tier:<user_id>` (TTL 60s); (2) on miss, reads `kyc.applicants WHERE user_id = ?`; (3) maps `current_tier` text to `KycTier` enum; (4) if no row, returns `KycTier.TIER_0` (default — user hasn't started KYC); (5) writes cache; (6) returns. The cache hit path is sub-millisecond.

- **AC-phase3-kyc-003-04:** Given the `get_tier_limits(tier)` (sync), when called, then it returns `TIER_LIMITS[tier]`. For unknown tier (shouldn't happen with enum), `KeyError`. mypy enforces exhaustiveness — adding a new enum value without updating `TIER_LIMITS` is a compile-time error.

- **AC-phase3-kyc-003-05:** Given a `kyc.TierChanged{user_id, ...}` event, when the `OnTierChangedHandler` (in transactions context) subscribes, then it deletes Redis key `kyc_tier:<user_id>`. The next `get_tier(user_id)` call hits the DB and refreshes cache. Idempotent — re-delivery of the event is a no-op.

- **AC-phase3-kyc-003-06:** Given the `import-linter` contracts, when run, then: (1) `transactions.domain` may not import `kyc.*`; (2) `transactions.application` may not import `kyc.*`; (3) `transactions.infra` MAY import `kyc.infra` (the adapter is in `kyc.infra` per the producer-side adapter pattern — the adapter is wired in composition root, which crosses contexts intentionally). The adapter is the SINGLE allowed crossing. Documented in import-linter config.

- **AC-phase3-kyc-003-07:** Given the producer-side adapter `kyc/infra/transactions_kyc_tier_gateway_adapter.py`, when defined, then it does NOT import from `transactions.application` or `transactions.domain` — except for the Protocol type which is owned by Transactions and explicitly re-exported. Pattern: the Protocol is structurally satisfied; the adapter doesn't need to import the Protocol class for runtime, only `mypy` validates structural compatibility via `# type: assignment` at composition wiring.

- **AC-phase3-kyc-003-08:** Given the FakeKycTierGateway, when used in tests, then it allows configuring per-user-id tier and tier limits inline (`fake.set_tier(user_id, KycTier.TIER_1)`). Used across `phase3-transactions-003`'s tests. Reused by future briefs needing tier-aware testing.

- **AC-phase3-kyc-003-09:** Given the property test on tier limits exhaustiveness, when run, then for every `KycTier` enum value, `get_tier_limits(t)` returns a non-None `TierLimits`. Adding a new tier without updating constants fails this test (and mypy).

- **AC-phase3-kyc-003-10:** Given ADR-009, when committed, then `docs/decisions/ADR-009-kyc-tier-enforcement-boundary.md` exists with: Context (cross-context tier enforcement is a common DDD ACL example), Decision (consumer-owned port, producer-side adapter, tier limits as constants in consumer's domain), Consequences (acceptable: limits as code is the right change-control discipline; concerning: synchronous read on every withdrawal — mitigated by cache; trade-off: one redis-trip overhead, ~0.5ms cached, a few ms cold). The ADR explicitly addresses: "why not let KYC own the limits?" → answer: "limits are policy decisions about what Transactions does with information from KYC; KYC's job is to know the tier. Owning limits in Transactions keeps domain responsibilities aligned."

---

## Out of Scope

- Per-user limit overrides (allowlist a specific high-net-worth user with custom limits): V2.
- Time-window limit reset other than UTC midnight: V2.
- Async tier_2 enrollment automation: V2 (constants accommodate tier_2 already).
- Limit observability dashboards (which users hit limits, how often): V2 admin polish.

---

## Dependencies

- **Code dependencies:** `phase3-kyc-001` (kyc.applicants schema), `phase3-kyc-002` (TierChanged event).
- **Data dependencies:** `kyc.applicants` populated.
- **External dependencies:** none.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/transactions/domain/test_tier_limits.py` — TierLimits VO equality, frozen, exhaustive constants. Covers AC-02, AC-04.
- [ ] **Property tests:** `tests/transactions/domain/test_tier_limits_properties.py` — every KycTier enum value has limits defined. Covers AC-09.
- [ ] **Adapter tests:** `tests/kyc/infra/test_kyc_tier_gateway_adapter.py` — testcontainer Postgres, asserts: tier returned for existing applicant, tier_0 default for missing applicant, mapping from text to enum. Covers AC-03.
- [ ] **Adapter tests:** `tests/transactions/infra/test_cached_kyc_tier_gateway.py` — Redis testcontainer; cache hit/miss/refresh cycle. Covers AC-03.
- [ ] **Application tests:** `tests/transactions/application/test_on_tier_changed_handler.py` — event triggers cache invalidation; idempotent. Covers AC-05.
- [ ] **Architectural tests:** `tests/architecture/test_import_linter_kyc_boundary.py` — import-linter config exercises run cleanly; the only allowed crossing is the producer-side adapter. Covers AC-06, AC-07.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] `import-linter` contracts updated to capture the boundary; CI enforces.
- [ ] `mypy --strict` passes; tier exhaustiveness checked.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] No new domain events.
- [ ] One new port (`KycTierGateway`) declared; adapter implemented; fake provided.
- [ ] **ADR-009 drafted and committed.**
- [ ] Single PR. Conventional commit: `feat(transactions, kyc): kyc tier enforcement port + ADR-009 [phase3-kyc-003]`.

---

## Implementation Notes

- The `KycTier` enum lives in BOTH `kyc/domain/value_objects/kyc_tier.py` AND `transactions/domain/value_objects/kyc_tier.py` — same enum, two definitions. **This is the anti-corruption layer in action**: the Transactions-owned enum could diverge from KYC's (different naming, different states) without breaking. The mapping happens in the producer-side adapter. For Phase 3, the two enums are identical — call this out in code comments.
- The adapter file lives in `kyc/infra/` because it depends on `kyc.applicants` table access. The `transactions/` package never imports it; composition root wires it. mypy's structural typing makes the Protocol satisfaction implicit.
- The cache invalidation handler `OnTierChangedHandler` subscribes via the project's existing event bus (Phase 2's outbox + processor pattern). Subscription registered in composition root.
- The 60s cache TTL is the cold-path freshness guarantee; the event-driven invalidation is the warm-path freshness. Both together mean: at-most 60s stale on missed event delivery (rare); near-zero stale on delivered events.
- Decimal precision: `Decimal("5000")` vs `Decimal(5000)` — string preferred for clarity. Same for all `TIER_LIMITS` entries.

---

## Risk / Friction

- The "two KycTier enums" concept might confuse reviewers seeing duplication. ADR-009 explains; an inline comment in both files cross-references.
- A subtle issue: the adapter returns `KycTier.TIER_0` for missing applicants. If a user has an applicant in `tier_1` but the row is mid-transaction (write in flight), a concurrent read could miss. Acceptable: writes are within UoW transactions; reads are after commit; the visibility model (READ COMMITTED on Postgres default) is correct. Document.
- The cache key format `kyc_tier:<user_id>` is shared — naming collision with another context using the same pattern is a risk. Convention: prefix all transactions-owned cache keys with `txn:` (e.g., `txn:kyc_tier:<user_id>`). Apply this in implementation. Document the convention.
- A user transitioning tier_0 → tier_1 mid-flight (during a withdrawal use case) is an edge case: the policy may evaluate at tier_0 (route to admin), then the user gets tier_1, but the tx still goes through admin queue. Admin approves. Behavior is correct (the routing decision was made and is honored). The user might be confused why their first post-KYC withdrawal still went to admin. Document in user-facing FAQ as a known minor delay.
- ADR-009 is small and conceptual; some reviewers might consider it overkill. Defense: the architectural pattern (consumer-owned port, producer-side adapter) is non-obvious DDD craft; the ADR documents that the team thought about it deliberately. This is the kind of detail that signals maturity.
