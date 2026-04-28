---
id: phase1-admin-003
phase: 1
context: admin
title: Admin dashboard skeleton (empty queues)
complexity: S
sdd_mode: lightweight
estimated_hours: 4
state: merged
depends_on:
- phase1-admin-001
- phase1-admin-002a
- phase1-admin-002b
blocks:
- phase1-deploy-001
touches_adrs: []
ac_count: 3
---

# Brief: phase1-admin-003 — Admin dashboard skeleton (empty queues)


## Title

Admin dashboard skeleton (empty queues)

## Context

Phase 1 ends with a deployable admin SPA where an admin can sign in and land on a "real" dashboard — even if every queue is empty because the underlying contexts (KYC, Custody, Withdrawals, Audit) don't exist yet. This brief delivers that landing page: a four-card overview ("KYC Queue: 0," "Withdrawals Pending: 0," "Recent Transactions: 0," "Audit Events Today: 0") plus a sidebar nav and the authed-shell wrapper from `admin-001`. Each card has an "Open queue" button that navigates to a placeholder route (`/applicants`, `/withdrawals`, etc.) which renders "Coming in Phase 3" — same explicit-stub pattern used in the user app.

This brief does NOT call any backend endpoints — there are no admin queue endpoints in Phase 1. The "0" counts are hardcoded. In Phase 2 / 3, brief-by-brief, each card switches from hardcoded to a real `useQueueCountQuery()` hook against `/admin/api/v1/<resource>/count`. The structure (card, count, label, action button) is the stable contract; only the data source changes.

The header shows the admin's email + a logout button. Logout calls `POST /admin/api/v1/auth/logout` (from admin-002) and redirects to `/login`. The sidebar nav (now visible because the user is authed) shows: Dashboard (active), Applicants, Transactions, Withdrawals, Users, Audit. All but Dashboard route to placeholder pages.

---

## Architecture pointers

- **Layer:** delivery (admin frontend) only.
- **Packages touched:** `apps/admin/src/routes/dashboard.tsx`, `apps/admin/src/components/queue-card/`, `apps/admin/src/auth/sessionGuard.tsx`, `apps/admin/src/routes/_placeholders.tsx`.
- **Reads:** `GET /admin/api/v1/auth/me` (from admin-002) for session validation and admin email display. No queue data calls.
- **Writes:** `POST /admin/api/v1/auth/logout` on logout button.
- **Events / migrations / OpenAPI:** none new.

---

## Acceptance Criteria

- **AC-phase1-admin-003-01:** Given an authenticated admin lands on `/` (or `/dashboard`), when the SPA mounts, then the session bootstrap calls `GET /admin/api/v1/auth/me`. On 200, the `AdminShellAuthed` from admin-001 renders with the admin's email in the header. On 401, redirect to `/login` (preserving original URL via `?redirect=`). The same minimum-250ms splash pattern applies for visual stability.

- **AC-phase1-admin-003-02:** Given the authed shell renders, when sidebar nav is shown, then it lists exactly: Dashboard (active for `/`), Applicants (`/applicants`), Transactions (`/transactions`), Withdrawals (`/withdrawals`), Users (`/users`), Audit (`/audit`). Active route gets a visual highlight. Clicking a non-Dashboard item navigates to a placeholder page rendering "Coming in Phase 3" with the queue name.

- **AC-phase1-admin-003-03:** Given the dashboard route renders, when content loads, then a 4-card grid (2x2 on desktop, single column on mobile) shows: KYC Queue (count: 0, "Open queue" → `/applicants`), Withdrawals Pending (count: 0, "Open queue" → `/withdrawals`), Recent Transactions (count: 0, "Open list" → `/transactions`), Audit Events Today (count: 0, "Open log" → `/audit`). Cards are visually consistent and ready to bind to real data later.

- **AC-phase1-admin-003-04:** Given the admin is on any page, when they click the logout button in the header, then `POST /admin/api/v1/auth/logout` is called, the SPA clears its admin-userStore, and redirects to `/login`. On logout error (network), the SPA still clears local state and redirects (defensive — an admin who clicks logout expects to be logged out regardless).

