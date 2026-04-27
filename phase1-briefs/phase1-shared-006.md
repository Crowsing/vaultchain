---
ac_count: 8
blocks:
- phase1-identity-005
complexity: M
context: shared
depends_on:
- phase1-shared-005
estimated_hours: 4
id: phase1-shared-006
phase: 1
sdd_mode: strict
state: in_progress
title: Idempotency middleware (Redis-backed dual-layer)
touches_adrs: []
---

# Brief phase1-shared-006: Idempotency middleware (Redis-backed dual-layer)


## Context

Architecture-decisions Section 4 specifies dual-layer idempotency: an HTTP layer keyed on `(user_id, endpoint, idempotency_key)` cached in Redis with `SET NX EX 86400`, plus a domain-layer DB UNIQUE constraint on `transactions.idempotency_key` as a safety net. This brief delivers only the HTTP layer — the DB UNIQUE on transactions arrives with the Transactions context bootstrap (Phase 2).

The middleware is a Stripe-style implementation: claim the key, hash the request body, and on retry either return the cached response (if body-hash matches) or 422 with `idempotency.conflict_body_mismatch` (if body changed). Fail-open on Redis outage with structured WARN log — invariant: an outage of the cache must not block writes. The DB UNIQUE is the actual safety net, not the cache.

This brief is a single piece of middleware plus a Redis port. It is short by design — the work is in the corner cases, captured by ACs.

---

## Architecture pointers

