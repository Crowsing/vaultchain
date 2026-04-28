---
ac_count: 7
blocks:
- phase1-admin-002b
- phase1-admin-003
complexity: M
context: admin
depends_on:
- phase1-identity-001
- phase1-identity-003
- phase1-identity-004
- phase1-shared-005
- phase1-shared-006
estimated_hours: 4
id: phase1-admin-002a
phase: 1
sdd_mode: strict
state: ready
title: Admin auth backend (password+TOTP, session, seed CLI)
touches_adrs: []
---

# Brief: phase1-admin-002a — Admin auth backend (password+TOTP, session, seed CLI)


## Title

Admin auth backend (password+TOTP, session, seed CLI)

## Context

Admins authenticate differently from users. Per architecture Section 2, "admin-side has password+TOTP middleware plus a per-action audit logger." There are no magic links for admins — admins are seeded directly into `identity.users` with `actor_type='admin'` and a bcrypt-hashed password. They login with email + password + TOTP (TOTP enrollment happens at seed-time, out-of-band: a backup-code list is printed once that the admin keeps on paper). This brief delivers the **backend half** of admin auth: the bcrypt password verification flow, an admin-only login endpoint, the admin session middleware, and a Click seed CLI to provision admins. The matching frontend (login.tsx + totp.tsx + admin apiFetch) is split into `phase1-admin-002b` so each half can land within the 2-iteration CI cap.

The session model is identical to user sessions (opaque tokens, Redis-backed, httpOnly cookies, CSRF) — see identity-004. The differences are: cookie path is `/admin/api/v1/` (path-restricted, so user app cannot accidentally read it), session row in `identity.sessions` has `actor_type='admin'`, and the middleware guarding admin endpoints checks `actor_type='admin'` strictly. A user-actor session presented at an admin endpoint returns `403 identity.admin_required`.

The Identity domain entities from identity-001 (User, Session, MagicLink, TotpSecret) accommodate admins, but **the admin-side columns on `identity.users` are NOT yet in the schema**. The blocked-state audit on the prior single-brief version of admin-002 confirmed that `identity-001`'s migration added only `id, email, email_hash, status, kyc_tier, version, created_at, updated_at`, and the lockout migration (identity-003 follow-up) added `failed_totp_attempts` and `locked_until`. The columns `password_hash`, `actor_type`, `metadata`, and `login_failure_count` are genuinely missing. **This brief therefore widens the migration scope** to add all four (additive, with safe defaults so existing user rows backfill cleanly).

The seed CLI is a small Click-based command at `cli/scripts/seed_admin.py`: `python -m cli.scripts.seed_admin --email <e> --password <p>`. It prompts for confirmation, hashes the password with bcrypt (cost 12), enrolls a fresh TOTP secret, prints the otpauth URI + 10 backup codes ONCE to stdout (not stored anywhere else, written by the admin to paper), and inserts the user row + totp_secret row in a single UoW. This is run manually post-deploy by the operator (the developer, in V1) — no admin-creates-admin flow in V1.

---

## Architecture pointers

- **Layer:** delivery + application + domain (backend only — frontend is in admin-002b).
- **Packages touched:**
  - `identity/application/use_cases/admin_login.py`, `identity/application/use_cases/admin_totp_verify.py`
  - `identity/domain/services/password_hasher.py` (port) and `identity/infra/bcrypt_password_hasher.py` (adapter)
  - `identity/domain/value_objects.py` — `PasswordPolicy` VO; `ActorType` StrEnum
  - `identity/domain/errors.py` — `InvalidCredentials`, `SessionRequired`, `AdminRequired`
  - `identity/delivery/admin_routers.py`, `identity/delivery/dependencies.py` (admin auth dependency)
  - `cli/scripts/seed_admin.py`
  - `backend/alembic/versions/<ts>_admin_user_columns.py` (new migration)
