---
ac_count: 8
blocks:
- phase3-kyc-002
- phase3-kyc-003
- phase3-admin-005
- phase3-admin-007
complexity: L
context: kyc
depends_on:
- phase1-identity-004
estimated_hours: 4
id: phase3-kyc-001
phase: 3
sdd_mode: strict
state: ready
title: KYC context + Sumsub adapter + applicant create + status query
touches_adrs: []
---

# Brief: phase3-kyc-001 — KYC context + Sumsub adapter + applicant create + status query


## Context

VaultChain integrates Sumsub as the KYC/AML provider — used by major fintech for ID verification. The architecture already names `kyc` as one of the 13 bounded contexts. This brief introduces the context bootstrap: tables, domain primitives, the Sumsub adapter, and two user-facing endpoints (`POST /api/v1/kyc/start`, `GET /api/v1/kyc/status`).

Sumsub's flow is webhook-driven:
1. **Create applicant** server-side via `POST https://api.sumsub.com/resources/applicants?levelName=basic-kyc-level` with the user's external user-id (we use VaultChain's `user_id` UUID). Returns Sumsub `applicantId`.
2. **Generate Web SDK token** — short-lived signed token the frontend embeds in the Sumsub Web SDK iframe. The user uploads ID documents, takes selfies, etc.
3. **Sumsub processes** asynchronously (typically minutes; can take hours during high load). Sends a webhook `applicantReviewed` to our endpoint when done. Webhook handling is `phase3-kyc-002`'s scope.
4. **Status polling** — the user's dashboard polls `GET /api/v1/kyc/status` to render their current tier + review state.

This brief delivers steps 1, 2, and the status query. The webhook handler is in kyc-002.

The KYC tiers we model:

- **`tier_0`** — default for all users (no KYC). Withdrawals always route to admin (per `phase3-transactions-003`).
- **`tier_1`** — basic KYC complete (Sumsub `basic-kyc-level` = ID + selfie + liveness). Per-tx $5k, daily $10k limits (per `phase3-kyc-003`).
- **`tier_2`** — enhanced KYC (Sumsub `enhanced-kyc-level` = address proof, source of funds). $25k / $50k limits. **Out of scope for V1** — the schema accommodates tier_2 but the upgrade path is V2.
- **`tier_0_rejected`** — applicant submitted KYC but was rejected by Sumsub. Treated as tier_0 for limits but flagged in admin views.

**Schema:**

```sql
CREATE SCHEMA IF NOT EXISTS kyc;

CREATE TABLE kyc.applicants (
  applicant_id TEXT PRIMARY KEY,                -- Sumsub's applicantId
  user_id UUID NOT NULL UNIQUE REFERENCES identity.users(id),
  level_name TEXT NOT NULL,                     -- 'basic-kyc-level' | 'enhanced-kyc-level'
  current_tier TEXT NOT NULL DEFAULT 'tier_0',  -- tier_0 | tier_1 | tier_2 | tier_0_rejected
  review_answer TEXT,                           -- 'GREEN' | 'RED' | 'YELLOW' (null until first review)
  reject_labels TEXT[],                         -- e.g., ['DOCUMENT_DAMAGED', 'FACE_MISMATCH']
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE kyc.kyc_events (
  event_id BIGSERIAL PRIMARY KEY,
  applicant_id TEXT NOT NULL REFERENCES kyc.applicants(applicant_id),
  event_type TEXT NOT NULL,                     -- 'applicantCreated' | 'applicantReviewed' | 'applicantPending' | ...
  raw_payload JSONB NOT NULL,                   -- Sumsub webhook body (PII-redacted in kyc-002)
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ
);

CREATE INDEX idx_kyc_events_applicant_received ON kyc.kyc_events(applicant_id, received_at DESC);
```

**The endpoints:**

- **`POST /api/v1/kyc/start`** — idempotent. If user has an existing applicant, returns it; else creates one. Response: `{applicant_id, current_tier, websdk_url, expires_at}`. The `websdk_url` is a Sumsub-hosted URL with a short-lived token; the frontend opens this in an iframe.
- **`GET /api/v1/kyc/status`** — returns `{current_tier, review_answer, reject_labels, last_updated_at, applicant_exists: bool}`. Polled by the dashboard.

