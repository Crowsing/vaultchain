---
ac_count: 10
blocks:
- phase1-identity-005
- phase1-admin-002a
complexity: M
context: identity
depends_on:
- phase1-identity-001
- phase1-shared-003
estimated_hours: 4
id: phase1-identity-004
phase: 1
sdd_mode: strict
state: merged
title: Session management — cookies, CSRF, refresh-token rotation
touches_adrs:
- ADR-002
---

# Brief phase1-identity-004: Session management — cookies, CSRF, refresh-token rotation


## Context

Architecture-decisions Section 4 specifies the auth model: opaque session tokens (NOT JWT), 15-minute access-token TTL via Redis (`at:<token_hash> → {user_id, expires_at, scopes}`), 30-day refresh-token TTL stored in `identity.sessions` Postgres table, both in httpOnly+Secure+SameSite=Lax cookies. Refresh-token cookie is path-restricted to `/api/v1/auth/refresh`. CSRF via double-submit cookie pattern.

This brief delivers all of that as application-layer use cases plus the Redis adapter for the access-token cache plus the FastAPI dependencies that read cookies and resolve the current user. HTTP routes are `phase1-identity-005`; this brief stops at the use cases and the request-side dependency that is wired from any future authenticated route.

The use cases: `CreateSession` (after successful TOTP verify), `RefreshSession` (rotates refresh token, mints new access token), `RevokeSession` (logout, also invalidates access token), `RevokeAllSessions` (admin / "logout everywhere" — V1 has only the use case wired; the admin route is Phase 3).

---

## Architecture pointers

- **Layer(s):** `application` (use cases + FastAPI dependency `get_current_user`), `infra` (Redis access-token cache, cookie helpers)
- **Affected packages:** `vaultchain.identity.application`, `vaultchain.identity.infra.tokens`, `vaultchain.identity.delivery.dependencies`
- **Reads from:** `identity.users`, `identity.sessions`, Redis
- **Writes to:** `identity.sessions`, Redis (`SET EX`)
- **Publishes events:** `SessionCreated`, `SessionRefreshed`, `SessionRevoked`
- **Subscribes to events:** `none`
- **New ports introduced:** `AccessTokenCache` Protocol (Redis-backed), `RefreshTokenGenerator` (so tests inject deterministic tokens)
- **New adapters introduced:** `RedisAccessTokenCache`, `SecretsRefreshTokenGenerator`, plus fakes
- **DB migrations required:** `no` (sessions table from identity-001).
- **OpenAPI surface change:** `no` (routes in identity-005); however, the `securitySchemes` block is updated in identity-005, and this brief writes the `SessionCookie` security scheme definition that identity-005 references.

---

## Acceptance Criteria

