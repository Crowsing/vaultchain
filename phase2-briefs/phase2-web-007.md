---
ac_count: 3
blocks: []
complexity: L
context: web
depends_on:
- phase2-web-006
- phase2-transactions-002
- phase2-faucet-001
- phase2-notifications-001
estimated_hours: 4
id: phase2-web-007
phase: 2
sdd_mode: lightweight
state: ready
title: Send flow UI + funding flow UI + Playwright E2E
touches_adrs: []
---

# Brief: phase2-web-007 — Send flow UI + funding flow UI + Playwright E2E


## Context

This is the closing brief for Phase 2: the user-facing send wizard and the funding (faucet) flow. After this lands, a user can sign in, get tokens via faucet, send to another testnet address, and watch the confirmation arrive — the full round-trip Phase 2 promises.

**Send wizard** (4 steps, modal/page hybrid):
1. From-wallet selector — defaulted from the entry point (e.g., user clicked "Send ETH" on Dashboard, ETH wallet pre-selected). If multiple wallets, dropdown.
2. Recipient + amount form — address input with paste/QR-scan affordance, asset picker (ETH or USDC), amount input with "Max" shortcut + USD equivalent. Inline validation: address checksum, amount > 0, amount ≤ available - fee.
3. Review card — uses `POST /transactions/prepare` to fetch fee estimate; shows "Sending 0.05 ETH to 0x1234…abcd", fee estimate (~$0.50), USD value, total. Editable: tap a field to go back. "Confirm" button.
4. TOTP modal — same UX as Phase 1 magic-link TOTP screen; 6-digit input, paste-from-authenticator, on success transitions to "Broadcasting…" state with the optimistic Transaction id from `POST /transactions/confirm` response. SSE event `tx_status_changed` advances the state to "Pending (waiting for confirmation)". On `tx_confirmed`, the modal shows success with a "View transaction" CTA → tx detail page.

**Funding flow** per spec `04-funding-flow.md`:
- Triggered from: dashboard empty state, wallet card empty state, receive screen footer, AI chat (Phase 4).
- Layout: full-screen on mobile, large modal on desktop.
- Per-chain section. Phase 2 ships only Ethereum: "Quick fund 0.05 ETH" button (primary, disabled if rate-limited with countdown), "Use external faucet" link → modal with Alchemy + PoW deep links, "Quick fund 100 USDC" button. Last requested timestamp displayed if recent.
- On Quick Fund tap: card transitions to in-progress state ("Sending 0.05 ETH… usually under 30 seconds"), polls or SSE-driven state change to "✓ 0.05 ETH on its way · 1 confirmation" with link to TxDetail. On failure: error state with retry CTA + external faucet fallback link.

The **single Playwright E2E spec** for this brief is the critical journey from architecture Section 5 line 552: `signup-to-send-confirmed`. It covers magic-link signup, TOTP setup, dashboard load, faucet drip, balance update, send wizard, TOTP confirm, broadcasting state, confirmation. Runtime budget: 90 seconds (generous for chain delays via Anvil).

---

## Architecture pointers