The Sumsub adapter wraps `https://api.sumsub.com` with HMAC-SHA256 request signing (Sumsub's auth model: `X-App-Token` header + signed payload via `X-App-Access-Sig` + `X-App-Access-Ts`). The `SUMSUB_APP_TOKEN` and `SUMSUB_SECRET_KEY` are env-driven (operator provisions Sumsub sandbox account).

Tests use **vcrpy cassettes** for the Sumsub HTTP calls — same pattern as Tron. Live Sumsub sandbox calls happen during cassette recording; replay is deterministic.

---

## Architecture pointers

- **Layer:** all 4 hexagonal layers (new context).
- **Packages touched:**
  - `kyc/__init__.py` (new context root)
  - `kyc/domain/entities/applicant.py` (Applicant aggregate)
  - `kyc/domain/value_objects/kyc_tier.py` (KycTier enum + KycReviewAnswer enum)
  - `kyc/domain/ports.py` (KycProvider Protocol — for Sumsub abstraction; ApplicantRepository)
  - `kyc/application/use_cases/start_kyc.py` (creates or returns applicant + Web SDK URL)
  - `kyc/application/queries/get_kyc_status.py`
  - `kyc/infra/sumsub_adapter.py` (httpx client, HMAC signing, retry/circuit-breaker)
  - `kyc/infra/sqlalchemy_applicant_repo.py`
  - `kyc/infra/migrations/<ts>_init_kyc.py`
  - `kyc/web/routes.py` (FastAPI router)
  - `tests/kyc/cassettes/` (vcrpy directory)
  - `docs/openapi/kyc.yaml`
- **Reads:** `kyc.applicants`.
- **Writes:** `kyc.applicants` (create + update), `kyc.kyc_events` (insert on Sumsub interactions).
- **Publishes events:** `kyc.ApplicantCreated{applicant_id, user_id, level_name}` — registered. Tier changes live in kyc-002 (webhook handler).
- **Migrations:** init kyc schema.
- **OpenAPI:** new spec for `/kyc/*` endpoints.

---

## Acceptance Criteria

- **AC-phase3-kyc-001-01:** Given the migration runs, when applied, then `kyc` schema + `applicants` + `kyc_events` tables exist per spec. Idempotent. Indexes created.

- **AC-phase3-kyc-001-02:** Given `POST /api/v1/kyc/start` with valid auth, when no existing applicant, then: (1) generates a `request_id`; (2) calls `SumsubAdapter.create_applicant(external_user_id=user_id, level_name='basic-kyc-level')` → returns Sumsub `applicantId`; (3) inserts `kyc.applicants` row with `current_tier='tier_0', review_answer=None`; (4) records `kyc_events` row event_type='applicantCreated' with raw response; (5) calls `SumsubAdapter.generate_websdk_link(applicant_id, level_name='basic-kyc-level', user_email)` → returns URL + expiry; (6) publishes `kyc.ApplicantCreated`; (7) returns `200 OK` with `{applicant_id, current_tier: 'tier_0', websdk_url, expires_at}`.

- **AC-phase3-kyc-001-03:** Given `POST /api/v1/kyc/start` for a user with existing applicant, when called, then it: (1) loads existing applicant; (2) **generates a fresh Web SDK link** (the previous one likely expired); (3) returns same shape as AC-02 with the existing `applicant_id` and current tier. **Idempotent** — never creates duplicate applicants for one user. The UNIQUE(user_id) constraint on `kyc.applicants` is the integrity guarantee.

- **AC-phase3-kyc-001-04:** Given `GET /api/v1/kyc/status` with valid auth for a user with an applicant, when called, then returns `200` with `{applicant_exists: true, current_tier, review_answer, reject_labels, last_updated_at}`. For a user without an applicant: `{applicant_exists: false, current_tier: 'tier_0', review_answer: null, reject_labels: [], last_updated_at: null}` — i.e., the user hasn't started KYC.

- **AC-phase3-kyc-001-05:** Given the `SumsubAdapter.create_applicant`, when called, then the HTTP request includes: `X-App-Token: <SUMSUB_APP_TOKEN>`, `X-App-Access-Ts: <unix_seconds>`, `X-App-Access-Sig: <HMAC_SHA256(secret, ts + method + path + body)>`. The body is `{externalUserId: user_id_uuid, type: "individual", levelName: "basic-kyc-level"}`. Response shape: `{id, createdAt, ...}`. Adapter returns `{applicant_id: response['id'], created_at: response['createdAt']}`.

- **AC-phase3-kyc-001-06:** Given the `SumsubAdapter.generate_websdk_link`, when called, then it makes a `POST https://api.sumsub.com/resources/sdkIntegrations/levels/{level_name}/websdkLink` with the applicant's `externalUserId` and `userEmail` (for prefill). Response includes `url` and `expiresIn` (seconds). Adapter returns the URL and `expires_at = now + expiresIn`.

- **AC-phase3-kyc-001-07:** Given Sumsub returns a 4xx error (e.g., 400 for invalid level), when received, then the adapter raises `KycProviderError(reason)` (a domain-level error). The use case catches and returns `502 Bad Gateway` to the user with a generic message; full details logged to Sentry.

- **AC-phase3-kyc-001-08:** Given Sumsub returns a 5xx or times out, when received, then adapter retries up to 3 times with exponential backoff (200ms, 1s, 5s); after final failure, raises `KycProviderUnavailable`. Use case returns `503 Service Unavailable` to the user.

- **AC-phase3-kyc-001-09:** Given the test environment, when adapter tests run, then vcrpy cassettes provide deterministic Sumsub responses. Cassette refresh procedure: run `pytest --vcr-record=new_episodes` against live Sumsub sandbox with valid `SUMSUB_APP_TOKEN` and `SUMSUB_SECRET_KEY`, review diff (filter the secret values from cassettes — vcrpy supports header filtering), commit.

- **AC-phase3-kyc-001-10:** Given the import-linter contracts, when run, then `kyc.application` may not import `kyc.infra` directly; only `kyc.domain.ports`. Cross-context: `kyc` is imported only by `transactions` (via the KycTierGateway port from `phase3-kyc-003`), not the other way around.

- **AC-phase3-kyc-001-11:** Given the OpenAPI spec for `/kyc/*`, when committed, then `docs/openapi/kyc.yaml` includes `POST /api/v1/kyc/start`, `GET /api/v1/kyc/status`. Spectral lint passes. Schemathesis fuzz against a running server in CI.

---

## Out of Scope

- `enhanced-kyc-level` flow (tier_2 upgrade): V2.
- Document re-upload after a partial-rejection: V2 (Sumsub handles via the Web SDK; admin-005 surfaces Sumsub's review iframe).
- Email notifications on KYC status changes: V2 (Notifications could subscribe to `kyc.TierChanged` from kyc-002).
- Sumsub Liveness mode customization (passive vs active): use Sumsub defaults.
- Cancel/restart KYC: V2 (the existing applicant accumulates rejection state; reset would be admin action).

---

## Dependencies

- **Code dependencies:** `phase1-identity-004` (auth middleware), `phase1-shared-005` (Sentry / error envelope).
- **Data dependencies:** `identity.users` table.
- **External dependencies:** Sumsub sandbox account (operator provisions, env vars `SUMSUB_APP_TOKEN`, `SUMSUB_SECRET_KEY`, `SUMSUB_BASE_URL=https://api.sumsub.com`), `httpx` (already in stack), `vcrpy` (already pulled in for chains).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/kyc/domain/test_applicant.py` — factory, tier transitions (V1 allowed: `tier_0 → tier_1`, `tier_0 → tier_0_rejected`; invalid transitions raise. The `tier_1 → tier_2` transition is **V2 — skipped via `pytest.mark.skip(reason='tier_2 V2 enhanced-KYC, see kyc-001 Out of Scope')`** but the case is wired so the V2 PR removes the skip rather than adding the test).
- [ ] **Application tests:** `tests/kyc/application/test_start_kyc.py` — happy path (new applicant), idempotency (existing applicant returns same id with fresh URL), Sumsub failure raises KycProviderError. Uses `FakeKycProvider`. Covers AC-02, AC-03, AC-07, AC-08.
- [ ] **Application tests:** `tests/kyc/application/test_get_kyc_status.py` — applicant exists, applicant doesn't exist. Covers AC-04.
- [ ] **Adapter tests:** `tests/kyc/infra/test_sumsub_adapter.py` — vcrpy cassettes; create applicant, generate websdk link, signature header verification (assert request signing is correct via cassette inspection), 5xx retry logic. Covers AC-05, AC-06, AC-08.
- [ ] **Adapter tests:** `tests/kyc/infra/test_sqlalchemy_applicant_repo.py` — testcontainer Postgres; insert/update/UNIQUE constraint on user_id; load by user_id and by applicant_id.
- [ ] **Contract tests:** `tests/api/test_kyc_endpoints.py` — Schemathesis fuzz; assert auth required (401 without). Covers AC-11.
- [ ] **Integration tests:** `tests/integration/test_kyc_start_e2e.py` — real DB + vcrpy Sumsub; user calls /start, applicant created, websdk URL returned.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] vcrpy cassettes committed; secrets filtered (CI grep check).
- [ ] OpenAPI spec lints clean; Schemathesis passes.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (85% application + 95% domain).
- [ ] One new domain event registered (`kyc.ApplicantCreated`).
- [ ] Two new ports declared (KycProvider, ApplicantRepository) with fakes.
- [ ] `docs/runbook.md` updated: how to provision Sumsub sandbox, env vars required, how to record/refresh cassettes.
- [ ] Single PR. Conventional commit: `feat(kyc): kyc context + sumsub adapter + start/status endpoints [phase3-kyc-001]`.

---

## Implementation Notes

- The Sumsub HMAC signing per request is documented at https://docs.sumsub.com/reference/authentication. The signature is over `ts + httpMethod + uri + bodyAsString` with HMAC-SHA256 keyed by `SUMSUB_SECRET_KEY`. Keep this in a small helper in `sumsub_adapter.py`.
- Sumsub's "external user ID" must be ≤ 64 chars and accept UUIDs; pass our user.id UUID as string. Keep the format consistent.
- The Web SDK URL has a short expiration (~30 minutes typical). Don't cache it — generate fresh on each `/start` call (AC-03).
- Testing against live Sumsub sandbox: the sandbox supports automated test users — Sumsub provides documentation for "test mode" applicants that auto-pass without real document upload. Use these for cassette recording. Don't try to upload real test docs from CI.
- vcrpy filters: configure `filter_headers=['X-App-Token', 'X-App-Access-Sig', 'Authorization']` and `filter_query_parameters=[]` (no query params). The signature header itself is sensitive (reveals signing pattern with timestamp); filter it.
- The `kyc.kyc_events` table is the SOURCE OF TRUTH for the Sumsub-side journey. Every Sumsub interaction (create, webhook, manual override) writes a row. The `applicants.current_tier` is a denormalized projection of the latest event. Reconcileable.

---

## Risk / Friction

- Sumsub free sandbox limits: ~10 applicant creates/hour at sandbox. Cassette-driven tests don't hit live; manual recording bursts can hit the limit. Document.
- The "Sumsub returned RED but we still let the user log in" — that's correct. KYC failure = stays at tier_0 = withdrawals all go to admin, no user-facing block. The admin dashboard surfaces the rejection so admins decide manually. Document.
- Sumsub Web SDK is a third-party iframe; XSS / CSP considerations. The frontend brief (`phase3-admin-005` for admin side, plus a small extension to user dashboard for the iframe) needs CSP `frame-src https://api.sumsub.com`. Document for the frontend brief.
- Webhook delivery from Sumsub is at-least-once and retries on non-2xx. The webhook endpoint (kyc-002) MUST be idempotent. This brief delivers the SOURCE-OF-TRUTH `kyc_events` table that supports the idempotent design.
- Operator's responsibility: keeping `SUMSUB_SECRET_KEY` confidential. Document in runbook: rotate via Sumsub dashboard quarterly; CI secrets are different from production secrets.
- The "tier_0_rejected" state: a user who failed KYC can theoretically retry by uploading new documents via Web SDK. Sumsub handles re-review without us creating a new applicant. The webhook handler in kyc-002 transitions on subsequent reviews. Document the edge case explicitly.
