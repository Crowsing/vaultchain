---
ac_count: 8
blocks:
- phase4-demo-001
complexity: M
context: web
depends_on:
- phase4-web-008
- phase1-web-003
- phase1-web-004
- phase1-web-005
- phase1-admin-003
- phase2-web-006
- phase2-web-007
- phase3-admin-004
- phase3-admin-005
- phase3-admin-006
- phase3-admin-007
- phase3-admin-008
estimated_hours: 4
id: phase4-polish-001
phase: 4
sdd_mode: lightweight
state: ready
title: Empty/loading/error states pass + mobile responsive QA
touches_adrs: []
---

# Brief: phase4-polish-001 — Empty/loading/error states pass + mobile responsive QA


## Context

This brief is the polish pass across every user-facing surface the project ships. After three phases of feature delivery, surfaces accumulate small inconsistencies: an empty state that just shows a blank panel, a loading state that's a spinner-on-grey, an error state that's a raw error message, mobile breakpoints that crack at 320px, focus rings that are inconsistent, accessibility violations that have crept in unnoticed.

The brief is deliberately scoped as a polish pass, not a redesign. No new features. No new endpoints. The scope: walk every surface, identify gaps against a checklist, fix in place. The deliverable is a single PR that reviewer can scan via a screenshot grid showing before/after.

**Surfaces audited:**

1. **Login + magic-link** (Phase 1) — empty input states, loading during link send, error toast on bad email.
2. **Dashboard** (Phase 1 + Phase 2 + Phase 4) — empty state for new user (no wallets, no tx, no AI history); loading skeleton for portfolio + activity; error state if `GET /portfolio` fails (offline mode).
3. **Wallets** (Phase 2 + Phase 3) — empty state for new chain not yet provisioned; loading per-wallet card; error state on chain RPC failure ("Couldn't reach Ethereum — retry?").
4. **Activity / Transaction list** (Phase 2 + Phase 3) — empty state for fresh user; loading skeleton; pagination loading; error.
5. **Transaction detail** (Phase 2) — loading; error if tx not found; pending state with progress indicator.
6. **Send wizard** (Phase 2 + Phase 3) — every step's empty/error/loading state; address validation feedback; insufficient balance feedback.
7. **Funding flow** (Phase 2) — rate-limit countdown UX; error state if faucet down.
8. **Receive screen** (Phase 2) — QR generation states; address-copy feedback animation.
9. **KYC flows** (Phase 3) — Sumsub iframe loading state; tier_0_rejected hard-fail copy + support CTA; in-progress applicant continuation copy.
10. **AI chat panel** (Phase 4) — empty conversation list state for new user; conversation-loading skeleton; SSE error state; markdown content edge cases (very long messages, deeply nested lists, code blocks overflowing on mobile).
11. **Prep card** (Phase 4) — already 5 states from `phase4-web-008` AC-06; this brief verifies each renders correctly across viewports.
12. **Suggestions strip** (Phase 4) — already covered in `phase4-web-008`; verifies empty (hidden) and 1/2/3/5 state visual correctness.

**Mobile responsive QA breakpoints:**
- 320px (iPhone SE — smallest realistic)
- 375px (iPhone 13 mini, baseline mobile)
- 414px (iPhone 13 Pro Max)
- 768px (tablet portrait, iPad)
- 1024px (tablet landscape, small laptop)
- 1440px (typical desktop)

**Standardised states (the checklist):**

Every surface that fetches data must have:
- **Empty state** — illustration or muted icon + headline + sub-copy + optional CTA. Not a blank rectangle.
- **Loading state** — skeleton (preferred; matches the eventual layout shape) or spinner (acceptable for in-flight mutations <1s). Not a flash of blank content.
- **Error state** — error envelope's `message` field as the primary text, retry CTA, optional support link. Not a raw exception message.
- **Stale state** (where applicable) — e.g., portfolio prices stale per `phase2-balances-001` AC-03 — small banner "Prices may be outdated" without breaking the rendered numbers.

---

## Architecture pointers

- **Layer:** frontend SPA only. No backend changes.
- **Packages touched:**
  - `web/src/components/EmptyState.tsx` (new — shared component for all empty states; props: `icon, title, description, action?`)
  - `web/src/components/LoadingSkeleton.tsx` (new — variants: `card`, `list-row`, `text-block`, `chart`)
  - `web/src/components/ErrorState.tsx` (new — props: `error: ApiError, onRetry?, supportLink?`)
  - `web/src/components/StaleBanner.tsx` (new — small inline banner)
  - audited surfaces above (modifications, not new files): each gets the standardised states wired in.
  - `web/src/styles/breakpoints.ts` (new — single source of truth for responsive breakpoints; consumed via Tailwind config)
  - `web/tests/visual/` (new directory — Storybook visual snapshots for each new shared component across the 6 viewports; not blocking CI but committed for reviewer reference)
  - `web/tests/e2e/responsive-smoke.spec.ts` (new Playwright spec — opens key surfaces at 320/375/768/1024/1440 and asserts no horizontal scrollbar, no overlapping content, no unreadable text)
