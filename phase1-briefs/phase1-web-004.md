---
ac_count: 7
blocks:
- phase1-deploy-001
complexity: M
context: web
depends_on:
- phase1-web-005
- phase1-web-002
estimated_hours: 4
id: phase1-web-004
phase: 1
sdd_mode: lightweight
state: ready
title: Dashboard skeleton, Tier 0 banner, empty states
touches_adrs: []
---

# Brief: phase1-web-004 — Dashboard skeleton, Tier 0 banner, empty states


## Context

Phase 1 ends with a deployable, demonstrable wallet skeleton: signup → magic link → TOTP enroll → land on a dashboard that already looks credible. This brief builds the dashboard at the visual fidelity of the design refinement (`design/app/dashboard.jsx`, `design/app/empty-states.jsx`, `design/app/tier-banner.jsx`) but with all wallet/transaction data stubbed because Phase 1 has no chain or custody contexts yet. The design refinement explicitly accounts for this state via `EmptyDashboard` from `empty-states.jsx`: a Tier-0 user, three empty wallet placeholders (Ethereum / Tron / Solana), no balance, no transactions, no AI suggestions yet — with the Tier 0 banner front-and-center directing the user to KYC (which is also stubbed in Phase 1 — banner button shows "Coming in Phase 3" alert).

