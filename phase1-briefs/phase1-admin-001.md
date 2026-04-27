---
id: phase1-admin-001
phase: 1
context: admin
title: Admin SPA bootstrap (separate Vite app)
complexity: S
sdd_mode: lightweight
estimated_hours: 4
state: in_progress
depends_on: []
blocks:
- phase1-admin-002
- phase1-admin-003
touches_adrs: []
ac_count: 8
---

# Brief: phase1-admin-001 — Admin SPA bootstrap


## Title

Admin SPA bootstrap (separate Vite app)

## Context

The admin surface is a separate React SPA, deployed at `admin.vaultchain.io` (or a subdomain decided at deploy time). The architecture (Section 2) puts admin in its own bounded context that is delivery-only — it does not own a domain, it consumes read-views and a few mutating actions atop existing contexts (KYC, Custody, Ledger, Transactions). Mirror that on the frontend: a separate Vite project under `apps/admin/`, separate `package.json` workspace member, separate build artifact, separate deploy. Sharing the auth cookie domain with the user app is acceptable because the backend keys sessions with `actor_type='admin'` distinct from `actor_type='user'`, and admin endpoints live under `/admin/api/v1/...` with their own middleware.

The admin frontend is intentionally minimal in styling — utilitarian, dense, designed to read at glance for someone reviewing 50 KYC applicants in a session. It does NOT mirror the user-facing design system one-to-one. It uses the same `tokens.css` for colors/typography (so light/dark works) but with denser layouts (table-heavy, tabbed views, fewer empty-state niceties). There is no design refinement spec for admin (only `claude-design-spec.md` mentions admin in passing) — so this brief sets the visual baseline: a left sidebar with sections (Dashboard, Applicants, Transactions, Withdrawals, Users, Audit), a top header with the admin's name + logout, and a main content area. shadcn-ui components (Table, Dialog, Tabs, Card) are heavily used. No exotic UI work; functional > beautiful.

This brief delivers ONLY the bootstrapped Vite app with routing scaffolding and an unauthenticated landing page that says "Admin login" with an email + password form (the form is wired in `admin-002`, this brief just renders the placeholder layout). All admin-specific routes (`/dashboard`, `/applicants`, `/withdrawals`, etc.) are stubbed as "Coming in Phase 3" placeholders for now — Phase 1's admin scope is just the shell + auth.

---

## Architecture pointers