- **Layer:** frontend SPA.
- **Packages touched:**
  - `web/src/pages/Send.tsx` (main send wizard page; routed at `/send/:walletId`)
  - `web/src/components/send/FromWalletPicker.tsx`
  - `web/src/components/send/RecipientAmountForm.tsx`
  - `web/src/components/send/ReviewCard.tsx`
  - `web/src/components/send/BroadcastingState.tsx`
  - `web/src/components/totp/TotpModal.tsx` (refines Phase 1's TOTP entry)
  - `web/src/pages/Funding.tsx` (full-screen / modal funding)
  - `web/src/components/funding/ChainFundingCard.tsx`
  - `web/src/components/funding/ExternalFaucetModal.tsx`
  - `web/src/api/hooks/usePrepareSend.ts`, `useConfirmSend.ts`, `useFaucetRequest.ts`, `useFaucetStatus.ts`
  - `web/src/router.tsx` (add `/send`, `/funding` routes)
  - Playwright spec: `tests/web/e2e/signup-to-send-confirmed.spec.ts`
- **Reads:** `/wallets`, `/portfolio`, `/transactions/{id}`, `/faucet/status`.
- **Writes:** `/transactions/prepare`, `/transactions/confirm`, `/faucet/request`.

---

## Acceptance Criteria

- **AC-phase2-web-007-01:** Given a user clicks "Send" on a wallet card, when they navigate to `/send/:walletId`, then they see Step 1 (from-wallet pre-selected from URL) → tap continue → Step 2. The wizard is breadcrumbed at top: "From wallet → Recipient & amount → Review → Confirm". Tapping a previous step navigates back without losing form state.

- **AC-phase2-web-007-02:** Given Step 2 (RecipientAmountForm), when the user enters an Ethereum address, then on blur the address is validated client-side via the `Address.parse('ethereum', addr)` equivalent in TS (a port from shared schema). Invalid → red border + error text "Invalid Ethereum address". Valid → green check + truncated display below input. Address paste works; QR scan triggers a stub `<QRScanner />` for V2 (out of scope here — clicking the QR icon shows "QR scan coming soon" toast).

- **AC-phase2-web-007-03:** Given the user enters an amount, when validating, then: client-side checks `amount > 0` (numeric input) and `amount + fee_estimate <= available` (using the latest portfolio data from TanStack Query cache). On insufficient balance, shows "Insufficient balance — you have 0.04 ETH" inline. The "Max" shortcut sets `amount = available - fee_estimate_buffer`. The asset picker (ETH/USDC) updates the available figure.

- **AC-phase2-web-007-04:** Given the user taps "Continue" from Step 2, when they land on the Review card, then `usePrepareSend()` mutation fires `POST /transactions/prepare` with the form data. Loading skeleton for ~300ms; on success, the card displays: "Sending 0.05 ETH to 0x1234…abcd", fee estimate ($0.51), total ($143.04), USD equivalent of amount ($142.53). Tapping any field navigates back to Step 2 with the field focused.

- **AC-phase2-web-007-05:** Given the user taps "Confirm" on the Review card, when they advance, then the TotpModal opens. The user enters their 6-digit code; on success the modal transitions inline to a "Broadcasting…" state showing a circular spinner and the transaction id. Backend returns `{transaction_id, status: 'broadcasting'}` from `POST /transactions/confirm`. The optimistic UI shows "Sent" within 500ms.

- **AC-phase2-web-007-06:** Given the SSE event `tx_status_changed{transaction_id, status}` arrives for the in-progress send, when received, the BroadcastingState component updates: `broadcasting → pending` shows "Submitted to network · Waiting for confirmation"; `pending → confirmed` shows "Confirmed ✓" with a CTA "View transaction" linking to detail; `pending → failed` or `expired` shows an error with retry CTA. Polling fallback: if SSE drops, query `GET /transactions/{id}` every 3s.

- **AC-phase2-web-007-07:** Given the user taps "Get testnet tokens" anywhere in the app, when they navigate to the Funding flow, then on mobile they see a full-page screen, on desktop a centered modal. Header: "Get testnet tokens"; subtitle: "These tokens have no real value. They're for testing only on Sepolia." Below: one chain section (Ethereum) with the per-chain card design from spec 04. Tron and Solana sections are deferred to Phase 3 — placeholder cards with "Coming soon" disabled state are NOT shown (cleaner to omit entirely).

- **AC-phase2-web-007-08:** Given the per-chain Funding card for Ethereum, when rendered, then it shows: chain header, user's ETH address (mono, copy button), "Quick fund 0.05 ETH" primary button (disabled with countdown if rate-limited per `useFaucetStatus()`), "Use external faucet" secondary button (opens the External Faucet modal), "Quick fund 100 USDC" primary button. Last-requested-at timestamp shown if within 24h: "Last quick fund · 18h ago".

- **AC-phase2-web-007-09:** Given the user taps "Quick fund 0.05 ETH", when triggered, then `POST /faucet/request {chain: 'ethereum', asset: 'ETH'}` fires. The card morphs to in-progress state ("Sending 0.05 ETH to your Sepolia wallet… Usually under 30 seconds") with a spinner. On success (`faucet_completed` SSE event), card morphs to "✓ 0.05 ETH on its way · 1 confirmation" with link to TxDetail. On failure (5xx, faucet exhausted), card shows "Faucet temporarily unavailable. Try external faucet." with retry button + external faucet link. On race rate-limit (parallel tab), shows "Quick fund just used. Try again in 23h."

- **AC-phase2-web-007-10:** Given the External Faucet modal, when opened from "Use external faucet", then it shows a list of options per spec 04: "Alchemy Sepolia faucet (requires Alchemy login)" → opens https://www.alchemy.com/faucets/ethereum-sepolia in new tab with the user's address pre-filled in the URL hash; "PoW faucet (captcha-based)" → opens sepolia-faucet.pk910.de in new tab. Each option has a brief description. Modal is dismissable.

- **AC-phase2-web-007-11:** Given the user is at "Broadcasting…" in the send flow and they navigate away, when they return to the dashboard or activity list, then the in-progress transaction is visible there (the optimistic Transaction was created server-side). The dashboard's wallet card shows "Sending 0.05 ETH…" inline below the balance until the tx terminalizes.

- **AC-phase2-web-007-12:** Given the Playwright E2E spec `signup-to-send-confirmed.spec.ts`, when running in CI, then it: (1) navigates to landing page; (2) clicks "Sign up", enters email; (3) intercepts the magic-link email (test-mode redirects link to a localStorage-readable token); (4) follows magic link, lands on dashboard; (5) sets up TOTP (test mode uses a fixed seed); (6) wallet provisions; (7) clicks "Get testnet tokens"; (8) Quick Fund 0.05 ETH; (9) waits for SSE `deposit_detected` event (Anvil mines blocks via fixture cheat); (10) dashboard shows balance; (11) clicks Send on wallet card; (12) enters recipient address (a known Anvil-funded test address); (13) enters amount 0.01 ETH; (14) reviews; (15) confirms with TOTP; (16) waits for `tx_confirmed`; (17) asserts success state. Total runtime ≤ 90s.

---

## Out of Scope

- "Speed up" / "Cancel" tx UX: V2.
- QR scanner (camera): V2.
- Address book / contacts in send flow: Phase 3 (introduces Contacts context).
- Multi-asset/batched send: V2.
- Smart contract interactions beyond ERC-20: V2.
- Saving drafts and resuming later: V2 (drafts exist server-side; UX is auto-save in Phase 2 but no "drafts list").
- Keyboard shortcuts in the wizard: V2.

---

## Acceptance Tests / E2E

- [ ] **Playwright E2E `signup-to-send-confirmed.spec.ts`** (the canonical Phase 2 critical journey) — covers AC-12.
- [ ] **Component tests:** RecipientAmountForm validation cases, ReviewCard rendering with various fees, BroadcastingState transitions on SSE events, ChainFundingCard rate-limit countdown.
- [ ] **Hook tests:** `usePrepareSend` invalidation logic, `useFaucetRequest` rate-limit handling.
- [ ] **A11y:** axe-core scan on Send and Funding pages.

---

## Done Definition

- [ ] All ACs verified via tests above.
- [ ] One Playwright E2E covering the full critical journey passes in CI.
- [ ] All TanStack Query hooks use generated types; OpenAPI drift-check passes.
- [ ] `tsc --noEmit` passes.
- [ ] `eslint` clean.
- [ ] Lighthouse a11y ≥ 95 on Send and Funding pages.
- [ ] Single PR. Conventional commit: `feat(web): send wizard + funding flow + e2e [phase2-web-007]`.
- [ ] PR description: screenshots of all four send wizard steps and the funding screen, mobile + desktop, light + dark.
- [ ] **Demo script** committed at `docs/demo-script.md` covering the full Phase 2 happy path: signup → faucet → send → confirmed. ~5-minute walkthrough for portfolio reviewers.

---

## Implementation Notes

- The wizard's step state lives in URL search params (`?step=2&to=0x...&amount=...`) so refresh/back-button work naturally. React Router's `useSearchParams` is sufficient. Don't over-engineer with Zustand for this.
- The TotpModal extends Phase 1's TOTP entry — extract a shared component if not already done. The "broadcasting" state lives inside the modal until terminalized; user can dismiss but the tx continues server-side.
- For the optimistic UI in AC-05, use TanStack Query's optimistic updates: `useMutation({ onMutate: insert into ['transactions'] cache })`. Invalidation on SSE event corrects any drift.
- The "Max" amount calculation: `available - fee_estimate * 1.1` (10% buffer for fee fluctuation). For USDC sends, "Max" is just `available_usdc` (fee is paid in ETH, not USDC).
- The funding flow is a single page, not a wizard. Each chain card is independent. Don't cross-link them.
- For the Playwright E2E, use Anvil's `evm_mine` cheat after each broadcast to auto-confirm. Test-mode SSE uses a faster heartbeat (1s vs 25s) to keep the connection lively. Document the test-mode env vars in the spec.

---

## Risk / Friction

- The send wizard is the most-watched user flow by reviewers. Polish matters: smooth step transitions (Framer Motion's `<AnimatePresence>` for slide animations), consistent loading skeletons, no layout shift between steps. Budget extra time for interaction polish.
- The Playwright E2E is the most fragile test in Phase 2 because it crosses many systems. Use Playwright's `expect.poll` for SSE-event waits with generous timeouts (30s per assertion). On flaky failure in CI, retry once before failing.
- The "Faucet just used (race)" UX (AC-09) is rare but the message must be clear: don't silently reset to the rate-limited state — explain. Reviewers test edge cases.
- The optimistic UI for transactions has a subtle bug surface: if the server returns failure (insufficient balance check on backend), the optimistic row remains in the cache as `broadcasting` until invalidated. Make sure `onError` of the mutation invalidates the cache.
- The wizard's "tap to go back" navigation can lose form state if not carefully wired. Test the back-and-forth manually before merging.
- Phase 2 demo: a reviewer who walks through the full flow will see ~3 minutes of waiting (12 confirmations on Sepolia × ~12s/block = ~2.5 minutes). Demo script must call this out: "Production would tune this to 32 confirmations on mainnet; testnet uses 12 to keep demos under 5 minutes." Without context, a reviewer might think the app is slow.
