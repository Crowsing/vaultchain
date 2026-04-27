---
ac_count: 4
blocks:
- phase3-admin-008
complexity: L
context: admin
depends_on:
- phase1-admin-002
- phase2-wallet-001
- phase3-custody-003
- phase3-custody-004
- phase3-wallet-002
- phase3-kyc-001
- phase3-ledger-003
- phase3-admin-004
estimated_hours: 4
id: phase3-admin-007
phase: 3
sdd_mode: lightweight
state: ready
title: Admin user search + detail (cross-context, hot+cold visibility)
touches_adrs: []
---

# Brief: phase3-admin-007 — Admin user search + detail (cross-context, hot+cold visibility)


## Context

When something looks off in a real custodial wallet — a user reports a missing deposit, a withdrawal stuck in admin queue too long, suspicious activity on their account — the operator's first move is "look up the user". They need a single page that shows everything we know in one glance, organised by what is most likely to matter. This brief delivers that page plus the search bar that gets you to it.

The search must accept three input types: email (substring match, case-insensitive), user_id UUID (exact), and on-chain address (exact, across both hot and cold). Address-based search is the operationally-useful one — the most common real-world question is "whose wallet is `0xabc…`" when looking at a chain explorer. Address search must check `wallet.wallets` and `custody.cold_wallets` and find the match in either, returning the same user. Email search uses ILIKE prefix-match for snappy autocomplete potential.

The detail page is wide and read-heavy. It pulls from five contexts via dedicated admin-side gateways (one per context) so we keep the boundary discipline: admin-shell does not reach into other schemas directly, it asks an `AdminGateway` defined in each context's adapters. This trades a small amount of code (~5 thin adapters) for big architectural payoff — when one of those contexts changes its internal model, only its admin gateway needs updating. The pattern is already established in admin-004 for the transactions queue; admin-007 reuses and extends it.

Lightweight SDD: no real-time updates (a refresh button is enough), no charts, no exports. The detail view is a tall scroll of grouped sections rendered server-side. Two integration tests, two snapshots, ship it.

---

## Architecture pointers

- `architecture-decisions.md` §"Admin shell" + §"Bounded context boundaries" (admin reads via context-owned gateways, never direct schema access).
- `phase3-admin-004.md` for the established admin-gateway pattern (transactions admin queue).
- `phase3-ledger-003.md` (the cold-balance read; `LedgerAdminGateway.get_balances` returns hot+cold+pending per (chain, asset) — see AC-05 here).
- `phase3-custody-003.md` for `custody.cold_wallets` schema.
- `phase3-kyc-001.md` AC-04 for the user-side `GET /kyc/status` shape — admin sees the same structure plus extras.

---

## Acceptance Criteria

- **AC-phase3-admin-007-01:** Given the `GET /admin/api/v1/users/search?q=<string>` endpoint with valid admin auth, when called, then input classification rules apply: (a) input matching `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` is treated as `user_id` (exact match on `identity.users.id`); (b) input matching `^0x[a-fA-F0-9]{40}$` (Ethereum), `^T[A-HJ-NP-Za-km-z1-9]{33}$` (Tron base58check), or `^[1-9A-HJ-NP-Za-km-z]{32,44}$` (Solana base58 ed25519 pubkey) is treated as on-chain address (exact match on `wallet.wallets.address ∪ custody.cold_wallets.address`, joined back to `user_id`); (c) anything else: email substring (`ILIKE '%' || q || '%'`). Response: `{"results": [{"user_id", "email", "tier", "matched_via": "email|user_id|address", "matched_address": "..." | null}], "total": int}`. Limit 20.

- **AC-phase3-admin-007-02:** Given an admin navigates to `/admin/users` (server-rendered search page), when authenticated, then a single text input submits to AC-01 and renders results: email, tier badge, matched-via tag, link to detail page. Empty state: "No users found for query."

- **AC-phase3-admin-007-03:** Given an admin opens `/admin/users/{user_id}` (server-rendered detail page), when authenticated, then the page renders sections in this order: **Identity** (email, created_at, last_login_at, active sessions count); **KYC** (tier badge, review_answer, reject_labels chip-list, applicant_id with copy button, link to `/admin/kyc/applicants/{applicant_id}`); **Wallets** (table per (chain, asset): chain, asset, hot_address, hot_balance, cold_address, cold_balance, pending_balance — six columns, currency-formatted); **Recent Transactions** (top 10 most recent, filter dropdowns above for chain/direction/status, link to AC-04); **Audit Highlights** (top 10 most recent audit rows where this user was actor or subject, link to admin-008 timeline filtered for this user).

