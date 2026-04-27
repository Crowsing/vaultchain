---
ac_count: 2
blocks:
- phase2-web-007
complexity: L
context: web
depends_on:
- phase2-wallet-001
- phase2-balances-001
- phase2-transactions-002
- phase2-notifications-001
- phase1-web-005
estimated_hours: 4
id: phase2-web-006
phase: 2
sdd_mode: lightweight
state: ready
title: Real wallet/balance/history UI + receive screen + tx detail
touches_adrs: []
---

# Brief: phase2-web-006 — Real wallet/balance/history UI + receive screen + tx detail


## Context

Phase 1's `web-005` shipped the dashboard skeleton with stubs (`walletsStub.ts`, `transactionsStub.ts`). This brief replaces them with real TanStack Query hooks reading from the Phase 2 backend, plus three new screens: Receive (per-chain QR + address), Activity (transaction history list), and Transaction Detail (single tx view with chain explorer link). The send flow itself is `phase2-web-007` — this brief focuses on the read-side surfaces.

The frontend pattern: each backend endpoint gets a typed hook (e.g., `useWalletsQuery()`, `usePortfolioQuery()`, `useTransactionsQuery({status})`, `useTransactionQuery(id)`). Hooks generate types from `docs/api-contract.yaml` via `openapi-typescript` per architecture Section 4. The dashboard's wallet cards now render real balances + USD totals, with the "provisioning" edge state from `wallet-001` AC-06 wired to a small loading variant.

The SSE layer: a `useEventStream()` hook opens `EventSource('/api/v1/events')` on login, exposes events through a tiny event bus. Components subscribe via `useEvent('tx_confirmed', callback)`. On `tx_confirmed`, the relevant TanStack Query keys are invalidated (`['portfolio']`, `['transactions']`, `['transactions', id]`), triggering refetch. This is the architecture Section 4 "SSE primary, polling fallback" pattern: SSE invalidates → query refetches. If SSE drops, TanStack Query's stale-while-revalidate (3s on `pending` tx pages) fills the gap.

Three new pages in this brief:
1. **Receive screen** (`/wallets/:walletId/receive`): per-chain QR code (qrcode.react), address with copy button, "Send only <chain> testnet tokens to this address" warning, expected-arrival hint ("Deposits typically appear within 3 minutes"), recent deposits list (filtered transactions where `to_address == this_wallet`).
2. **Activity list** (`/activity`): paginated transactions grouped by date, status icons (broadcasting / pending / confirmed / failed), incoming vs outgoing distinction. Empty state for new users.
3. **Transaction detail** (`/transactions/:id`): full tx view, status timeline (using `history` JSONB), USD value + crypto amount, fee breakdown, chain explorer link (`https://sepolia.etherscan.io/tx/<hash>`), "Cancel/Speed Up" CTAs disabled (placeholder for V2).

The wallet card stub from Phase 1 evolves to show: the chain badge, native asset balance + USD, stable asset balance + USD if any, plus a small "Send" CTA per asset (deep-links to send flow with pre-filled wallet). The empty (zero-balance) wallet shows a "Get testnet tokens" button linking to the funding flow (built in `web-007`).

---

## Architecture pointers

- **Layer:** frontend SPA (TypeScript + Vite + React + TanStack Query + shadcn/ui per architecture Section 4).
- **Packages touched:**
  - `web/src/api/hooks/useWallets.ts`, `usePortfolio.ts`, `useTransactions.ts`, `useTransaction.ts`, `useNotifications.ts`
  - `web/src/api/eventStream.ts` (SSE hook + event bus)
  - `web/src/pages/Dashboard.tsx` (replace stub references)
  - `web/src/pages/Receive.tsx` (new)
  - `web/src/pages/Activity.tsx` (new)
  - `web/src/pages/TransactionDetail.tsx` (new)
  - `web/src/components/wallet-card/WalletCard.tsx` (real-data version)
  - `web/src/components/transaction-row/TransactionRow.tsx` (new)
  - `web/src/components/empty-states/ProvisioningWallets.tsx` (refine from Phase 1)
  - `web/src/lib/format.ts` (extends `formatChainNativeAmount`, `formatUsd`)
  - `web/src/types/api.ts` (auto-generated from openapi)
  - `web/src/router.tsx` (add new routes)
- **Reads:** all Phase 2 user-facing endpoints via the hooks.
- **Writes:** none new (mark-read for notifications via existing endpoint).
- **Removes:** `web/src/stubs/walletsStub.ts`, `web/src/stubs/transactionsStub.ts`. Files deleted in this PR.

---

## Acceptance Criteria

