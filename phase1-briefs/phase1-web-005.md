---
ac_count: 8
blocks:
- phase1-web-004
- phase1-deploy-001
complexity: M
context: web
depends_on:
- phase1-web-001
- phase1-web-002
- phase1-identity-005
estimated_hours: 4
id: phase1-web-005
phase: 1
sdd_mode: lightweight
state: merged
title: App shell, routing, session bootstrap
touches_adrs: []
---

# Brief: phase1-web-005 — App shell, routing, session bootstrap


## Context

The user-facing SPA needs a single, opinionated shell that owns layout, navigation, theme, and the "is the user authenticated?" decision before any route renders. The design refinements (`design/app/shell.jsx`) lock in two layouts: a desktop layout with a left sidebar (logo, primary nav, user-card pinned bottom) plus a top header (page title, search-stub, "Ask AI"-stub), and a mobile layout with a top header (avatar, page title, settings-icon) plus a bottom tab bar (5 of the 7 nav items: Home, Send, Contacts, Activity, Assistant). Settings on mobile is reachable from the header icon, Receive on mobile is reachable from inside Send/Receive flows. This split is intentional and matches the design — do not flatten it.

Session bootstrap is the second concern of this brief. On every cold load (and on tab focus after long idle), the shell calls `GET /api/v1/auth/me`. If 200 → render the authed shell with the user payload in a Zustand store; if 401 with `code: identity.session_expired` → redirect to `/auth/login`; if 401 with `code: identity.totp_required` → redirect to `/auth/totp`; if network error → show the `NetworkFailure` edge component from `empty-states.jsx` with a retry button. The "Validating session…" splash renders for at least 250ms to avoid flicker, same pattern as the magic-link verify state.

Routing is deliberately kept tight: a small set of routes (`/dashboard`, `/send`, `/receive`, `/contacts`, `/history`, `/ai`, `/settings`, `/tx/:id`, plus the `/auth/*` family from web-003) using React Router v6. Routes split into two groups: pre-auth routes (rendered without the shell) and authed routes (rendered inside the shell with session-bootstrap guarding). The `/dashboard` route is the post-login destination; the actual dashboard content is a separate brief (web-004), so this brief renders only a placeholder with the page title.

---

## Architecture pointers

- **Layer:** delivery (frontend) only — no backend touched.
- **Packages touched:** `web/src/shell/`, `web/src/routes/`, `web/src/auth/session.ts`, `web/src/store/userStore.ts`, `web/src/components/edge/` (for NetworkFailure / Provisioning / Maintenance reused at app boundary).
- **Reads:** `GET /api/v1/auth/me`.
- **Writes:** none (this brief).
- **Events:** none.
- **Ports / adapters:** uses `apiFetch` from web-002.
- **Migrations:** none.
- **OpenAPI:** consumes `GET /api/v1/auth/me` defined in identity-005.

---

## Acceptance Criteria

- **AC-phase1-web-005-01:** Given the SPA loads at any authed route URL (`/dashboard`, `/send`, etc.), when the shell mounts, then it calls `GET /api/v1/auth/me` exactly once before rendering route content. While the call is in flight, a centered "Validating session…" splash renders (minimum 250ms to avoid flicker). On 200 response, the user payload is written to the Zustand `userStore` and route content renders. On 401 `identity.session_expired` or `identity.totp_required`, the SPA navigates to `/auth/login` or `/auth/totp` respectively, preserving the original target URL in `?redirect=` for post-login navigation. On network/5xx error, render the `NetworkFailure` edge with a Retry button that re-issues the call.

- **AC-phase1-web-005-02:** Given the user is authenticated on a desktop viewport (≥md breakpoint), when any authed route renders, then the `DesktopShell` from `shell.jsx` is the layout: left sidebar (240px wide, collapses below md) with VaultChain brand at top, primary nav (Home, Send, Receive, Contacts, Activity, Assistant, Settings — 7 items, Assistant gets the `ai` accent class), user-card pinned bottom (avatar + name + tier badge from `userStore`), and main area with a top header showing the active route's title and the two stub buttons (Search, Ask AI). The active nav item gets `.on` class. Clicking a nav item calls React Router's `navigate()`.

- **AC-phase1-web-005-03:** Given the user is authenticated on a mobile viewport (<md breakpoint), when any authed route renders, then the `MobileShell` is the layout: top header (avatar left, page title center, settings-cog right), main body (scrollable), and bottom tab bar with exactly the 5 mobile tabs (`dashboard, send, contacts, history, ai`) per `MOB_TABS` constant. Hidden routes (Receive, Settings) are still navigable but not in the tab bar. Tap targets ≥44px. Active tab gets `.on`.

- **AC-phase1-web-005-04:** Given the user toggles theme (light ↔ dark) via the toggle in Settings (which is a placeholder in this brief, real screen in Phase 4), when toggled, then the entire SPA re-themes via `data-theme` on the root, the choice persists to `localStorage` under key `vc-theme`, and the `prefers-color-scheme` media query is the default if no explicit choice is stored. Pre-auth screens (auth from web-003) also respect this.