- **Layer:** delivery (frontend) only — no backend touched.
- **Packages touched:** new package `apps/admin/` with `package.json`, `vite.config.ts`, `tsconfig.json`, `tailwind.config.ts`, `postcss.config.cjs`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/routes/login.tsx` (placeholder), `src/routes/dashboard.tsx` (placeholder), `src/components/admin-shell/`.
- **Reads / writes:** none (this brief).
- **Events / migrations:** none.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase1-admin-001-01:** Given the monorepo at `apps/admin/`, when `pnpm --filter admin dev` is run, then a Vite dev server starts on port 5174 (distinct from `web`'s 5173), Tailwind compiles, the design tokens from `design/tokens.css` are imported into `apps/admin/src/index.css`, and the browser shows the admin login placeholder page on `/`.

- **AC-phase1-admin-001-02:** Given the monorepo at `apps/admin/`, when `pnpm --filter admin build` is run, then a production bundle is emitted to `apps/admin/dist/` with hashed asset filenames, no errors, no warnings about unused code-splitting that would surprise a deploy reviewer.

- **AC-phase1-admin-001-03:** Given the admin SPA is loaded, when any unauthenticated route is visited, then the layout is the `AdminShellEmpty` (no sidebar, just centered card on a neutral background) — used for the login screen. Authenticated routes (added in admin-002) use `AdminShellAuthed` with sidebar + header. Both shells live under `src/components/admin-shell/`.

- **AC-phase1-admin-001-04:** Given the admin SPA is built, when inspecting the bundle, then it is a separate artifact from `web/`, with its own entrypoint, its own `index.html`, and no shared runtime code beyond what tree-shakes naturally from `pnpm` workspace packages. The two SPAs do not share React Router instances or Zustand stores.

- **AC-phase1-admin-001-05:** Given the admin login placeholder page is rendered, when viewed, then it shows a centered card titled "VaultChain Admin" with a subdued color palette, an email input, a password input, and a "Sign in" button. The button is disabled (admin-002 wires it). The page also shows a tiny footer line: "Admin access · audited · all actions logged."

- **AC-phase1-admin-001-06:** Given the admin SPA references shared design tokens, when the user toggles the prefers-color-scheme system setting, then the admin SPA respects it (light/dark) — the admin app does not have a theme toggle in V1, system preference is the single signal.

- **AC-phase1-admin-001-07:** Given a route URL is invalid in the admin SPA, when matched, then a 404 page renders with "Page not found" + a link back to `/`.

- **AC-phase1-admin-001-08:** Given the workspace `pnpm-workspace.yaml`, when `apps/admin` is added, then it is correctly picked up: `pnpm install` resolves dependencies for both `web/` and `apps/admin/`, `pnpm --filter admin <cmd>` works, and the root `package.json` `scripts.dev` runs both apps concurrently (using `concurrently` or `npm-run-all`).

---

## Out of Scope

- Admin auth API wiring: `phase1-admin-002`.
- Admin dashboard content: `phase1-admin-003`.
- KYC review queue, withdrawal queue, audit log viewer, user management: Phase 3 admin briefs.
- shadcn-ui components beyond the bare minimum needed for the login placeholder: added incrementally per brief.
- Admin-specific design refinement: not budgeted for V1; functional UI is the bar.
- Real domain isolation (separate ASGI app for admin): explicit non-goal per architecture Section 2.

---

## Dependencies

- **Code dependencies:** none (parallels web-001).
- **Data dependencies:** none.
- **External dependencies:** Vite 5+, React 18, react-router-dom v6, Tailwind 3.4+, shadcn-ui (only the components installed when needed). The shared `tokens.css` lives in a workspace package `packages/design-tokens/` (or copied — the choice is made in this brief; recommend a workspace package so both SPAs reference one source of truth).

---

## Test Coverage Required

- [ ] **Vitest unit tests:** `apps/admin/tests/unit/admin-shell.test.tsx` — renders both `AdminShellEmpty` and `AdminShellAuthed` and asserts structure differences. Covers AC-03.
- [ ] **Smoke build check:** CI step `pnpm --filter admin build` must pass; this is a CI guarantee, not a Vitest test, but called out.

> Lightweight mode. No domain/property/adapter/contract/E2E tests in this brief.

---

## Done Definition

- [ ] All ACs verified.
- [ ] `pnpm --filter admin tsc --noEmit` passes.
- [ ] `pnpm --filter admin lint` passes.
- [ ] `pnpm --filter admin build` produces `dist/` cleanly.
- [ ] `pnpm-workspace.yaml` updated.
- [ ] No new ADR.
- [ ] Single PR. Conventional commit: `feat(admin): bootstrap admin SPA [phase1-admin-001]`.
- [ ] PR description shows screenshots of the login placeholder in light + dark mode.

---

## Implementation Notes

- Decide upfront whether `tokens.css` is duplicated or shared via a workspace package. Recommend the workspace package (`packages/design-tokens/tokens.css` + tiny `package.json` exposing the file), and have both `web/` and `apps/admin/` import from it. This avoids drift.
- The admin SPA does NOT need TanStack Query in this brief — admin-002 introduces it. Bare React + react-router is enough.
- Use a different favicon for the admin app — visual differentiation when both tabs are open in browser. A simple "A" mark, or a recolored VaultChain logo.
- Set the `<title>` to "VaultChain Admin" so browser tabs and history are obviously distinguishable from the user app.
- Do not pre-build sidebar nav items for routes not yet implemented — empty sidebar is fine; admin-003 fills it.

---

## Risk / Friction

- Sharing the cookie domain (`.vaultchain.io`) means the browser can in theory see admin cookies on the user app domain. The HttpOnly + path-restricted (`/admin/api/v1/...` for refresh) settings mitigate, but document this trade-off in the deploy brief (admin-001 is just the SPA shell, deploy-001 owns the cookie-domain decision).
- The admin SPA uses a separate Vite port for dev; ensure no team scripts hardcode 5173.
- Workspace tooling (turbo / nx) is overkill for two SPAs; pnpm workspaces + concurrently is sufficient. Don't add turbo just because.
