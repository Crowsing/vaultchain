---
ac_count: 6
blocks: []
complexity: L
context: admin
depends_on:
- phase3-kyc-001
- phase3-kyc-002
- phase1-admin-002
- phase1-admin-003
estimated_hours: 4
id: phase3-admin-005
phase: 3
sdd_mode: lightweight
state: ready
title: Admin KYC review UI (queue + applicant detail + Sumsub iframe)
touches_adrs: []
---

# Brief: phase3-admin-005 — Admin KYC review UI (queue + applicant detail + Sumsub iframe)


## Context

This brief delivers the admin-side KYC review interface — the UI portion of the Sumsub-integrated KYC flow. Sumsub provides a "review iframe" that admins use to look at submitted documents, view extracted data, and trigger manual overrides. This brief embeds that iframe within VaultChain's admin shell, adds a queue listing applicants needing attention, and an applicant detail page.

UI surface:

1. **`/admin/kyc/queue`** — paginated list of applicants. Filters: `status` (`needs_review`, `auto_approved_recently`, `auto_rejected`, `tier_2_request`), `chain_activity` (any user with on-chain activity ranks higher visually), `submitted_within` (last 24h, 7d, 30d). Each row: user email, applicant_id, level, current_tier, latest review_answer, reject_labels (if any), submitted_at, "Review" button.

2. **`/admin/kyc/applicants/{applicant_id}`** — detail page. Top: user info (email, account age, KYC tier history, last 5 transactions). Middle: Sumsub review iframe embedded via the Sumsub-provided URL (loaded via a backend call to `SumsubAdapter.get_admin_review_url(applicant_id)` — short-lived signed URL). Bottom: action buttons — "Manually approve to tier_1" (with TOTP), "Manually reject" (with TOTP + reason), "Request additional documents" (passes through to Sumsub via API).

3. **`POST /admin/api/v1/kyc/applicants/{id}/manual-tier`** — backend endpoint for manual overrides. Body: `{target_tier: 'tier_1' | 'tier_0_rejected', reason, totp_code}`. Validates TOTP, applies the transition via `kyc.application.use_cases.admin_set_tier`, publishes `kyc.TierChanged` (same event as auto-transition). Audit row records the manual action.

Lightweight SDD mode: fewer ACs, more thumbnail descriptions; behavior validated by Playwright E2E + a couple of contract tests for the manual-tier endpoint. The visual polish is real but the business logic is thin (mostly delegation to existing kyc-001/002 use cases + a new manual-tier use case).

---

## Architecture pointers

- **Layer:** presentation (admin web app) + small application addition (manual-tier use case).
- **Packages touched:**
  - `admin-web/src/pages/kyc/queue.tsx`
  - `admin-web/src/pages/kyc/applicant-detail.tsx`
  - `admin-web/src/api/kyc.ts` (queue + detail + manual-tier client)
  - `admin-web/src/components/sumsub-review-iframe.tsx`
  - `admin-web/src/components/totp-modal.tsx` (reused from admin-006 if delivered first; else extracted here)
  - `kyc/application/use_cases/admin_set_tier.py` (new)
  - `kyc/web/admin_routes.py` (new endpoints under `/admin/api/v1/kyc/*`)
  - `kyc/infra/sumsub_adapter.py` (extend with `get_admin_review_url` and `request_additional_documents`)
