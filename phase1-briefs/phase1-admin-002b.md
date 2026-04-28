---
ac_count: 3
blocks:
- phase1-admin-003
complexity: S
context: admin
depends_on:
- phase1-admin-001
- phase1-admin-002a
estimated_hours: 3
id: phase1-admin-002b
phase: 1
sdd_mode: lightweight
state: ready
title: Admin auth frontend (login + TOTP routes)
touches_adrs: []
---

# Brief: phase1-admin-002b — Admin auth frontend (login + TOTP routes)


## Title

Admin auth frontend (login + TOTP routes)

## Context

This brief delivers the **frontend half** of admin auth, paired with the backend in `phase1-admin-002a`. The admin SPA shell from `admin-001` already renders the routing skeleton and an unauthed `/login` placeholder; this brief turns the placeholder into a real two-step login flow (`/login` → `/totp` → `/dashboard`) wired to the admin auth endpoints from `admin-002a`.

The admin app is a separate Vite app under `apps/admin/`, with its own apiFetch wrapper. The admin's apiFetch instance is distinct from the user web app's: it points at `/admin/api/v1/`, includes `credentials: 'include'`, sends the admin's CSRF header (read from the `admin_csrf` cookie set in AC-002a-03), and surfaces the structured error envelope from `shared-005` so error codes drive inline messages.

There are NO new backend changes here. If a UI bug surfaces a backend contract gap, the fix goes in a follow-up brief, not by widening this one.

---

## Architecture pointers

