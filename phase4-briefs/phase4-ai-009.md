---
ac_count: 12
blocks:
- phase4-evals-001
- phase4-web-008
complexity: M
context: ai
depends_on:
- phase4-ai-001
- phase1-shared-003
- phase1-shared-004
- phase2-balances-001
- phase2-pricing-001
- phase3-kyc-001
- phase1-identity-004
estimated_hours: 4
id: phase4-ai-009
phase: 4
sdd_mode: strict
state: ready
title: Suggestions sub-domain (proactive banners on dashboard)
touches_adrs: []
---

# Brief: phase4-ai-009 — Suggestions sub-domain (proactive banners on dashboard)


## Context

This brief realises the **suggestions** sub-domain — the simplest of the four AI sub-domains. The product story: a small banner appears on the user's dashboard saying things like "Your USDC balance is below 50 USD — top up?" or "You haven't completed KYC verification yet — verify to unlock larger withdrawals." These are proactive nudges, not chat. The user can dismiss any banner; it disappears for that user (configurably for a window or permanently).

The architecture (Section 1) lists Suggestions as one of four AI sub-domains and §"API surface" line 428 names `/api/v1/ai/...` as covering "chat (SSE), tools, suggestions". That is the only architectural input — there's no ADR, no schema diagram, no event flow specified. This brief makes the design decisions inside-the-brief.

**Design choices:**

The "AI" framing in the sub-domain name might suggest LLM involvement. **It doesn't have to.** V1 suggestions are deterministic rule evaluation — a small set of conditions (low balance, incomplete KYC, large pending withdrawal, etc.) checked by a periodic worker. This is simpler, predictable, testable, and fast. The "AI" placement reflects the banner being part of the assistant-facing UX, not the backing implementation. Future V2 could add LLM-generated suggestions ("Based on your activity, you might want to enable X feature") — the rule registry pattern below accommodates this without restructuring.

**What ships in V1:**

1. The `ai.suggestions` table — stores active suggestions per user, with status `pending | dismissed | superseded | expired | actioned`.
2. The `Suggestion` aggregate with the state machine.
3. A `SuggestionRule` Protocol — pluggable, each rule decides "should this user get this suggestion right now?"
4. Three concrete rules for V1: `LowBalanceRule`, `KycIncompleteRule`, `LargePendingWithdrawalRule`.
5. A periodic worker `evaluate_suggestions` (every 5 minutes per user, but bounded — see AC-09) that evaluates rules against each active user and creates/supersedes/expires suggestions.
6. Two REST endpoints: `GET /api/v1/ai/suggestions` (list active for current user), `POST /api/v1/ai/suggestions/{id}/dismiss` (user dismisses).

**What does NOT ship:**

