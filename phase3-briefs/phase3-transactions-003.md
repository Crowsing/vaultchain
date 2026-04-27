---
ac_count: 9
blocks:
- phase3-admin-004
- phase3-ledger-003
complexity: M
context: transactions
depends_on:
- phase2-transactions-002
- phase3-kyc-003
- phase2-pricing-001
- phase3-chains-004
- phase3-chains-006
estimated_hours: 4
id: phase3-transactions-003
phase: 3
sdd_mode: strict
state: ready
title: ChainAwareThresholdPolicy (real threshold + KYC tier integration)
touches_adrs: []
---

# Brief: phase3-transactions-003 — ChainAwareThresholdPolicy (real threshold + KYC tier integration)


## Context

Phase 2 shipped `AlwaysPassThresholdPolicy` — a stub that approved every withdrawal. The architecture document (Section 2 line 168, Section 6.5) requires a real `ChainAwareThresholdPolicy` that combines:

1. **Per-chain, per-asset USD-equivalent threshold** (e.g., `>$1000 USD value on any chain → admin approval`).
2. **KYC tier gating** (Tier 0 = unverified: ALL withdrawals route to admin regardless of amount; Tier 1 = basic KYC: standard threshold applies; Tier 2 = enhanced KYC: higher thresholds).
3. **Daily and per-tx caps** (per tier).

The output is binary: `pass` (transaction proceeds via hot signing) OR `route_to_admin` (transaction enters admin queue, awaits cold signing). The decision is logged for audit (every routing decision creates an audit row recording the inputs that produced it — reproducibility for compliance review).

The policy is consumed by the `PrepareSendTransaction` use case (created in `phase2-transactions-001`). The injection point is via the `ThresholdPolicy` Protocol — same shape as Phase 2's stub, just a real implementation. **No use case code changes** — the policy is wired in composition root.

The KYC tier and tier-limits come from `KycTierGateway` (a port owned by Transactions, implemented as adapter in KYC context — defined in `phase3-kyc-003`). USD-equivalent comes from `PricingPort` (already from Phase 2). Threshold config (per chain, per asset) comes from a new repo `custody.threshold_config` table — separate from `custody.rebalance_config` to keep policy concerns clean. (Alternative: same table with a `policy_type` column. Rejected — separate tables read clearer in SQL.)

The threshold defaults (env-overridable):

| chain | asset | threshold_usd |
|---|---|---|
| ethereum | ETH | 100 |
| ethereum | USDC | 100 |
| tron | TRX | 100 |
| tron | USDT | 100 |
| solana | SOL | 100 |
| solana | USDC | 100 |

`$100` is the testnet-portfolio sweet spot: small enough that demo withdrawals (e.g., 0.05 ETH ≈ $150 at typical price) DO trigger admin approval and showcase the flow; large enough that micro-transactions don't pile up the queue. Mainnet would have higher thresholds + tiered behavior. Documented in seed comments.

KYC tier limits (defined in `phase3-kyc-003`, restated here for context):

| tier | per_tx_max_usd | daily_max_usd |
|---|---|---|
| 0 (unverified) | always-admin | always-admin |
| 1 (basic KYC) | $5,000 | $10,000 |
| 2 (enhanced) | $25,000 | $50,000 |

The `ChainAwareThresholdPolicy.evaluate(user_id, unsigned_tx, value_usd)` returns `Decision.PASS | Decision.ROUTE_TO_ADMIN`. The decision logic:

```
tier = KycTierGateway.get_tier(user_id)
if tier == TIER_0:
    return ROUTE_TO_ADMIN  # always
threshold_usd = ThresholdConfigRepo.get(chain, asset).threshold_usd
if value_usd > threshold_usd:
    return ROUTE_TO_ADMIN
limits = KycTierGateway.get_tier_limits(tier)
if value_usd > limits.per_tx_max_usd:
    return ROUTE_TO_ADMIN  # exceeds tier per-tx cap
daily_so_far = TransactionRepo.sum_user_daily_outgoing_usd(user_id, today)
if daily_so_far + value_usd > limits.daily_max_usd:
    return ROUTE_TO_ADMIN  # would exceed tier daily cap
return PASS
```

---

## Architecture pointers

- **Layer:** application + infra. Domain has no changes.
- **Packages touched:**
  - `transactions/application/policies/chain_aware_threshold_policy.py` (new — implements `ThresholdPolicy` Protocol from `phase2-transactions-001`)
  - `transactions/domain/ports.py` (no change — KycTierGateway and PricingPort already declared)
  - `custody/domain/entities/threshold_config.py` (new VO)
  - `custody/domain/ports.py` (extend with `ThresholdConfigRepository`)
  - `custody/infra/sqlalchemy_threshold_config_repo.py`
  - `custody/infra/migrations/<ts>_threshold_config.py` (creates table + seeds 6 rows)
  - **Threshold config lives in Custody** (administered by ops via admin endpoints) — Transactions reads it through a port. (Alternative: own it in Transactions. Rejected — Custody already owns operational config like rebalance, threshold is the same flavor.)
  - Composition root rewires `ThresholdPolicy` from `AlwaysPassThresholdPolicy` to `ChainAwareThresholdPolicy`.
