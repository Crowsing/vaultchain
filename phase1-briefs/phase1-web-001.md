---
ac_count: 2
blocks:
- phase1-web-002
- phase1-web-005
complexity: M
context: web
depends_on: []
estimated_hours: 4
id: phase1-web-001
phase: 1
sdd_mode: lightweight
state: ready
title: Web SPA bootstrap (Vite, Tailwind, design tokens, shadcn)
touches_adrs: []
---

# Brief phase1-web-001: Web SPA bootstrap (Vite, Tailwind, design tokens, shadcn)


## Context

Bootstrap installed Vite + React 19 + TS + Tailwind + shadcn CLI. This brief turns that into a working SPA shell: imports `tokens.css` from `docs/design/tokens.css` into the global stylesheet, configures Tailwind v4 to pick up the design-token CSS variables, sets up the base `App.tsx` with router placeholder, and adds the foundational typography + dark-mode wiring per `tokens.css`. No real screens yet — those land in subsequent web briefs.

The visual proof: running `pnpm --filter web dev` opens a page that renders a styled "VaultChain" heading using the indigo brand color, Inter font, with a working light/dark toggle. That's enough to prove the design system is wired.

The design artifacts are the source of truth: `tokens.css` for variables, the per-feature CSS files (`auth.css`, etc.) imported as needed, and the `*-host.jsx` files as visual references. The React port reads from these — same tokens, same component patterns.

---

## Architecture pointers

- **Layer(s):** `delivery` (frontend; the layer model applies loosely — `app/` for routes, `components/` for shared UI, `lib/` for cross-cutting)
- **Affected packages:** `web/`
- **Reads from:** `docs/design/tokens.css`, `docs/design/refinements/*` for visual reference only
- **Writes to:** `none` (stateless on this brief)
- **Publishes events:** `none`
- **Subscribes to events:** `none`
- **New ports introduced:** `none`
- **New adapters introduced:** `none`
- **DB migrations required:** `no`
- **OpenAPI surface change:** `no`

---

## Acceptance Criteria

- **AC-phase1-web-001-01:** Given `pnpm --filter web dev`, when run, then the dev server starts on a stable port and serves a page that renders without TS errors and without console errors.
- **AC-phase1-web-001-02:** Given the page in light mode, when inspected, then the body uses the indigo `--brand-primary` color from `tokens.css` and the Inter typeface (loaded from a self-hosted source under `web/public/fonts/` or via `fontsource`).
- **AC-phase1-web-001-03:** Given a `[data-theme="dark"]` attribute on the document root, when applied via a working toggle component, then the visual switches to the dark-mode tokens (specifically: background to `--surface-base-dark`, text to `--text-primary-dark`, border to `--border-subtle-dark`).
- **AC-phase1-web-001-04:** Given Tailwind, when arbitrary `bg-[--brand-primary]` or semantic class references are inspected, then the CSS variables from `tokens.css` resolve correctly. Tailwind v4's `@theme` directive maps the design tokens.
- **AC-phase1-web-001-05:** Given the build, when `pnpm --filter web build` runs, then the output is produced under `web/dist/` and is < 200KB gzipped for the initial route (no real components yet, but the bound is enforced as a baseline).
- **AC-phase1-web-001-06:** Given shadcn/ui CLI, when `npx shadcn add button` is run, then the Button component lands at `web/src/components/ui/button.tsx`, uses the design tokens (no shadcn defaults), and renders correctly in the demo route.
- **AC-phase1-web-001-07:** Given the `tsconfig.json`, when `pnpm --filter web tsc --noEmit` runs, then it passes with `strict`, `noUncheckedIndexedAccess`, and `exactOptionalPropertyTypes` all on.

---

## Out of Scope

- Auth screens: `phase1-web-003`.
- Dashboard / app shell: `phase1-web-004` and `phase1-web-005`.
- API client and TanStack Query setup: `phase1-web-002`.
- Routing tree: stub `<Routes>` with a single demo route here; real routes in web-005.
- Empty-state visuals beyond the placeholder demo: `phase1-web-004` and Phase 4 polish briefs.
- Internationalization (English only V1).
- Marketing landing page: a separate Phase 4 brief.

---

## Dependencies

- **Code dependencies:** none beyond bootstrap.
- **Data dependencies:** none.
- **External dependencies:** Vite, React 19, Tailwind v4, shadcn/ui CLI, Inter + JetBrains Mono fonts (self-hosted or via fontsource).

---

## Test Coverage Required

- [ ] **Application tests (Vitest unit):** `web/tests/unit/theme-toggle.test.tsx`
  - covers AC-03
  - test cases: `theme_toggle_switches_data_theme_attribute`
- [ ] **Snapshot test:** `web/tests/unit/demo-route.test.tsx` for the demo route — guards against accidental visual regressions on the bootstrap surface.
- E2E and adapter tests do not apply at this brief.

---

## Done Definition

- [ ] All ACs verified by tests (where applicable) or manual smoke (documented in PR description with screenshots for AC-02, AC-03).
- [ ] `pnpm --filter web tsc --noEmit` passes.
- [ ] `pnpm --filter web lint` passes.
- [ ] `pnpm --filter web build` succeeds.
- [ ] `tokens.css` is the single source of truth for colors / spacing / typography — no hardcoded hex values anywhere in `web/src/`.
- [ ] No new ADR.
- [ ] Single PR. Conventional commit: `feat(web): SPA bootstrap with design tokens [phase1-web-001]`.

---

## Implementation Notes

- Tailwind v4 uses `@import "tailwindcss"` + the new `@theme` block to register design tokens as theme values. Map every CSS variable from `tokens.css` to a Tailwind token name via `@theme inline`. This means components can use either the token directly (`var(--brand-primary)` or `bg-[--brand-primary]`) or a semantic Tailwind class (`bg-brand`). Prefer semantic classes for components, raw vars for one-offs.
- Theme toggle: store the user preference in `localStorage` under `vc:theme`, default to `prefers-color-scheme` media query result. Respect the toggle on the document root via `data-theme` attribute. Persist Zustand later (web-002 sets up Zustand) — for now a simple `useState` + effect is fine.
- Self-host Inter and JetBrains Mono via `@fontsource/inter` and `@fontsource/jetbrains-mono` — avoids Google Fonts dependency and works offline. Load only the weights actually used in `tokens.css` (likely 400, 500, 600, 700 for Inter; 400 for mono).
- shadcn/ui components: do NOT preinstall the full set. Add components as features need them in subsequent briefs. The Button used in the demo route is the only one this brief installs.
- Reference the design `*-host.jsx` files when porting to React: they are vanilla JSX with token classes and demonstrate the visual exactly. Treat them as visual reference, not as code to copy verbatim — the React port uses TS + shadcn primitives.

---

## Risk / Friction

- Tailwind v4 is recent and the `@theme` directive syntax is the new way; older docs/StackOverflow answers from v3 days will mislead. Confirm against the official v4 docs at the time of writing — the tokens-to-Tailwind mapping is the most likely friction point.
- Self-hosted fonts require correct CORS headers if the SPA is served from a different origin than the font asset. In dev with Vite, this is automatic. In production via Cloudflare Pages, fonts under `public/fonts/` are same-origin — no issue.