The brief does NOT pull live wallet data from a backend, because the backend has no Custody or Chains context yet. Instead the dashboard reads from a frontend stub module `web/src/stubs/walletsStub.ts` that returns the three pre-canned wallet shapes for the current user with `totalUsd: 0`, `empty: true`, and the addresses being placeholder `0x000…000` strings. This stub is replaced in Phase 2 brief `phase2-custody-...` with real `useWalletsQuery()`. The same applies to transactions (empty array) and AI suggestions (empty array). The Tier 0 banner reads `user.tier` from the `userStore` (populated by web-005's session bootstrap from `GET /auth/me`).

The visual quality bar matters here. This is the first authed screen a portfolio reviewer sees after the magic-link flow. It must render at desktop and mobile fidelity, with the tier-banner-as-CTA prominent, the three empty wallet cards with their chain colors / gradients per design tokens, and the `WelcomeHero` for Tier 0 saying "Welcome to VaultChain, Alex — three wallets are ready. Verify your identity to start moving funds." If a reviewer screen-records the first 30 seconds, this is what they see.

---

## Architecture pointers

- **Layer:** delivery (frontend) only.
- **Packages touched:** `web/src/routes/dashboard.tsx`, `web/src/components/wallet-card/`, `web/src/components/tier-banner/`, `web/src/components/welcome-hero/`, `web/src/components/empty-tx-list/`, `web/src/stubs/walletsStub.ts`, `web/src/stubs/transactionsStub.ts`.
- **Reads:** `userStore` (from web-005). No new API calls.
- **Writes:** none.
- **Events:** none.
- **Migrations:** none.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase1-web-004-01:** Given an authenticated Tier-0 user lands on `/dashboard`, when the page renders, then the layout (top-down, desktop): (1) `TierBanner` with `variant="tier0"`, "Verify your identity to send transactions and unlock higher limits" copy, "Start verification" CTA (clicking shows an alert "KYC flow coming in Phase 3" — explicit stub, not silent); (2) `WelcomeHero` for Tier 0 with the user's first name from `userStore`; (3) "Your wallets" section with three `EmptyWalletCard`s (Ethereum, Tron, Solana — order from `walletsStub`); (4) "Recent activity" section with the empty-tx-list copy "No activity yet. Your transactions will appear here."

- **AC-phase1-web-004-02:** Given a Tier-1 user (i.e. the userStore has `user.tier = 1` — this state is unreachable in Phase 1 without backend support, but the component must handle it), when the dashboard renders, then the Tier 0 banner is hidden, the hero shows "Total balance · Tier 1 · $0.00 · Your wallets are ready. Get tokens to start," and the wallet cards remain `EmptyWalletCard`s. The Tier-1 path is exercised via Storybook / a feature-flag query param `?tier=1` for screenshot purposes.

- **AC-phase1-web-004-03:** Given mobile viewport (<md breakpoint), when the dashboard renders, then the layout is single-column, wallet cards stack vertically (not the `wallets-grid` desktop layout — use `wallets-stack`), the tier banner is full-width, and the welcome hero copy is sized for mobile per the design tokens. Tap targets ≥44px.

- **AC-phase1-web-004-04:** Given each wallet's "Share address to receive" button on an `EmptyWalletCard`, when clicked, then the SPA navigates to `/receive?wallet=<chain>` (the receive route is a placeholder shell from web-005; this brief does not build receive content).

- **AC-phase1-web-004-05:** Given the AI assistant area on the dashboard is part of the design but no AI exists in Phase 1, when the dashboard renders for a Tier-0 user, then a single `AIBannerWelcome` from `empty-states.jsx` is shown: kicker "Assistant · Say hello," copy "Hi {firstName}. I'm your VaultChain assistant. Ask me anything about how the wallet works, or how to verify your identity." Clicking it navigates to `/ai`, which is a placeholder route ("AI assistant — coming in Phase 4").

- **AC-phase1-web-004-06:** Given the user toggles theme on the dashboard (the toggle lives in app-shell from web-005), when toggled, then all dashboard components re-theme correctly using design tokens — no hardcoded colors leak through. Both modes verified via screenshots in the PR.

- **AC-phase1-web-004-07:** Given the Tier 0 banner has a dismiss button per `tier-banner.jsx`, when the user dismisses it, then it stays dismissed for the current session only (sessionStorage key `vc-tier-banner-dismissed`); on next page load the banner reappears. This pressures the user to verify without being permanently dismissable.

- **AC-phase1-web-004-08:** Given each `EmptyWalletCard` shows a placeholder short address (e.g. `0x000…000`), when the user clicks the copy-address button, then no clipboard write happens; instead a toast appears: "Real addresses arrive in Phase 2 (custody)." This is explicitly a stub-with-feedback.

---

## Out of Scope

- Real wallet data (balances, addresses): Phase 2 custody briefs.
- Real transaction list: Phase 2.
- AI banner content / suggestions / chat: Phase 4.
- Send / Receive screens themselves: Phase 2 / Phase 3.
- KYC flow: Phase 3.
- The "wallets-first" or "ai-forward" dashboard variants from `dashboard.jsx`: only `total-first` (the default) is implemented in Phase 1.
- Network-failure / maintenance / rate-limit edges: web-005 handled the app-level edges; per-page edges are deferred.
- Skeleton-loading states for the dashboard: Phase 4 polish.

---

## Dependencies

- **Code dependencies:** `phase1-web-005` (for shell + userStore + theme), `phase1-web-002` (for shared components / TanStack Query client even if no calls happen here).
- **Data dependencies:** none on the frontend.
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Vitest unit tests:** `web/tests/unit/dashboard-tier0.test.tsx` covers AC-01, AC-04, AC-05 (renders the dashboard with a Tier-0 stub `userStore`, asserts banner + hero + wallet count + empty-tx copy + click handlers fire). `web/tests/unit/empty-wallet-card.test.tsx` covers AC-08 (asserts copy-address triggers the stub toast).
- [ ] **E2E (Playwright):** extend `web/tests/e2e/auth-signup-to-dashboard.spec.ts` from web-003 to additionally assert that after TOTP success, the dashboard renders the tier-0 banner ("Verify your identity") and three empty wallet cards labeled Ethereum / Tron / Solana. No new spec file.

> Lightweight mode. Domain/property/adapter/contract/locust omitted.

---

## Done Definition

- [ ] All ACs verified by tests or PR screenshots (AC-02, AC-03, AC-06 lean on screenshots).
- [ ] `pnpm --filter web tsc --noEmit` passes.
- [ ] `pnpm --filter web lint` passes.
- [ ] No hardcoded color values; all token-based. The chain colors / gradients come from a `chainTheme.ts` constant aligned with `design/tokens.css`.
- [ ] No new ADR.
- [ ] Single PR. Conventional commit: `feat(web): dashboard skeleton with tier-0 banner and empty states [phase1-web-004]`.
- [ ] PR description shows desktop + mobile screenshots in light + dark mode (4 screenshots minimum), plus a brief note explaining why Phase-1 stubs are present.

---

## Implementation Notes

- Do NOT inline `dashboard.jsx` from the design refinement. Port the structure into typed React components, but the refinement is a visual reference — the production code uses Tailwind utility classes built on the design tokens, not the prototype's hand-written CSS classes (`wc`, `hero-total`, etc.). However, keep the same DOM shape for screenshot parity, and consider using `@apply` in `dashboard.css` for the wallet-card structure if utility-soup gets unreadable.
- The chain → color mapping (Ethereum blue gradient, Tron red, Solana purple gradient) lives in `web/src/lib/chains.ts` as a single source of truth — both `WalletCard` and `EmptyWalletCard` and future Phase 2 components import from it.
- Stub modules (`walletsStub.ts`, `transactionsStub.ts`) are flagged with a top-of-file comment: `// PHASE 1 STUB — replaced in Phase 2 by useWalletsQuery() from custody.` This makes it grep-able for the cleanup pass.
- The "Coming in Phase X" alerts use a shared `<Toast>` component (toasts come from web-002's app-shell wiring). If web-002 does not yet have toasts, add them here as a tiny addition; do not block.
- The `WelcomeHero` for Tier 0 from `empty-states.jsx` uses a "welcome-eyebrow" tag with a sparkle icon — port that decoration carefully, it carries the AI-forward brand cue.

---

## Risk / Friction

- The "Coming in Phase X" stubs feel like a smell, but they are the right approach: silently-broken buttons are worse for portfolio review than explicit stubs that signal "this is intentionally deferred." Document the convention once in `web/README.md` so it doesn't proliferate ad-hoc strings.
- The dashboard is the first impression. Spend the time on visual fidelity — pixel-level mismatch with the design prototype on the wallet cards or tier banner will undercut the rest of the work. Reviewers will compare the demo against the HTML prototypes.
- Light/dark mode token coverage is the most common bug class here. The PR screenshot requirement for both modes catches it.
