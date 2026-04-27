---
ac_count: 1
blocks:
- phase1-deploy-001
complexity: L
context: web
depends_on:
- phase1-web-002
- phase1-identity-005
estimated_hours: 4
id: phase1-web-003
phase: 1
sdd_mode: lightweight
state: ready
title: Auth screens (signup, magic-link sent, login, TOTP enrollment)
touches_adrs: []
---

# Brief phase1-web-003: Auth screens (signup, magic-link sent, login, TOTP enrollment)


## Context

This brief implements the user-facing authentication screens per the design refinement in `docs/design/refinements/auth-onboarding/` and the state machine in `auth-onboarding-notes.md`. The visual reference is `auth.jsx`, `enrollment.jsx`, `login.jsx` from the design artifacts; the React port reuses the same JSX structure with TanStack Query hooks bound to the backend endpoints from identity-005.

Screens: landing, signup email entry, "check your email", magic-link landing (validating / first-time / returning / expired states), TOTP enrollment wizard (4 steps: explain, scan QR, verify code, save backup codes), TOTP login challenge (with backup-code fallback), demo-mode banner stub (full demo flow is Phase 4).

The state machine drives the routing structure: each state has a route or a sub-route under `/auth/*`. Transitions follow the canonical diagram exactly.

---

## Architecture pointers

- **Layer(s):** `app/` (routes), `features/auth/` (hooks + components)
- **Affected packages:** `web/src/app/auth/`, `web/src/features/auth/`
- **Reads from:** identity-005 endpoints via `apiFetch`
- **Writes to:** none locally; mutations go through the backend
- **Publishes events:** `none`
- **Subscribes to events:** `none`
- **DB migrations required:** `no`
- **OpenAPI surface change:** `no`

---

## Acceptance Criteria

- **AC-phase1-web-003-01:** Given the landing screen at `/`, when rendered, then it shows the hero one-liner from `00-product-identity.md`, three feature highlights (multi-chain custody, KYC compliance, AI assistant), and two CTAs ("Sign up" / "Try as demo user"). The "Try as demo user" button is wired to navigate but the demo flow itself is stubbed (alert "Demo coming in Phase 4" — explicit, not silent).
- **AC-phase1-web-003-02:** Given the signup screen at `/auth/signup`, when an email is typed, then "Continue" enables only on a valid email regex; on submit, calls `POST /api/v1/auth/request` with mode=signup and idempotency-key; on 202 navigates to `/auth/sent?email=<email>&mode=signup`; on 4xx error envelope, displays inline error using `.input.is-error` styling per `auth.css`.
- **AC-phase1-web-003-03:** Given the "check your email" screen at `/auth/sent`, when rendered, then it shows the email passed via query param, "Resend link" button (disabled for 30s after each send with countdown), "Use a different email" link → back to /auth/signup, and the "Link sent, but not received?" hint (open by default per `auth-onboarding-notes.md`).
- **AC-phase1-web-003-04:** Given the magic-link landing at `/auth/verify?token=...&mode=...`, when loaded, then it shows the "Validating…" state and calls `POST /api/v1/auth/verify`. On success branches:
  - First-time signup: store `pre_totp_token` in memory (sessionStorage) and navigate to `/auth/enroll`.
  - Returning login: store `pre_totp_token` and navigate to `/auth/totp`.
  - On expired/used/invalid: show error state with "Request a new link" CTA → back to /auth/signup or /auth/login.
- **AC-phase1-web-003-05:** Given `/auth/enroll`, when loaded, then the 4-step wizard from `enrollment.jsx` renders: step 1 (explain + recommended apps), step 2 (QR + manual base32 secret with tap-to-copy), step 3 (6-digit TOTP input), step 4 (10 backup codes with "Download as txt" + "I've saved them"). Step 3 calls `POST /api/v1/auth/totp/enroll` (one-shot to fetch QR data) on entering step 2, then `POST /api/v1/auth/totp/enroll/confirm` on step-3 submit. On 3 failures at step 3, restart the wizard from step 2 (per state machine).
- **AC-phase1-web-003-06:** Given `/auth/totp` (returning user), when loaded, then a centered card on desktop (full-screen on mobile <md breakpoint) renders a 6-digit input + "Use a backup code instead" link + lockout messaging on 5+ failures. Uses the visual pattern from `login.jsx`. Submission calls `POST /api/v1/auth/totp/verify`. On `attempts_remaining > 0`, render attempts. On 403 `identity.user_locked`, show the locked screen with countdown computed from `details.locked_until`.
- **AC-phase1-web-003-07:** Given a successful TOTP enroll-confirm or login verify, when the response arrives (cookies are set by the backend), then navigate to `/dashboard` (which is the next brief's surface — for THIS brief, navigation works but the dashboard route's content is the placeholder shell from web-001). The frontend has no "session bootstrap" concern — the cookies are the session.
- **AC-phase1-web-003-08:** Given mobile viewport (375px), when each screen above is rendered, then it is mobile-first per the design tokens; nothing horizontal-scrolls; tap targets are ≥44px.
- **AC-phase1-web-003-09:** Given the auth screens, when the user toggles theme, then both light and dark modes render correctly using design tokens (no hardcoded colors). The shared toggle component lives in app shell from web-005, but is also accessible on these pre-auth screens.