- **Reads:** `custody.threshold_config`, `transactions.transactions` (for daily-sum), `kyc.applicants` (via gateway).
- **Writes:** `transactions.routing_decisions` audit rows (NEW small table — captures every routing decision with inputs).
- **Events:** the existing `transactions.RoutedToAdmin` (from phase2-transactions-002) is now actually fired with real data.
- **Migrations:** `custody.threshold_config` table (+ seeds) + `transactions.routing_decisions` table + `transactions.transactions.value_usd_at_creation NUMERIC(78,8)` column (NULL for Phase 2 rows; backfill from PricingPort + chain-native amount is **out of scope**, NULL is acceptable).
- **OpenAPI:** none new for users.

---

## Acceptance Criteria

- **AC-phase3-transactions-003-01:** Given the `ChainAwareThresholdPolicy.evaluate(user_id, unsigned_tx, value_usd)`, when the user's KYC tier is `tier_0` (unverified), then the result is `Decision.ROUTE_TO_ADMIN` regardless of amount, with `decision_reason='kyc_tier_0_always_admin'`.

- **AC-phase3-transactions-003-02:** Given a `tier_1` user with a `value_usd` of $50, when the threshold is $100, when `evaluate` is called, then result is `Decision.PASS` with `decision_reason='under_threshold'`.

- **AC-phase3-transactions-003-03:** Given a `tier_1` user with `value_usd` of $200, when the threshold is $100, when `evaluate` is called, then result is `Decision.ROUTE_TO_ADMIN` with `decision_reason='over_threshold_amount'`.

- **AC-phase3-transactions-003-04:** Given a `tier_1` user attempting `value_usd=$6,000`, when tier_1 per-tx cap is $5,000, when evaluated, then result is `ROUTE_TO_ADMIN` with `decision_reason='exceeds_tier_per_tx_cap'`.

- **AC-phase3-transactions-003-05:** Given a `tier_1` user who has already withdrawn $9,500 today (daily cap $10,000) and is attempting another $1,000, when evaluated, then result is `ROUTE_TO_ADMIN` with `decision_reason='exceeds_tier_daily_cap'`. The daily-sum query selects from `transactions.transactions` where `(user_id, status IN ['confirmed', 'broadcasting'], created_at >= today_start_user_tz)`. Pending and failed don't count.

- **AC-phase3-transactions-003-06:** Given the `ThresholdConfigRepository.get(chain, asset)`, when called for a configured pair, then it returns `ThresholdConfig(chain, asset, threshold_usd, enabled)`. For unknown pair, returns a deterministic default `ThresholdConfig(threshold_usd=Decimal('100'), enabled=True)` with `is_default=True` flag — assets we haven't explicitly configured aren't a security hole, they default to admin-required for high amounts.

- **AC-phase3-transactions-003-07:** Given the `transactions.routing_decisions` audit, when a routing decision is made, then a row is inserted with `(decision_id UUID, user_id, transaction_id (nullable until tx is created), chain, asset, value_chain_units, value_usd_at_decision, decision (PASS/ROUTE_TO_ADMIN), decision_reason, kyc_tier_at_decision, threshold_usd_at_decision, daily_so_far_usd, created_at)`. **Reproducibility:** given the row, an auditor can replay the decision logic and verify the same output. The `value_usd_at_decision` is captured for historical accuracy (USD prices change).

- **AC-phase3-transactions-003-08:** Given the policy is composed in production, when wired in composition root, then `transactions.application.dependency_container.threshold_policy` resolves to `ChainAwareThresholdPolicy` (replaces `AlwaysPassThresholdPolicy` from Phase 2). **No `PrepareSendTransaction` use case changes** — the policy injection point is unchanged.

- **AC-phase3-transactions-003-09:** Given the test suite, when running, then there's a fake `FakeKycTierGateway` returning configurable tier + limits, and a fake `FakePricingPort` returning configurable USD conversion. Both are reused across many transactions tests. Property tests validate the decision logic monotonically: increasing `value_usd` must transition `PASS → ROUTE_TO_ADMIN` exactly once (no oscillation); the same is true for `daily_so_far`.