- **Reads:** none direct — admin login reads the User aggregate via `IdentityUnitOfWork`.
- **Writes:** insert into `identity.sessions` (actor_type='admin'). Update `users.last_login_at`. Same outbox event types as user login (`identity.UserAuthenticated` with `actor_type='admin'` in payload).
- **Events:** `identity.UserAuthenticated` reused. Plus `audit.AdminAuthenticated` published to the audit subscriber (the audit context comes online in Phase 2; for now the event is published and ignored — outbox handles late-binding subscribers).
- **Ports / adapters:** new `PasswordHasher` port + `BcryptPasswordHasher` adapter.
- **Migrations:** additive migration adding to `identity.users`:
  - `password_hash TEXT NULL` (NULL for user-actor rows; required for admin-actor rows — enforced by domain rule, not DB constraint, so user-side path is unaffected)
  - `actor_type TEXT NOT NULL DEFAULT 'user'` with `CHECK (actor_type IN ('user','admin'))` — backfills existing rows safely
  - `metadata JSONB NOT NULL DEFAULT '{}'::jsonb` — JSON column for admin role and future extensions
  - `login_failure_count INTEGER NOT NULL DEFAULT 0` — admin password-failure counter, distinct from `failed_totp_attempts`
- **OpenAPI:** new endpoints under `/admin/api/v1/auth/`: `POST /login`, `POST /totp/verify`, `POST /logout`, `GET /me`. Filtered OUT of the public `/openapi.json` per architecture Section 4.

---

## Acceptance Criteria

- **AC-phase1-admin-002a-01:** Given an admin row exists in `identity.users` with `actor_type='admin'` and a bcrypt `password_hash`, when `POST /admin/api/v1/auth/login` is called with `{email, password}` and the password verifies, then a `pre_totp_token` (5-min Redis-backed opaque token, same shape as user-side from identity-002) is issued in the response body and a transient `admin_pre_totp` cookie is set (path `/admin/api/v1/auth/totp/verify`). Response 200, body shape `{pre_totp_required: true}`. The endpoint enforces idempotency-key from `phase1-shared-006`.

- **AC-phase1-admin-002a-02:** Given a wrong password is submitted, when `POST /admin/api/v1/auth/login` is called, then the response is `401 identity.invalid_credentials` per the error envelope from `phase1-shared-005`. Failure counting uses the new `users.login_failure_count` column (additive in this brief's migration, distinct from `users.failed_totp_attempts` from identity-003) and the shared `users.locked_until` timestamp (already present from identity-003's lockout migration). After 5 password failures within 15 minutes for a single email, the account is locked for 30 minutes (admin lockout is stricter than the user-side TOTP lockout of 15 min — admins are higher-value targets and slower to recover from compromise; documented intentionally in Implementation Notes). A successful password verification resets `login_failure_count` to 0. On a locked account, the response is `403 identity.user_locked` with `details.locked_until` ISO timestamp. The same `locked_until` is honored by the user-side TOTP lockout in identity-003 — a single locked admin cannot bypass via either entry path.

- **AC-phase1-admin-002a-03:** Given a valid `pre_totp_token` and a 6-digit TOTP code, when `POST /admin/api/v1/auth/totp/verify` is called, then the existing TOTP verification use case from identity-003 is invoked, the pre_totp_token is consumed (single use), and on success a new admin session is created: row in `identity.sessions` with `actor_type='admin'`, an opaque access token issued, refresh token issued. Cookies are set: `admin_at` (HttpOnly, Secure, SameSite=Lax, path `/admin/api/v1/`, 15-min TTL on Redis), `admin_rt` (HttpOnly, Secure, SameSite=Strict, path `/admin/api/v1/auth/refresh`, 30-day TTL), `admin_csrf` (HttpOnly=false, double-submit cookie pattern). Response 200 with `{user: {id, email, actor_type: 'admin'}}`.

- **AC-phase1-admin-002a-04:** Given any admin endpoint is hit without a valid `admin_at` cookie, when middleware processes the request, then the response is `401 identity.session_required`. Given a valid USER access token (`vc_at_...`) is presented at an admin endpoint, when middleware processes it, then the response is `403 identity.admin_required` — distinct error code, surfaced to logs. The middleware reads the session by token hash, asserts `actor_type='admin'` on the loaded session row.

- **AC-phase1-admin-002a-05:** Given an admin session is active, when `GET /admin/api/v1/auth/me` is called, then the response is the admin's `{id, email, full_name, role, last_login_at}`. The `role` field is derived from the new `users.metadata->>'admin_role'` JSONB path — V1 has only one role `'admin'`, but the field exists so Phase 3 can introduce `'reviewer'` and `'approver'` distinctions. `full_name` is also stored in `metadata` (no top-level column needed in V1).

