---
ac_count: 3
blocks:
- phase1-identity-005
complexity: L
context: identity
depends_on:
- phase1-identity-001
- phase1-shared-003
estimated_hours: 4
id: phase1-identity-002
phase: 1
sdd_mode: strict
state: ready
title: Magic-link signup/login flow + email port + console adapter
touches_adrs: []
---

# Brief phase1-identity-002: Magic-link signup/login flow + email port + console adapter


## Context

This brief implements the magic-link half of auth: `RequestMagicLink`, `ConsumeMagicLink`. Both are application use cases that orchestrate the `User`, `MagicLink`, and `Email` VO from the domain (delivered by `phase1-identity-001`), plus introduce a new `EmailSender` port whose V1 adapter prints to console (per `00-product-identity.md` open question — Resend/Postmark decision deferred to Phase 2).

The flow drives the `LANDING → SIGNUP/LOGIN_EMAIL → MAGIC_SENT → VALIDATING → ENROLL/LOGIN_TOTP` transitions in `auth-onboarding-notes.md`. This brief delivers the SIGNUP/LOGIN_EMAIL → MAGIC_SENT and MAGIC_SENT → VALIDATING segments. TOTP enrollment/verification is `phase1-identity-003`; session creation on success is `phase1-identity-004`.

The use cases publish events: `MagicLinkRequested` (consumed by future Notifications context — for V1, just goes to outbox), and `MagicLinkConsumed` (consumed by an event handler in this same brief that triggers the `verify_email` transition on the User if mode=`signup`).

---

## Architecture pointers

- **Layer(s):** `application` (use cases), `infra` (email console adapter, magic-link token generator), `domain` (event registration only — events declared in identity-001)
- **Affected packages:** `vaultchain.identity.application`, `vaultchain.identity.infra.email`, `vaultchain.shared.events.registry`
- **Reads from:** `identity.users`, `identity.magic_links`
- **Writes to:** `identity.users`, `identity.magic_links`, `shared.domain_events` (via UoW)
- **Publishes events:** `MagicLinkRequested`, `MagicLinkConsumed`, `UserSignedUp` (the latter when consume succeeds in `signup` mode and verification transitions the user)
- **Subscribes to events:** `MagicLinkConsumed` → handler `mark_user_verified_on_signup_link` (registered in this brief; runs in the outbox worker from `phase1-shared-004`).
- **New ports introduced:** `EmailSender` Protocol in `identity/domain/ports.py`. `MagicLinkTokenGenerator` Protocol (so that tests can inject a deterministic token).
- **New adapters introduced:** `ConsoleEmailSender` in `identity/infra/email/console.py` (prints to stdout with structured layout — subject, to, body), `SecretsTokenGenerator` (uses `secrets.token_urlsafe`), and fakes for both in `tests/identity/fakes/`.
- **DB migrations required:** `no` (tables exist from identity-001).
- **OpenAPI surface change:** `no` (HTTP routes arrive in identity-005).

---

## Acceptance Criteria