- **Layer(s):** `delivery` (middleware), `infra` (Redis adapter)
- **Affected packages:** `vaultchain.shared.delivery`, `vaultchain.shared.infra.redis_idempotency`
- **Reads from:** Redis cache
- **Writes to:** Redis cache
- **Publishes events:** `none`
- **Subscribes to events:** `none`
- **New ports introduced:** `IdempotencyStore` Protocol in `shared/domain/ports.py`
- **New adapters introduced:** `RedisIdempotencyStore`, `FakeIdempotencyStore` (test fake)
- **DB migrations required:** `no`
- **OpenAPI surface change:** `yes` — every mutating endpoint adds `Idempotency-Key` header parameter (optional except where flagged required by an endpoint's brief). Update the `securitySchemes` and add `parameters` block to operations.

---

## Acceptance Criteria

- **AC-phase1-shared-006-01:** Given a POST request with `Idempotency-Key: <uuid>` and a request body, when the middleware runs and Redis has no key, then the key is claimed via `SET NX EX 86400` and the request proceeds to the route handler.
- **AC-phase1-shared-006-02:** Given a POST request that succeeded (claimed key, ran handler, cached response), when the same `Idempotency-Key` is sent with the *same* request body, then the cached response (status, headers, body) is returned without invoking the route handler.
- **AC-phase1-shared-006-03:** Given a POST request that succeeded, when the same `Idempotency-Key` is sent with a *different* request body, then the response is 422 with envelope `code="idempotency.conflict_body_mismatch"` and `details.original_body_hash` and `details.actual_body_hash`.
- **AC-phase1-shared-006-04:** Given a POST request whose handler raised an unexpected `Exception`, when the middleware catches it, then the cache stores the resulting 500 response (so retries with the same key get the same 500). For `DomainError` 4xx responses, behavior is the same — the response is cached and returned on retry.
- **AC-phase1-shared-006-05:** Given Redis is unreachable, when a POST request arrives, then the middleware logs a structured WARN, sets a `X-Idempotency-Disabled: 1` response header, and lets the request proceed without idempotency enforcement (fail-open). The route handler still runs.
- **AC-phase1-shared-006-06:** Given a GET, HEAD, or OPTIONS request, when received, then the middleware does not interact with Redis (idempotency applies only to mutating verbs).
- **AC-phase1-shared-006-07:** Given a POST request without an `Idempotency-Key` header, when the middleware runs, then it passes through unchanged (idempotency is opt-in via header presence; route-level requirement is enforced by the route's own dependency, not here).
- **AC-phase1-shared-006-08:** Given two concurrent POSTs with the same `Idempotency-Key`, when both arrive within milliseconds, then exactly one acquires `SET NX` and runs; the other receives an `idempotency.in_flight` 409 response and the client may retry — verified by an adapter test using a real Redis under concurrent execution.

---

## Out of Scope

- DB UNIQUE on `transactions.idempotency_key`: arrives with the Transactions context (Phase 2).
- Hot-path payload hashing optimization (e.g., streaming hash on large bodies): V1 caps body at 1MB at the FastAPI level; in-memory hash is fine.
- Idempotency-key format validation (whether the client must send a UUIDv4 vs any opaque string): accept any string ≤200 chars; reject longer with envelope `code="validation.idempotency_key_too_long"`. No UUID requirement.
- Per-user rate limiting: separate concern, lives with rate-limit middleware (Phase 2).

---

## Dependencies

- **Code dependencies:** `vaultchain.shared.domain.ports`, `vaultchain.shared.delivery` (error handlers from `phase1-shared-005`).
- **Data dependencies:** `none`.
- **External dependencies:** `redis[hiredis]`, Redis service in docker-compose (bootstrap-delivered).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/shared/domain/test_idempotency_store_protocol.py`
  - covers AC-phase1-shared-006-01 (Protocol shape only)
  - test cases: `test_idempotency_store_protocol_signatures`
- [ ] **Application tests:** `tests/shared/application/test_idempotency_middleware.py`
  - uses `FakeIdempotencyStore` (in-memory dict)
  - covers AC-phase1-shared-006-01 through -07
  - test cases: `test_first_request_claims_and_proceeds`, `test_replay_same_body_returns_cached`, `test_replay_different_body_returns_422`, `test_handler_4xx_response_cached`, `test_handler_500_response_cached`, `test_redis_outage_fails_open`, `test_get_request_unaffected`, `test_no_header_proceeds_unchanged`, `test_key_too_long_rejected`
- [ ] **Adapter tests:** `tests/shared/infra/test_redis_idempotency_store.py`
  - testcontainers Redis, real connection
  - covers AC-phase1-shared-006-08
  - test cases: `test_set_nx_real_redis`, `test_concurrent_claim_exactly_one_wins`, `test_ttl_expires_key`
- [ ] **Property tests:** `tests/shared/application/test_idempotency_replay_properties.py`
  - hypothesis-driven (per architecture Section 5 must-have list #7)
  - properties: `for any command and any sequence of N replays of the same idempotency key with the same body, the cached response is byte-identical and the handler is invoked exactly once`

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] Property test for idempotency replay is in place (Section 5 must-have list item #7).
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Coverage ≥85% on `shared/delivery/`.
- [ ] OpenAPI updated: `Idempotency-Key` header parameter declared as a reusable `parameters` component, referenced from mutating routes' specs (route-level wiring happens in subsequent briefs).
- [ ] No new ADR.
- [ ] No new port introduced beyond `IdempotencyStore` (with one fake).
- [ ] Single PR. Conventional commit: `feat(shared): idempotency middleware (Redis-backed dual-layer) [phase1-shared-006]`.

---

## Implementation Notes

- The cache key is `idempotency:{user_id_or_anonymous}:{path}:{idempotency_key}`. For anonymous endpoints (signup, magic-link request), use the IP address in place of user_id.
- Body hashing: `sha256(raw_request_body_bytes).hexdigest()`. Read body via `request.body()` (FastAPI), then re-inject for the route handler — the cleanest path is `await request.body()` once at middleware level, attach to `request.state.body`, and use a custom `Request` subclass that returns from state on subsequent reads.
- Cached response: serialize `{status_code, headers (filtered), body_bytes}`. Strip `Set-Cookie` and other non-idempotent response headers from the cache so that retries don't blow up session state. Document the strip-list in the module.
- `SET NX EX 86400`: 24 hours TTL — long enough for any reasonable retry window, short enough to not balloon Redis.
- Concurrency: the `SET NX` is atomic. The losing client receives `nil`, which the middleware translates to 409 `idempotency.in_flight`. The client retries after a short delay.
- Use the `IdempotencyStore` Protocol so the middleware itself is unit-testable without Redis. Wire `RedisIdempotencyStore` in DI at composition root.

---

## Risk / Friction

- Body re-injection after `await request.body()` is FastAPI's known sharp edge; use the documented pattern (override `request._body`). Add a comment with link to FastAPI issue for the next reader.
- Filtering response headers for caching is a known compliance pitfall — never cache `Set-Cookie`, `WWW-Authenticate`, or anything with secrets. Document the allow-list explicitly in the module.
- Property test depth: hypothesis-generated body bytes can blow up memory if unbounded. Cap example body size at 64KB via `@settings(max_examples=200, deadline=2000)`.
