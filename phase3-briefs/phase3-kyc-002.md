---
ac_count: 12
blocks:
- phase3-kyc-003
- phase3-admin-005
complexity: M
context: kyc
depends_on:
- phase3-kyc-001
estimated_hours: 4
id: phase3-kyc-002
phase: 3
sdd_mode: strict
state: ready
title: Sumsub webhook handler + tier transitions + PII redaction
touches_adrs: []
---

# Brief: phase3-kyc-002 — Sumsub webhook handler + tier transitions + PII redaction


## Context

Sumsub processes KYC submissions asynchronously and notifies our backend via webhooks. The architecture (Section 6.4) specifies HMAC-SHA256 webhook verification — same pattern as Resend (notifications) and Stripe (payments, future). This brief delivers the webhook receiver, signature verification, **PII redaction before persistence**, tier transition logic, and the `kyc.TierChanged` event publication.

Sumsub webhook payload shape (relevant subset):
```json
{
  "applicantId": "5b9bb55c0a975a35a13ad...",
  "inspectionId": "5b9bb...",
  "applicantType": "individual",
  "correlationId": "...",
  "levelName": "basic-kyc-level",
  "externalUserId": "<our user_id UUID>",
  "type": "applicantReviewed",
  "reviewResult": {
    "reviewAnswer": "GREEN",                  // or "RED" or "YELLOW"
    "rejectLabels": ["DOCUMENT_DAMAGED"],     // present on RED
    "reviewRejectType": "RETRY",              // RETRY (resubmission allowed) or FINAL
    "moderationComment": "...",               // free-text from human reviewer (PII risk)
    "clientComment": "..."
  },
  "reviewStatus": "completed",
  "createdAtMs": 1735000000000,
  "applicantMemberOf": [...]                  // sometimes contains email/phone
}
```

