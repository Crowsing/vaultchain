---
ac_count: 1
blocks:
- phase1-web-002
- phase1-web-003
- phase1-web-005
- phase1-deploy-001
complexity: M
context: identity
depends_on:
- phase1-identity-002
- phase1-identity-003
- phase1-identity-004
- phase1-shared-005
- phase1-shared-006
estimated_hours: 4
id: phase1-identity-005
phase: 1
sdd_mode: strict
state: ready
title: Auth API endpoints + OpenAPI
touches_adrs:
- ADR-002
---

# Brief phase1-identity-005: Auth API endpoints + OpenAPI


## Context

The application use cases for magic-link, TOTP, and sessions are all in place. This brief wires them through HTTP: the FastAPI routers under `/api/v1/auth/...` and `/api/v1/me`, the Pydantic request/response schemas (with `extra="forbid"` and `example` annotations), the OpenAPI `securitySchemes` block, and the regenerated `docs/api-contract.yaml` checked into the repo.

This is the seam where the backend becomes externally usable — Phase 1 web and Phase 1 admin both read from this OpenAPI contract via `openapi-typescript`. Get the schema right and downstream is mechanical.

The route set covers exactly what the auth state machine in `auth-onboarding-notes.md` needs: signup/login email entry → `/auth/request`; magic-link consume → `/auth/verify`; TOTP enroll → `/auth/totp/enroll` and `/auth/totp/enroll/confirm`; TOTP login → `/auth/totp/verify`; session refresh → `/auth/refresh`; logout → `/auth/logout`; profile fetch → `/me`; backup-code regenerate → `/auth/totp/backup-codes/regenerate`.

---

## Architecture pointers

- **Layer(s):** `delivery` (routers, schemas)
- **Affected packages:** `vaultchain.identity.delivery`, `docs/api-contract.yaml`
- **Reads from:** identity application use cases (all five)
- **Writes to:** via use cases only — no direct repo or DB access
- **Publishes events:** `none` directly (events come from use cases)
- **Subscribes to events:** `none`
- **New ports introduced:** `none`
- **New adapters introduced:** `none`
- **DB migrations required:** `no`
- **OpenAPI surface change:** `yes` — the full Phase 1 auth surface lands here. Endpoints listed in Acceptance Criteria.

---

## Acceptance Criteria

- **AC-phase1-identity-005-01:** Given the FastAPI app, when `/openapi.json` is fetched, then it contains the following operations:
  - `POST /api/v1/auth/request` — body `{email, mode: "signup"|"login"}`, idempotency-key header optional, returns 202 `{message_sent: true}`.
  - `POST /api/v1/auth/verify` — body `{token: string, mode: "signup"|"login"}`, returns 200 `{user_id, email, is_first_time, requires_totp_enrollment, requires_totp_challenge}`. No session cookie set yet — TOTP must complete first.
  - `POST /api/v1/auth/totp/enroll` — auth: requires `pre-totp-token` (short-lived 5-min token issued by `/auth/verify`), returns 200 `{secret_for_qr, qr_payload_uri, backup_codes}` (one-shot).
  - `POST /api/v1/auth/totp/enroll/confirm` — body `{code: string}`, returns 200 + sets session cookies on success.
  - `POST /api/v1/auth/totp/verify` — auth: requires `pre-totp-token`, body `{code, use_backup_code?: bool}`, returns 200 + sets session cookies on success, or 200 with `{success: false, attempts_remaining: int}` on wrong code, or 403 `identity.user_locked` after lockout.
  - `POST /api/v1/auth/refresh` — auth: refresh-token cookie, returns 204 + rotates cookies.
  - `POST /api/v1/auth/logout` — auth: session cookie, returns 204 + clears cookies.
  - `POST /api/v1/auth/totp/backup-codes/regenerate` — auth: full session + recent TOTP verify, returns `{backup_codes: [string]}`.
  - `GET /api/v1/me` — auth: session cookie, returns `{id, email, status, kyc_tier, totp_enrolled, created_at}`.
- **AC-phase1-identity-005-02:** Given every endpoint above, when its OpenAPI operation object is inspected, then `extra="forbid"` is enforced on request body schemas and every response schema has an `example` populated; if any example is missing, the CI gate `tests/api/test_openapi_examples.py` fails.
- **AC-phase1-identity-005-03:** Given a valid signup flow (`/auth/request` → `/auth/verify` → `/auth/totp/enroll` → `/auth/totp/enroll/confirm`), when executed end-to-end via the test client, then the final response sets the three session cookies (vc_at, vc_rt, csrf) with the correct attributes (httpOnly, Secure, SameSite, path).
- **AC-phase1-identity-005-04:** Given the auth-state-machine constraint that TOTP must be enrolled before sessions are issued, when a verified user without TOTP attempts `GET /api/v1/me`, then the dependency raises 403 with `code="identity.totp_required"`. (However, the `/auth/verify` response indicates whether enrollment is required, so the frontend never sends this request without TOTP.)
- **AC-phase1-identity-005-05:** Given the `pre-totp-token` mechanism, when `/auth/verify` succeeds, then the response body includes `pre_totp_token: <token>` (a short-lived Redis-cached token, 5-min TTL, scoped to either "enroll" or "challenge" depending on `is_first_time`). All TOTP routes require this token via `Authorization: Bearer <pre_totp_token>` header. Once consumed (on enroll-confirm or verify success), the token is evicted.
- **AC-phase1-identity-005-06:** Given any error envelope from any of these endpoints, when inspected, then it conforms to `phase1-shared-005`'s shape — including `request_id` from middleware and `documentation_url`.
- **AC-phase1-identity-005-07:** Given the idempotency middleware from `phase1-shared-006`, when `POST /auth/request` is replayed with the same `Idempotency-Key` and same body, then the cached 202 is returned and no second magic link is created.
- **AC-phase1-identity-005-08:** Given the API contract, when CI runs `python scripts/regenerate_openapi.py && diff docs/api-contract.yaml fresh.yaml`, then the diff is empty (drift check passes). The script runs in CI stage 8 per architecture-decisions Section 5.