- **AC-phase3-admin-007-04:** Given a "View all transactions" link on the detail page, when followed, then it routes to `/admin/users/{user_id}/transactions?chain=&status=&from=&to=` with offset pagination (50 rows per page). Reuses `TransactionsAdminGateway.list_for_user` (existing from admin-004 or extended here if not yet user-filtered). Each row shows tx_id (truncated, copy-on-click), chain, direction, amount with asset, USD-equivalent at creation time, status, created_at, broadcast_tx_hash (link to chain explorer if present).

- **AC-phase3-admin-007-05:** Given the five new admin-side ports, when defined, then each context declares a `Protocol` in its `domain/ports.py` (and adapter in `<context>/infra/admin/`), and the `admin/` package wires them via composition root. Methods needed:
  - `IdentityAdminGateway.get_user_summary(user_id) -> UserSummary` (email, created_at, last_login_at, active_session_count)
  - `WalletAdminGateway.get_wallets(user_id) -> list[WalletSummary]` (chain, asset, hot_address)
  - `CustodyAdminGateway.get_cold_wallets(user_id) -> list[ColdWalletSummary]` (chain, asset, cold_address)
  - `KycAdminGateway.get_applicant_summary(user_id) -> ApplicantSummary | None` (tier, applicant_id, review_answer, reject_labels)
  - `LedgerAdminGateway.get_balances(user_id) -> list[BalanceRow]` (chain, asset, hot, cold, pending)
  - `LedgerAdminGateway.search_address(address) -> AddressOwner | None` (resolves any chain address to `(user_id, kind ∈ {hot, cold})`)
  - `TransactionsAdminGateway.list_for_user(user_id, filters, limit, offset)` reuses or extends admin-004's gateway.

- **AC-phase3-admin-007-06:** Given `LedgerAdminGateway.search_address(addr)`, when invoked, then it executes `SELECT user_id, 'hot' AS kind FROM wallet.wallets WHERE address = $1 UNION ALL SELECT user_id, 'cold' AS kind FROM custody.cold_wallets WHERE address = $1`. Returns the first match (addresses must be unique by construction across hot+cold; if `> 1` row returned, log a critical alarm). If no match, returns `None`. Implemented as a `LedgerAdminGateway` method specifically because Ledger sits at the read-model layer; it is the natural place for cross-context joins.

- **AC-phase3-admin-007-07:** Given the user detail page is read-only (no forms, no mutating buttons except admin-008's "Rebalance now" delegated button), when rendered, then no "edit user" / "force tier change" / "rotate keys" controls exist. Manual interventions live in their dedicated endpoints (admin-005's escalate, admin-006's approve, admin-008's rebalance trigger).

- **AC-phase3-admin-007-08:** Given a snapshot test in `tests/admin/snapshots/test_user_detail.py`, when rendered for a fixture user with one applicant in `tier_1`, three hot+cold wallet pairs across all three chains, three transactions in mixed states, and several audit rows, then the rendered HTML matches the committed snapshot. The snapshot is the contract for "no PII leaks into the page through unexpected fields" and "no fields missing from any section".

---

## Out of Scope

- Editing user data (email change, password reset, force-logout). Those are separate admin operations that live in their own narrow endpoints, none of which Phase 3 builds. Operator does these via DB if truly necessary.
- Real-time updates. The page has a refresh button. Phase 4 may add SSE if portfolio review demands it.
- Exporting user data (CSV download for compliance requests). Phase 4 if needed.
- Search by partial address (prefix match). Exact match only.
- Bulk operations (select multiple users, delete, export). Out of scope.

---

## Dependencies

- Five context-owned admin gateways (defined in this brief if not already present); one per: identity, wallet, custody, kyc, ledger. Transactions reuses admin-004's gateway.
- `phase1-admin-001`/`002` for admin shell layout and admin auth (TOTP).
- All Phase 3 schema migrations applied (cold wallets, kyc tables) so the queries work.
- `phase3-custody-004` for rebalance history visible in the user-detail view's wallet section.