- **Layer:** delivery (frontend only).
- **Packages touched:**
  - `apps/admin/src/routes/login.tsx` (replace placeholder from admin-001)
  - `apps/admin/src/routes/totp.tsx` (new)
  - `apps/admin/src/auth/apiFetch.ts` (admin-side wrapper)
  - `apps/admin/src/auth/csrf.ts` (read `admin_csrf` cookie, attach `X-CSRF-Token` header)
  - `apps/admin/src/auth/AuthGuard.tsx` (redirect unauthed → `/login`; reuse pattern from admin-001's shell)
- **Reads:** `GET /admin/api/v1/auth/me` to bootstrap the session on app load.
- **Writes:** `POST /admin/api/v1/auth/login`, `POST /admin/api/v1/auth/totp/verify`, `POST /admin/api/v1/auth/logout`.
- **Events:** none directly emitted by frontend.
- **Migrations:** none.
- **OpenAPI:** consumes endpoints already documented by `admin-002a`. No schema changes.

---

## Acceptance Criteria

- **AC-phase1-admin-002b-01:** Given the admin SPA renders `/login`, when an admin submits valid email + password, then `POST /admin/api/v1/auth/login` is called via the admin apiFetch (separate instance from web's; `credentials: 'include'`, attaches `X-Idempotency-Key` and `X-CSRF-Token` headers), and on success the SPA navigates to `/totp` where a 6-digit input renders. On invalid credentials (`401 identity.invalid_credentials`), an inline error message is rendered next to the password input. On a locked account (`403 identity.user_locked`), the message displays "Account locked until <locked_until>" using `details.locked_until` from the error envelope. Field validation: email must match a basic email regex; password is `required` (no client-side length rule — the server is authoritative).

- **AC-phase1-admin-002b-02:** Given the admin SPA is on `/totp` with a valid `pre_totp_token` cookie, when the admin submits a 6-digit code, then `POST /admin/api/v1/auth/totp/verify` is called and on success the SPA navigates to `/dashboard`. On `401 identity.totp_invalid`, the input clears and an inline error renders. On `403 identity.user_locked`, the SPA navigates back to `/login` with the locked-until message preserved across navigation. If the user lands on `/totp` without the pre-totp cookie present (e.g. direct URL navigation, expired token), the SPA redirects to `/login` and renders an info message "Please sign in again."

- **AC-phase1-admin-002b-03:** Given the admin app loads (cold start or refresh), when bootstrapping, then `GET /admin/api/v1/auth/me` is called once via the AuthGuard. On `200`, the user object is hydrated into the admin auth store and routing proceeds; on `401 identity.session_required`, the AuthGuard redirects to `/login` (unless already on `/login` or `/totp`). The same call wires logout: a "Sign out" action invokes `POST /admin/api/v1/auth/logout`, clears the in-memory store, and redirects to `/login`.

---

## Out of Scope

- Backend admin auth (port, adapter, use cases, routes, middleware, seed CLI, migration): `phase1-admin-002a`.
- "Remember this device" / persistent device trust: V2.
- Visual polish beyond the design tokens already shipped by admin-001.
- Password reset UI: V2 (no backend support yet — admin recovery is the seed CLI).
- Admin profile page / change-password UI: V2.

---

## Dependencies

- **Code dependencies:** `phase1-admin-001` (Vite app shell, routing skeleton, design tokens, login placeholder route to replace), `phase1-admin-002a` (the four `/admin/api/v1/auth/` endpoints + admin session cookie scheme + error codes this brief consumes), `phase1-shared-005` (error envelope shape used inline).
- **Data dependencies:** none.
- **External dependencies:** none beyond what admin-001 already pulled in (React, React Router, the design-tokens package).

---

## Test Coverage Required

- [ ] **Component tests (Vitest + RTL):** `apps/admin/src/routes/__tests__/login.test.tsx` — renders the form, submits valid credentials, asserts apiFetch call payload + navigation to `/totp`. Mocks the apiFetch module. Covers AC-01.
- [ ] **Component tests:** `apps/admin/src/routes/__tests__/totp.test.tsx` — renders the input, submits valid code, asserts navigation to `/dashboard`; tests redirect when pre-totp token absent. Covers AC-02.
- [ ] **Component tests:** `apps/admin/src/auth/__tests__/AuthGuard.test.tsx` — `/me` 200 hydrates store; `/me` 401 redirects to `/login`; logout flow. Covers AC-03.
- [ ] **Error-path tests:** for each AC, a dedicated test asserts the inline error message renders for the documented error codes (`identity.invalid_credentials`, `identity.user_locked`, `identity.totp_invalid`, `identity.session_required`).
- [ ] **E2E:** none in Phase 1. End-to-end admin auth E2E is deferred to Phase 3 once the dashboard has real data.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All component tests pass under Vitest.
- [ ] `tsc --noEmit` clean for `apps/admin`.
- [ ] ESLint + Prettier clean.
- [ ] Coverage gate for `apps/admin/src/routes/login.tsx`, `totp.tsx`, `auth/AuthGuard.tsx` ≥ project threshold.
- [ ] Manual smoke test (documented in PR): seed an admin via the CLI from admin-002a → login → totp → dashboard → logout → login again with wrong password → see locked message after 5 attempts.
- [ ] Single PR. Conventional commit: `feat(admin): admin auth frontend (login+totp) [phase1-admin-002b]`.

---

## Implementation Notes

- The admin apiFetch is a **separate module** from `apps/web/src/auth/apiFetch.ts`. Do not import across apps. If you find yourself wanting to share, that's a sign for a future shared package; out of scope here.
- CSRF: read the `admin_csrf` cookie on every mutating request and send it in `X-CSRF-Token`. The `admin_csrf` cookie is intentionally NOT HttpOnly (double-submit pattern), set by `admin-002a`'s AC-03.
- Store the in-memory admin user via the same lightweight store pattern admin-001 introduced (no Redux). Do not persist to localStorage — admin sessions are cookie-bound and short-lived.
- Idempotency: the login POST attaches a `X-Idempotency-Key` (UUID v4 generated client-side per submit). The TOTP verify does NOT need idempotency — replay protection is via single-use of the `pre_totp_token` server-side.
- Routing: `/login` and `/totp` are public; everything else is behind `AuthGuard`. `AuthGuard` is the single redirect choke point — do not scatter redirect logic across components.

---

## Risk / Friction

- Cookie path scoping (`/admin/api/v1/`) means the admin SPA must be served from a path or subdomain that issues requests to that prefix. `phase1-deploy-001` must wire this correctly. If during local dev the admin app runs on a Vite dev server that proxies to the backend, ensure the proxy preserves the cookie domain/path (Vite's default proxy is fine; just verify in the smoke test).
- Inline error messages need to handle both the structured envelope (`{code, message, details}`) and a generic 5xx fallback ("Something went wrong, try again"). Do not swallow unknown codes silently.
- This brief was split off the original `phase1-admin-002` along with the backend half (`phase1-admin-002a`). The split followed operator-selected option 2 from the blocked-state audit on the original brief.
