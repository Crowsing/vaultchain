---
ac_count: 8
blocks: []
complexity: M
context: admin
depends_on:
- phase3-admin-004
- phase3-custody-003
- phase1-admin-002
- phase1-admin-003
- phase2-notifications-001
estimated_hours: 4
id: phase3-admin-006
phase: 3
sdd_mode: lightweight
state: ready
title: Admin withdrawal approval UI + 2FA + tx detail
touches_adrs: []
---

# Brief: phase3-admin-006 — Admin withdrawal approval UI + 2FA + tx detail


## Context

This brief delivers the admin UI consuming `phase3-admin-004`'s endpoints. UI surface:

1. **`/admin/withdrawals/queue`** — paginated list of `awaiting_admin` transactions. Filters: chain (all/ETH/Tron/Solana), asset, min/max value USD, age (1h/4h/24h), user email. Sort: `created_at DESC` default; `value_usd DESC` available. Each row: chain badge, user email, amount + USD-equivalent, destination address (truncated, click to copy), age (relative time), KYC tier badge, "Review" button. Live-updating: SSE subscription on the existing notifications channel filters for `transactions.RoutedToAdmin` events to highlight new entries with a pulse animation.

2. **`/admin/withdrawals/{transaction_id}`** — detail page. Three columns:
    - **Left: Transaction info** — chain, asset, amount, USD value, destination address (full), source hot wallet, fee estimate, routing decision (which rule triggered), created at.
    - **Middle: User info** — email, account age, KYC tier (with link to applicant detail in admin-005), recent activity (last 10 confirmed txs across all chains with chain badges), hot+cold balance preview, balance impact preview ("After this withdraws, hot balance will be X").
    - **Right: Actions** — Approve button (opens TOTP modal), Reject button (opens reason+TOTP modal), "View on explorer" links for relevant addresses.

3. **TOTP modals** — same component as admin-005 (extracted). Approve modal: TOTP input only. Reject modal: reason text (required, ≥10 chars) + TOTP. Both submit to the respective POST endpoint from admin-004.

4. **Real-time updates** — after approve, the page polls `GET /admin/api/v1/withdrawals/{id}` every 2s (or subscribes to the SSE channel) until status changes from `approved` → `broadcasting` → `confirmed`. UI shows a progress strip: "Cold-signing… → Broadcasting… → Confirmed (block #N)". On `failed`, shows the failure reason inline.

Lightweight SDD mode: behavior is mostly already validated in `phase3-admin-004`'s integration tests. The frontend tests focus on rendering, interaction (TOTP flow), and live-updates wiring.

---

## Architecture pointers

- **Layer:** presentation only.
- **Packages touched:**
  - `admin-web/src/pages/withdrawals/queue.tsx`
  - `admin-web/src/pages/withdrawals/detail.tsx`
  - `admin-web/src/api/withdrawals.ts` (list, detail, approve, reject)
  - `admin-web/src/components/totp-modal.tsx` (shared with admin-005)
  - `admin-web/src/components/withdrawal-status-strip.tsx` (the progress visualization)
  - `admin-web/src/hooks/use-withdrawal-live.ts` (SSE + polling fallback)
- **Reads:** existing admin-004 endpoints + SSE channel.
- **Writes:** none directly (delegates to admin-004 endpoints).
- **Publishes events:** none.
- **Migrations:** none.
- **OpenAPI:** consumes admin-004's spec; no new spec.

---

## Acceptance Criteria

- **AC-phase3-admin-006-01:** Given an admin navigates to `/admin/withdrawals/queue`, when authenticated, then the page lists awaiting_admin transactions with all filters working. Each row displays chain badge with chain-appropriate color (ethereum=blue, tron=red, solana=purple — design system tokens). USD-equivalent shown alongside chain-native amount. Empty state: "Queue is empty — all caught up."

- **AC-phase3-admin-006-02:** Given the live-updates hook is active on the queue, when a new `transactions.RoutedToAdmin` event arrives via SSE, then the queue prepends the new row with a 2-second pulse-highlight animation. No full page reload.

- **AC-phase3-admin-006-03:** Given the admin clicks a row's "Review" button, when navigated to `/admin/withdrawals/{id}`, then the detail page loads with all three columns populated. The user info column includes a click-through link to the user's profile (admin-007) and KYC applicant (admin-005).

- **AC-phase3-admin-006-04:** Given the admin clicks "Approve" on the detail page, when the TOTP modal opens, when the admin enters a valid 6-digit code and submits, then `POST /admin/api/v1/withdrawals/{id}/approve {totp_code}` fires. On 202, modal closes; the page transitions to live-updates mode showing the status strip animating "Cold-signing → Broadcasting → Confirming…". On 401 invalid TOTP, modal stays open with inline error "Invalid code, try again."

- **AC-phase3-admin-006-05:** Given the admin clicks "Reject", when the modal opens with reason text + TOTP fields, when both are valid (reason ≥ 10 chars), when submitted, then `POST /admin/api/v1/withdrawals/{id}/reject {reason, totp_code}` fires. On 200, modal closes and the page shows "Rejected" state with the reason displayed; a "Back to queue" button appears.