- **AC-phase1-identity-002-01:** Given `RequestMagicLink(email="new@x.io", mode="signup")`, when executed and the email is not in `identity.users`, then a User row is created with `status="unverified"`, a MagicLink row is created with `mode="signup"`, `expires_at = now + 15min`, and the `EmailSender.send_magic_link` is called with the (raw) token.
- **AC-phase1-identity-002-02:** Given `RequestMagicLink(email="existing@x.io", mode="login")` for an existing verified user, when executed, then no new User is created, a MagicLink row is created with `mode="login"`, and `EmailSender.send_magic_link` is called.
- **AC-phase1-identity-002-03:** Given `RequestMagicLink(email="locked@x.io", ...)` for a `status="locked"` user, when executed, then the use case raises `UserLocked` (envelope code `identity.user_locked`, status 403). No magic link is created. No email is sent.
- **AC-phase1-identity-002-04:** Given a `RequestMagicLink` with mode=`login` for an email that does NOT exist, when executed, then the use case still returns success (no row created, no email sent in reality, but the response is identical to the "email exists" path) — to prevent user-enumeration. A WARN log is emitted with `event="login_request_for_unknown_email"`. The case is verified by inspecting the response shape, NOT by inspecting log output (logs are not a contract).
- **AC-phase1-identity-002-05:** Given `ConsumeMagicLink(raw_token=t, request_metadata={user_agent, ip})`, when executed and the token hash matches a `MagicLink` row that is unexpired and not consumed, then `consumed_at` is set, the use case returns `MagicLinkConsumeResult(user_id, mode, is_first_time: bool)`, and a `MagicLinkConsumed` event is captured.
- **AC-phase1-identity-002-06:** Given `ConsumeMagicLink` with a token whose hash does not match any row, when executed, then it raises `MagicLinkInvalid` (code `identity.magic_link_invalid`, status 401). No partial mutation occurs.
- **AC-phase1-identity-002-07:** Given `ConsumeMagicLink` with a token whose row has `consumed_at IS NOT NULL`, when executed, then it raises `MagicLinkAlreadyUsed` (code `identity.magic_link_already_used`, status 401). The row is NOT modified again — re-consumption is a no-op pending the error.
- **AC-phase1-identity-002-08:** Given `ConsumeMagicLink` with a row whose `expires_at < NOW()`, when executed, then it raises `MagicLinkExpired` (code `identity.magic_link_expired`, status 401).
- **AC-phase1-identity-002-09:** Given a successful `ConsumeMagicLink` in `mode="signup"`, when the `MagicLinkConsumed` event is dispatched by the outbox worker, then the registered handler transitions the User from `unverified` to `verified` and increments `version`. The handler is idempotent (re-delivery via `event_handler_log` does NOT re-transition).
- **AC-phase1-identity-002-10:** Given the `ConsoleEmailSender`, when `send_magic_link(email, raw_token, mode)` is called, then a structured line is printed (or logged) with `to`, `subject`, and the magic-link URL. The URL format is `{FRONTEND_URL}/auth/verify?token={raw_token}&mode={signup|login}` — `FRONTEND_URL` from settings.

---

## Out of Scope

- TOTP enrollment / verification: `phase1-identity-003`.
- Session creation: `phase1-identity-004`.
- HTTP routes (`POST /api/v1/auth/request`, `POST /api/v1/auth/verify`): `phase1-identity-005`.
- Real email provider (Resend/Postmark): Phase 2 — when one is selected, `ConsoleEmailSender` is replaced via DI; the port stays.
- "New device detected" detection (per auth notes): heuristic out of V1 — the `Session` repository stores `user_agent` and `ip_inet`, but the new-device branch is a Phase 4 polish item.
- "Try as demo user" flow: a separate Phase 4 brief (it short-circuits this whole flow with a synthetic session).
- Rate limiting on magic-link requests (per chain, per-IP): Phase 2.

---

## Dependencies

- **Code dependencies:** `phase1-identity-001` (domain), `phase1-shared-003` (UoW). `EmailSender` port is introduced here.
- **Data dependencies:** identity-001 migration applied.
- **External dependencies:** `secrets` (stdlib), `argon2-cffi` (already imported by identity-001).

---

## Test Coverage Required

- [ ] **Domain unit tests:** N/A — domain unchanged from identity-001.
- [ ] **Application tests:** `tests/identity/application/test_request_magic_link.py`, `test_consume_magic_link.py`
  - fakes for repos, fake `EmailSender`, fake `MagicLinkTokenGenerator`
  - covers AC-01 through -09
  - test cases: `test_signup_new_email_creates_user_and_link`, `test_login_existing_user_creates_link`, `test_locked_user_rejected`, `test_login_unknown_email_returns_success_no_email_sent`, `test_consume_valid_link_returns_result_and_emits_event`, `test_consume_invalid_token_raises`, `test_consume_already_used_raises`, `test_consume_expired_raises`, `test_signup_consume_handler_transitions_user_to_verified`, `test_signup_consume_handler_idempotent_on_redelivery`