- **AC-phase1-identity-004-01:** Given `CreateSession(user_id, request_metadata={user_agent, ip})`, when executed, then a row is INSERTed into `identity.sessions` with `refresh_token_hash` (argon2id), `expires_at = NOW() + 30 days`, `created_at`, `last_used_at`, the access-token cache is populated with `at:<sha256(access_token)>` → `{user_id, expires_at, scopes}` with 15-minute TTL, and the use case returns `CreateSessionResult(access_token_raw, refresh_token_raw, csrf_token_raw, expires_at)`. The raw tokens are returned ONCE for the route layer to set as cookies; never logged.
- **AC-phase1-identity-004-02:** Given an access token, when `AccessTokenCache.get(sha256(token))` is called and the key exists, then it returns `{user_id, expires_at, scopes}`; when missing or expired, returns None.
- **AC-phase1-identity-004-03:** Given the FastAPI dependency `get_current_user(request)`, when the request has a valid access-token cookie, then the dependency returns the User. When missing or expired, raises `Unauthenticated` (code `identity.unauthenticated`, status 401). When user is locked, raises `UserLocked`.
- **AC-phase1-identity-004-04:** Given `RefreshSession(refresh_token_raw)`, when the raw token's argon2id hash matches an active session row (`revoked_at IS NULL`, `expires_at > NOW()`), then a new access token is minted (cache populated), a new refresh token is generated and the old hash is replaced (rotation), `last_used_at` updates, and `SessionRefreshed` event is captured. The result is `RefreshSessionResult(access_token_raw, refresh_token_raw, csrf_token_raw, expires_at)`.
- **AC-phase1-identity-004-05:** Given `RefreshSession(refresh_token_raw)` with a token whose hash matches no row, when called, raises `RefreshTokenInvalid` (code `identity.refresh_token_invalid`, status 401).
- **AC-phase1-identity-004-06:** Given `RefreshSession(refresh_token_raw)` with a token whose row is revoked or expired, when called, raises `RefreshTokenInvalid` (same code — do not differentiate to avoid information leakage).
- **AC-phase1-identity-004-07:** Given `RevokeSession(session_id)`, when executed, sets `revoked_at = NOW()` (idempotent — already-revoked stays revoked), evicts the access-token cache entry for the session's last access token (if known), and captures `SessionRevoked` event.
- **AC-phase1-identity-004-08:** Given `RevokeAllSessions(user_id)`, when executed, sets `revoked_at` on every active session, evicts cache entries, and captures one `SessionRevoked` event per session.
- **AC-phase1-identity-004-09:** Given a request with a state-changing method (POST/PUT/PATCH/DELETE) and a session cookie but missing or mismatched `X-CSRF-Token` header vs the `csrf` cookie, when the CSRF dependency runs, raises `CsrfFailed` (code `identity.csrf_failed`, status 403). GET requests are exempt.
- **AC-phase1-identity-004-10:** Given the cookie-helper utility, when called to set session cookies on a response, then the access-token cookie has `httpOnly=True, Secure=True, SameSite=Lax, path="/", max_age=900`; the refresh-token cookie has `httpOnly=True, Secure=True, SameSite=Lax, path="/api/v1/auth/refresh", max_age=2592000`; the CSRF cookie has `httpOnly=False, Secure=True, SameSite=Lax, path="/", max_age=900`.

---

## Out of Scope

- HTTP routes for refresh / logout: `phase1-identity-005`.
- "Logout everywhere" admin route: Phase 3.
- "New device detected" flow: Phase 4 polish.
- Mobile bearer-header auth: per architecture Section 4, mentioned in ADR for V2; not implemented here.
- Cross-site cookie strategies (`SameSite=None` for embedded use cases): out of V1 — VaultChain is not embedded.
- Session sliding-window extension: V1 keeps fixed 30-day refresh tokens. Sliding extension is a polish item.

---

## Dependencies

- **Code dependencies:** `phase1-identity-001`, `phase1-shared-003`.
- **Data dependencies:** identity-001 migration applied.
- **External dependencies:** Redis (docker-compose), `argon2-cffi`.

---

## Test Coverage Required

- [ ] **Domain unit tests:** N/A — domain unchanged.
- [ ] **Application tests:** `tests/identity/application/test_create_session.py`, `test_refresh_session.py`, `test_revoke_session.py`, `test_get_current_user_dependency.py`
  - fakes for repos, fake `AccessTokenCache`, fake `RefreshTokenGenerator`
  - covers AC-01 through -09
  - test cases: `test_create_session_persists_and_caches`, `test_get_current_user_with_valid_token_returns_user`, `test_get_current_user_with_expired_token_raises_401`, `test_get_current_user_with_locked_user_raises_403`, `test_refresh_rotates_token_and_invalidates_old`, `test_refresh_invalid_token_raises_401`, `test_refresh_revoked_session_raises_401`, `test_refresh_expired_session_raises_401`, `test_revoke_idempotent_on_already_revoked`, `test_revoke_all_sessions_evicts_all`, `test_csrf_dependency_rejects_missing_header_on_post`, `test_csrf_dependency_passes_get_through`