- **AC-phase2-web-006-01:** Given a fresh user (signed up, wallets provisioning in flight), when they land on Dashboard, then they see a `<ProvisioningWallets />` state with a small spinner and copy "Setting up your wallets… this takes a few seconds." After successful provisioning, the screen transitions to the wallet cards. The polling logic auto-detects via the `provisioning: true` flag from `GET /portfolio`.

- **AC-phase2-web-006-02:** Given a user with provisioned wallets and zero balance, when on Dashboard, then they see one Ethereum wallet card showing: chain badge "Ethereum (Sepolia)", address truncated `0x1234…abcd` with copy icon, "0 ETH ≈ $0.00", "0 USDC ≈ $0.00", an empty-state CTA "Get testnet tokens" linking to the funding flow.

- **AC-phase2-web-006-03:** Given a user with non-zero balance, when on Dashboard, then the wallet card shows accurate amounts (e.g., "0.05 ETH ≈ $142.03", "100 USDC ≈ $100.00"), formatted via `formatChainNativeAmount(amount, decimals)` and `formatUsd(value)`. Decimals come from the API response, not hardcoded. The total at top of dashboard shows sum across all assets.

- **AC-phase2-web-006-04:** Given the SSE connection delivers `tx_confirmed` for a tx the user owns, when the event arrives, then: TanStack Query keys `['portfolio']` and `['transactions']` are invalidated; UI refetches automatically; a toast notification appears "Transaction confirmed" with a link to detail. The toast uses shadcn/ui's `<Toaster />` from Phase 1.