- **Reads:** `kyc.applicants`, `kyc.kyc_events`, `identity.users`, `transactions.transactions` (for the user's recent activity sidebar).
- **Writes:** `kyc.applicants` (manual tier change), `audit.events` (admin manual override audit).
- **Publishes events:** `kyc.TierChanged{actor='admin'}` — same event, distinguished by actor.
- **Migrations:** none.
- **OpenAPI:** new admin endpoints in `docs/openapi/kyc-admin.yaml`.

---

## Acceptance Criteria

- **AC-phase3-admin-005-01:** Given an admin navigates to `/admin/kyc/queue`, when authenticated, then the page renders a paginated list with filters per Context. Sort default: `submitted_at DESC`. Empty state shows "No KYC submissions in the selected window."

- **AC-phase3-admin-005-02:** Given the queue row's "Review" button click, when activated, then navigates to `/admin/kyc/applicants/{applicant_id}` showing the applicant detail. The Sumsub iframe loads via the backend-provided URL; CSP `frame-src https://api.sumsub.com` permits embedding.

- **AC-phase3-admin-005-03:** Given the manual-tier action, when admin clicks "Manually approve to tier_1", when TOTP modal opens and admin enters code, then `POST /admin/api/v1/kyc/applicants/{id}/manual-tier {target_tier:'tier_1', reason:'<required>', totp_code}` fires. On 200, page reloads with new tier. On 401 invalid TOTP, modal shows error inline.

- **AC-phase3-admin-005-04:** Given the `AdminSetTier(applicant_id, target_tier, admin_id, reason, request_id)` use case, when invoked, then within UoW: (1) load applicant; (2) verify the target_tier is reachable from current per the tier transition state machine (admin overrides bypass Sumsub but still respect the state machine — e.g., can't go from tier_0_rejected to tier_2 in one step); (3) UPDATE applicant; (4) INSERT `kyc.kyc_events` with `event_type='manualTierChange'` and `raw_payload={admin_id, reason, from_tier, to_tier}`; (5) audit row in `audit.events`; (6) publish `kyc.TierChanged{actor='admin', actor_admin_id=admin_id, reason}`.

- **AC-phase3-admin-005-05:** Given the queue's filter "needs_review", when applied, then the API returns applicants with `review_answer = 'YELLOW'` OR `review_answer = 'RED' AND reviewRejectType = 'RETRY'` — applicants where Sumsub couldn't auto-decide. These are the high-priority work items.

- **AC-phase3-admin-005-06:** Given the applicant detail page sidebar, when rendered, then it shows: (1) user email, account age, current tier, kyc tier history (from `kyc.kyc_events` — last 10 events with timestamps); (2) chain activity summary (last 5 confirmed transactions across all chains, total value USD); (3) flags: "Repeat KYC attempts" (if `kyc_events` count > 3 for this applicant), "First send to fresh address" (cross-checked with the routing decisions table), "High-velocity user" (>5 txs in last 24h).

- **AC-phase3-admin-005-07:** Given the Sumsub iframe loads, when the admin reviews the applicant inside it, when Sumsub fires its own webhook to our endpoint with the admin-side decision (Sumsub admin actions also trigger webhooks), then our `kyc-002` webhook handler processes normally — same path. The admin's actions in the iframe are recorded by Sumsub as their reviewer; our webhook captures the result.

- **AC-phase3-admin-005-08:** Given the OpenAPI spec for admin KYC endpoints, when `docs/openapi/kyc-admin.yaml` is committed, then it includes: `GET /admin/api/v1/kyc/applicants` (queue), `GET /admin/api/v1/kyc/applicants/{id}` (detail), `POST /admin/api/v1/kyc/applicants/{id}/manual-tier`, `GET /admin/api/v1/kyc/applicants/{id}/sumsub-review-url` (returns the iframe URL).

- **AC-phase3-admin-005-09:** Given Playwright E2E test runs, when admin logs in, navigates to queue, opens an applicant, manually approves to tier_1 with TOTP, then: (1) the applicant row updates; (2) the user's `/api/v1/kyc/status` reflects tier_1 within 60s (cache TTL); (3) the audit log captures the manual override.

- **AC-phase3-admin-005-10:** Given the manual override use case, when admin tries an invalid transition (e.g., `tier_0_rejected → tier_2` in one step — manual overrides bypass Sumsub but still respect the auto-state-machine's reachability rules; `tier_2` requires an enhanced-KYC review), when validated, then `400 Bad Request` with `{error: 'invalid_transition'}`. The state machine in `kyc.domain.services.tier_transition` is the single source of truth.

---

## Out of Scope

- Bulk operations (approve N applicants at once): V2.
- AI-assisted review suggestions ("this applicant looks suspicious, here's why"): never (out of scope).
- Document re-request workflow customization beyond Sumsub's API call: V2.
- Per-admin queue assignment / claim ownership: V2.

---

## Dependencies

- **Code dependencies:** `phase3-kyc-001/002`, `phase1-admin-002` (admin shell + TOTP), `phase1-admin-003` (design system), `phase2-audit-001` (audit subscriber).
- **External dependencies:** Sumsub admin review URL endpoint (POST `https://api.sumsub.com/resources/applicants/{id}/oneSecondReview`).

---

## Test Coverage Required

- [ ] **Application tests:** `tests/kyc/application/test_admin_set_tier.py` — happy paths for each allowed transition; invalid transition raises; audit + event publication. Covers AC-04, AC-10.
- [ ] **Adapter tests:** vcrpy cassette for `SumsubAdapter.get_admin_review_url` against sandbox. Sumsub returns short-lived URL.
- [ ] **Contract tests:** `tests/api/test_admin_kyc_endpoints.py` — Schemathesis fuzz; auth required; TOTP validation. Covers AC-08.
- [ ] **Frontend component tests:** lightweight — assert queue table renders, filter changes refetch, applicant detail loads iframe (mocked URL). Vitest + Testing Library.
- [ ] **E2E:** `tests/e2e/admin-kyc-flow.spec.ts` — Playwright; admin navigates queue → opens applicant → approves with TOTP → verifies tier change in DB and via API. Covers AC-09.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] OpenAPI spec lints clean.
- [ ] Frontend coverage gate (~70% on this brief's components).
- [ ] Backend coverage gates (per-directory).
- [ ] `mypy --strict` (backend) + `tsc --noEmit` (frontend) pass.
- [ ] CSP updated to allow Sumsub iframe.
- [ ] One new use case (`AdminSetTier`) with tests.
- [ ] Single PR. Conventional commit: `feat(admin): kyc review queue + applicant detail + sumsub iframe [phase3-admin-005]`.

---

## Implementation Notes

- The Sumsub admin review URL (`oneSecondReview` endpoint per their docs) returns a short-lived URL embeddable in our admin shell. Our backend hits Sumsub once, caches the URL with a 5-min TTL; admin's iframe loads it directly. Don't try to proxy the iframe.
- The TOTP modal component is reusable — extract once and reuse in admin-006.
- The "high-velocity user" flag (AC-06) is a soft signal — render as an info badge. Don't auto-block any actions.
- The kyc_events history sidebar is reverse-chronological, raw event types preserved (not redacted — admin views are privileged). Note: the raw_payload was already redacted at insert time (kyc-002 AC-05). Admin sees the redacted version + the structured fields (review_answer, reject_labels). True PII (e.g., the document images) lives in Sumsub, accessed via the iframe.
- The empty queue state (no submissions in window) should be friendly — design-system has a "no-results" component. Show "All caught up — no submissions awaiting review." with the timeframe filter visible to remind admin to expand if needed.

---

## Risk / Friction

- The Sumsub iframe is a third-party UI we don't control. If Sumsub changes their UI in breaking ways, our admin's review experience changes. Mitigation: track Sumsub's breaking-change communications; their releases are reasonably stable.
- CSP for Sumsub iframe: ensure `frame-src https://api.sumsub.com` is set in admin shell's CSP headers. Verify in CI via a header inspection test against staging.
- The "actor=admin" branch of `kyc.TierChanged` event: consumers (e.g., notifications) may want to message users differently for admin overrides ("Your KYC was manually approved by our team") vs Sumsub auto-approvals. Phase 3 doesn't differentiate in messaging; V2 does. Document.
- The Playwright E2E test depends on a working admin TOTP flow + a seeded test applicant. Use the test fixtures from phase1-admin-002 for TOTP and a kyc test fixture creating an applicant in `tier_0` state. Document fixture composition.
- Manual override use case's "validate transition is allowed" rule (AC-10): admin can't skip multiple steps. This is a feature, not a bug — admins shouldn't manually grant tier_2 without going through enhanced KYC (V2). If a reviewer pushes back on the rigidity, the answer is "the audit trail is cleaner if every transition has a clear cause; multi-step jumps obscure attribution."