---

## Out of Scope

- Demo-user "Try as demo" route: separate Phase 4 brief.
- Admin auth routes: `phase1-admin-002`.
- Rate limiting at the route level: middleware in Phase 2.
- "New device detected" branch: Phase 4 polish.
- Resend email button rate limiting (the 30s countdown in the auth UX): client-side concern; backend simply allows replays.

---

## Dependencies

- **Code dependencies:** all four prior identity briefs, `phase1-shared-005` (error envelope), `phase1-shared-006` (idempotency middleware).
- **Data dependencies:** all prior identity migrations applied.
- **External dependencies:** Redis (for pre-totp-token), already wired via `AccessTokenCache` adapter (reuse the same Redis port).

---

## Test Coverage Required

- [ ] **Domain unit tests:** N/A.
- [ ] **Application tests:** N/A — no new use cases, only delivery wiring.
- [ ] **Adapter tests:** N/A.
- [ ] **Contract tests:** `tests/api/test_auth_request.py`, `test_auth_verify.py`, `test_auth_totp_enroll.py`, `test_auth_totp_verify.py`, `test_auth_refresh.py`, `test_auth_logout.py`, `test_me.py`, `test_openapi_schema.py`, `test_openapi_examples.py`
  - FastAPI TestClient with full local stack (testcontainers Postgres, Redis)
  - covers AC-01 through -08
  - test cases per file: happy path, all error envelope cases, cookie-attribute assertions, OpenAPI inclusion checks
- [ ] **E2E:** N/A at this brief — the journey-level E2E `tests/e2e/auth-signup.spec.ts` is delivered by `phase1-web-003` (the auth screens brief), which is the consumer of this API.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Coverage ≥85% on `identity/delivery/`.
- [ ] OpenAPI schema regenerated, `docs/api-contract.yaml` committed, drift check passes.
- [ ] `errors-reference.md` regenerated to include all identity error codes (`identity.magic_link_invalid`, `identity.magic_link_expired`, `identity.magic_link_already_used`, `identity.totp_already_enrolled`, `identity.user_locked`, `identity.unauthenticated`, `identity.csrf_failed`, `identity.refresh_token_invalid`, `identity.totp_required`, `identity.pre_totp_token_invalid`).
- [ ] No new ADR.
- [ ] No new port introduced.
- [ ] Single PR. Conventional commit: `feat(identity): auth API endpoints + OpenAPI [phase1-identity-005]`.

---

## Implementation Notes

- The `pre-totp-token` is a 32-byte secret stored in Redis at `pre_totp:{sha256(token)} → {user_id, intent: "enroll"|"challenge"}` with 5-min TTL. The `/auth/verify` use case mints it and the route returns it. TOTP routes consume via `Authorization: Bearer ...` and a dependency `get_pre_totp_user(intent)`. Implementation lives in `identity/delivery/dependencies.py` next to `get_current_user`.
- Cookie setting happens in the route layer, not the use case. The use case returns the raw tokens; the route calls a `set_session_cookies(response, raw_tokens)` helper from `phase1-identity-004`. Logout calls `clear_session_cookies(response)`.
- The `responses` examples per endpoint are the largest block of new YAML. Use Pydantic's `Field(..., examples=[...])` syntax to generate them inline; verify with the OpenAPI examples test.
- `/auth/verify` does not yet issue session cookies — that happens on TOTP success. This split is what the auth state machine requires (LOGIN_TOTP screen exists between MAGIC_SENT and DASHBOARD).
- Idempotency-key applies to `/auth/request` only in this brief. `/auth/verify`, `/auth/refresh`, and `/auth/logout` are all naturally idempotent by their own logic (consume-once, rotate, revoke-once).
- The `/me` route is a tiny query — straight `get_current_user` dependency + serialize. It's the simplest way to prove the cookie-bearer auth pipeline works end-to-end. Frontend's first authenticated request after enroll/verify is `GET /me`.

---

## Risk / Friction

- The `pre-totp-token` is technically a second auth credential. Justification: it gates TOTP routes from being callable without a recent valid magic-link consume — which would otherwise let an attacker who steals a TOTP code submit it independently. The token expires fast (5 min) so the attack window is small. Document explicitly in the dependency module.
- OpenAPI schema correctness is verified by drift check + examples check; both must run in CI stage 8. If a brief author forgets `extra="forbid"` or omits an `example`, the gate catches it before merge. Add a brief test that explicitly fails on a schema missing `extra="forbid"` to make the error message clear.
- Logout has a subtle case: revoking a session that's not the current user's session (someone else's session). V1 only allows revoking the current session via `/auth/logout` (no `session_id` parameter). `RevokeAllSessions` is wired but not routed — that's a Phase 3 admin feature.
- The error envelope test relies on `phase1-shared-005`'s middleware. If shared-005 is regressed, this brief's tests fail noisily — that's the right failure mode (downstream catches upstream regressions).
