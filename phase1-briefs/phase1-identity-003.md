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
id: phase1-identity-003
phase: 1
sdd_mode: strict
state: merged
title: TOTP enrollment + verification use cases
touches_adrs: []
---

# Brief phase1-identity-003: TOTP enrollment + verification use cases


## Context

This brief delivers the TOTP half of auth: `EnrollTotp`, `VerifyTotp`, `RegenerateBackupCodes`. The state machine in `auth-onboarding-notes.md` drives the design: enrollment is a 4-step wizard (explain → scan → verify → backup codes); verification handles the LOGIN_TOTP screen plus the backup-code recovery branch; failure counters lock the account at 5 wrong attempts (15-minute self-healing lockout, also reflected in the state machine).

The `pyotp` library handles the TOTP math; this brief is mostly about lifecycle, side-effect orchestration, and the lockout state machine. The TOTP secret is encrypted at rest using the `TotpSecretEncryptor` port from `phase1-identity-001`.

The use cases publish events: `TotpEnrolled` (consumed by Notifications later), `TotpVerified` (consumed by session-creation in identity-004), `TotpVerificationFailed` (drives the lockout counter — handler in this brief). The lockout is an attribute on the user (not a separate aggregate): `User.failed_totp_attempts INTEGER NOT NULL DEFAULT 0` and `User.locked_until TIMESTAMPTZ NULL` — both columns added in this brief's migration as an additive change.

---

## Architecture pointers

- **Layer(s):** `application` (use cases + handler), `infra` (TOTP code-checker adapter — `pyotp` wrapper), `domain` (only adds methods to `User`: `record_totp_failure`, `clear_totp_failures`, `is_locked_now`)
- **Affected packages:** `vaultchain.identity.application`, `vaultchain.identity.infra.totp`, Alembic versions/, `vaultchain.identity.domain.user` (additive methods only)
- **Reads from:** `identity.users`, `identity.totp_secrets`
- **Writes to:** `identity.users`, `identity.totp_secrets`, `shared.domain_events`
- **Publishes events:** `TotpEnrolled`, `TotpVerified`, `TotpVerificationFailed`, `UserLockedDueToTotpFailures`
- **Subscribes to events:** `TotpVerificationFailed` → `increment_user_lockout_counter` (registered here; runs in outbox worker).
- **New ports introduced:** `TotpCodeChecker` Protocol (so tests inject deterministic verification — fakes can return True/False without TOTP math).
- **New adapters introduced:** `PyOtpCodeChecker` in `identity/infra/totp/`, plus `BackupCodeGenerator` and `BackupCodeChecker` (the latter compares argon2id of the input against the stored hashes). Fakes in `tests/identity/fakes/`.
- **DB migrations required:** `yes` — additive on `identity.users`: `failed_totp_attempts INTEGER NOT NULL DEFAULT 0`, `locked_until TIMESTAMPTZ NULL`. Migration file: `<date>_identity_user_lockout_columns.py`.
- **OpenAPI surface change:** `no` (HTTP routes in identity-005).

---

## Acceptance Criteria