The webhook handler:
1. **Signature verification.** Sumsub sends `X-Payload-Digest` header (HMAC-SHA256 of body keyed by `SUMSUB_SECRET_KEY`). Reject if mismatch.
2. **Idempotency.** A `correlationId` (or `applicantId + reviewStatus + createdAtMs` as fallback) UNIQUE on `kyc.kyc_events.event_dedupe_key` ensures replay-safety.
3. **PII redaction.** **Before storing the raw payload**, walk the JSON and scrub: `email`, `phone`, `firstName`, `lastName`, `dob`, `country`, document numbers (any field name matching `/document|passport|id_number/i`), `address` fields, GPS coords, `moderationComment` and `clientComment` (free-text reviewer notes that may contain PII). Replace with `"<redacted>"` string. The redacted JSON is what goes into `kyc.kyc_events.raw_payload`.
4. **Tier transition.** Apply the state machine: review_answer = GREEN → tier_1 (assuming basic-kyc-level); RED with `reviewRejectType=RETRY` → keep current tier (likely tier_0) but record reject_labels (so admin sees what to address); RED with FINAL → tier_0_rejected. YELLOW (manual review pending) → keep current tier, no transition; record event.
5. **Publish `kyc.TierChanged{user_id, applicant_id, from_tier, to_tier, review_answer, reject_labels, request_id}`** if the tier changed. This event is consumed by Notifications (kyc-002 doesn't notify directly — keep concerns separate).

Tier transition state machine (this is the **automated** webhook-driven function `tier_transition.apply(current_tier, review_answer, reject_type)`, a pure function. Manual admin overrides are a separate path through `admin-005`'s `AdminSetTier` use case and bypass this function):

```
tier_0 + GREEN(basic) → tier_1
tier_0 + RED(RETRY)   → tier_0 (record reject_labels, no transition)
tier_0 + RED(FINAL)   → tier_0_rejected
tier_0 + YELLOW       → tier_0 (no transition)

tier_0_rejected + ANY → tier_0_rejected  (V1: SINK. No automated recovery —
                                          Sumsub `RED + FINAL` is permanent.
                                          Recovery requires admin-005 manual override.)

tier_1 + GREEN(enhanced)  → tier_2  [V2, not implemented in V1]
tier_1 + RED(any)         → tier_1 (Sumsub doesn't downgrade)
```

Important: **Sumsub doesn't auto-downgrade tiers.** If a tier_1 user later submits another document that's rejected, they stay tier_1. Admin can manually downgrade via `phase3-admin-005`.

---

## Architecture pointers

- **Layer:** application (handler + state machine logic) + presentation (webhook endpoint).
- **Packages touched:**
  - `kyc/application/handlers/sumsub_webhook_handler.py`
  - `kyc/domain/services/tier_transition.py` (pure function, easy property test)
  - `kyc/infra/pii_redactor.py` (recursive JSON walker)
  - `kyc/infra/sumsub_signature_verifier.py` (HMAC-SHA256 verifier)
  - `kyc/web/webhook_routes.py` (POST endpoint, public — no auth, signature is the auth)
  - `kyc/infra/migrations/<ts>_kyc_event_dedupe.py` (adds UNIQUE constraint on event_dedupe_key)
- **Reads:** `kyc.applicants` (load + update).
- **Writes:** `kyc.applicants` (tier transitions), `kyc.kyc_events` (event log with redacted payload).
- **Publishes events:** `kyc.TierChanged` — registered. `kyc.WebhookReceived{applicant_id, event_type}` — optional small audit signal.
- **Migrations:** add UNIQUE constraint on `kyc.kyc_events(applicant_id, event_dedupe_key)`.
- **OpenAPI:** `POST /api/v1/kyc/webhook` — public endpoint with explicit "auth via X-Payload-Digest" note.

---

## Acceptance Criteria

- **AC-phase3-kyc-002-01:** Given `POST /api/v1/kyc/webhook` with valid HMAC-SHA256 `X-Payload-Digest` matching `HMAC(SUMSUB_SECRET_KEY, raw_body)`, when received, then signature verifies. Mismatch → `401 Unauthorized` with `{error: 'invalid_signature'}`. Replay-safe: signature includes the body, so altering the body invalidates.

- **AC-phase3-kyc-002-02:** Given a webhook with `type: 'applicantReviewed', reviewResult.reviewAnswer: 'GREEN', levelName: 'basic-kyc-level'` for a tier_0 applicant, when handler runs, then within a UoW: (1) load applicant, assert current_tier ∈ valid source states; (2) compute new_tier='tier_1' via `tier_transition.apply(...)`; (3) UPDATE `kyc.applicants.current_tier='tier_1', review_answer='GREEN', reject_labels=[]`; (4) INSERT `kyc.kyc_events` with redacted payload; (5) publish `kyc.TierChanged{from_tier='tier_0', to_tier='tier_1'}`; (6) return `200 OK` with empty body (Sumsub expects 2xx).

- **AC-phase3-kyc-002-03:** Given a webhook `applicantReviewed` with `reviewAnswer: 'RED', reviewRejectType: 'RETRY', rejectLabels: ['DOCUMENT_DAMAGED']`, when handler runs, then: tier stays tier_0 (no transition), `reject_labels` updated, event row inserted, **no `TierChanged` event published** (no transition occurred). Admin sees the labels in the queue.

- **AC-phase3-kyc-002-04:** Given a webhook `applicantReviewed` with `reviewAnswer: 'RED', reviewRejectType: 'FINAL'`, when handler runs, then: tier transitions to `tier_0_rejected`, `TierChanged{from_tier='tier_0', to_tier='tier_0_rejected'}` published.

- **AC-phase3-kyc-002-05:** Given the PII redactor, when invoked on a sample webhook payload containing `firstName`, `lastName`, `dob`, `email`, `passport.number`, `address.street`, `moderationComment="Customer name verified, John Doe"`, when redacted, then those fields are `"<redacted>"`. Top-level keys we KEEP: `applicantId, externalUserId, levelName, type, reviewResult.reviewAnswer, reviewResult.reviewRejectType, reviewResult.rejectLabels, reviewStatus, createdAtMs`. **Property test:** for a synthesized payload with PII fields, after redaction, no PII string survives in the JSON. The redactor's allowlist (vs blocklist) approach: define the keep-list and redact everything else under sensitive keys. Document the strategy in inline comments.

- **AC-phase3-kyc-002-06:** Given a duplicate webhook delivery (same `correlationId` or computed `event_dedupe_key`), when received, then: (1) the INSERT into `kyc.kyc_events` hits the UNIQUE constraint → caught and treated as no-op; (2) the applicant state is NOT re-updated; (3) `TierChanged` is NOT re-published; (4) the response is `200 OK` (Sumsub gets the ack and stops retrying). **Idempotency is the safety net for at-least-once delivery.**

- **AC-phase3-kyc-002-07:** Given an unknown applicant_id (Sumsub-side bug or test webhook), when received, then handler logs warning and returns `200 OK` (don't 4xx — Sumsub would retry indefinitely). Event NOT inserted (no FK target).

- **AC-phase3-kyc-002-08:** Given a webhook signature is missing or empty, when received, then `401 Unauthorized` with `{error: 'missing_signature'}`. No request-body parsing. Defends against unauthenticated probes.

- **AC-phase3-kyc-002-09:** Given an event_type other than `applicantReviewed` (e.g., `applicantPending`, `applicantPrechecked`, `applicantOnHold`), when received, then handler logs the event, inserts into `kyc_events` (with redacted payload), but does NOT trigger tier transition or publish events. Acknowledged with `200 OK`. **Forward compatibility** — Sumsub may add new event types; we don't break.

- **AC-phase3-kyc-002-10:** Given the test environment, when handler tests run, then a fixture provides synthesized Sumsub webhook payloads (GREEN, RED-RETRY, RED-FINAL, YELLOW, unknown event_type) with valid HMAC signatures (computed in-test against a test secret). Tests cover all transition paths, idempotency, signature failures, PII redaction.

- **AC-phase3-kyc-002-11:** Given the property test on `tier_transition.apply(current_tier, review_answer, reject_type)`, when fuzzed across all combinations, then: (1) only the documented transitions occur (any other combination raises `InvalidTierTransition` or is a no-op); (2) the function is deterministic and pure (no DB, no clock).

- **AC-phase3-kyc-002-12:** Given the property test on **PII redaction totality** (`tests/kyc/infra/test_pii_redactor_properties.py::test_pii_totality`), when fuzzed via Hypothesis with synthesized PII fields injected at any nesting depth (`firstName`, `lastName`, `dob`, `email`, `phone`, `passport.number`, `address.street`, `moderationComment`, `clientComment`, plus any field name matching `/document|passport|id_number/i`), then after `redact(payload)` the resulting JSON serialized to a string contains NO PII string literal from the original payload. Property holds across 1000 generated cases. **Architecture-mandated property test (PHASE3-SUMMARY property #10).**

- **AC-phase3-kyc-002-13:** Given the property test on **PII redaction structural preservation** (`tests/kyc/infra/test_pii_redactor_properties.py::test_structural_preservation`), when fuzzed via Hypothesis with arbitrary JSON payloads (any keys, any depth, mixed PII and non-PII fields), then after `redact(payload)`: (1) the JSON tree shape (key set, nesting structure, array lengths) is preserved — no spurious key drops or spurious key additions; (2) every value under a `KEEP_KEYS` dotted-path retains its original value byte-for-byte; (3) every value under a non-keep path is the literal string `"<redacted>"`. **Architecture-mandated property test (PHASE3-SUMMARY property #11).**

- **AC-phase3-kyc-002-14:** Given the property test on **tier transitions monotonic toward `tier_0_rejected` sink** (`tests/kyc/domain/test_tier_transition_properties.py::test_tier_0_rejected_is_sink`), when fuzzed via Hypothesis over `(review_answer × reject_type)` for `current_tier=tier_0_rejected`, then `tier_transition.apply(tier_0_rejected, *, *) == tier_0_rejected` for every combination — the auto-transition function never exits the sink. (Manual admin overrides via `admin-005` bypass this function and are out of scope of the property.) **Architecture-mandated property test (PHASE3-SUMMARY property #13).**

---

## Out of Scope

- Email notifications on tier change: handled by Notifications context subscribing to `TierChanged` (V2 — kyc-002 doesn't notify directly).
- Automatic tier_2 upgrade flow on `enhanced-kyc-level` GREEN: V2 (transition is documented; implementation is deferred).
- Manual tier override admin endpoint: `phase3-admin-005` adds an endpoint for the admin queue UI; the underlying use case is added there, not here.
- Webhook replay/inspection admin tool (manually re-process a stored event): V2.

---

## Dependencies

- **Code dependencies:** `phase3-kyc-001` (KYC context bootstrapped).
- **Data dependencies:** `kyc.applicants` populated via kyc-001's start endpoint.
- **External dependencies:** Sumsub's webhook configuration (operator points Sumsub dashboard at `https://<our-domain>/api/v1/kyc/webhook`).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/kyc/domain/test_tier_transition.py` — exhaustive table of (from_tier × review_answer × reject_type) → expected to_tier or raise. Covers AC-11.
- [ ] **Property tests:** `tests/kyc/domain/test_tier_transition_properties.py` — function is pure, deterministic. Includes `test_tier_0_rejected_is_sink` covering AC-14.
- [ ] **Application tests:** `tests/kyc/application/test_sumsub_webhook_handler.py` — happy GREEN, RED-RETRY, RED-FINAL, YELLOW, unknown-event-type, unknown-applicant, idempotency. Covers AC-02 through AC-04, AC-07, AC-09.
- [ ] **Property tests:** `tests/kyc/infra/test_pii_redactor_properties.py` — `test_pii_totality` (synthesized PII, post-redaction no PII string survives, covers AC-12) and `test_structural_preservation` (JSON tree shape preserved, covers AC-13). Together cover AC-05 too.
- [ ] **Adapter tests:** `tests/kyc/infra/test_signature_verifier.py` — valid signature passes; mismatched body fails; missing header fails. Covers AC-01, AC-08.
- [ ] **Adapter tests:** `tests/kyc/infra/test_kyc_event_dedupe.py` — UNIQUE constraint catches duplicate. Covers AC-06.
- [ ] **Contract tests:** `tests/api/test_kyc_webhook_endpoint.py` — Schemathesis fuzz; auth via signature; valid signature → 200, invalid → 401.
- [ ] **Integration tests:** `tests/integration/test_kyc_webhook_e2e.py` — full webhook → tier transition → TierChanged event → consumer fires. Uses in-memory event bus.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] PII property test asserts no PII leakage after redaction.
- [ ] OpenAPI spec extended with webhook endpoint; lints clean.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes; tier transition state machine exhaustive.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] One new domain event registered (`kyc.TierChanged`).
- [ ] `docs/runbook.md` updated: how to register webhook URL with Sumsub, how to inspect kyc_events for forensic review.
- [ ] Single PR. Conventional commit: `feat(kyc): sumsub webhook handler + pii redaction + tier transitions [phase3-kyc-002]`.

---

## Implementation Notes

- The signature verifier reads the **raw request body** (not parsed JSON) — FastAPI's `Request` object exposes `await request.body()`. Compute HMAC over the raw bytes; compare via `hmac.compare_digest` (constant-time).
- The PII redactor is a recursive walker. Define `KEEP_KEYS = {"applicantId", "externalUserId", "levelName", "type", "reviewStatus", "createdAtMs", "reviewResult.reviewAnswer", "reviewResult.reviewRejectType", "reviewResult.rejectLabels"}` (dotted-path keep-list). Walk with current path; if path is in keep-list AND parent is in keep-list, keep; else redact. **Default-redact** is the conservative choice: future Sumsub fields we haven't seen are redacted by default.
- The `event_dedupe_key`: prefer Sumsub's `correlationId` if present; fall back to `f"{applicantId}:{reviewStatus}:{createdAtMs}"`. UNIQUE INDEX on this column.
- Tier transitions are computed by a pure function — easy to unit-test exhaustively. The function uses Python's `match` statement for pattern matching. mypy's exhaustiveness checking catches missing cases.
- The `TierChanged` event includes the user_id (looked up from applicant.user_id). The event is consumed by `phase3-kyc-003`'s `KycTierGateway.get_tier(user_id)` cache invalidation (Phase 3's cache TTL is 60s; the event invalidates immediately for responsiveness).
- Webhook responses: Sumsub treats any 2xx as success. Don't return body content (Sumsub ignores). Empty `200 OK` is sufficient.

---

## Risk / Friction

- **PII redaction is a quality-of-implementation issue.** A bug here (missing a field) leaks customer PII into our event log — a portfolio-wreck-level mistake. **The property test (AC-05) is critical** and should fuzz extensively. Manually verify: deploy to staging, trigger a real KYC, inspect the stored event row directly via DB, confirm no PII strings present.
- The default-redact strategy can be over-eager: if Sumsub adds a new diagnostically-useful field (e.g., `sandbox_test_mode: true`), it gets redacted unhelpfully. Add to keep-list as needed. Document the policy.
- Sumsub's webhook delivery from sandbox is sometimes delayed (10s to several minutes). Don't time-out wait synchronously; the user dashboard polls `/kyc/status` (kyc-001) and reflects when ready.
- Edge case: the same Sumsub applicant could be reviewed multiple times (user retries). Each review is a distinct webhook event. The dedupe key includes `createdAtMs`, so each review is distinct. Idempotency works correctly.
- The "unknown event type" path (AC-09) acknowledges with 200 to keep Sumsub happy. If Sumsub starts firing critical events we silently ignore, we might miss them. Mitigation: log a metric "kyc.webhook.unknown_event_type" with the type name; alert if it spikes (V2 ops polish).
- Webhook security depends on `SUMSUB_SECRET_KEY` confidentiality. Sumsub doesn't rotate this automatically; operator rotates quarterly per runbook. If the secret leaks, attackers can forge webhooks → false tier_1 elevations. Defenses: (a) rotate; (b) the audit_log captures all tier transitions with the webhook event_id, so forensic recovery is possible; (c) `phase3-admin-005` shows recent tier_1 grants, ops can review.