- **AC-phase1-web-005-05:** Given a 401 response on any authenticated request after the initial bootstrap (e.g. session expired mid-session), when the global response interceptor in `apiFetch` (web-002) catches it, then it dispatches a session-expired event. The shell subscribes to this event and navigates to `/auth/login?redirect=<currentPath>`, clearing the `userStore`. This works without a full page reload — the SPA stays mounted, only the route changes.

- **AC-phase1-web-005-06:** Given a route URL is invalid (e.g. `/nonexistent`), when matched, then a 404 page renders inside the shell (if authed) or stand-alone (if pre-auth) with a clear "page not found" message + a button back to `/dashboard` (or `/auth/login`).

- **AC-phase1-web-005-07:** Given the shell is mounted, when the user idle-tabs for >10 minutes and returns, then on `visibilitychange → visible`, the shell silently re-validates session by calling `/api/v1/auth/me` again. On 200, no UI change. On 401, follow AC-05 path. This keeps the cookie-session and the SPA's perceived session in sync.

- **AC-phase1-web-005-08:** Given the SPA renders the `/dashboard` route in this brief, when no other brief has yet built the dashboard content, then the route shows a placeholder ("Dashboard — coming in next brief") inside the shell. This is a deliberate stub; web-004 replaces it.

---

## Out of Scope

- Real dashboard content: phase1-web-004.
- Search functionality (the header button is a stub): V2.
- "Ask AI" header button is a stub navigating to `/ai` route which itself stays a placeholder until Phase 4.
- Active session list / "log out other devices": Phase 3.
- Deep-linking inside Send/Receive flows beyond the route URL: Phase 2 / Phase 3.
- Service worker / offline mode: deferred indefinitely.
- Mobile pull-to-refresh: V2.

---

## Dependencies

- **Code dependencies:** `phase1-web-001` (Vite, Tailwind, design tokens, base SPA), `phase1-web-002` (apiFetch, TanStack Query, error boundary).
- **Data dependencies:** none on the frontend; backend `/auth/me` from identity-005 must be deployed for E2E.
- **External dependencies:** `react-router-dom` v6, `zustand`. No new build tooling.

---

## Test Coverage Required

- [ ] **Vitest unit tests:** `web/tests/unit/session-bootstrap.test.tsx` — covers AC-01 (mocking `apiFetch` to return 200 / 401 / network-error), `web/tests/unit/shell-layout.test.tsx` — covers AC-02 / AC-03 (renders DesktopShell vs MobileShell based on `matchMedia`), `web/tests/unit/theme-toggle.test.tsx` — covers AC-04.
- [ ] **E2E (Playwright):** extend `web/tests/e2e/auth-signup-to-dashboard.spec.ts` from web-003 to assert the dashboard placeholder is rendered inside the shell after TOTP success — confirms shell mounts post-auth correctly. No new spec file.

> Lightweight mode: domain/property/adapter/contract/locust categories omitted.

---

## Done Definition

- [ ] All ACs verified by named tests or PR-attached screenshots (AC-02, AC-03, AC-06 may rely on screenshots).
- [ ] `pnpm --filter web tsc --noEmit` passes.
- [ ] `pnpm --filter web lint` passes.
- [ ] No hardcoded color values; all token-based.
- [ ] No new ADR.
- [ ] Single PR. Conventional commit: `feat(web): app shell, routing, session bootstrap [phase1-web-005]`.
- [ ] PR description shows desktop + mobile screenshots of each authed route's empty shell, plus the validating-session splash.
- [ ] Lighthouse / a11y: keyboard-only nav can reach every nav item, focus rings visible, ARIA labels on icon-only buttons.

---

## Implementation Notes

- The 250ms minimum splash duration is achieved via `Promise.all([fetch, sleep(250)])` — common pattern, do not skimp on it.
- `userStore` (Zustand): `{ user: User | null, status: 'idle' | 'loading' | 'authenticated' | 'unauthenticated' | 'error', actions }`. Hydrate on bootstrap; clear on 401 interceptor.
- The 401 event-bus pattern: tiny `EventTarget`-based pubsub in `web/src/auth/session.ts`, no new dependency. The `apiFetch` interceptor `dispatchEvent`s a `'session:expired'` event with the offending response code.
- React Router v6: use `createBrowserRouter` with route config. Wrap authed routes in a `RequireAuth` element that reads `userStore` and redirects on `unauthenticated`.
- The `/auth/*` routes from web-003 must NOT mount inside the shell — they live in their own route group with their own minimal layout.
- The theme toggle wires up to a CSS-variable swap on the `<html>` element via `data-theme="light|dark"`; no per-component theme prop.
- Match the design's `data-theme` placement (on `desk-inner` / `mob-frame` in the prototype, but for the real app put it on `<html>`; the prototype simulates a frame).

---

## Risk / Friction

- The `matchMedia` SSR concern doesn't apply here (Vite SPA, no SSR), but ensure the `useMediaQuery` hook has a sensible initial render to avoid hydration-style flashes.
- React-Router's `useNavigate` outside of a Route can be a gotcha — confine session-expired navigation logic to a top-level `Layout` component that always sits inside `RouterProvider`.
- The lightweight SDD mode means full a11y / responsive matrix testing is owner-attested via screenshots in the PR. If reviewers want stricter, add `@axe-core/playwright` in a follow-up.