- **AC-phase1-admin-003-05:** Given a route URL is invalid in the admin SPA, when matched, then a 404 page renders inside the authed shell (if authed) or the empty shell (if pre-auth) — same pattern as web-005's 404.

- **AC-phase1-admin-003-06:** Given the admin SPA references shared design tokens, when light/dark system preference is set, then the dashboard / cards / sidebar all theme correctly with no hardcoded colors. Verified by screenshot in PR.

- **AC-phase1-admin-003-07:** Given the dashboard renders, when an admin's `last_login_at` is available from `/auth/me`, then the header (or a small subtitle on the dashboard) shows "Last sign in: <timestamp>" — a security-conscious touch admins value.

---

## Out of Scope

- Real queue data: each Phase 2/3 admin brief switches one card to live data.
- KYC review workflow, withdrawal approval workflow: Phase 3.
- User management screen: Phase 3.
- Audit log viewer: Phase 3.
- Per-action audit logging trace inside the SPA: Phase 3 audit context.
- Multi-admin presence indicator (who else is online): not budgeted.
- Cmd-K / search: V2.

---

## Dependencies

- **Code dependencies:** `phase1-admin-001` (shell + routing), `phase1-admin-002a` (login + session + /me + logout endpoints), `phase1-admin-002b` (login/totp routes that produce a hydrated session before the dashboard renders).
- **Data dependencies:** none.
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Vitest unit tests:** `apps/admin/tests/unit/dashboard.test.tsx` — renders dashboard with a stubbed admin-userStore, asserts 4 cards render with the labels and zero counts, asserts navigation handlers wire correctly (mocks `useNavigate`). Covers AC-02, AC-03.
- [ ] **Vitest unit tests:** `apps/admin/tests/unit/session-guard.test.tsx` — covers AC-01 (200 / 401 / network branches).

> Lightweight mode. No E2E for admin in Phase 1; admin E2E starts in Phase 3 once real workflows exist.

---

## Done Definition

- [ ] All ACs verified by tests or PR screenshots.
- [ ] `pnpm --filter admin tsc --noEmit` passes.
- [ ] `pnpm --filter admin lint` passes.
- [ ] No hardcoded color values; all token-based.
- [ ] No new ADR.
- [ ] Single PR. Conventional commit: `feat(admin): dashboard skeleton with empty queue cards [phase1-admin-003]`.
- [ ] PR description shows desktop screenshot in light mode + mobile screenshot — proves the responsive layout works.

---

## Implementation Notes

- The `QueueCard` component takes `{ label, count, href, openLabel }` props. Hardcoded `count={0}` in Phase 1; in Phase 2/3 each card receives `count={data?.count ?? 0}` from a TanStack Query hook. The component is the stable contract.
- Session guard pattern: a top-level `<RequireAdminAuth>` element wraps all authed routes in the router config — mirrors web-005's `<RequireAuth>` but reads from the admin-userStore and redirects to `/login` (not `/auth/login`).
- Logout: a single button in the header. Use a confirmation `<Dialog>` from shadcn-ui only if the team prefers; not a hard requirement for admins (they expect logout to be a single click — no confirm).
- Avoid copying `userStore` from `web/`. The admin-userStore is its own thing, in its own SPA, with its own state shape (admin schema differs — has `role`, no `tier`).
- Add a tiny "Phase 1 — admin shell" note in the dashboard footer (8px gray text) for the duration of Phase 1, removed in Phase 2 brief that introduces real data. Helps reviewers understand the demo state.

---

## Risk / Friction

- The hardcoded zeros are fine for Phase 1 — but ensure each card has a `data-testid` so the Phase 2/3 brief that wires real data can switch it without touching markup.
- The "Last sign in" timestamp is small but valued by reviewers familiar with security-tooling UIs (Sumsub admin, Stripe Dashboard) — don't skip it. The data is already in `/auth/me` payload from admin-002.
- The placeholder routes ("Coming in Phase 3") are deliberate. Reviewers should see the nav structure but be unsurprised that content is deferred.
