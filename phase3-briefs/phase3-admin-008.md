---
ac_count: 7
blocks: []
complexity: L
context: admin
depends_on:
- phase2-audit-001
- phase3-custody-003
- phase3-custody-004
- phase3-admin-004
- phase3-admin-007
estimated_hours: 4
id: phase3-admin-008
phase: 3
sdd_mode: lightweight
state: ready
title: Admin transactions monitoring + audit timeline + manual rebalance trigger
touches_adrs: []
---

# Brief: phase3-admin-008 — Admin transactions monitoring + audit timeline + manual rebalance trigger


## Context

Admin-004 gave operators a workdesk for the *withdrawal queue* — the txs that need their attention. Admin-008 gives them a *monitoring view* for the rest of the system: every transaction across every chain in any state, plus the cross-context audit timeline that explains why each one is where it is. This is the page operators leave open during a demo or during normal operations to watch the system breathe.

Two read models drive the screens. The transactions monitor is `AdminTxQuery.list_all(filters)` — a flat paginated table over `transactions.transactions` with optional joins to `transactions.transaction_events` for state-history breadcrumbs. The audit timeline is `AdminAuditQuery.list_all(filters)` — a UNION over `audit.events` (the global cross-context log) and `custody.audit_log` (Custody's KMS-specific log) so operators do not have to context-switch between two views. Custody's separate audit table exists because of the no-PII-in-shared-log invariant from Phase 2; admin-008 reads both and synthesises one timeline at the read layer.

Phase 3 also adds one operator action beyond observation: trigger a rebalance manually for a specific (user, chain, asset). Custody-004's worker runs every 4 hours, but operators sometimes need to rebalance immediately — a user complains a deposit has not yet moved to cold, or a demo wants to show the cold transfer happening live. The endpoint `POST /admin/api/v1/custody/rebalance-trigger` enqueues an immediate rebalance job for a single triple, gated by superadmin role + TOTP, and surfaces the result via the standard audit log so the action is traceable. The button lives on admin-007's user detail page (small, gated UI element); the endpoint lives here architecturally because it sits adjacent to the monitoring view that shows its effects.

The optional per-chain charts are a small visual aid: three sparklines (one per chain) showing transaction count over the last 24h binned hourly. They use `recharts` (already in the design system) and a tiny aggregation query. Sparklines are valuable for spotting anomalies (Solana volume drop hints at watcher trouble) without committing to a full observability stack.

Lightweight SDD: server-rendered tables, query-string filters, no SSE, no SPA. The sparklines are the only client-side render and they are <30 lines of Recharts boilerplate.

---

## Architecture pointers

- `architecture-decisions.md` §"Admin shell" + §"Audit log" (separation of audit.events from context-specific logs).
- `phase2-audit-001.md` for `audit.events` schema and write contract.
- `phase3-custody-003.md` for `custody.audit_log` schema (separate log; merged at read time here).
- `phase3-custody-004.md` AC-phase3-custody-004-04 for rebalance worker contract — the manual trigger reuses the same job runner, just bypasses the schedule check.
- `phase3-admin-007.md` for admin-gateway pattern; reused/extended here.

---

## Acceptance Criteria

**AC-phase3-admin-008-01 — `/admin/transactions` page**

Server-rendered. Filter sidebar: chain (multi-select: ethereum, tron, solana), status (multi-select: all 7 transaction statuses), direction (deposit/withdrawal/all), time range (preset: last 1h, 24h, 7d, custom from/to datetime), amount range (min/max in chain-native units, asset-aware — disabled until both chain and asset filters are set), user (autocomplete by email or address — reuses admin-007's search). Result table: tx_id (truncated), user_email, chain, direction, amount + asset, USD@creation, status badge, created_at, broadcast_tx_hash (chain-explorer link). Pagination: offset-based, 100 rows per page. Default sort: `created_at DESC`. URL state reflects filters.

**AC-phase3-admin-008-02 — `GET /admin/api/v1/transactions` API endpoint**

Powers AC-01. Accepts the same filters as query params. Returns `{"results": [...], "total": int, "page_size": 100, "offset": int}`. ≤500ms p50 for the default view (no filters, last 24h implicit). Backed by a covering index on `transactions.transactions(created_at DESC, status, chain)` — verify present, add if missing.

**AC-phase3-admin-008-03 — Per-chain sparklines on the page header**

Above the filter+results, three small charts (one per chain) show "transactions per hour, last 24h". Backed by `GET /admin/api/v1/transactions/per-chain-counts?window=24h` returning `{"ethereum": [{"hour": "2026-04-26T18:00", "count": 12}, ...], "tron": [...], "solana": [...]}`. Aggregation query: `SELECT chain, date_trunc('hour', created_at) AS hour, COUNT(*) FROM transactions.transactions WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY chain, hour`. Cached server-side for 60s — sparklines refresh on full page reload, not live.

**AC-phase3-admin-008-04 — `/admin/audit` timeline page**

Server-rendered. Filter sidebar: actor type (user/admin/system/external — multi-select), operation (free text contains-match), entity type (transaction/wallet/applicant/cold_wallet/etc — derived from `metadata` keys), time range (same presets as AC-01), user (same autocomplete). Result list: timestamp, actor (name + type badge), operation, entity (type + id, link to relevant detail page if known), short metadata preview (key fields only — never the full JSON). Pagination: cursor-based on `created_at DESC` because the table is append-only and high-volume. 100 rows per page.

**AC-phase3-admin-008-05 — `GET /admin/api/v1/audit` endpoint**

Powers AC-04. UNIONs `audit.events` and `custody.audit_log`, merged by `created_at`. The custody log gets a synthetic `actor_type='system'` and `actor_id='custody'` for entries that lack them, so the unified shape is consistent. Returns `{"results": [...], "next_cursor": "...", "has_more": bool}`. The cursor is `(created_at, event_id_or_log_id)` encoded as base64 — handles ties at the same timestamp deterministically.

**AC-phase3-admin-008-06 — Highlight rule for sensitive operations**

In the audit-timeline rendering, rows with `operation IN ('kyc.tier_escalated', 'custody.cold_signed', 'admin.withdrawal_approved', 'admin.withdrawal_rejected', 'custody.rebalance_triggered_manually')` are styled with a left-border accent (warning-amber). Three CSS classes max — keep it understated. Helps an operator spot what humans did versus what the system did.

**AC-phase3-admin-008-07 — `POST /admin/api/v1/custody/rebalance-trigger` endpoint**

Admin-only, role `superadmin`. Body: `{"user_id": "...", "chain": "ethereum", "asset": "ETH", "totp_code": "123456"}`. Validates TOTP, asserts user has both hot and cold wallets for (chain, asset), enqueues a one-off rebalance job in the same arq queue used by custody-004's worker but with a job tag `manual=true`. Returns 202 `{"job_id": "..."}` immediately; the rebalance proceeds asynchronously. Writes audit row `operation='custody.rebalance_triggered_manually'` with `actor_id` = admin user id, `metadata={user_id, chain, asset, job_id}`. The worker honours the job exactly as it would a scheduled rebalance — same logic, same RebalanceSettled event on success.

**AC-phase3-admin-008-08 — Trigger button on `/admin/users/{user_id}` detail page**

Admin-007's wallet section gets a small "Rebalance now" button per row (one per chain+asset triple), gated to `superadmin` role only (hidden for `kyc_reviewer`-only admins). Click → TOTP modal → submit → calls AC-07 → success toast "Rebalance enqueued, job_id=..." → suggest "see audit log for completion". The button does *not* poll for status; the operator monitors via the timeline.

**AC-phase3-admin-008-09 — Rate limit on manual trigger**

The trigger endpoint is rate-limited at the admin-shell level: 10 manual rebalance triggers per admin per hour, enforced via Redis bucket. Beyond that, returns 429 with `Retry-After`. Prevents operator typos or scripts from hammering the chain. Tested with a 11th call → 429.

**AC-phase3-admin-008-10 — Empty states and slow-query guards**

Each page renders a friendly empty state when no results match. Each query has a hard limit of 5 seconds (statement timeout for the admin-app pool). Beyond timeout, return 504 with "Query took too long, narrow your filters." Avoids accidental full-table scans bringing the page down.

---

## Out of Scope

- Live updates (SSE/WebSocket). Operators reload. Phase 4 if needed.
- Exports (CSV/JSON download). Phase 4.
- Cross-context joins beyond what the audit log already provides. If an operator wants "txs joined with kyc tier joined with audit", they pull data manually.
- A unified search bar at the top of the admin shell that searches across users + transactions + audit. Future polish.
- Full observability stack (Grafana, Prometheus). Sparklines are the operator-visible view; underlying metrics are the operator's own concern.
- Bulk admin actions on transactions (e.g., "reject all stuck withdrawals"). Manual one-by-one only.

---

## Dependencies

- `phase2-audit-001` for `audit.events` table.
- `phase3-custody-003` for `custody.audit_log` table.
- `phase3-custody-004` for the rebalance worker queue (the manual trigger enqueues into the same queue).
- `phase3-admin-004` for transactions admin gateway (extended here with `list_all`).
- `phase3-admin-007` for the admin-gateway pattern + the user-detail page that gets the trigger button.

---

## Test Coverage Required

- **Unit (`admin/handlers/transactions`, `admin/handlers/audit`, `admin/handlers/rebalance_trigger`):** filter SQL builders (parameterised), cursor encoding/decoding, sensitive-operation highlight rule.
- **Integration (`admin/integration/`):**
  - `test_admin_transactions_filters_by_chain`: seed mixed-chain txs, filter `?chain=ethereum` → only ETH rows.
  - `test_admin_transactions_filters_by_time_range`: seed across timestamps, filter last-1h → only recent rows.
  - `test_admin_audit_unions_custody_log`: seed an entry in `audit.events` and one in `custody.audit_log` at adjacent timestamps; GET timeline; assert both appear in correct chronological order.
  - `test_admin_rebalance_trigger_enqueues_job`: superadmin + valid TOTP → 202, audit row written, arq queue has the job.
  - `test_admin_rebalance_trigger_role_denied`: kyc_reviewer → 403.
  - `test_admin_rebalance_trigger_rate_limited`: 10 triggers OK, 11th → 429.
  - `test_admin_per_chain_counts_aggregates`: seed N txs across 3 chains; GET counts; assert correct hour-bucketed numbers.
- **Snapshot:** transactions page render, audit timeline page render — two snapshots, regenerate on UX change.
- **No property tests** (lightweight).

---

## Done Definition

- All AC pass.
- Three new admin sidebar links: "Transactions", "Audit", neither visible to non-admin roles. Existing "Users" link from admin-007 stays.
- OpenAPI spec at `docs/openapi/admin.yaml` includes transactions, audit, per-chain-counts, and rebalance-trigger endpoints.
- Operator runbook entries: `docs/runbooks/admin-monitoring.md` (how to use filters, what each tx status means, how to read the sparklines for anomalies); `docs/runbooks/admin-manual-rebalance.md` (when to trigger, when not to, what the audit row looks like, how to verify completion).
- Sidebar order in admin shell: Withdrawals → KYC → Users → Transactions → Audit. Withdrawals is most-used (admin-006), audit is a deep-dive surface.

---

## Implementation Notes

The transactions filter UI is the most-touched piece of this brief. Use server-side rendering of the filter form with checkboxes/text-inputs, hidden iframe target for instant submit-without-flash, or a simple `<form method=GET>` that reloads. Either is fine for V1; pick the one consistent with the rest of admin-shell. Do not introduce React for this page.

The UNION query in AC-05 deserves a small read-only view (`audit.unified_events_v` or similar) that pre-shapes the columns. Keeps the handler code clean. Document the view in the migration that creates it.

For the cursor in AC-05: encode `f"{created_at.isoformat()}|{event_id}".encode()` as base64. Decode on inbound, validate format, reject malformed. Tests should include a malformed cursor → 400.

Manual rebalance trigger and admin-006's withdrawal approval share the same TOTP plumbing. If you have not already extracted `TotpVerifier` in admin-005, do it here and refactor admin-005/006 to use it. Consolidating is cheaper than the third paste-job.

The rate limit at AC-09 is in admin-shell, not at the worker. The worker still happily processes any job that lands in the queue. The point of the rate limit is to prevent an admin from creating a backlog; once jobs are in the queue, they run on their schedule. Document this — operators should know that 10 triggers in an hour will all eventually run, just spaced by the worker's job concurrency settings (custody-004 has `max_jobs=1` so they run one at a time).

The sparkline data fetching is *not* live (60s cache); decline any request to make it tail real-time data. The page reload pattern is acceptable; live sparklines invite WebSocket complexity that does not pay off in V1.

For sensitive operation highlighting at AC-06: do *not* tie this to a specific role check. The highlight is informational, visible to all admins. The role-based access is on the actions themselves (who can call escalate/approve/trigger), not on who sees that someone else did.

---

## Risk / Friction

- **Audit log volume.** With Phase 3's rebalance worker adding ~12k internal_rebalance audit rows per day at upper-bound, the audit page query needs the right indexes. Verify `audit.events(created_at DESC)` and `custody.audit_log(created_at DESC)` indexes exist; add if missing.
- **Filter combinatorics on transactions.** Some filter combinations (e.g., user + amount range + 7 days) will produce small result sets fast. Other combinations (no filters + last 7 days on a busy system) will hit the statement timeout. The slow-query guard at AC-10 is the catch-all; document the recommended filter strategy in the runbook.
- **Manual rebalance race with scheduled rebalance.** If an admin triggers and the scheduled job fires concurrently, both jobs grab the same `(user, chain, asset)` row in custody. Custody-004's `max_jobs=1` serialises arq workers; the second job sees the rebalance complete and no-ops. No data corruption. Document.
- **Cursor encoding edge cases.** Two events with identical `created_at` to microsecond — possible under high load. The cursor includes `event_id` so ties are broken; just verify in integration test that re-paginating with the cursor does not lose or duplicate.
- **Sidebar growth.** Five links (Withdrawals, KYC, Users, Transactions, Audit) is the upper bound for tasteful sidebar UX. Future admin features should be sub-pages of one of these, not new top-level links.