- [ ] **Adapter tests:** `tests/identity/infra/test_redis_access_token_cache.py`, `test_refresh_token_generator.py`, `test_cookie_helpers.py`
  - testcontainers Redis
  - covers AC-02, -10
  - test cases: `test_redis_set_and_get_with_ttl`, `test_redis_get_after_ttl_returns_none`, `test_redis_evict_clears_key`, `test_token_generator_urlsafe_and_unique`, `test_cookie_helper_sets_correct_attributes_on_response`
- [ ] **Property tests:** `tests/identity/application/test_session_lifecycle_properties.py`
  - hypothesis-driven on sequences of (create, refresh, revoke)
  - properties: `for any sequence of session-lifecycle ops on a single user, at most one session is ever simultaneously active for a given (user_id, refresh_token_hash); revoked sessions never become active again; refresh always rotates the hash`

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Coverage ≥85% on `identity/application/`.
- [ ] OpenAPI: no change in this brief; identity-005 will reference the security-scheme block.
- [ ] Three events registered: `SessionCreated`, `SessionRefreshed`, `SessionRevoked`.
- [ ] No new ADR. (Cookie attributes are canonical per architecture-decisions Section 4.)
- [ ] No new port beyond `AccessTokenCache` and `RefreshTokenGenerator` (each with one fake).
- [ ] Single PR. Conventional commit: `feat(identity): session management — cookies, CSRF, refresh rotation [phase1-identity-004]`.

---

## Implementation Notes

- Access token format: `vc_at_<base64url(secrets.token_bytes(32))>`. Refresh token: `vc_rt_<base64url(secrets.token_bytes(32))>`. Prefixes make logs grep-able.
- Cache key: `at:{sha256(token).hexdigest()}` (NOT the raw token — never store raw tokens in Redis or logs). Value: JSON-encoded `{user_id, expires_at_iso, scopes: ["user"]}`.
- Refresh-token rotation: when `RefreshSession` succeeds, the old session row is UPDATEd in place — `refresh_token_hash` to the new hash, `last_used_at` to NOW. The session row is the same identity (same `id`), only the token changes. This preserves audit continuity.
- CSRF token: 32-byte random, base64url. Lives in the `csrf` cookie (`httpOnly=False` so JS can read it; this is intentional per double-submit pattern). Frontend reads it via `document.cookie`, sets the `X-CSRF-Token` header on every mutating request.
- The `get_current_user` FastAPI dependency reads the `vc_at` cookie via `request.cookies.get("vc_at")`, hashes it, looks up in cache, returns the User by user_id (one DB hit). Add a structlog binding `bind_contextvars(user_id=...)` so all subsequent logs in the request carry it.
- `SessionRevoked` event handler is NOT in this brief. Notifications (Phase 3) and any audit consumers will subscribe later.
- The `scopes` field on cached sessions is a forward-compat hook for Phase 3 admin scopes. V1 user sessions get `["user"]` only.

---

## Risk / Friction

- Argon2id is intentionally slow — verifying the refresh token on every refresh costs ~50ms. That's acceptable on the refresh path (called every 15 minutes). Do NOT use argon2 for *access*-token verification on every request — that's why access tokens are cached in Redis with sha256 (fast) lookup.
- `Secure=True` on cookies in local dev (`http://localhost`) means cookies don't get set in HTTP. Use a settings flag `COOKIES_SECURE` (default True; override to False in `.env.local`) to allow local dev. Document the override.
- The `csrf_token_raw` is returned from the use case alongside the raw access/refresh tokens — three returned secrets per session creation. The route in identity-005 sets all three as cookies in the same response. Do not return them in the JSON body, only as cookies.
- The CSRF dependency must be invokable both as a FastAPI Depends() and standalone for testing. Implement as a callable class with `__call__(self, request) -> None` — easier to test than a function.
