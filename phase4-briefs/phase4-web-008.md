---
ac_count: 7
blocks:
- phase4-evals-001
- phase4-polish-001
complexity: L
context: web
depends_on:
- phase4-ai-002
- phase4-ai-005
- phase4-ai-006
- phase4-ai-009
- phase2-web-007
- phase2-web-006
estimated_hours: 4
id: phase4-web-008
phase: 4
sdd_mode: lightweight
state: ready
title: Chat panel UI + dashboard suggestions banner + Playwright E2E
touches_adrs: []
---

# Brief: phase4-web-008 — Chat panel UI + dashboard suggestions banner + Playwright E2E


## Context

This is the user-facing closure of Phase 4. After this brief lands, a user can open the chat panel from anywhere in the SPA, ask the AI assistant about their balances, history, or KYC status, prepare a withdrawal via natural language, confirm with TOTP, and watch the prep card morph into a confirmation card — the full Phase 4 round-trip the architecture promises. Plus the dashboard surfaces proactive suggestion banners from `phase4-ai-009` that the user can act on or dismiss.

**Three surfaces ship here:**

1. **Chat panel** (slide-in right-rail on desktop, full-screen on mobile, accessible from a bottom-right floating button on every authenticated page): a sticky header with conversation title + new-chat button + archive button; a scrollable message list rendering Markdown content, tool-running affordances ("Looking up your balances…"), and prep cards inline; a bottom composer with text input + send button. Conversation switcher on the left (desktop) or via a hamburger menu (mobile) listing the user's recent conversations from `GET /api/v1/ai/conversations`.

2. **Prep card** — the heart of the AI flow's safety: when the SSE handler emits `prepared_action`, a card renders inline in the assistant's message showing the structured preview (chain icon, asset/amount, recipient short address, fee USD, total USD, "requires admin approval" badge if applicable, expiry countdown). Two CTAs: **Confirm** opens the TOTP modal pattern from `phase2-web-007`; **Cancel** simply dismisses the card locally (the server-side prepared action expires naturally). On `prepared_action_superseded`, the card fades out (server already moved it to `superseded`). On expiry, the card greys out with "Expired — start a new send" copy. On successful confirm, the card morphs in place to a "Submitted" state with a CTA "View transaction →".

3. **Dashboard suggestions strip** — a thin row above the portfolio rendering pending suggestions from `GET /api/v1/ai/suggestions`. Each suggestion is a small dismissible card with icon, message, optional CTA (e.g., "Verify now" → `/kyc/start`). Up to 3 visible at once; older ones collapse behind a "Show all (5)" link. Dismissal calls `POST /api/v1/ai/suggestions/{id}/dismiss` and optimistically removes from view.

**The frontend SSE consumer** is the most subtle piece. Unlike `phase2-notifications-001`'s multiplexed `/events` channel (single long-lived connection on login), the AI chat SSE is **per-turn**: the chat composer's "Send" button POSTs to `/api/v1/ai/chat`, opens a fresh `EventSource`-style stream for that one turn, drains 8 event types into local React state, closes when `message_complete` or `error` arrives. A new turn opens a new connection. This matches the architecture's per-turn semantics and keeps each turn fully independent from a UI state perspective. The `useEventStream` hook from `phase2-web-006` is for the multiplexed `/events` channel; this brief introduces a separate `useChatStream(conversationId, text)` hook with its own lifecycle.