---

## Test Coverage Required

- **Unit (`admin/handlers/users`):** input-classification logic in AC-01 (uuid vs address vs email), table-driven over the regex set.
- **Integration (`admin/integration/`):**
  - `test_search_by_email_finds_user`: seed three users, search prefix → returns matching user(s).
  - `test_search_by_address_finds_owner_hot`: seed user with hot wallet, search address → returns user.
  - `test_search_by_address_finds_owner_cold`: same but cold wallet.
  - `test_search_unknown_returns_empty`: search a nonexistent UUID/address/email → empty results.
  - `test_user_detail_renders_all_sections`: seed user with KYC, wallets, txs, audit; GET detail; assert section headers and field values appear.
- **Snapshot:** AC-08.
- **No property tests** (lightweight).

---

## Done Definition

- All AC pass.
- Five admin gateways (identity, wallet, custody, kyc, ledger) defined and wired.
- Admin shell sidebar adds "Users" link visible to all admin roles.
- OpenAPI spec at `docs/openapi/admin.yaml` includes search endpoint (the detail page is a HTML route, not API).
- Operator runbook entry: `docs/runbooks/admin-user-lookup.md` covering "how to find a user from a chain address", "what each balance column means" (hot vs cold vs pending), and "what the link buttons do".

---

## Implementation Notes

The five admin-gateway adapters are tiny — each is one or two SELECT statements wrapped in a method. Resist the temptation to pull in ORM relationships or eager-loading; raw SQL with hand-shaped row dataclasses is clearer here and faster to render. The whole detail page should query in one round-trip per gateway — five queries total, all concurrent via `asyncio.gather`. P99 page render budget: 300ms.

The address-classification regexes in AC-01 should live in a shared module: `admin.application.address_classifier`. Useful in admin-008 too. Keep it pure (no DB), unit-test it exhaustively.

For the transactions sub-tab pagination at AC-04: the URL is `/admin/users/{id}/transactions` not `/admin/transactions?user_id=...`. The user-scoped path is more natural when bookmarking, makes back-button navigation predictable, and keeps the breadcrumb sensible. The unscoped `/admin/transactions` belongs to admin-008.

Section ordering on the detail page is deliberate: identity (who), KYC (status), wallets (assets), transactions (activity), audit (history). It mirrors the operator's mental model of triage — "what is this user's verified status" comes before "what are they holding". Resist UX changes to this order without a clear reason.

The snapshot test at AC-08 is the load-bearing safety net. Take the time to seed a *thorough* fixture user — multiple chains, both kinds of wallets, mixed-state transactions, several audit rows — so the snapshot actually exercises every code path. A weak fixture makes the snapshot test useless.

For audit highlights at the bottom of the detail page: filter by `actor_id = user_id` OR `metadata->>'user_id' = user_id::text`. The OR is necessary because some operations are user-actor (logged in, started KYC) and some are system-actor with user as subject (KYC tier changed, withdrawal routed). Both should surface in the user's history.

---

## Risk / Friction

- **Five-gateway sprawl.** This brief introduces or extends ports in five contexts. Each is small but the total surface adds up. Mitigation: document the pattern in `docs/architecture/admin-gateways.md` so future admin features have a clear template. Future briefs that need cross-context data should use this.
- **Address-uniqueness assumption.** The address search assumes addresses are unique across `wallet.wallets` and `custody.cold_wallets` for the same user. They are by construction (different KMS roots, different generation paths) but a future bug or migration could violate it. The snapshot test should include a guard: if the search returns more than one user, log a critical alarm.
- **Page render budget.** With five queries in parallel and HTML rendering, hitting 300ms p99 is achievable but not free. Watch for query plans that fall back to seq scans (e.g., on `audit.events` if not indexed by user). If render times bloat, add `audit.events(actor_id, created_at DESC)` index — likely already present from phase2-audit-001.
- **Snapshot brittleness.** The snapshot test will need re-baselining whenever the layout changes meaningfully. Document the regeneration command in the runbook (`pytest --snapshot-update`).
- **Cross-context schema migrations.** Future Phase 4 work that adds new fields to wallet/custody/kyc will need to update the corresponding admin gateway. Forgetting will produce "field missing" template errors. Mitigation: integration test renders the page; broken templates fail loudly.