- [ ] **Adapter tests:** `tests/identity/infra/test_console_email_sender.py`, `test_secrets_token_generator.py`
  - covers AC-10
  - test cases: `test_console_email_sender_emits_structured_line`, `test_token_generator_produces_urlsafe_string`
- [ ] **Property tests:** `tests/identity/application/test_consume_magic_link_idempotency_properties.py`
  - hypothesis-driven on event re-delivery (validates the handler is at-most-once)
  - properties: `for any sequence of redeliveries of MagicLinkConsumed for the same magic link, the user is verified at most once and version is incremented at most once`

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Coverage ≥85% on `identity/application/` and `identity/infra/email/`.
- [ ] OpenAPI: no change.
- [ ] Three events registered in `shared/events/registry.py`: `MagicLinkRequested`, `MagicLinkConsumed`, `UserSignedUp`.
- [ ] `MagicLinkConsumed` handler registered with the EventBus and discovered by the outbox worker.
- [ ] No new ADR.
- [ ] No new port introduced beyond `EmailSender` and `MagicLinkTokenGenerator` (each with one fake).
- [ ] Single PR. Conventional commit: `feat(identity): magic-link signup/login + email console adapter [phase1-identity-002]`.

---

## Implementation Notes

- The `RequestMagicLink` use case is *idempotent on email* — calling it twice with the same email creates two distinct magic-link rows. Both are valid until consumed/expired. This is intentional: it lets users hit "Resend" without invalidating prior links the email client may also receive. Add a comment.
- Token hash strategy: `sha256(raw_token).digest()`. Compare via constant-time `hmac.compare_digest`. Never store the raw token.
- The "user enumeration" defense (AC-04) is a known auth pattern — both code paths must take similar wall-clock time. A simple strategy: always perform the `secrets.token_urlsafe` work (cheap) and a no-op `pass` when the email is unknown. Hypothesis will flag timing differences only if you let them through; do not optimize the unknown path away.
- The `MagicLinkConsumed` handler runs in the outbox worker and uses its OWN UoW — separate from the consume use case's UoW. Hence the explicit idempotency check via `event_handler_log` plus the version check on user UPDATE. If the user was already verified by a re-delivered handler, `User.verify_email()` raises `InvalidStateTransition`; the handler catches it and treats it as success (the desired end state was reached).
- The `ConsumeMagicLink` use case returns `MagicLinkConsumeResult` with `is_first_time: bool`. This drives the frontend route choice: first-time → enrollment screen, returning → TOTP login screen. The `mode` field on the link disambiguates, but `is_first_time` derives from `User.totp_secret_id IS NULL` (or rather: from a `TotpSecretRepository.exists_for_user` query).
- Console adapter format (one structured line per email):
  ```
  [EMAIL stdout] to=user@x.io subject="Your VaultChain magic link"
                 url=https://app.example/auth/verify?token=...&mode=signup
  ```
  Use `structlog` so it's parseable in dev tooling.

---

## Risk / Friction

- The handler-on-consume pattern (event drives state transition) is more elaborate than calling `User.verify_email()` synchronously inside `ConsumeMagicLink`. The reason for the asynchrony: it forces the outbox/handler-idempotency machinery to be exercised by the simplest possible flow, surfacing wiring bugs in Phase 1 rather than Phase 2 when the cost of a bug rises. Push back is reasonable but architecture-decisions Section 3 favors this pattern.
- AC-04 (enumeration defense) is the kind of thing a reviewer might call paranoid. Justification: this is a custodial wallet, and an enumeration oracle on signup is a textbook auth weakness. The portfolio reads stronger with it than without.
- The first-time / returning split happens at consume time but matters at the *next* step (where the user goes — enrollment or TOTP challenge). The frontend uses `is_first_time` from the consume response; the backend does not redirect.