- **AC-phase3-transactions-003-10:** Given the policy is exercised end-to-end via `PrepareSendTransaction`, when a tier_0 user attempts a $5 send, when the use case runs, then: (1) the policy returns `ROUTE_TO_ADMIN`; (2) the use case publishes `transactions.RoutedToAdmin{transaction_id, kyc_tier='tier_0', decision_reason='kyc_tier_0_always_admin'}`; (3) the transaction's status is set to `awaiting_admin` (per the state machine from `phase2-transactions-002`). The Ledger context (in `phase3-ledger-003`) subscribes and posts the `withdrawal_reserved`.

- **AC-phase3-transactions-003-11:** Given the threshold_config seed data, when the migration runs, then 6 rows seed (chain × asset × threshold_usd) per the table in Context. Migration is idempotent (re-running doesn't duplicate). Operator can update via `UPDATE custody.threshold_config SET threshold_usd = ... WHERE chain=... AND asset=...` — no admin UI needed in V1 (V2 polish).

- **AC-phase3-transactions-003-12:** Given the property test on **tier monotonicity**, when fuzzed via `tests/transactions/application/test_threshold_policy_properties.py::test_tier_monotonicity`, then for any fixed (`value_usd`, `daily_so_far_usd`, chain, asset) inputs, evaluating the policy across `tier_0 → tier_1 → tier_2` must NEVER transition `PASS → ROUTE_TO_ADMIN` as the tier increases. Equivalently: a higher tier may only relax routing, never tighten it. **Architecture-mandated property test (PHASE3-SUMMARY property #5).**

- **AC-phase3-transactions-003-13:** Given the property test on **policy idempotency under same clock**, when fuzzed via `tests/transactions/application/test_threshold_policy_properties.py::test_idempotency_same_clock`, then for any input tuple `(user_id, unsigned_tx, value_usd, frozen_clock_ts)`, calling `evaluate(...)` twice in succession (with the same frozen clock and unchanged DB state) returns byte-equal `Decision`, `decision_reason`, `kyc_tier_at_decision`, `daily_so_far_usd`. Decisions are pure functions of (inputs + observable state at the frozen clock); no internal RNG, no time-based drift. **Architecture-mandated property test (PHASE3-SUMMARY property #7).**

- **AC-phase3-transactions-003-14:** Given the migration adding `transactions.transactions.value_usd_at_creation NUMERIC(78,8) NULL`, when applied, then: (1) the column is nullable; (2) existing Phase 2 rows are NOT backfilled (left NULL); (3) `PrepareSendTransaction` sets the value at write time as `PricingPort.to_usd(unsigned_tx.value)` quantized to 8 decimal places (sufficient precision for USD); (4) the daily-sum query (`SELECT SUM(value_usd_at_creation) ...` per AC-05) treats NULL as 0 via `COALESCE`. Migration is idempotent (`IF NOT EXISTS`-style guards).

---

## Out of Scope

- Velocity rules (tx/hour, suspicious patterns): V2.
- Per-user threshold overrides (allowlist for specific high-value users): V2.
- Whitelisted destination addresses (skip admin if recipient is pre-approved): V2.
- Geofencing / IP-based limits: V2.
- ML-based fraud scoring: never (out of scope for portfolio).

---

## Dependencies

- **Code dependencies:** `phase2-transactions-001` and `phase2-transactions-002`, `phase2-pricing-001` (PricingPort with `to_usd(money)`), `phase3-kyc-003` (KycTierGateway port).
- **Data dependencies:** `transactions.transactions` schema (Phase 2). `kyc.applicants` populated for any user beyond tier_0 (gateway returns tier_0 if no applicant row).
- **External dependencies:** none.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/transactions/domain/test_routing_decision.py` — VO equality, reason enum exhaustiveness.
- [ ] **Application tests:** `tests/transactions/application/test_chain_aware_threshold_policy.py` — exhaustive table-driven test of all decision paths: tier_0 always admin, tier_1 under threshold, tier_1 over threshold, tier_1 over per-tx cap, tier_1 over daily cap, tier_2 with higher caps, default-config fallback. Covers AC-01 through AC-06.
- [ ] **Property tests:** `tests/transactions/application/test_threshold_policy_properties.py` — three Hypothesis-driven properties: (a) **amount monotonicity** — increasing `value_usd` transitions `PASS→ROUTE_TO_ADMIN` exactly once with no oscillation (PHASE3-SUMMARY property #6, covers AC-09); (b) **tier monotonicity** — increasing tier never tightens routing (covers AC-12); (c) **idempotency under same clock** — repeated `evaluate(...)` with frozen clock returns byte-equal decision (covers AC-13).
- [ ] **Adapter tests:** `tests/custody/infra/test_sqlalchemy_threshold_config_repo.py` — testcontainer Postgres, asserts seed rows, default fallback for unknown.
- [ ] **Application tests:** `tests/transactions/application/test_routing_decision_audit.py` — every decision creates a `routing_decisions` row with all fields populated. Covers AC-07.
- [ ] **Application tests:** `tests/transactions/application/test_prepare_send_with_real_policy.py` — tier_0 user attempting send → `RoutedToAdmin` event, transaction status `awaiting_admin`. Covers AC-10.
- [ ] **Contract tests:** none.
- [ ] **E2E:** the broader admin approval flow E2E lives in `phase3-admin-006`.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] `import-linter` contracts pass — Transactions doesn't import from KYC directly, only via port.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] No new domain events.
- [ ] One new port (`ThresholdConfigRepository`) declared with fake.
- [ ] Composition root rewired (single line replacing `AlwaysPassThresholdPolicy` with `ChainAwareThresholdPolicy`).
- [ ] `docs/runbook.md` updated: how to update threshold_config (SQL or future admin UI), how to inspect routing_decisions audit (`SELECT * FROM transactions.routing_decisions WHERE user_id = ? ORDER BY created_at DESC`).
- [ ] Single PR. Conventional commit: `feat(transactions): chain-aware threshold policy with KYC tier integration [phase3-transactions-003]`.

---

## Implementation Notes

- The decision-reason enum should be exhaustive in the type system: `PassReason = Literal['under_threshold']`, `RouteReason = Literal['kyc_tier_0_always_admin', 'over_threshold_amount', 'exceeds_tier_per_tx_cap', 'exceeds_tier_daily_cap', 'kyc_tier_unknown']`. Mypy's exhaustiveness checking on the Decision union ensures we don't add new reasons without also handling them everywhere.
- `value_usd_at_decision` captures the USD-equivalent at decision time. If price moves between PrepareSend and broadcast, the decision is still based on the moment-of-decision price. This is the auditable approach (vs re-evaluating throughout). Document.
- The daily-sum query: `SELECT COALESCE(SUM(value_usd_at_creation), 0) FROM transactions.transactions WHERE user_id = ? AND status IN ('confirmed', 'broadcasting', 'awaiting_admin') AND created_at >= ? AND tx_type = 'withdrawal'`. The `awaiting_admin` is included — pending admin approval still counts toward daily cap (otherwise a user could spam admin queue with sub-threshold-but-cumulative txs). Document the semantic clearly. The `value_usd_at_creation` column is added by AC-14's migration; rows from before Phase 3 are NULL and `COALESCE` treats them as 0 (acceptable — the daily cap window is 24h, so legacy rows cannot affect a current decision).
- Time zones: use UTC for `today_start`. Don't try to do user-tz; tier limits are reset at UTC midnight. Phase 4 polish could expose this in user settings.
- The default fallback (AC-06) when an unknown asset hits: returns `threshold_usd=$100` and `is_default=True`. Log a warning whenever this triggers — surface unknown assets to ops attention.
- The `routing_decisions` table is append-only; no UPDATEs. Index on `(user_id, created_at DESC)` for the admin user-detail view.

---

## Risk / Friction

- The "tier_0 always admin" rule (AC-01) means new users see admin approval for any withdrawal until KYC completes. This is correct security but UX-painful: a user signs up, gets airdropped 0.1 ETH, tries to withdraw, sees "awaiting admin." Mitigations: (a) the dashboard's withdrawal flow surfaces a "Complete KYC to enable instant withdrawals" CTA when the user is tier_0; (b) the admin queue's same-day approval makes this acceptable for portfolio scope. Document in `phase2-web-006`'s success/failure card flows.
- The daily-cap calculation reads `transactions.transactions` filtered by status. If a transaction is mid-flight (`broadcasting` for several seconds), it counts. If it later fails (`failed`), the cap should "free up" for retry — but the policy reads at decision time, so naturally a re-try after failure sees a fresh daily window minus only confirmed/awaiting amounts. Document.
- USD-equivalent at decision time is fixed — but if a tier_1 user tries to withdraw $99 worth (under $100 threshold) and chain volatility moves the value above $100 by broadcast time, the policy still passes. This is correct: the decision was made; the in-flight is settled. **However, if the policy decides ROUTE_TO_ADMIN at $200 and admin approves at a moment when value is $190**, the admin approves the original tx (specific amount in chain-native units), so the cold-signed tx still pays out the original amount. USD pricing fluctuation is mostly irrelevant after decision; only the audit row preserves the at-decision USD for review. Document.
- A reviewer may ask: "what if a malicious user spams admin queue?" Answer: tier_1+ requires KYC, which is rate-limited at Sumsub. Tier_0 users CAN spam — but each spam transaction is created fresh, has a UUID, and the queue handles them (can be batch-rejected by admin). Documented as an accepted risk for portfolio testnet scope.
- The `kyc_tier_unknown` reason exists for resilience: if the KycTierGateway throws (KYC service unreachable), the policy treats it as tier_0 (route to admin) with this reason. Fail-safe-to-admin is the conservative default. Document.