- LLM-generated suggestions (V2 — the rule registry pattern is the seam).
- Personalized suggestions based on transaction history (V2 — would consume `phase4-ai-007`'s tx memory; deferred because V1 lacks a chat surface that wants this).
- Push notifications for suggestions (V2 — `phase2-notifications-001` could plug in).
- A/B testing of suggestion copy (V2 — V1 ships hardcoded English copy per rule).
- An admin UI to manage suggestions (V2 — admin can `psql` and `UPDATE` if needed in V1 emergencies).
- Multi-language suggestion text (V2 — V1 English only).

**State machine:**

- `pending` → `dismissed` (user pressed dismiss).
- `pending` → `superseded` (rule re-evaluation determined the suggestion's premise changed materially — e.g., user topped up, Low Balance no longer applies).
- `pending` → `expired` (suggestion has a soft TTL of 7 days; old un-dismissed suggestions get garbage-collected to avoid stale dashboard clutter).
- `pending` → `actioned` (user took the suggested action — e.g., started KYC after seeing the KycIncomplete banner; detected via subscriber).

All four are terminal sinks. Property test (AC-12) covers no-orphan-states + sink-finality.

**Idempotency / supersession:**

The worker re-evaluates every 5 minutes per user. It must NOT spam the user with duplicate banners. Discipline: each rule has a stable `kind` identifier (e.g., `low_balance:USDC:ethereum`); the worker queries `existing pending suggestion of this kind for this user` first. If exists and rule still says "show", do nothing (the existing banner stays). If exists and rule says "no longer applicable", supersede it (transition `pending` → `superseded`, no replacement). If doesn't exist and rule says "show", create new. Single UoW per (user, rule) evaluation.

---

## Architecture pointers

- `architecture-decisions.md` §"AI Assistant" sub-domain catalog (suggestions: "proactive banners on dashboard"), §"API surface" line 428 (the URL prefix `/api/v1/ai/...` covers suggestions endpoints).
- **Layer:** domain (aggregate, state, ports, rule Protocol) + application (worker + 3 concrete rules + REST handlers) + infra (repo + migration + cron registration).
- **Packages touched:**
  - `ai/suggestions/domain/suggestion.py` (aggregate)
  - `ai/suggestions/domain/value_objects/suggestion_status.py` (enum)
  - `ai/suggestions/domain/value_objects/suggestion_kind.py` (string-shaped: `low_balance:<asset>:<chain>`, `kyc_incomplete`, `large_pending_withdrawal`)
  - `ai/suggestions/domain/ports.py` (`SuggestionRepository`, `SuggestionRule` Protocol)
  - `ai/suggestions/domain/errors.py` (`SuggestionNotFound`, `SuggestionAlreadyDismissed`, `SuggestionAlreadyTerminal`)
  - `ai/suggestions/application/use_cases/dismiss_suggestion.py`
  - `ai/suggestions/application/use_cases/list_user_suggestions.py`
  - `ai/suggestions/application/use_cases/evaluate_suggestions_for_user.py` (the per-user evaluation orchestrator — invokes each registered rule, applies create/supersede/no-op logic)
  - `ai/suggestions/application/jobs/evaluate_suggestions_periodic.py` (arq scheduled job — selects active users in batches, calls per-user evaluation)
  - `ai/suggestions/application/rules/low_balance_rule.py`
  - `ai/suggestions/application/rules/kyc_incomplete_rule.py`
  - `ai/suggestions/application/rules/large_pending_withdrawal_rule.py`
  - `ai/suggestions/application/handlers/on_kyc_tier_changed.py` (subscribes to `kyc.TierChanged` to mark KycIncomplete suggestions `actioned`)
  - `ai/suggestions/application/handlers/on_transaction_confirmed.py` (subscribes to `transactions.Confirmed` to mark LargePendingWithdrawal `actioned`)
  - `ai/suggestions/delivery/router.py` (REST: `GET /api/v1/ai/suggestions`, `POST /api/v1/ai/suggestions/{id}/dismiss`)
  - `ai/suggestions/infra/sqlalchemy_suggestion_repo.py`
  - `ai/suggestions/infra/migrations/007_suggestions.py` (Alembic; revision after `006_kb_embeddings`)
  - `ai/suggestions/infra/composition.py`
- **Reads (cross-context):** `balances.application.use_cases.GetPortfolio` (LowBalance rule), `pricing.application.queries.GetQuotes` (USD valuation), `kyc.application.queries.get_kyc_status` (KycIncomplete rule), `transactions.application.queries.list_user_transactions` (LargePendingWithdrawal rule).
- **Writes:** `ai.suggestions`.
- **Publishes events:** `ai.SuggestionCreated{suggestion_id, user_id, kind}`, `ai.SuggestionDismissed{suggestion_id, user_id, kind}`, `ai.SuggestionActioned{suggestion_id, user_id, kind, by_event_kind}` — all three are informational; **no V1 subscriber** for any of them, registered for V2 (notifications context could subscribe to `SuggestionCreated` for push, and analytics could subscribe to all three).
- **Subscribes to events:** `kyc.TierChanged`, `transactions.Confirmed`.
- **New ports introduced:** `SuggestionRepository`, `SuggestionRule`.
- **New adapters introduced:** `SqlAlchemySuggestionRepository`. Three concrete rule classes implementing `SuggestionRule`. Plus `FakeSuggestionRepository`, `FakeSuggestionRule` in `tests/ai/fakes/`.
- **DB migrations required:** yes — `007_suggestions`.
- **OpenAPI surface change:** yes — two new endpoints under `/api/v1/ai/suggestions`.

---

## Acceptance Criteria

- **AC-phase4-ai-009-01:** Given migration `007_suggestions`, when applied, then table `ai.suggestions(id UUID PK, user_id UUID NOT NULL REFERENCES identity.users(id), kind TEXT NOT NULL, payload JSONB NOT NULL, status TEXT NOT NULL CHECK (status IN ('pending', 'dismissed', 'superseded', 'expired', 'actioned')) DEFAULT 'pending', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), expires_at TIMESTAMPTZ NOT NULL, terminal_reason TEXT NULL, INDEX idx_sugg_user_status ON (user_id, status, created_at DESC), INDEX idx_sugg_user_kind_pending ON (user_id, kind) WHERE status = 'pending', INDEX idx_sugg_pending_expiry ON (expires_at) WHERE status = 'pending')` exists. The partial indexes are: `(user_id, kind) WHERE status='pending'` for the supersession lookup ("does this user have a pending suggestion of this kind?"); `(expires_at) WHERE status='pending'` for the expiry sweeper. Migration is idempotent.

- **AC-phase4-ai-009-02:** Given the `Suggestion` aggregate in `ai/suggestions/domain/suggestion.py`, when constructed via `Suggestion.create(user_id, kind, payload, expires_at)`, then it returns a state-bearing dataclass with `id`, the constructor args, `status='pending'`, `terminal_reason=None`, `created_at`/`updated_at` set to now. A pending `ai.SuggestionCreated` event is collected. State transitions are domain methods with strict guards: `dismiss()` requires `status == 'pending'` else raises (`SuggestionAlreadyDismissed` if already dismissed, `SuggestionAlreadyTerminal` for other terminal states); `supersede(reason: str)` requires pending else raises; `expire()` requires pending else is silent no-op (sweeper safety); `mark_actioned(by_event_kind: str)` requires pending else raises. Each transition collects the corresponding event and updates `updated_at`. `terminal_reason` is set on supersede/expire/actioned.

- **AC-phase4-ai-009-03:** Given the `SuggestionRule` Protocol in `ai/suggestions/domain/ports.py`, when defined, then it declares: `kind_prefix: str` (e.g., `"low_balance"`), `async def kind_for(user_id: UUID) -> list[str]` (returns the list of concrete kinds this rule could produce for this user — e.g., `["low_balance:USDC:ethereum", "low_balance:USDC:solana"]` if the user has wallets on both chains; the rule worker calls this first to know what kinds to look up), `async def evaluate(user_id: UUID, kind: str) -> RuleDecision` where `RuleDecision = ShouldShow{payload, expires_at} | ShouldNotShow`. The Protocol is `runtime_checkable`. The split between `kind_for` and `evaluate` lets the worker do a batch SELECT for existing pending suggestions before per-rule evaluation, avoiding per-rule queries.

- **AC-phase4-ai-009-04:** Given the `LowBalanceRule` in `ai/suggestions/application/rules/low_balance_rule.py`, when constructed with `get_portfolio: GetPortfolio` and threshold config (`low_balance_usd_threshold: Decimal = 10`), then: (1) `kind_prefix = "low_balance"`; (2) `kind_for(user_id)` returns `[f"low_balance:{asset}:{chain}" for (chain, asset) in <user's wallet+asset pairs from portfolio>]`; (3) `evaluate(user_id, kind="low_balance:USDC:ethereum")` returns `ShouldShow(payload={asset: 'USDC', chain: 'ethereum', current_usd: '7.50', threshold_usd: '10.00', message: 'Your USDC balance on Ethereum is $7.50 — top up to use it for sends.'}, expires_at=now()+7days)` if the user's USDC@ethereum balance USD value is below threshold AND non-zero (zero-balance is a "you don't use this asset" signal, not "low"); returns `ShouldNotShow` otherwise. **Threshold is per-user, not per-asset** in V1 — keeping it simple. V2 could differentiate (low for stablecoins might be $10, low for ETH might be $50).

- **AC-phase4-ai-009-05:** Given the `KycIncompleteRule` in `ai/suggestions/application/rules/kyc_incomplete_rule.py`, when constructed with `get_kyc_status_query`, then: (1) `kind_prefix = "kyc_incomplete"`; (2) `kind_for(user_id)` returns `["kyc_incomplete"]` (single kind per user); (3) `evaluate(user_id, "kyc_incomplete")` returns `ShouldShow(payload={current_tier: 'tier_0', message: 'Verify your identity to unlock larger transaction limits.', cta_label: 'Verify now', cta_route: '/kyc/start'}, expires_at=now()+7days)` if `tier == 'tier_0'` AND `applicant_started == False`; returns `ShouldShow` with `message: 'Continue your verification — Sumsub needs your documents.'` if `applicant_started == True` and `tier == 'tier_0'` (in-progress case); returns `ShouldNotShow` if tier is `tier_1` or `tier_0_rejected` (the rejected case is handled by a different banner in `phase4-web-008`, not via this rule — that's a hard fail not a nudge).

- **AC-phase4-ai-009-06:** Given the `LargePendingWithdrawalRule` in `ai/suggestions/application/rules/large_pending_withdrawal_rule.py`, when constructed with `list_user_transactions: ListUserTransactions`, then: (1) `kind_prefix = "large_pending_withdrawal"`; (2) `kind_for(user_id)` returns either `[]` (no pending withdrawals) or `[f"large_pending_withdrawal:{tx_id}" for tx_id in <pending tx_ids>]`; (3) `evaluate(user_id, kind="large_pending_withdrawal:<tx_id>")` returns `ShouldShow(payload={tx_id, status: 'awaiting_admin', amount, asset, value_usd, message: 'Your $5,000 withdrawal is awaiting admin review. Typically processed within 1–2 business hours.', cta_route: '/transactions/<tx_id>'}, expires_at=now()+24hours)` if a transaction with this `tx_id` is in `awaiting_admin` status AND `value_usd >= 1000`; the 24-hour expiry is shorter than the others because the tx will resolve (one way or the other) within typical SLA. Returns `ShouldNotShow` if tx no longer awaiting_admin OR no longer above $1000 threshold.

- **AC-phase4-ai-009-07:** Given the `EvaluateSuggestionsForUser` use case, when invoked with `user_id`, then within a single UoW: (1) calls each registered rule's `kind_for(user_id)` to get all candidate kinds; (2) batch-loads existing pending suggestions for `user_id` filtered by those kinds — single SQL using the `idx_sugg_user_kind_pending` partial index; (3) for each `(rule, kind)` pair: (a) call `rule.evaluate(user_id, kind)`; (b) if `ShouldShow` AND no existing pending: create new `Suggestion`, persist, collect `SuggestionCreated`; (c) if `ShouldShow` AND existing pending: no-op (banner stays); (d) if `ShouldNotShow` AND existing pending: call `existing.supersede(reason='rule_no_longer_applicable')`, persist, collect `SuggestionDismissed`-style event; (e) if `ShouldNotShow` AND no existing: no-op; (4) commit events via outbox. Returns `EvaluationSummary{user_id, created_count, superseded_count, evaluated_count, duration_ms}` — observability.

- **AC-phase4-ai-009-08:** Given the periodic worker `evaluate_suggestions_periodic` in arq, when triggered (cron every 5 minutes), then: (1) selects active users from `identity.users` filtered by `last_login_at > NOW() - INTERVAL '7 days'` (only evaluates "recent" users — no point creating banners for inactive accounts); (2) processes in batches of 100 users; (3) per batch, parallel-dispatches `EvaluateSuggestionsForUser` via `asyncio.gather` with concurrency cap 10; (4) total batch wall-clock target: <30 seconds for 100 users; (5) logs structlog with `{batch_size, total_created, total_superseded, total_duration_ms}`. Disable-flag: `EVALUATE_SUGGESTIONS_ENABLED=true` default; `false` in local dev to avoid noisy log lines. The 5-min cadence is configurable via `EVALUATE_SUGGESTIONS_INTERVAL_SECONDS` (default 300).

- **AC-phase4-ai-009-09:** Given the periodic expiry sweeper, when triggered (separate cron, every 60 seconds — different from the rule-evaluation worker, simpler job): (1) runs `SELECT id FROM ai.suggestions WHERE status = 'pending' AND expires_at < NOW() ORDER BY expires_at ASC LIMIT 500`; (2) for each id, loads, calls `expire()`, persists. Single UoW per row (low-volume operation, no batching needed). The two cron jobs (evaluate + sweeper) are independent: evaluation handles "rule says no longer applicable" via supersede; sweeper handles "user ignored the banner for 7 days" via expire.

- **AC-phase4-ai-009-10:** Given the `OnKycTierChanged` handler, when `kyc.TierChanged` event arrives indicating `new_tier ∈ {'tier_1', 'tier_2'}`, then: (1) finds pending suggestions for `user_id` of kind `kyc_incomplete`; (2) for each, calls `mark_actioned(by_event_kind='kyc.TierChanged')`, persists, collects `ai.SuggestionActioned`. The `OnTransactionConfirmed` handler does the parallel: pending `large_pending_withdrawal:<tx_id>` matching the confirmed tx_id → mark actioned. These handlers are the "honesty" of the suggestions: when the user does the thing, the banner closes itself elegantly rather than waiting for the next eval cycle to supersede.

- **AC-phase4-ai-009-11:** Given `GET /api/v1/ai/suggestions`, when called with valid auth, then returns `{suggestions: [{id, kind, payload, created_at, expires_at}, ...]}` filtered to `status='pending'` AND `user_id=<requester>`, ordered by `created_at DESC`, capped at 20 (cosmetic — even active users rarely have 20+ pending). `POST /api/v1/ai/suggestions/{id}/dismiss` calls `DismissSuggestion(id, requesting_user_id=<requester>)`: authorisation via `SuggestionNotFound` on cross-user (same discipline as `phase4-ai-002` AC-12); idempotent — re-dismissing returns the dismissed state without error (200 with the dismissed entity, NOT 409); `SuggestionAlreadyTerminal` only fires for non-dismissed terminal states (superseded/expired/actioned). Returns `{suggestion: {id, kind, status: 'dismissed', updated_at}}` (200).

- **AC-phase4-ai-009-12:** Given the property test on **Suggestion state machine no-orphan-states** (`tests/ai/suggestions/domain/test_suggestion_state_machine_properties.py::test_no_orphan_states`), when fuzzed via Hypothesis over random sequences of `[create, dismiss, supersede, expire, mark_actioned, dismiss_again, ...]` of varying lengths, then: (a) the final `status` is always one of `{pending, dismissed, superseded, expired, actioned}`; (b) once non-pending, no event mutates state; (c) `terminal_reason` is set whenever status ∈ `{superseded, expired, actioned}` and unset otherwise; (d) re-dismissing already-dismissed is silent (no exception, no event). **New mandatory property test #19 for Phase 4** — extends the pattern from `phase4-ai-005` AC-13 (`PreparedAction` state machine) to suggestions.

---

## Out of Scope

- LLM-generated suggestions (V2; the rule registry seam accepts them).
- Suggestions based on transaction memory / past behaviour (V2 — would consume `phase4-ai-007`).
- Push notifications for new suggestions (V2 via `phase2-notifications-001`).
- Multi-language suggestion text (V2).
- A/B testing suggestion copy (V2).
- Admin UI for suggestions (V2).
- Rule deprecation/migration (V2 — V1 ships three rules, frozen; renaming or removing a rule's `kind_prefix` would orphan rows but V1 has no such case).
- Per-user rule preferences ("don't show me low balance banners"): V2.
- Contextual / time-of-day rules (e.g., "Friday afternoon: weekend reminder"): V2.

---

## Dependencies

- **Code dependencies:** `phase4-ai-001` (ai schema infra); `phase2-balances-001` (`GetPortfolio`); `phase2-pricing-001` (`GetQuotes` for USD value); `phase3-kyc-001` (`get_kyc_status`); `phase2-transactions-002` (`ListUserTransactions` query, lifted in `phase4-ai-003`); `phase1-shared-003` (UoW, outbox); `phase1-shared-004` (arq cron registry); `phase1-identity-004` (auth on REST endpoints).
- **Data dependencies:** migrations 001–006 applied. `kyc.TierChanged` and `transactions.Confirmed` events already published from prior phases.
- **External dependencies:** none new.
- **Configuration:** `EVALUATE_SUGGESTIONS_ENABLED` (default `true`), `EVALUATE_SUGGESTIONS_INTERVAL_SECONDS` (default `300`), `LOW_BALANCE_USD_THRESHOLD` (default `10`), `LARGE_PENDING_WITHDRAWAL_USD_THRESHOLD` (default `1000`), `SUGGESTION_TTL_DAYS` (default `7`).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/ai/suggestions/domain/test_suggestion.py` — `create`, all four transitions (valid + each invalid prior state), `expire` silent no-op idempotency, `dismiss` after `dismiss` silent (covers AC-11 idempotency clause). Covers AC-02.
- [ ] **Property tests:** `tests/ai/suggestions/domain/test_suggestion_state_machine_properties.py` — covers AC-12 (mandatory).
- [ ] **Application tests:** `tests/ai/suggestions/application/rules/test_low_balance_rule.py` — happy show, just-above-threshold no-show, zero-balance no-show, multi-asset/multi-chain kind enumeration. Covers AC-04.
- [ ] **Application tests:** `tests/ai/suggestions/application/rules/test_kyc_incomplete_rule.py` — tier_0 fresh user → show, tier_0 applicant_started → show with continue copy, tier_1 → no-show, tier_0_rejected → no-show. Covers AC-05.
- [ ] **Application tests:** `tests/ai/suggestions/application/rules/test_large_pending_withdrawal_rule.py` — awaiting_admin above threshold → show, below threshold → no-show, broadcasting/confirmed → no-show. Covers AC-06.
- [ ] **Application tests:** `tests/ai/suggestions/application/test_evaluate_suggestions_for_user.py` — fresh user no existing → 3 created; same user evaluated again no rule changes → 0 changes (idempotency); rule flips to no-longer-applicable → supersede; mixed scenarios. Covers AC-07.
- [ ] **Application tests:** `tests/ai/suggestions/application/test_evaluate_suggestions_periodic.py` — batch over 250 users in 3 batches of 100/100/50, parallel cap respected, summary metric logged. Covers AC-08.
- [ ] **Application tests:** `tests/ai/suggestions/application/test_expire_suggestions_sweeper.py` — pending past expiry marked expired, idempotent re-run. Covers AC-09.
- [ ] **Application tests:** `tests/ai/suggestions/application/handlers/test_on_kyc_tier_changed.py`, `test_on_transaction_confirmed.py` — events mark suggestions actioned. Covers AC-10.
- [ ] **Application tests:** `tests/ai/suggestions/application/test_dismiss_suggestion.py` — happy path, cross-user → SuggestionNotFound, re-dismiss idempotent, dismiss already-superseded → SuggestionAlreadyTerminal. Covers AC-11.
- [ ] **Application tests:** `tests/ai/suggestions/application/test_list_user_suggestions.py` — only pending, ordering, cap 20.
- [ ] **Adapter tests (testcontainers):** `tests/ai/suggestions/infra/test_sqlalchemy_suggestion_repo.py` — JSONB round-trip, partial-index usage on three indexes via EXPLAIN, idempotent INSERT semantics if needed.
- [ ] **Migration tests:** `tests/ai/suggestions/infra/test_migration_007_suggestions.py` — apply + rollback, idempotency. Covers AC-01.
- [ ] **Contract tests:** `tests/api/test_ai_suggestions_routes.py` — list returns pending only, dismiss happy/cross-user/idempotent, OpenAPI examples match. Covers AC-11.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass — `ai.suggestions.application` may import from `balances`, `pricing`, `kyc`, `transactions` application use cases (Pragmatic reads); does not touch `custody`.
- [ ] `mypy --strict` passes for `vaultchain.ai.suggestions.*`.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (`ai/suggestions/domain/` ≥ 95%, `ai/suggestions/application/` ≥ 90%).
- [ ] OpenAPI schema diff reviewed: two new endpoints with examples committed.
- [ ] Three new error codes (`ai.suggestion_not_found`, `ai.suggestion_already_dismissed`, `ai.suggestion_already_terminal`) registered in `errors-reference.md`.
- [ ] Two new ports declared (`SuggestionRepository`, `SuggestionRule`) with fakes.
- [ ] One new Alembic revision (`007_suggestions`) committed + applied + rolled-back tested.
- [ ] Three new domain events registered (`ai.SuggestionCreated`, `ai.SuggestionDismissed`, `ai.SuggestionActioned`).
- [ ] Three concrete rules registered in `ai/suggestions/infra/composition.py:configure_suggestions(container, extra_rules=[])`. Same `extra_rules` extension seam as `phase4-ai-003`'s tool catalog — V2 LLM rule plugs in here.
- [ ] Two arq cron jobs registered (`evaluate_suggestions_periodic`, `expire_suggestions_sweeper`).
- [ ] `docs/runbook.md` updated with: how to disable the evaluator (`EVALUATE_SUGGESTIONS_ENABLED=false`), how to clear stale suggestions during incidents (`UPDATE ai.suggestions SET status='expired' WHERE ...`), the meaning of each rule's threshold env var.
- [ ] Single PR. Conventional commit: `feat(ai/suggestions): aggregate + 3 rules + worker + REST [phase4-ai-009]`.
- [ ] PR description: a state diagram of the five Suggestion states + a table of the three V1 rules (`name | trigger | TTL | actioned-by-event`).

---

## Implementation Notes

- **The "AI" framing is UX-positioned, not implementation-required.** This is worth a sentence in the PR description so a reviewer doesn't expect an LLM call inside the rule worker. The rule registry seam (AC of registering rules via `extra_rules` parameter) makes V2 LLM-rules a clean extension; V1 keeps things deterministic.
- **`kind` is a string, not an enum.** Concrete kinds like `low_balance:USDC:ethereum` are dynamic per user (their wallet+asset combinations); enum-ising would force schema changes per chain/asset addition. The `kind_prefix` on the rule (`low_balance`) is the structural part; the suffix is the discriminator. CHECK constraints on the column would over-fit.
- **Why supersession + expire (two terminal-but-not-actioned paths)**: supersede means "the rule's premise changed" (user topped up — Low Balance no longer applies); expire means "user ignored the banner long enough that we GC it." They're observationally different — supersession indicates user behavior; expiry indicates user inaction. Both are valuable signals if V2 wants suggestion-conversion analytics.
- **The two cron jobs (5-min eval + 60-sec expire-sweep)** are separate intentionally: the eval job is heavier (per-user rule evaluation, multiple cross-context reads); the expire job is light (single UPDATE-shaped batch). Co-mingling them would force the lighter one to wait for the heavier; separation lets each run on its natural cadence.
- **The active-user filter (last_login_at > 7 days)** in the eval worker is a pragmatic cost optimization. A future user who hasn't logged in for 30 days doesn't need a daily Low Balance banner generated. When they return, their first dashboard load includes one eval cycle (handled outside the cron — the REST `GET /suggestions` endpoint can call a "lazy eval" path; explicit non-goal in V1 to keep things simple). V1 acceptable: dormant users see suggestions on next active session.
- **The handlers in AC-10** are the cleanup that makes suggestions feel responsive. Without `mark_actioned`, a user who completes KYC sees the "Verify your identity" banner persist until next eval cycle (5 min) — confusing UX. With the handler, the banner closes the instant the `kyc.TierChanged` event fires (subsecond).
- **The `extra_rules` parameter** on `configure_suggestions` follows the pattern from `phase4-ai-003`'s tool catalog. V2's LLM-driven suggestions register here without modifying this brief's wiring.
- **`SuggestionNotFound` (404) on cross-user dismiss** follows the timing-oracle discipline from `phase4-ai-002`. Suggestions IDs are UUIDv7 and time-ordered; leaking existence via 403 vs 404 distinction would let an attacker enumerate creation order.

---

## Risk / Friction

- **Rule quality is judgement-call territory.** A reviewer may push back on the $10 low-balance threshold ("too low for ETH") or the kyc message ("too pushy"). Make these env-var-tunable (per the Configuration list) so adjusting is one config change, not a code change.
- **The 5-minute eval cadence × 100-user batches × 10-concurrency means** at ~10k active users in V2, a single batch run takes ~5 minutes, exactly filling the cadence. V1 (~100s of users) is fine; V2 will need either reduced cadence or larger concurrency. Documented as known scaling limit.
- **Rule supersession can flip back-and-forth** if the user oscillates around a threshold (balance jumps to $11 then back to $9). The banner would supersede + recreate every 5 min. Mitigation: not implemented in V1 (the cost is just one extra DB row per oscillation cycle). V2 could add hysteresis (don't recreate within X hours of supersession). Documented.
- **`mark_actioned` requires the handler to find the right pending suggestion.** Edge case: user has TWO pending `large_pending_withdrawal:<id>` suggestions (sequence: tx1 went to awaiting_admin, suggestion created; tx2 went to awaiting_admin, suggestion created; tx1 confirmed → only tx1's suggestion gets actioned, tx2 untouched). The kind suffix `:<tx_id>` keys this correctly. Tested in AC-10.
- **`SuggestionRule.kind_for` may return many kinds for power users.** A user with 5 wallets × 5 assets = 25 LowBalance kinds. Per-rule evaluation is async; the `for kind in kinds: await rule.evaluate(...)` loop is sequential per rule, parallel across rules via the worker's `asyncio.gather`. If a power user's batch exceeds 30 seconds, the worker logs a warning and continues — V1 acceptable, V2 might add per-rule parallelism.
- **The `kyc_incomplete` "applicant_started" copy variant** depends on the kyc query exposing that field. Verify during implementation; if Phase 3 didn't surface it, a small extension to the kyc query is included in this PR (similar lift pattern to `phase4-ai-003`'s `ListUserTransactions`).
- **CSV export of all suggestions for analytics** — explicit non-goal in V1. The events provide this implicitly; admin can `psql` for ad-hoc queries.