- **AC-phase1-admin-002a-06:** Given the seed CLI is run with `python -m cli.scripts.seed_admin --email admin@vaultchain.io --password "<strong-password>"`, when executed, then it: validates email format, requires the password to be ≥12 chars (per a domain rule in `PasswordPolicy` value object), hashes with bcrypt cost 12, generates a fresh TOTP secret with a random 32-byte base32, computes 10 backup codes (8-char, hex), stores the row in `identity.users` with `actor_type='admin'` + the totp_secret row in a single UoW transaction, and prints to stdout: the email, the otpauth-uri (so admin can scan with Google Authenticator), and the 10 backup codes — once, never logged. If a row with that email already exists, fail loud (no overwrite).

- **AC-phase1-admin-002a-07:** Given the audit context does not yet exist in Phase 1 (it comes in Phase 2), when an admin logs in, then a `audit.AdminAuthenticated` event is published to the outbox with payload `{admin_id, ip, user_agent, login_at}`. The outbox publisher (shared-004) successfully writes to event_log (or whatever subscriber is registered); since no consumer exists yet, the event sits in the bus quietly. This is the architectural-correct way to defer the audit subscriber.

---

## Out of Scope

- Admin frontend (login.tsx, totp.tsx, admin apiFetch wrapper): split into `phase1-admin-002b`.
- Multi-role admin (reviewer / approver / superadmin): Phase 3.
- Admin password reset flow: V2 — handled out-of-band by re-running the seed CLI.
- Admin SSO / SAML: V2.
- Audit-log persistence and viewer: Phase 2 / Phase 3.
- Admin-creates-admin endpoint: V2.
- Per-IP allowlisting for admin endpoints: production hardening beyond V1 scope; Cloudflare Access can be added at deploy time without code changes.
- "Sign out other admin sessions" UI: V2.

---

## Dependencies