- **AC-phase1-identity-003-01:** Given the migration applied, when `\d identity.users` is inspected, then `failed_totp_attempts` and `locked_until` columns exist with the specified types and defaults.
- **AC-phase1-identity-003-02:** Given `EnrollTotp(user_id=u)` for a user without an existing TOTP secret, when executed, then a fresh secret is generated, the secret is encrypted via the encryptor port and persisted, 10 backup codes are generated and their argon2id hashes stored, and the use case returns `TotpEnrollmentResult(secret_for_qr, qr_payload_uri, backup_codes_plaintext)`. Plaintext is returned ONCE — re-fetching the secret never returns plaintext.
- **AC-phase1-identity-003-03:** Given `EnrollTotp` for a user who already has a TOTP secret, when executed, then it raises `TotpAlreadyEnrolled` (code `identity.totp_already_enrolled`, status 409). To re-enroll, a separate `RegenerateBackupCodes` flow exists; full re-enrollment is a recovery flow out of V1.
- **AC-phase1-identity-003-04:** Given `VerifyTotp(user_id, code="123456")` and the user's secret produces "123456" for the current 30-second window, when executed, then `TotpVerified` event is captured, `failed_totp_attempts` resets to 0, `last_verified_at` updates, and the result is `TotpVerifyResult(success=True, attempts_remaining=None)`.
- **AC-phase1-identity-003-05:** Given `VerifyTotp` with a wrong code, when executed, then the result is `TotpVerifyResult(success=False, attempts_remaining=4)` (5 minus current failed count post-increment), `TotpVerificationFailed` event is captured. The use case does NOT raise — the failure is a successful return value (frontend displays attempts remaining).
- **AC-phase1-identity-003-06:** Given the user has `failed_totp_attempts=4` and `VerifyTotp` fails again (5th failure), when the `TotpVerificationFailed` handler runs, then `locked_until = NOW() + 15min`, `User.status` set to `locked`, and `UserLockedDueToTotpFailures` event is captured. Subsequent verification attempts during the lockout window raise `UserLocked` (code `identity.user_locked`, status 403) with `details.locked_until` set.
- **AC-phase1-identity-003-07:** Given a user with `locked_until` in the past, when `VerifyTotp` is called, then `failed_totp_attempts` is reset, `locked_until` is cleared, `status` returns to `verified`, and the verification proceeds normally (lockout is self-healing).
- **AC-phase1-identity-003-08:** Given `VerifyTotp(user_id, code, use_backup_code=True)` with a code matching one of the user's stored backup codes (argon2id verify), when executed, then the matching code is *removed* from `backup_codes_hashed` (one-time use) and verification succeeds. `attempts_remaining` is the standard 5-failures policy independent of backup codes — backup codes do NOT consume the failure counter.
- **AC-phase1-identity-003-09:** Given `RegenerateBackupCodes(user_id)`, when executed (typically gated by a fresh TOTP verification within the same session, but that gating happens in identity-005's route layer), then 10 fresh backup codes replace the stored hashes and the use case returns plaintext exactly once. Old backup codes become invalid in the same UoW.
- **AC-phase1-identity-003-10:** Given the `qr_payload_uri` returned from `EnrollTotp`, when inspected, then it is an `otpauth://totp/VaultChain:{email}?secret={base32}&issuer=VaultChain` URI (industry-standard format, scannable by 1Password, Authy, Google Authenticator, Aegis per the auth spec).

---

## Out of Scope

- Account-recovery via support: docs link in spec; no implementation.
- TOTP "remember this device" (skip TOTP for 30 days on this device): not in V1 — every transaction requires fresh TOTP per `00-product-identity.md` invariant.
- Phone/SMS 2FA: explicitly rejected in V1.
- Biometric: V2.
- HTTP routes: `phase1-identity-005`.
- Session creation on success: `phase1-identity-004`.
- Admin-side reset of a locked user (admin overrides lockout): a dedicated admin brief in Phase 3 (admin-userlock).

---

## Dependencies

- **Code dependencies:** `phase1-identity-001` (User entity, TotpSecret aggregate, encryptor port), `phase1-shared-003` (UoW).
- **Data dependencies:** identity-001 migration applied; this brief adds two columns to `identity.users`.
- **External dependencies:** `pyotp` (already in `pyproject.toml`).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/identity/domain/test_user_lockout.py`
  - covers AC-06, -07 (state methods only — no I/O)
  - test cases: `test_record_totp_failure_increments`, `test_5th_failure_locks_user`, `test_is_locked_now_returns_true_within_window`, `test_is_locked_now_returns_false_after_window`, `test_clear_totp_failures_resets`
- [ ] **Application tests:** `tests/identity/application/test_enroll_totp.py`, `test_verify_totp.py`, `test_regenerate_backup_codes.py`
  - fakes for repos, fake `TotpCodeChecker`, fake encryptor
  - covers AC-02 through -09
  - test cases: `test_enroll_creates_secret_and_backup_codes`, `test_enroll_idempotent_blocked`, `test_verify_success_resets_counter`, `test_verify_failure_returns_attempts_remaining`, `test_5th_failure_locks_user_via_handler`, `test_locked_user_rejected_during_window`, `test_locked_user_self_heals_after_window`, `test_verify_with_backup_code_consumes_code`, `test_regenerate_backup_codes_replaces_old_hashes`
- [ ] **Adapter tests:** `tests/identity/infra/test_pyotp_code_checker.py`, `test_backup_code_hashing.py`
  - covers AC-04, -10
  - test cases: `test_pyotp_verifies_current_window`, `test_pyotp_rejects_outside_window`, `test_qr_payload_uri_format`, `test_backup_code_argon2id_roundtrip`
- [ ] **Property tests:** `tests/identity/application/test_lockout_state_machine_properties.py`
  - hypothesis-driven on sequences of (success, failure) attempts (no orphan states)
  - properties: `for any random sequence of N verify attempts, the user state stays in the valid graph (verified | locked); after K failures (K<5), counter == K and status stays verified; on K==5, status is locked; on success after lockout window, counter resets to 0 and status returns to verified`

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] Property test for lockout state machine in place.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Coverage ≥85% on `identity/application/`.
- [ ] OpenAPI: no change.
- [ ] Four events registered in `shared/events/registry.py`: `TotpEnrolled`, `TotpVerified`, `TotpVerificationFailed`, `UserLockedDueToTotpFailures`.
- [ ] Lockout handler registered with EventBus and discovered by outbox worker.
- [ ] No new ADR.
- [ ] Migration `<date>_identity_user_lockout_columns.py` committed with downgrade tested.
- [ ] Single PR. Conventional commit: `feat(identity): TOTP enrollment + verification + lockout [phase1-identity-003]`.

---

## Implementation Notes

- TOTP window: `pyotp.TOTP(secret).verify(code, valid_window=1)` accepts the current window and one window each side (90 seconds total tolerance). This handles clock drift on user devices. Document the choice in the use case.
- The lockout is a User-aggregate concern (state lives on the user row), but the *trigger* is an event from the verify use case. The reason for going through the event bus rather than a direct method call: the lockout transition is itself a state change that should be observable (handler logs, future Notifications, audit trail). The synchronous alternative would be one less moving part but loses observability.
- Backup codes: 10 codes, format `XXXX-XXXX` (8 alphanum chars, uppercase, hyphenated for readability — matches the demo data `4HK9-2PXM` in `auth-onboarding-notes.md`). Generate via `secrets.choice` over the alphanum alphabet; argon2id-hash before storage.
- The `TotpEnrollmentResult.secret_for_qr` is the *base32-encoded* secret string (what `pyotp.random_base32()` produces). The `qr_payload_uri` is the full otpauth URI. Frontend renders the QR client-side or via a simple library.
- The handler `increment_user_lockout_counter` is the only handler in identity that mutates the User. It uses its OWN UoW with the standard idempotency pattern (`event_handler_log` UNIQUE).
- DI wiring: `EnrollTotp`, `VerifyTotp`, `RegenerateBackupCodes` are constructed with the injected repos, encryptor, code-checker, backup-code-generator, and UoW factory. Document the constructor in a docstring; subsequent briefs (especially admin-002 reusing TOTP) will assemble these the same way.

---

## Risk / Friction

- The lockout handler reads/writes the User row that the failed verify just read. There is no race in the simple case (the handler runs after the verify's UoW commits), but if a user retries fast enough, two `TotpVerificationFailed` events could be in the outbox simultaneously. The handler's UoW uses optimistic locking (version check on User), so the second handler invocation will retry on `StaleAggregate` — verified by the property test. Document the retry path explicitly in the handler.
- "Backup codes don't consume the failure counter" (AC-08) is a usability-vs-security tradeoff. Argued: the backup code flow is the recovery path; punishing failures there too aggressively bricks users. Documented as the chosen tradeoff. Reviewers may push back; the answer is in this brief.
- The TOTP secret plaintext returned from enrollment is the only time it ever leaves the backend. Once persisted, the encryptor port has no `decrypt_for_display` method — only `decrypt_for_verify` which feeds `pyotp.TOTP(secret).verify(...)` internally. The seam is `TotpSecret.verify_code(code, encryptor, code_checker) -> bool`; `secret` plaintext stays in a local variable, never returned.