- **API consumed:** none new — existing.
- **OpenAPI surface change:** no.

---

## Acceptance Criteria

- **AC-phase4-polish-001-01:** Given the shared `<EmptyState>` component, when rendered with `{icon: WalletIcon, title: "No wallets yet", description: "Connect a chain to start", action: {label: "Set up wallet", onClick}}`, then it shows the icon (size 48px, muted color), centered title (h3, semibold), sub-copy (muted), and CTA button (if `action` provided). Used by every "no data" surface across Wallets, Activity, AI chat conversation list, Suggestions (in the rare empty case visible to admins). Component is documented in Storybook with 4 example variants.

- **AC-phase4-polish-001-02:** Given the shared `<LoadingSkeleton>` component with variants, when rendered, then: `variant="card"` produces a card-shaped skeleton matching the wallet card / tx card dimensions; `variant="list-row"` matches a single Activity row; `variant="text-block"` is a 3-line text shimmer; `variant="chart"` matches the portfolio chart placeholder. All variants use the same Tailwind shimmer animation (CSS `@keyframes` defined once in `globals.css`). `prefers-reduced-motion` disables the shimmer (replaced with static muted background). Used everywhere `isLoading` is true.

- **AC-phase4-polish-001-03:** Given the shared `<ErrorState>` component, when rendered with `{error: {code: 'balances.unavailable', message: 'Balance service is temporarily unavailable.'}, onRetry: refetch}`, then it shows: a warning icon, the `message` text as headline, a "Try again" button wired to `onRetry`, and (if the error code's documentation_url is provided in the error envelope) a small "Learn more" link. **Never** displays the raw error code as visible copy; the code is in the DOM as a `data-error-code` attribute for support debugging. Used by every surface that catches a query/mutation failure.

- **AC-phase4-polish-001-04:** Given the audit pass over Dashboard, when a fresh user with no wallets / no tx / no chats lands, then: the portfolio card shows `<EmptyState>` with "Welcome — let's get you started" + "Connect a testnet wallet to begin" + "Set up wallet" CTA navigating to wallet provisioning; the activity preview shows `<EmptyState>` "No transactions yet"; the suggestions strip is hidden (zero pending — covered by `phase4-web-008` AC-10); the AI chat button still floats but the panel's empty state shows "Hi! I'm your assistant — ask me anything about your wallet." The Dashboard with all empty states fits within a single mobile viewport without scrolling.

- **AC-phase4-polish-001-05:** Given the audit pass over Activity, when a user has 0 / 1 / many transactions, then: 0-tx renders `<EmptyState>` with "No transactions yet" + "When you send or receive, they'll show here"; 1-tx renders the single row plus `<EmptyState>` muted hint at the bottom "That's all for now"; many-tx (>20) shows pagination with a `<LoadingSkeleton variant="list-row">` for the next-page placeholder during fetch. Filter-with-no-results: a separate `<EmptyState>` "No transactions match these filters" + "Clear filters" CTA.

- **AC-phase4-polish-001-06:** Given the audit pass over Send wizard, when the user enters an invalid address on Step 2, then: the address input shows a red ring + inline error "Invalid Ethereum address — check the format"; the Continue button is disabled until valid; the error message is screen-reader-announced via `aria-live="polite"`. Address validation runs on blur, not on every keystroke (avoid noisy errors mid-typing). For chain-mismatched addresses (e.g., Solana address typed when chain selector is Ethereum), the inline error is "This looks like a Solana address — switch chain or paste an Ethereum address" with a "Switch to Solana" inline button.

- **AC-phase4-polish-001-07:** Given the audit pass over the AI chat panel, when the user has no conversations and opens the panel, then: the conversation list shows `<EmptyState>` with chat icon + "No chats yet" + "Ask me anything to get started"; the message area shows a centered greeting card "Hi 👋 I can check your balances, look up your transactions, and help you send. What's up?". This greeting is visible only on a fresh empty conversation (when conversation_id is unset in panel state); existing conversations show their own message history.

- **AC-phase4-polish-001-08:** Given the audit pass over chat panel error handling, when SSE fails immediately (server returns 503 before any event), then: the optimistic user-message bubble stays; below it renders `<ErrorState>` inline (NOT replacing the message — message stays for retry context) with "AI assistant is temporarily unavailable" + "Try again" CTA that re-submits the same text. Mid-stream drop is already handled by `phase4-web-008` AC-05's polling fallback; this AC covers the immediate-failure case the polling doesn't address.

- **AC-phase4-polish-001-09:** Given the audit pass over KYC flows, when the user is `tier_0_rejected` with `reject_labels: ['DOCUMENT_DAMAGED', 'WRONG_USER_DATA']`, then: the KYC page shows a non-dismissable callout (NOT a `<SuggestionCard>` — too important to be dismissable) with a warning icon, copy "Your verification was not approved." + a numbered list of friendly translations of the reject_labels (e.g., "DOCUMENT_DAMAGED" → "Documents were unclear or damaged"), and a "Contact support" CTA → `mailto:` or in-app support link. The translation map is committed in `web/src/features/kyc/reject-label-translations.ts` with all common Sumsub reject label values seeded.

- **AC-phase4-polish-001-10:** Given the responsive QA pass over all surfaces at 320/375/414/768/1024/1440, when each surface is loaded at each viewport, then: no horizontal scrollbar appears; tappable elements (buttons, links, list rows) meet the 44×44 px tap-target minimum on mobile breakpoints (CSS rule via Tailwind or inline; verified by axe-playwright's `target-size` rule); text remains readable (no >120-char lines on desktop, no line-wrapping mid-word on mobile); modal dialogs are full-screen on <768px and centered with backdrop on ≥768px (already true for `<TotpConfirmModal>` and chat panel from `phase4-web-008` AC-02; this AC verifies). Documented via the new `responsive-smoke.spec.ts` Playwright run.

- **AC-phase4-polish-001-11:** Given the focus-ring consistency audit, when any interactive element receives keyboard focus, then: the focus ring is the design-system's accent color, 2px outline, 2px offset; consistent across buttons, links, inputs, list rows, and shadcn/ui components. A grep audit confirms no `outline: none` exists outside the explicit "remove default browser outline only when replaced with custom ring" pattern. Tab order on every primary surface (Dashboard, Send wizard, Chat panel) is logical (top-to-bottom, left-to-right reading order). Documented via a `tab-order.spec.ts` Playwright spec that uses `keyboard.press('Tab')` repeatedly and asserts the focused-element sequence on Dashboard.

- **AC-phase4-polish-001-12:** Given the toast notification consistency audit, when any user action triggers a toast (success, info, error), then: positioning is bottom-right on desktop, top-center on mobile (matching mobile platform conventions); auto-dismiss timing is 4s for info/success, 6s for errors (longer reading time); error toasts include a "Dismiss" close button explicitly; no toast stack ever exceeds 3 visible (older ones evict). The shadcn/ui `<Toaster>` from Phase 1 is configured with these defaults; existing per-call overrides are reviewed and consolidated.

---

## Out of Scope

- New features. Period. Any "while we're polishing, let's also..." goes into a separate brief.
- Backend changes. Polish is frontend only.
- Visual redesign / rebranding. Existing design tokens stay.
- Translation / i18n preparation. V2 — V1 ships English UI.
- Print stylesheets. V2 (or never).
- Browser-specific bug workarounds beyond iOS Safari / Android Chrome / Firefox / Chrome desktop. Edge / Safari desktop are best-effort.
- Performance optimization beyond the obvious (e.g., adding skeletons reduces perceived latency; deeper bundle-splitting is V2).
- Switching component libraries.

---

## Dependencies

- **Code dependencies:** every shipped web brief through `phase4-web-008`.
- **Data dependencies:** none new.
- **External dependencies:** none new beyond what `phase4-web-008` adds (axe-playwright is reused here for the `target-size` and other rule checks).

---

## Test Coverage Required

- [ ] **Component tests:** `EmptyState.test.tsx`, `LoadingSkeleton.test.tsx`, `ErrorState.test.tsx`, `StaleBanner.test.tsx` — render with various props; `prefers-reduced-motion` disables animations; covers AC-01, AC-02, AC-03.
- [ ] **Storybook stories:** one story file per shared component covering all variants and viewports — visual reference for reviewers.
- [ ] **Component tests:** `KycRejectedCallout.test.tsx` — translates known reject labels; renders contact-support CTA. Covers AC-09.
- [ ] **Playwright responsive smoke:** `responsive-smoke.spec.ts` — Dashboard, Send wizard step 2, Chat panel open at 320/375/768/1024 viewports; assert no horizontal overflow via `page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)`. Covers AC-10.
- [ ] **Playwright accessibility:** `accessibility-audit.spec.ts` — runs axe-playwright on Dashboard, Activity, Chat panel; asserts zero serious/critical issues, including the new `target-size` rule for mobile. Tab-order asserted on Dashboard. Covers AC-11.
- [ ] **Playwright tab order:** `tab-order.spec.ts` — covers AC-11 via repeated Tab presses asserting expected focus sequence.
- [ ] **Visual regression (opportunistic, not blocking):** Storybook + Chromatic or Percy diff on the four shared components and the chat panel open state at three viewports. If the project has a visual-regression tool wired up, attach this as a per-PR signal; if not, skip.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] Four new shared components committed: `<EmptyState>`, `<LoadingSkeleton>`, `<ErrorState>`, `<StaleBanner>`.
- [ ] Every audited surface (the 12-surface list above) has standardised empty/loading/error/stale states wired in.
- [ ] Responsive QA passes at all 6 documented breakpoints.
- [ ] axe-playwright reports zero serious/critical issues across the audit.
- [ ] The `web/src/features/kyc/reject-label-translations.ts` map seeded with at least the 10 most common Sumsub reject labels.
- [ ] `tsc --noEmit --strict` clean.
- [ ] `eslint` + `prettier` clean.
- [ ] Single PR. Conventional commit: `polish(web): empty/loading/error states + responsive QA [phase4-polish-001]`.
- [ ] PR description: a screenshot grid (before/after) showing 6+ surfaces in their previously-bare states and now polished. Mobile and desktop both. The PR description is essentially the deliverable — the reviewer should be able to scan it and see the polish quality.

---

## Implementation Notes

- **The screenshot-grid PR description is intentional.** A reviewer sees 12 before/after pairs and grasps the value in 60 seconds. Code review is secondary; visual review is primary. Use a tool like `playwright screenshot` to capture them programmatically if practical, or hand-screenshot if quicker.
- **`<EmptyState>`'s icon prop accepts a Lucide component reference**, not a rendered element. The component renders it at standardised size internally. Keeps usage call-sites tidy: `<EmptyState icon={Wallet} title="..." />`.
- **`<LoadingSkeleton variant="card">` should match the actual card layout** — same border-radius, same height, same internal padding shape. Otherwise the layout shifts when content loads (CLS — Cumulative Layout Shift accessibility issue). Test: visual diff between skeleton and loaded states should show only content change, not structural shift.
- **The KYC reject-label translations** are not the responsibility of the backend; Sumsub's labels are stable enough to translate frontend-side. The translation map in `reject-label-translations.ts` is the source of truth; unknown labels fall back to a generic "We couldn't verify some of your information" copy. Document the map's update cadence (whenever Sumsub adds a new reject reason — practical: refresh quarterly).
- **`prefers-reduced-motion`** is honored in `<LoadingSkeleton>`'s shimmer, the chat panel's slide-in (already from `phase4-web-008`), the prep card morph, and any new transitions added in this brief. Use Tailwind's `motion-reduce:` variant for clean expression.
- **Tap target size** (44×44 px on mobile, AC-10): a common offender is clickable list rows where the visible content is small but the tap target is the whole row. Use `min-height: 44px` on `<button>` / `<a>` with `display: flex; align-items: center` to extend the hit area without changing the visual baseline. shadcn/ui buttons mostly comply; verify and patch any that don't.
- **The audit is intentionally surface-by-surface.** Don't try to write a generic "audit script" — the value is the human eye on each surface. The Storybook stories serve as reference for what good states look like; the actual implementation per surface is just plumbing (`isLoading ? <LoadingSkeleton variant="..." /> : isError ? <ErrorState ... /> : data.length === 0 ? <EmptyState ... /> : <RealContent />`).

---

## Risk / Friction

- **Scope creep is the biggest risk.** A polish pass invites "while we're here, let's also redesign the dashboard." Resist hard. Out-of-Scope is clear. Any tempting refactor goes into a follow-up brief.
- **The 6-viewport responsive QA can surface dozens of small bugs.** Triage: AC-10 lists the structural rules (no overflow, tap targets, modal sizing) — fix those. Pixel-level inconsistencies that don't affect usability (a 2px alignment gap on iPad portrait) get logged for V2 and not blocked here.
- **`prefers-reduced-motion` testing is hard to automate.** Playwright supports the emulation flag (`page.emulateMedia({ reducedMotion: 'reduce' })`); use it on a smoke test that renders the chat panel and asserts the slide-in CSS resolves to no animation. Manual verification covers the rest.
- **Reject-label translations getting stale** — Sumsub adds new labels occasionally. Mitigation: the unknown-label fallback prevents a broken UX; quarterly refresh suffices. Document in runbook.
- **Reviewer asking for dark-mode parity in the polish pass** — see `phase4-web-008` Risk/Friction; same answer (inherit if available, V2 if not). Document in PR description.
- **The `<ErrorState>`'s "Learn more" link** assumes the error envelope includes `documentation_url` per the architecture's error contract. Verify the backend actually populates this for the error codes commonly seen frontend-side (`balances.unavailable`, `llm.unavailable`, `embeddings.unavailable`, `ai.prepared_action_expired`, etc.); if any are missing, optional follow-up to populate, not blocking this brief.
- **Storybook stories don't catch regressions automatically** unless paired with visual regression (Chromatic/Percy). If the project doesn't have one yet, the stories are still useful as documentation; mention this in the PR.