---

## Out of Scope

- Real "Try as demo user" flow: Phase 4 brief.
- "New device detected" branch: Phase 4 polish.
- Account-recovery via support: docs link only (placeholder URL pointing to `/docs/account-recovery`, page itself is a Phase 4 deliverable).
- Email-disposable-blocking: backend concern, deferred.
- Marketing landing variants: V2.
- E2E test for entire happy path: included here as one Playwright spec (see Test Coverage).

---

## Dependencies

- **Code dependencies:** `phase1-web-002` for apiFetch and types; `phase1-identity-005` for endpoints.
- **Data dependencies:** none on the frontend; backend migrations from identity-001/003 must be applied for E2E.
- **External dependencies:** `react-hook-form` + `zod` for form validation; `qrcode` library for client-side QR rendering (the backend returns the otpauth URI, the client renders the QR pixels).

---

## Test Coverage Required

- [ ] **Vitest unit tests:** `web/tests/unit/auth-signup-form.test.tsx`, `auth-resend-countdown.test.tsx`, `enrollment-wizard.test.tsx`, `totp-input.test.tsx`
  - covers AC-02, -03, -05 (component-level)
  - test cases: form validation, countdown decrements, wizard step navigation, TOTP input only-digits constraint, backup-codes download generates txt
- [ ] **E2E (Playwright):** `web/tests/e2e/auth-signup-to-dashboard.spec.ts`
  - covers AC-02 through -07 end-to-end against running backend
  - one critical journey (the `signup-to-dashboard` from architecture Section 5 Layer 5 list)
  - depends on the E2E harness which spins up backend + frontend with stubs (the magic link is captured from the backend's `ConsoleEmailSender` log via a fixture-helper that polls the log file).

---

## Done Definition

- [ ] All ACs verified by tests or manual smoke (with screenshots in PR).
- [ ] `pnpm --filter web tsc --noEmit` passes.
- [ ] `pnpm --filter web lint` passes.
- [ ] No hardcoded color values; all token-based.
- [ ] All forms use `react-hook-form` + `zod` schemas; `zod` schemas align with backend Pydantic shapes (verified by importing types from `shared-types`).
- [ ] No new ADR.
- [ ] Single PR. Conventional commit: `feat(web): auth screens (signup, magic-link, enrollment, login) [phase1-web-003]`.
- [ ] Lighthouse / a11y: keyboard nav works on every screen; focus rings visible; ARIA labels on icons.

---

## Implementation Notes

- The 30s "Resend" countdown lives in client state (Zustand store, key `auth.resendCooldownEndAt: number | null`). Not persisted across reloads — a reload resets the countdown, which is acceptable.
- `pre_totp_token` lives in `sessionStorage` (not `localStorage`) so it dies with the tab. This aligns with the 5-min TTL on the backend.
- Backup codes "Download as txt": construct a Blob client-side with the codes, one per line, with a header comment, and trigger download via `<a download>`. No server round-trip.
- QR rendering: use `qrcode` npm package; render to an SVG (not canvas — sharper at any zoom level).
- The "Validating…" state should render for at least 250ms even on a fast resolution, otherwise the flicker is jarring. Use a minimum-duration helper.
- Reuse the design `*-host.jsx` files as the visual checklist — port screen by screen, verifying against `05_Auth_Onboarding.html` rendered.

---

## Risk / Friction

- The E2E test polling the backend's console-email log is fragile — concurrent tests, log file ordering. Document the limitation in the test file and acknowledge that this is a Phase-1-grade harness that the email-provider brief (Phase 2) will replace with a proper webhook-mock or test-mailbox.
- Mobile keyboard handling for the 6-digit TOTP input: ensure `inputmode="numeric"` and `autocomplete="one-time-code"` (so iOS / Android suggest the OTP from SMS — though SMS isn't used here, the autofill from authenticator-app integration is becoming available).
- The auth flow has more states (12+) than the dashboard. The lightweight SDD mode means we don't fill `Test Coverage Required` exhaustively — but the E2E covers the core journey. Frontend-only edge cases (404 on token, network drop mid-validate) are smoke-tested manually with PR screenshots.