**Polling fallback** for chat: if the EventSource drops mid-turn, the hook stops listening and the chat panel marks the assistant message as "interrupted — will check for completion." A polling fallback fires `GET /api/v1/ai/conversations/{id}` after 3 seconds; if the assistant message landed (i.e., the backend's stream completed and persisted), it renders. If still missing after 30 seconds (3 polls), the panel shows an "Unable to receive response" error with retry CTA. This realises the architecture's hybrid SSE + polling discipline (Section 4 line 495–499) for the AI chat path.

**The single Playwright E2E spec** for this brief is `chat-prepare-confirm-send`: open chat panel from dashboard, send "send 0.01 ETH to 0xABC...", assistant streams response with prep card, click Confirm, enter TOTP, watch card morph to Submitted state, navigate to transaction detail, see broadcasting → confirmed. Runtime budget: 60 seconds.

---

## Architecture pointers

- `architecture-decisions.md` §"AI streaming via SSE" (the eight event types — seven enumerated in canon plus `prepared_action_superseded` introduced in `phase4-ai-006` ADR-012), §"Tx status updates: hybrid SSE + polling" (the discipline this brief follows for the per-turn chat stream), §"Frontend stack" (Vite + React + TanStack Query + shadcn/ui).
- **Layer:** frontend SPA.
- **Packages touched:**
  - `web/src/features/ai-chat/` (new feature folder)
    - `ChatPanel.tsx` (the slide-in panel root; manages open/closed state, conversation switching)
    - `ConversationList.tsx` (sidebar list of conversations)
    - `MessageList.tsx` (scrollable, auto-scrolls on new content)
    - `MessageBubble.tsx` (single message; renders Markdown via `react-markdown` + remark-gfm; renders inline tool-running spinners; renders `<PrepCard>` blocks inline)
    - `Composer.tsx` (textarea + send button, keyboard shortcuts)
    - `PrepCard.tsx` (the prep card component — five states: pending, expiring-soon, expired, confirming, submitted)
    - `ToolRunningPill.tsx` (small inline pill: "🔍 Looking up balances…" or "⚡ Preparing send…")
    - `useChatStream.ts` (the SSE consumer hook for the per-turn chat stream)
    - `useChatPolling.ts` (the polling fallback)
    - `useConversations.ts` (TanStack Query hooks for the REST endpoints from `phase4-ai-002`)
    - `usePrepConfirm.ts` (mutation hook calling `POST /api/v1/ai/prepared-actions/{id}/confirm`)
  - `web/src/features/suggestions/`
    - `SuggestionsStrip.tsx` (the dashboard strip)
    - `SuggestionCard.tsx` (single banner)
    - `useSuggestions.ts` (TanStack Query hooks)
  - `web/src/components/FloatingChatButton.tsx` (the bottom-right button across all authenticated pages — wires into `ChatPanel` open state via Zustand or React context)
  - `web/src/types/ai-events.ts` (TypeScript discriminated union mirroring `phase4-ai-006` AC-05's `FrontendEvent`; types generated from the JSON schema committed in `phase4-ai-006`)
  - `web/src/pages/Dashboard.tsx` (extended to render `<SuggestionsStrip />` above existing content)
  - `web/src/App.tsx` (wires `<FloatingChatButton />` and `<ChatPanel />` at root)
  - `web/tests/e2e/chat-prepare-confirm-send.spec.ts` (Playwright E2E)
- **API consumed:**
  - `GET /api/v1/ai/conversations`
  - `GET /api/v1/ai/conversations/{id}`
  - `POST /api/v1/ai/conversations/{id}/archive`
  - `POST /api/v1/ai/chat` (SSE; per-turn stream)
  - `POST /api/v1/ai/prepared-actions/{id}/confirm`
  - `GET /api/v1/ai/suggestions`
  - `POST /api/v1/ai/suggestions/{id}/dismiss`
- **OpenAPI surface change:** no (consumer only).

---

## Acceptance Criteria

- **AC-phase4-web-008-01:** Given the floating chat button, when the user is authenticated and on any in-app page (Dashboard, Wallets, Activity, etc.), then a circular icon-only button is fixed at the bottom-right (`bottom: 24px; right: 24px`) with a chat-bubble Lucide icon; tap toggles the chat panel open/closed. Hidden on the Login page (no point) and during the TOTP modal flow (avoid stacking modals). The button has a subtle pulse animation if there are unread `prepared_action` events the user hasn't acknowledged (visual reminder a prep card is waiting).

- **AC-phase4-web-008-02:** Given the chat panel is opened, when rendered, then: on desktop (≥1024px) it's a 480px-wide right-side drawer with a backdrop scrim; on tablet (768–1024px) it's 380px wide; on mobile (<768px) it takes the full viewport with a top-left close button. The slide-in animation is 200ms ease-out; a `prefers-reduced-motion` media query disables animation per accessibility convention. Open state persists in `sessionStorage` across page navigations within the same tab so the user doesn't lose their chat when navigating around the app.

- **AC-phase4-web-008-03:** Given an existing conversation is selected (or newly created), when the message list renders, then: messages from `GET /api/v1/ai/conversations/{id}` are loaded via TanStack Query (`['ai', 'conversations', id]` key); ordered chronologically; user messages are right-aligned with neutral bubble; assistant messages are left-aligned with subtle accent background; tool-result blocks are rendered as collapsed `<details>` ("View tool data") that expand on click — kept compact because raw tool JSON is rarely interesting to the user but IS sometimes useful for debugging; prep cards render inline at their position in the message stream (not floating). Auto-scroll: on new message arrival, if the user is within 100px of the bottom, smooth-scroll to bottom; if they've scrolled up to read, do NOT auto-scroll — show a small "↓ New messages" jump button.

- **AC-phase4-web-008-04:** Given the user types a message and presses Enter (or clicks Send), when the chat composer submits, then: (1) `useChatStream(conversationId, text)` opens a fetch-stream to `POST /api/v1/ai/chat` with `Accept: text/event-stream` and body `{conversation_id?, text}`; (2) the user message appears immediately in the list (optimistic insertion); (3) an "Assistant is thinking…" pill renders below; (4) on first `content_delta`, the pill is replaced by a streaming assistant bubble that grows char-by-char as deltas arrive (use a state variable, not direct DOM manipulation); (5) on `tool_use_start`, render a `<ToolRunningPill>` inline with friendly copy (`get_balances → "Looking up your balances…"`, `get_recent_transactions → "Fetching your recent transactions…"`, `get_kyc_status → "Checking your verification status…"`, `prepare_send_transaction → "Preparing the send…"`); (6) on `tool_use_result`, the pill collapses to a check-marked completion state ("✓ Got your balances"); on `is_error=true`, it's a warning state ("⚠ Service temporarily unavailable") and the assistant continues; (7) on `prepared_action`, render an inline `<PrepCard>` immediately after the current text bubble; (8) on `prepared_action_superseded` for an earlier prep card in this conversation, that earlier card fades out over 300ms; (9) on `message_complete`, the streaming bubble settles, the SSE connection closes, the input re-enables. The full event sequence per `phase4-ai-006` AC-13's invariants is honoured.

- **AC-phase4-web-008-05:** Given the SSE connection drops mid-turn (network blip, server restart), when detected (`EventSource error` or fetch-stream abort), then: (1) the streaming assistant bubble freezes at its current content with an "(interrupted)" suffix; (2) `useChatPolling` activates and polls `GET /api/v1/ai/conversations/{id}` every 3 seconds (cap 10 attempts); (3) on poll, if the latest message is `role='assistant'` newer than the user's last message, the freeze-state bubble is replaced with the full server-persisted content (the backend completed the turn even though our stream dropped); (4) if 10 polls elapse without finding a new assistant message, render an "Couldn't receive the response — try again?" error in place of the bubble with a retry CTA that re-submits the user's last message. Tested via Playwright with network throttling. This realises the polling-fallback discipline.

- **AC-phase4-web-008-06:** Given a `<PrepCard>` is rendered, when in pending state, then: it shows the structured preview (chain icon + asset, formatted amount + asset symbol, "to" label + recipient address with copy-to-clipboard, fee USD, total USD with subtle line-divider, "requires admin approval (~1-2h)" badge if `requires_admin=true`, expiry countdown like "Expires in 4:32"); two buttons: primary "Confirm" (CTA color), secondary "Cancel" (subtle); the countdown updates every second client-side; when `expires_at - now < 30s` the countdown turns red. On Cancel: card is dismissed locally (state-only; backend supersedes naturally on next prepare or expires). On Confirm: opens the TOTP modal (the same `<TotpConfirmModal>` from `phase2-web-007` with `onConfirm` callback wired to `usePrepConfirm.mutate({prepared_action_id, totp_code, idempotency_key})`).

- **AC-phase4-web-008-07:** Given the TOTP modal's confirm callback, when invoked, then: (1) calls `POST /api/v1/ai/prepared-actions/{id}/confirm` with body `{totp_code, idempotency_key: <UUIDv4 generated client-side>}`; (2) the modal shows in-flight spinner; (3) on 202 success: modal closes, `<PrepCard>` morphs (200ms cross-fade) to "Submitted" state showing the new transaction id + status (`broadcasting` or `awaiting_admin`) + "View transaction →" CTA linking to `/transactions/<id>`; the prep card's TanStack Query cache for `['ai', 'conversations', id]` is invalidated so a refetch picks up any server-side message updates; (4) on 403 `identity.totp_invalid`: modal stays open with "Invalid code — please try again" inline error and clears the input; (5) on 409 `ai.prepared_action_expired`: modal closes; the prep card flips to "Expired" state (gray, no buttons); a toast appears "This action expired. Start a new send."; (6) on 409 `ai.prepared_action_superseded`: modal closes; toast "This action was replaced by a newer one"; (7) other errors: toast with the error envelope's `message` field. The `idempotency_key` is generated once per Confirm-button click (stored in component state); if the user retries due to network blip, the same key replays the cached response per `phase4-ai-005` AC-12.

- **AC-phase4-web-008-08:** Given the conversation list (sidebar on desktop, hamburger menu on mobile), when rendered, then: shows the user's conversations from `GET /api/v1/ai/conversations?include_archived=false&limit=20` ordered by `last_message_at DESC NULLS LAST`; each row shows truncated title (or "New conversation" if `title=null` until V2 auto-titling), relative time ("3m ago", "Yesterday", "Mar 14"), message_count badge if >0; clicking a row sets the active conversation; "+ New conversation" button at the top creates a fresh state (no API call until first message — first send POSTs to `/api/v1/ai/chat` without `conversation_id`, server lazy-creates per `phase4-ai-006` AC-03); archive icon on hover (desktop) or via long-press (mobile) calls `POST /api/v1/ai/conversations/{id}/archive` and removes from the list with optimistic update.

- **AC-phase4-web-008-09:** Given the markdown-rendering of assistant content, when an assistant text block contains common formatting, then: bold/italic/inline-code render correctly; bulleted/numbered lists render with appropriate spacing; URL-shaped tokens auto-link with `rel="noopener noreferrer" target="_blank"`; raw HTML in markdown is **stripped** (no `dangerouslySetInnerHTML` anywhere — react-markdown's default sanitisation suffices); code blocks render in a monospace block with a tiny "Copy" button (uses navigator.clipboard); transaction hashes (regex match `^0x[a-f0-9]{64}$|^[1-9A-HJ-NP-Za-km-z]{43,88}$`) inside text are auto-linked to the chain explorer (heuristic: 64-hex → Ethereum/Tron, base58 → Solana — same heuristic as the existing TxDetail page).

- **AC-phase4-web-008-10:** Given the dashboard `<SuggestionsStrip>`, when rendered, then: pulls from `GET /api/v1/ai/suggestions` via TanStack Query (`['ai', 'suggestions']` key, refetch on window focus + every 5 minutes); shows up to 3 cards in a horizontal flexbox (mobile: stacked vertically); each card has icon (per-kind: warning for low_balance, info for kyc_incomplete, clock for large_pending_withdrawal), message text, optional CTA button rendering the suggestion's payload `cta_label` linking to `cta_route`, and a small "✕" dismiss button; on dismiss tap: optimistic removal, `POST /api/v1/ai/suggestions/{id}/dismiss` fires; on error: card re-appears with toast. If >3 pending: show "+ N more" button that expands the strip to vertical-list. The strip is hidden entirely if zero pending. Reused on `Wallets` and `Activity` pages too if it makes sense (V2 decision — V1 dashboard only).

- **AC-phase4-web-008-11:** Given the Playwright E2E spec `chat-prepare-confirm-send.spec.ts`, when run against a seeded test user (Anvil + Sepolia testnet, similar to `phase2-web-007`'s E2E setup), then it executes: (1) login with magic link + TOTP; (2) navigate to dashboard; (3) click the floating chat button — panel slides in; (4) type "send 0.01 ETH to 0x70997970C51812dc3A010C7d01b50e0d17dc79C8" + Enter; (5) wait for assistant streaming response — assert "Looking up" pills appear and resolve; (6) wait for `<PrepCard>` to render — assert it shows "0.01 ETH" + "to 0x7099…" + a fee estimate; (7) click Confirm — TOTP modal opens; (8) enter TOTP from test seed; (9) assert prep card morphs to "Submitted" within 5s with a transaction id; (10) click "View transaction →" — navigate to `/transactions/<id>`; (11) assert status `broadcasting` or `pending`; (12) wait up to 30s for `confirmed`. Total runtime budget: 90 seconds. The test seeds a recorded Anthropic conversation trace via Tier-2 fixture stub (per `phase4-ai-006` AC-10 pattern) so it doesn't burn API quota in CI; flag `--against-real-anthropic` allows manual runs for true integration validation.

- **AC-phase4-web-008-12:** Given accessibility requirements, when the chat panel is interacted with via keyboard, then: `Tab` cycles through composer → send button → conversation list items → message list (focus trap inside panel when open); `Esc` closes the panel; the prep card's Confirm/Cancel buttons are keyboard-reachable; the TOTP modal traps focus per `phase2-web-007`'s existing pattern; ARIA: panel is `role="complementary" aria-label="AI assistant chat"`, prep card is `role="region" aria-label="Send transaction confirmation"`, streaming text bubble has `aria-live="polite"` so screen readers announce new content (without spamming on every char delta — debounce announces at sentence boundaries via `aria-busy="true"` during streaming, set to false at `message_complete`). Tested via `axe-playwright` plugin: zero serious/critical accessibility violations on the panel open state.

---

## Out of Scope

- Voice input / speech-to-text in the composer: V2.
- File attachment upload in chat (e.g., paste a CSV of addresses): V2.
- Auto-generated conversation titles: V2 (server-side worker per `phase4-ai-002` Out-of-Scope).
- Conversation search ("find my chat about that 0x456 address"): V2; the V2 brief consumes `phase4-ai-007`'s tx-memory retriever.
- Multi-language UI strings (Ukrainian, Russian translations): V2 — V1 ships English UI; the assistant itself can respond in any language per the system prompt.
- Streaming markdown re-rendering optimisation: V2 — V1 re-runs the full markdown parser on every delta (acceptable for ~2s turns, would matter for ~30s turns).
- Stop / cancel button while assistant is streaming: V2 (per `phase4-ai-006` Out-of-Scope — backend doesn't support stop yet).
- Suggestion strip on non-Dashboard pages: V2.
- Chat history full-page view (vs. side panel): V2.
- Swipe-to-archive on mobile conversation list: V2.

---

## Dependencies

- **Code dependencies:** all backend Phase 4 strict briefs (`ai-001` through `ai-009`) shipped to staging; existing `phase2-web-006` provides `useEventStream` pattern and shadcn/ui setup; `phase2-web-007` provides `<TotpConfirmModal>` reusable component.
- **Data dependencies:** all backend migrations 001–007 applied; the suggestions evaluator cron is producing rows in dev/staging.
- **External dependencies:** `react-markdown@^9` + `remark-gfm@^4` (markdown rendering with GitHub-flavoured-markdown); `lucide-react@^0.440` (icons; Phase 1 likely already pinned, verify); `axe-playwright@^2` (a11y testing; new dev dep).

---

## Test Coverage Required

- [ ] **Component tests (Vitest + React Testing Library):**
  - `ChatPanel.test.tsx` — opens/closes; sessionStorage persistence; mobile vs desktop responsive snapshot.
  - `MessageBubble.test.tsx` — renders user vs assistant styling; markdown rendering; tool-result `<details>` collapse/expand; transaction-hash auto-linking.
  - `PrepCard.test.tsx` — five states (pending, expiring-soon, expired, confirming, submitted); countdown updates; Confirm/Cancel actions wired; `requires_admin` badge.
  - `ToolRunningPill.test.tsx` — friendly copy per tool name; success vs error completion states.
  - `Composer.test.tsx` — Enter submits, Shift+Enter newlines; disabled while turn in flight; max-length enforced (8000 chars per `phase4-ai-006` AC-01).
  - `SuggestionsStrip.test.tsx` — renders 0/1/3/5 suggestions; dismissal optimistic update; expand-collapse for >3.
  - `SuggestionCard.test.tsx` — per-kind icon mapping; CTA renders if payload has `cta_label`.

- [ ] **Hook tests (Vitest):**
  - `useChatStream.test.ts` — stub a controlled fetch-stream that emits a fixture sequence (the same fixtures from `phase4-ai-006` AC-10's `tests/ai/conversations/fixtures/conv_*.jsonl` — re-use as JSON-stream input); assert resulting state changes match expected (the equivalent "expected trace" file from the backend).
  - `useChatPolling.test.ts` — mocks fetch with delayed assistant message arrival; polling resolves at attempt 2; gives up after 10.
  - `useConversations.test.ts` — list/get/archive happy paths.
  - `usePrepConfirm.test.ts` — happy 202; 403 invalid totp; 409 expired/superseded; idempotency key reuse.
  - `useSuggestions.test.ts` — list and dismiss; optimistic update; rollback on error.

- [ ] **Playwright E2E:** `chat-prepare-confirm-send.spec.ts` — covers AC-11.

- [ ] **Accessibility tests:** `axe-playwright` runs against the chat panel open state; assert zero serious/critical violations. Covers AC-12.

- [ ] **Visual regression (optional, opportunistic):** Storybook snapshots for `<PrepCard>` (5 states) and `<SuggestionCard>` (3 kinds) — not blocking CI; helps reviewer grok the visual surface.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] TypeScript types for the 8 SSE event variants are generated from `phase4-ai-006`'s JSON schema (`docs/api/ai-sse-events.schema.json`); the CI drift check (existing `openapi-types-check`) extended to include this schema.
- [ ] All TanStack Query hooks use generated types from `docs/api-contract.yaml`; OpenAPI drift-check passes.
- [ ] `tsc --noEmit --strict` clean.
- [ ] `eslint` + `prettier` clean.
- [ ] No raw `dangerouslySetInnerHTML` used anywhere (lint rule already in place from Phase 1).
- [ ] `axe-playwright` reports zero serious/critical issues on the chat panel.
- [ ] One Playwright E2E spec passes against the staging environment within the 90-second budget.
- [ ] `react-markdown@^9`, `remark-gfm@^4`, `axe-playwright@^2` added to `package.json` dev/runtime as appropriate.
- [ ] `web/src/types/ai-events.ts` committed; the type generation script in `web/scripts/generate-types.ts` extended to ingest the new schema.
- [ ] Single PR. Conventional commit: `feat(web): chat panel + prep card + suggestions strip [phase4-web-008]`.
- [ ] PR description: a screenshot grid showing the chat panel on desktop + mobile, prep card in three states (pending, confirming, submitted), suggestions strip with three banner kinds. A 30-second Loom-style screen recording attached if practical.

---

## Implementation Notes

- **`useChatStream` is the most subtle file.** Because the architecture's chat SSE is `POST` (not `GET`-based EventSource), native `EventSource` doesn't work — use `fetch` with `ReadableStream` parsing per the SSE wire format (`event: <name>\ndata: <json>\nid: <id>\n\n`). The parser is ~30 lines: split on `\n\n`, parse each block. There's a small npm package `@microsoft/fetch-event-source` if preferred (popular for this use case); decide based on existing dependency footprint. Document the choice in the file.
- **TanStack Query cache invalidation on `message_complete`:** the streaming hook accumulates content in local React state during the turn; on `message_complete`, invalidate `['ai', 'conversations', id]` so the canonical (server-persisted) message replaces the streamed-state representation. This avoids drift if the server's persisted content differs slightly from what the client streamed.
- **Optimistic insertion of user message** before server confirms: when Send fires, immediately append to local state with a temp id `optimistic-<uuid>`; the next conversation refetch overwrites with the real server-side message_id. If the stream errors before any backend persistence, the optimistic message stays in local state with an "(failed to send)" indicator — explicit not removed, so the user can retry the text.
- **The 8 event types map cleanly to React state updates** — write a single reducer in `useChatStream.ts` that takes `(state, FrontendEvent)` and returns new state. Reducer is pure; testable in isolation; clean diffs.
- **Prep card's countdown** uses a single `setInterval(..., 1000)` registered when the card mounts in pending state; cleared on unmount or state transition. Don't have one timer per card — if the user has multiple in-flight prep cards (rare but possible per `phase4-ai-005`'s supersession rules, only one is `pending` at a time per conversation, so timer count is bounded), just one timer per card is fine.
- **Idempotency key for prep confirm**: generate via `crypto.randomUUID()` ONCE when the Confirm button is first clicked; store in component state; reuse on retries. Don't generate fresh on every click — that defeats idempotency.
- **`prefers-reduced-motion`** disables the slide-in animation, the prep card's morph, AND the streaming-text-grow animation (instead, content appears whole at each `content_delta`). The CSS uses `@media (prefers-reduced-motion: reduce)` queries throughout. shadcn/ui components mostly handle this; verify the custom panel/prep-card animations follow suit.
- **`SuggestionsStrip` placement on Dashboard** is above the portfolio summary, below the page header. Don't push it to the very top — users are conditioned to skip "banner regions"; placing it inline-with-content increases attention.
- **`<details>` collapse for tool-result blocks** keeps the message list scannable. The summary text is `tool_use_result · ${toolName}`; the body is `<pre><code>{JSON.stringify(output, null, 2)}</code></pre>`. Power users / debugging — happy. Casual users — invisible.

---

## Risk / Friction

- **The fetch-streaming SSE parser is unforgiving on edge cases.** A `\r\n` instead of `\n` in the wire format breaks naive parsing. Either use a vetted library (`@microsoft/fetch-event-source`) or write the parser carefully with explicit tests covering CRLF + LF + ending-without-final-blank-line cases. The Phase 4 backend (`phase4-ai-006`) emits LF-only; document the assumption.
- **Markdown re-render performance during streaming.** Every `content_delta` re-runs `react-markdown` on the full accumulated text. For ~2KB messages this is fine (<10ms per render). If turns get longer in V2 (e.g., 10KB code-block-heavy responses), virtualisation or incremental parsing is needed. Document the V1 acceptable scale.
- **Auto-linking transaction hashes** is heuristic and can false-positive on regular text containing 64-hex strings. Mitigation: link only inside `<code>` markdown spans (a stricter regex); document the constraint.
- **Mobile keyboard coverage of the composer** — when the on-screen keyboard opens, it can hide the input. Use `inputMode="text"` and `autoCapitalize="sentences"`; on iOS Safari, `position: sticky` on the composer + `100dvh` panel height handles most cases. Test on real iOS Safari + Android Chrome; document any known bugs.
- **The Playwright E2E uses recorded Anthropic fixtures** to avoid CI quota burn. The fixture maps to a synthetic prompt; if a developer changes the system prompt, the prompt-hash drift check in `phase4-ai-006` AC-10 catches it server-side, and this E2E will fail because the response shape changes. Documented as feature, not bug.
- **`axe-playwright` baseline must be set carefully.** Some shadcn/ui components have known low-severity violations (color-contrast on disabled buttons, etc.); accept those at "moderate" severity, fail only on serious/critical. Configure in the test setup.
- **A reviewer might ask for dark-mode parity.** If Phase 1's design tokens already support dark mode, the chat surfaces inherit; if not, document as V2. The portfolio project's design system likely already has it; verify and inherit.
- **The conversation list pagination is not infinite-scroll in V1** — top 20 only, with a "Show all" link as V2 stub. Acceptable: a single user rarely has >20 conversations in V1 demo timeframes.