- **AC-phase2-web-006-05:** Given the SSE connection delivers `deposit_detected`, when the event arrives, then portfolio refetches; a toast "Received 0.05 ETH" appears with link to transaction detail. The transaction detail for a deposit fetches the tx via `GET /api/v1/transactions/{id}` if a Transaction row exists for it (deposits don't always have a Transaction; the detail page handles the "deposit-only" case by showing chain explorer info instead).

- **AC-phase2-web-006-06:** Given the user clicks "Receive" on a wallet card, when they navigate to `/wallets/:walletId/receive`, then the screen renders: large QR code (the address as plain text, QR'd via `qrcode.react`), address mono text with one-tap copy, a "Send only Ethereum Sepolia testnet tokens" warning callout, a list of recent incoming transactions if any (last 5), a "Need testnet tokens?" link to the funding flow.

- **AC-phase2-web-006-07:** Given a user navigates to `/activity`, when the page loads, then they see paginated transactions grouped by date ("Today", "Yesterday", "April 15"). Each row shows: incoming/outgoing arrow icon, status badge (with color: yellow for `broadcasting/pending`, green for `confirmed`, red for `failed`, gray for `expired`), amount + USD, recipient/sender truncated address, time. Pagination via "Load more" button (offset-based). Empty state: "No activity yet — send or receive testnet tokens to get started."

- **AC-phase2-web-006-08:** Given a user clicks a transaction row, when they navigate to `/transactions/:id`, then the screen shows: status header with icon + label, "Sent 0.05 ETH to 0x1234…abcd" or "Received 0.05 ETH from 0x...", USD value at time of confirmation (from `amount_usd`), fee breakdown (gas used × effective gas price = total fee + fee_usd), tx hash with copy + "View on Etherscan" external link, status timeline rendered from the `history` JSONB array (each transition with timestamp), notes field empty (V2).

- **AC-phase2-web-006-09:** Given a transaction is in `broadcasting` or `pending` status, when the detail page is open, then TanStack Query polls every 3 seconds until terminal status per architecture Section 4 line 497. After confirmed/failed/expired, polling stops. The status header animates the icon (pulsing for in-flight, static for terminal).

- **AC-phase2-web-006-10:** Given the user opens `/notifications`, when the page loads, then it shows a list of recent notifications with unread highlighted, mark-as-read on tap, "mark all read" button. The dashboard top bar shows an unread-count badge that updates via SSE.

- **AC-phase2-web-006-11:** Given the SSE connection drops (network blip), when reconnect happens, then `Last-Event-ID` resumes correctly per `notifications-001` AC-06; the user doesn't see duplicate toasts or missed events. If reconnect takes longer than 5 minutes (replay TTL), the next polling refetch covers any gap.

- **AC-phase2-web-006-12:** Given accessibility requirements per architecture Section 4 ("WCAG 2.1 AA baseline"), when the new pages are audited, then: keyboard navigation works (Tab through wallet cards, transaction rows, buttons); focus rings visible on all interactive elements; ARIA labels on icon-only buttons; status badges include `aria-label` redundantly with color (color is not the only signal); Lighthouse a11y score ≥ 95 on the three new pages.

---

## Out of Scope

- Send flow itself: `phase2-web-007`.
- Funding flow UI: `phase2-web-007`.
- Mobile-specific gestures (swipe to refresh, etc.): V2 polish.
- Charts / sparklines on portfolio: V2.
- Filtering/searching transactions: V2.
- Address book contacts integration: Phase 3.

---

## Acceptance Tests / E2E

- [ ] **Playwright E2E `tests/web/e2e/dashboard-deposit-flow.spec.ts`:** signup → wallets provision → dashboard shows zero balance → faucet quick-fund (calls `/faucet/request`) → wait for deposit → dashboard shows updated balance (via SSE) → click activity → see deposit row → click row → detail shows tx with Etherscan link.
- [ ] **Playwright E2E `tests/web/e2e/sse-reconnect.spec.ts`:** connect, simulate network drop (`page.context().setOffline(true)`), restore, assert no duplicate toasts, assert events received post-reconnect.
- [ ] **Component tests** (Vitest + React Testing Library): WalletCard renders correct formatted amounts; TransactionRow renders correct status colors; ProvisioningWallets shows spinner.
- [ ] **Hook tests:** `useWalletsQuery` happy path with mocked API response; `useEventStream` opens connection, dispatches events to subscribers.
- [ ] **A11y test:** axe-core scan via Playwright on the three new pages, asserts zero violations of WCAG 2.1 AA.

---

## Done Definition

- [ ] All ACs verified via tests above.
- [ ] Phase 1 stubs (`walletsStub.ts`, `transactionsStub.ts`) deleted.
- [ ] All TanStack Query hooks generate types from `docs/api-contract.yaml`; CI drift-check passes.
- [ ] `tsc --noEmit` passes.
- [ ] `eslint` clean.
- [ ] Lighthouse a11y ≥ 95 on Dashboard, Receive, Activity, TransactionDetail.
- [ ] Single PR. Conventional commit: `feat(web): real wallet/balance/history UI + receive + tx detail [phase2-web-006]`.
- [ ] PR description: a screenshot of each new screen on mobile + desktop (light + dark).

---

## Implementation Notes

- TanStack Query setup: `staleTime: 30_000` for portfolio (matches backend cache), `staleTime: 0` for transaction detail polling, `refetchOnWindowFocus: true` globally.
- The SSE hook uses native `EventSource` API. For React, wrap in a singleton context provider so multiple components share one connection: `<EventStreamProvider>` at app root, components consume via `useEvent('tx_confirmed', cb)` hook.
- For the address copy button, use `navigator.clipboard.writeText(address)` with a small "Copied" toast. Fallback for older browsers: select the text + execCommand. Phase 2 portfolio scope assumes modern browsers.
- The chain explorer link is hardcoded for Phase 2: `https://sepolia.etherscan.io/tx/{tx_hash}`. Move to a `chainExplorerUrl(chain, tx_hash)` helper now to prepare for Phase 3 (Tronscan, Solscan).
- Empty states are designed in `phase1-web-005`'s `empty-states.jsx` — reuse those components.
- The status timeline UI is the smallest non-trivial component in this brief. Render as a vertical list with connector lines; each entry shows `<status_icon> <label> <time_ago>`. Use `Intl.RelativeTimeFormat` for the time-ago strings.

---

## Risk / Friction

- The transition from stubs → real data has subtle UX implications: a fresh demo user sees "Setting up your wallets…" for ~2-5s on first login, where Phase 1 stubs showed everything immediately. Document this in the demo script: "first login is ~5s slower while wallets provision."
- SSE connection management across browser tabs is tricky. Each tab opens its own connection per AC-12 of `notifications-001` (3-tab limit). Document this so reviewers don't see connection limits as a bug.
- The "deposit detail page when no Transaction row exists" branch is easy to overlook. The page should gracefully handle: receives `id` query param → fetches → 404 → falls back to fetching by `tx_hash` from chain explorer. Or: deposit IDs are different from transaction IDs (this brief uses transaction IDs only; deposits without a tx_hash → no detail page link). Simpler: only link to detail page if there's a Transaction row; deposits-only show as activity-list rows that link to Etherscan directly.
- Lighthouse a11y can be flaky on color contrast for status colors (yellow for pending). Use shadcn/ui's pre-validated palette; if a custom yellow fails contrast, swap to amber-700 on white background.
- The `useTransactionQuery(id)` polling at 3s while `pending` is per-instance — multiple open detail pages all poll. Acceptable for portfolio scope; if scale demands, consolidate into a single SSE-driven update.