- **AC-phase3-admin-006-06:** Given the admin attempted approve but received 409 Conflict (race with another admin), when the response arrives, then a toast appears: "Another admin already processed this withdrawal." The page navigates back to the queue automatically after 3 seconds.

- **AC-phase3-admin-006-07:** Given the live-updates hook on the detail page (post-approve), when status transitions arrive via SSE or polling, then the status strip updates: `approved (cold-signing)` → `broadcasting (tx_hash: <abbrev>)` → `confirming (1/12, 2/12, …)` → `confirmed`. On `failed`, status strip shows red `Failed` with the `failure_message`.

- **AC-phase3-admin-006-08:** Given the destination address shown in the detail page, when the admin clicks the "fresh address" badge (rendered if `destination_is_fresh` is true), then a small explainer popover shows: "This destination has not received any prior transactions from this user." Helps the admin make informed decisions.

- **AC-phase3-admin-006-09:** Given the page renders the explorer links, when chain == 'ethereum', then the link is to `https://sepolia.etherscan.io/address/<addr>`. For Tron: `https://shasta.tronscan.org/#/address/<addr>`. For Solana: `https://explorer.solana.com/address/<addr>?cluster=devnet`. Links open in new tab with `rel="noopener noreferrer"`.

- **AC-phase3-admin-006-10:** Given Playwright E2E test runs, when admin logs in, navigates to queue, opens a tx detail, clicks approve with TOTP, observes status strip transitions to confirmed, then the test passes against an Anvil-backed Ethereum tx.

---

## Out of Scope

- Multi-tx batch approve: V2.
- Admin chat / notes per applicant: V2.
- Audit log of admin's approval actions surfaced in this UI (visible separately in admin-008 audit timeline): V2 here.
- Customizable queue layouts / saved filters: V2.

---

## Dependencies

- **Code dependencies:** `phase3-admin-004` (the endpoints), `phase1-admin-002` (admin shell + TOTP), `phase1-admin-003` (design system).
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Frontend component tests:** queue renders rows correctly, filters refetch; detail page columns render; TOTP modal opens/closes; approve / reject actions fire the right API calls. Vitest + Testing Library. Covers AC-01, AC-03, AC-04, AC-05.
- [ ] **Frontend hook tests:** `use-withdrawal-live` hook subscribes to SSE channel, falls back to polling on disconnect, handles status transitions. Covers AC-02, AC-07.
- [ ] **E2E:** `tests/e2e/admin-withdrawal-approve.spec.ts` — full admin approval flow against Anvil. Covers AC-10. Includes the race scenario (AC-06) by simulating two admin sessions trying to approve simultaneously (one wins; the other gets the 409 toast).

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] Frontend coverage gate (~70% on this brief's components).
- [ ] `tsc --noEmit` passes.
- [ ] Eslint + Prettier clean.
- [ ] Live-updates verified: opening two admin browser tabs, approve in one, the other tab updates via SSE within 2 seconds.
- [ ] Single PR. Conventional commit: `feat(admin): withdrawal approval queue UI [phase3-admin-006]`.

---

## Implementation Notes

- SSE channel reuse: phase2-notifications-001 already exposes a per-admin SSE endpoint for notifications. Extend the channel to multiplex `transactions.RoutedToAdmin` and `transactions.*` status update events alongside user-facing notifications. The admin's SSE subscription filters for events relevant to admin views.
- The status strip component should be reusable — it's used for the user-facing send confirmation UX too (in phase2-web-007). If Phase 2's component is reusable, import it. Otherwise extract here and refactor in V2.
- The "fresh address" badge rendering is a small ux hint. The data comes from admin-004's `destination_is_fresh` field (computed in detail endpoint). The popover uses the design system's existing `Tooltip` primitive.
- Polling fallback: if SSE disconnects (network blip), fall back to polling `GET /admin/api/v1/withdrawals/{id}` every 2s for 30s, then back-off to 10s. SSE reconnect attempts in parallel.
- Don't render destination addresses in full in the queue view — they're long; truncate with click-to-copy. The detail view shows full address.

---

## Risk / Friction

- The race-condition path (AC-06) is rare in practice (two admins reviewing same tx simultaneously) but should be handled cleanly. Test by mocking a 409 response.
- SSE multiplexing channels: care must be taken not to leak admin-context events to user-context SSE connections. The notifications channel must filter by `actor_type` of the subscriber. Phase 2's notifications-001 should already enforce this via auth context — verify.
- The status strip's "Cold-signing… → Broadcasting…" transitions are aspirational in the sense that the server-side `approved` status is brief (sub-second). The UX shows the steps to make the system feel intentional. If the transition from `approved` to `broadcasting` is faster than the animation, just snap forward — don't artificially delay.
- Sepolia/Shasta/Devnet explorer URLs must be configurable per deploy env (testnet ≠ mainnet). Read from env vars exposed to the frontend at build time.
- Reject reason is stored verbatim — admins should be careful what they write. The text is shown to other admins (and stored in audit). User-facing notifications about rejection don't include the reason text by default (V2 polish: opt-in disclosure).