- **Code dependencies:** `identity-001` (User, Session, TotpSecret, MagicLink entities + repos — but NOT the assumed admin columns; this brief's migration adds them), `identity-003` (TOTP verify use case + lockout machinery; reuse `users.failed_totp_attempts` + `users.locked_until`), `identity-004` (cookie / CSRF / refresh patterns; reuse the cookie-issuing helper but with admin path/name overrides), `shared-005` (error envelope + DomainError mapping), `shared-006` (idempotency middleware).
- **Data dependencies:** `identity` schema migrations from identity-001 and identity-003's lockout follow-up must be applied. **This brief adds a new migration** (`password_hash`, `actor_type`, `metadata`, `login_failure_count`).
- **External dependencies:** `bcrypt` (Python: `bcrypt`), `pyotp` for TOTP (already added in identity-003), `click` for the CLI.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/identity/domain/test_password_policy.py` covers AC-06's PasswordPolicy VO (length, no whitespace-only, etc.). `tests/identity/domain/test_password_hasher.py` covers the port contract via the in-memory fake (a hash-roundtrip property test).
- [ ] **Property tests:** `tests/identity/domain/test_password_hasher_properties.py` — for any random password ≥12 chars, `verify(hash(p)) == True`; `verify(hash(p1), p2 != p1) == False`. Per architecture Section 5 ("KMS envelope encryption" property test pattern, applied here to password hashing).
- [ ] **Application tests:** `tests/identity/application/test_admin_login.py` — happy path, wrong password, locked account, idempotency replay returns same `pre_totp_token`. Uses the in-memory `FakePasswordHasher` and `FakeTotpStore`.
- [ ] **Adapter tests:** `tests/identity/infra/test_bcrypt_password_hasher.py` — uses real `bcrypt`, asserts hash format starts with `$2b$12$` and verify works. Single test, no testcontainers needed.
- [ ] **Contract tests:** `tests/api/test_admin_auth.py` — covers AC-01 through AC-05 against a TestClient. Uses fixtures to seed an admin user, exercises full flow login → totp → /me → logout. Asserts cookie names, paths, HttpOnly, SameSite per AC-03. Asserts admin endpoints are filtered OUT of the public `/openapi.json`.
- [ ] **Migration tests:** the additive migration applies cleanly against a DB seeded by identity-001 + identity-003-lockout migrations; downgrade reverses cleanly.
- [ ] **CLI tests:** `tests/cli/test_seed_admin.py` — happy path inserts both rows in a single transaction, duplicate email fails loud, password <12 chars rejected.
- [ ] **E2E:** none new — admin E2E is Phase 3 territory.
- [ ] **Locust:** none.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass (admin delivery uses identity application; no admin → identity domain shortcut; AI never imports custody contract still satisfied).
- [ ] `mypy --strict` passes for touched modules.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] OpenAPI schema diff: 4 new endpoints under `/admin/api/v1/auth/` documented; `docs/api-contract.yaml` committed. Admin endpoints are filtered OUT of the public `/openapi.json` per architecture Section 4 — assert this in a contract test.
- [ ] Alembic migration up/down both clean against a DB that has identity-001 + identity-003-lockout migrations applied.
- [ ] No new domain events beyond the reused `identity.UserAuthenticated` and the new `audit.AdminAuthenticated`. The latter is registered in `shared/events/registry.py` even though no consumer exists yet.
- [ ] New port `PasswordHasher` declared in `identity/domain/ports.py` with a `FakePasswordHasher` in `tests/identity/fakes/`.
- [ ] Single PR. Conventional commit: `feat(identity,admin): admin auth backend [phase1-admin-002a]`.
- [ ] PR description: README snippet showing how to seed an admin (`python -m cli.scripts.seed_admin --email ...`).

---

## Implementation Notes

- The `PasswordHasher` port has a single method: `hash(password: str) -> str` and `verify(password: str, hash: str) -> bool`. Deliberately not `compare_hashes` — bcrypt comparison is via verify only.
- Reuse the cookie helper from identity-004 with parameters: `cookie_prefix='admin_'` and `path='/admin/api/v1/'`. Do not fork the helper.
- `ActorType` is a `StrEnum` with values `user` and `admin` (per project convention: StrEnum over `str`/`Literal[str]`).
- The TOTP verify path for admins increments `users.failed_totp_attempts` (shared with the user-side TOTP path from identity-003 — one user, one TOTP counter regardless of auth flow). The password-login path increments the SEPARATE `users.login_failure_count` column added in this brief's migration. The two counters are distinct so a brute-force attack on the password layer cannot trip the TOTP lockout (and vice versa), but both share the single `users.locked_until` column so reaching either threshold blocks all auth attempts for that user.
- Admin lockout: 5 failures / 15 min window / 30 min lockout (stricter than user TOTP's 15-min lockout). Admin login is rate-limited at the gateway too (60 req/min per IP from architecture-decisions Section 4 rate-limiting); the lockout is the second line of defense.
- The error code `identity.admin_required` is added to the `DomainError` registry, mapped to HTTP 403, and documented in the generated `errors-reference.md`.
- The seed CLI must NOT log the password or otpauth-uri. Use `print()` only for the otpauth-uri + backup codes; bcrypt-hashed password goes only into the DB.
- Filtering admin endpoints out of public OpenAPI: in FastAPI, set `include_in_schema=False` on the admin router prefix, and have a separate `/admin/openapi.json` available only behind the admin session check.
- Migration ordering: this brief's migration depends on `20260428_120000_identity_user_lockout_columns` (the lockout columns must exist before this brief runs, since AC-02 reads `users.locked_until`).

---

## Risk / Friction

- The "audit event with no consumer" pattern looks like a smell; document it explicitly in the PR description so reviewers don't flag it. The outbox semantics make this safe — events sit in `event_log`, the consumer comes online in Phase 2 and replays from a checkpoint cursor.
- bcrypt cost 12 takes ~250ms on a typical container — that's a deliberate latency floor on login. Don't lower it.
- The seed CLI prints backup codes to stdout. If the operator pipes the output to a file or a CI log, those secrets leak. Add a confirmation prompt: "Backup codes will be displayed once. Are you in a private terminal? [y/N]" — refuse to run if `--no-confirm` is set without `--accept-secret-display`. Belt-and-suspenders.
- This brief was split off the original `phase1-admin-002` after the migration-scope mismatch surfaced (the original brief assumed columns already existed that didn't). The migration in this brief is therefore wider than the original `+login_failure_count` description — see Architecture pointers.
