---
ac_count: 9
blocks:
- phase1-identity-002
- phase1-identity-003
- phase1-identity-004
- phase1-admin-002
complexity: M
context: identity
depends_on:
- phase1-shared-003
estimated_hours: 4
id: phase1-identity-001
phase: 1
sdd_mode: strict
state: merged
title: Identity domain (User, Session, MagicLink, TotpSecret)
touches_adrs: []
---

# Brief phase1-identity-001: Identity domain (User, Session, MagicLink, TotpSecret)


## Context

Identity is the auth context: users, sessions, magic links, TOTP secrets. This brief delivers the domain layer (entities, VOs, domain services, errors, events) plus the SQLAlchemy mappings, repositories, and the migration that creates the `identity` schema with all four tables. Application use cases (signup, verify, enroll) come in subsequent identity briefs.

The decision to bundle four aggregates into one brief: they are tightly coupled in the data model (Session FK to User, MagicLink FK to User, TotpSecret FK to User), they share migration cost, and splitting them would create per-aggregate briefs with no use case to justify them. The tradeoff: this is at the upper bound of an M brief (~4 hours). If Claude Code overflows, the M→L escalation is documented as a risk below.

The auth state machine from `auth-onboarding-notes.md` drives entity invariants: `UserStatus` is `unverified | verified | locked`; sessions have `created_at, last_used_at, expires_at, revoked_at`; magic links are one-shot with `consumed_at`. TOTP secrets are encrypted at rest (placeholder envelope encryption — real KMS arrives in Phase 2; here we use a configured static key from settings, with a TODO marker pointing to the KMS brief).

---

## Architecture pointers

- **Layer(s):** `domain` (entities, VOs, services, ports, events, errors), `infra` (SQLAlchemy mappers, repositories, migration)
- **Affected packages:** `vaultchain.identity.domain`, `vaultchain.identity.infra`, Alembic versions/
- **Reads from:** `none` (this brief introduces the data)
- **Writes to:** `identity.users`, `identity.sessions`, `identity.magic_links`, `identity.totp_secrets`
- **Publishes events:** `none` directly — events are emitted from the application use cases in identity-002/003/004. This brief only declares the event dataclasses (`UserSignedUp`, `MagicLinkRequested`, `MagicLinkConsumed`, `TotpEnrolled`, `TotpVerified`, `SessionCreated`, `SessionRevoked`).
- **Subscribes to events:** `none`
- **New ports introduced:** `UserRepository`, `SessionRepository`, `MagicLinkRepository`, `TotpSecretRepository` — all Protocols in `identity/domain/ports.py`. Plus `TotpSecretEncryptor` Protocol (KMS-port stub) for encrypt/decrypt of the secret bytes.
- **New adapters introduced:** SQLAlchemy implementations of each repository in `identity/infra/`; `StaticKeyTotpEncryptor` adapter (V1 placeholder — config-key based, not KMS); fakes for all of the above in `tests/identity/fakes/`.
- **DB migrations required:** `yes` — `identity` schema, four tables per architecture-decisions Section 3 plus engineering-spec data model:
  - `identity.users` (id UUIDv7 PK, email TEXT UNIQUE NOT NULL, email_hash BYTEA, status TEXT CHECK IN ('unverified','verified','locked'), kyc_tier INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ)
  - `identity.sessions` (id UUIDv7 PK, user_id FK→users, refresh_token_hash BYTEA NOT NULL UNIQUE, created_at, last_used_at, expires_at, revoked_at NULL, user_agent TEXT, ip_inet INET)
  - `identity.magic_links` (id UUIDv7 PK, user_id FK→users, token_hash BYTEA NOT NULL UNIQUE, mode TEXT CHECK IN ('signup','login'), created_at, expires_at, consumed_at NULL)
  - `identity.totp_secrets` (id UUIDv7 PK, user_id UUID UNIQUE NOT NULL FK→users, secret_encrypted BYTEA NOT NULL, backup_codes_hashed BYTEA[] NOT NULL, enrolled_at, last_verified_at NULL)
- **OpenAPI surface change:** `no`

---

## Acceptance Criteria

- **AC-phase1-identity-001-01:** Given the migration applied, when each of the four tables is inspected, then columns, types, NOT NULL, UNIQUE, FK, CHECK constraints all match the spec listed in "Architecture pointers."
- **AC-phase1-identity-001-02:** Given the migration applied, when downgraded, then all four tables and the schema are removed (no orphan objects).
- **AC-phase1-identity-001-03:** Given a `User` entity, when `verify_email()` is called on an `unverified` user, then `status` transitions to `verified` and `version` increments by 1; given a `verified` user, calling `verify_email()` raises `InvalidStateTransition` (subclass of `ConflictError`).
- **AC-phase1-identity-001-04:** Given a `User` entity, when `lock(reason: str)` is called, then `status` becomes `locked` regardless of previous status, and a `UserLocked` domain event is appended to the user's pending events.
- **AC-phase1-identity-001-05:** Given a `MagicLink` aggregate with `expires_at` in the past, when `consume()` is called, then the call raises `MagicLinkExpired` (subclass of `DomainError`, code `identity.magic_link_expired`); given an already-consumed link (`consumed_at IS NOT NULL`), it raises `MagicLinkAlreadyUsed` (code `identity.magic_link_already_used`).
- **AC-phase1-identity-001-06:** Given a `Session` aggregate with `expires_at` in the past or `revoked_at IS NOT NULL`, when `is_active()` is called, then it returns False; otherwise True. `revoke()` is idempotent — calling on an already-revoked session does not raise and does not change `revoked_at`.
- **AC-phase1-identity-001-07:** Given a `TotpSecret` aggregate created via `TotpSecret.enroll(user_id, generated_secret_bytes, encryptor)`, when persisted and reloaded, then the round-trip yields the same plaintext secret via `decrypt(encryptor)` (validates the encryptor port contract).
- **AC-phase1-identity-001-08:** Given the `UserRepository.get_by_email` method, when called with an email that has trailing whitespace or different casing than stored, then the lookup is normalized: emails are stored lowercase and trimmed (normalization happens in the `Email` VO constructor in `identity/domain/value_objects.py`).
- **AC-phase1-identity-001-09:** Given an aggregate UPDATE in a UoW, when two concurrent UoWs both load `version=N` and attempt UPDATE, then exactly one succeeds and the other raises `StaleAggregate` (uses the optimistic-lock plumbing from `phase1-shared-003`).

---

## Out of Scope

- Magic-link generation, sending, and consumption use cases: covered by `phase1-identity-002`.
- TOTP enroll, verify, lock-after-failures use cases: covered by `phase1-identity-003`.
- Session creation, refresh-token rotation, CSRF: covered by `phase1-identity-004`.
- HTTP routes: covered by `phase1-identity-005`.
- Real KMS integration for TOTP secret encryption: out of Phase 1. The `StaticKeyTotpEncryptor` is a stand-in keyed off `IDENTITY_TOTP_ENCRYPT_KEY` env var. Add a TODO comment referencing the KMS brief that will replace it.
- KYC tier transitions: handled by KYC context (Phase 3). The `kyc_tier` column on users is here only because every aggregate needs to be readable from day 1, not because identity owns its semantics.
- Rate limiting on signup / magic-link requests: middleware concern, separate brief.
- Event registration in `shared/events/registry`: the events are *declared* here (dataclass definitions); they are *registered* by the use-case brief that emits them, where the handler is also wired.

---

## Dependencies

- **Code dependencies:** `phase1-shared-003` UoW, `vaultchain.shared.domain` (Money, errors), `vaultchain.shared.events.base.DomainEvent`.
- **Data dependencies:** `phase1-shared-003` migration applied (UoW depends on `shared.domain_events`).
- **External dependencies:** `argon2-cffi` (for `refresh_token_hash` and `backup_codes_hashed` — argon2id), `pyotp` (for TOTP secret generation). Both already in `pyproject.toml`.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/identity/domain/test_user.py`, `test_session.py`, `test_magic_link.py`, `test_totp_secret.py`, `test_email_vo.py`
  - covers AC-01 through -08 (the domain ones)
  - test cases per file: state transitions, idempotency where applicable, edge cases on expiry boundaries
- [ ] **Property tests:** `tests/identity/domain/test_email_vo_properties.py`
  - hypothesis-driven on email normalization
  - properties: `Email(s).value == Email(s.upper()).value == Email(f" {s} ").value` (idempotent normalization round-trip).
- [ ] **Application tests:** N/A — no use cases in this brief.
- [ ] **Adapter tests:** `tests/identity/infra/test_repositories.py`, `test_migrations.py`, `test_static_key_totp_encryptor.py`
  - testcontainers Postgres, real migration applied
  - covers AC-01, -02, -07, -09
  - test cases: `test_migration_creates_all_four_tables`, `test_user_repo_get_by_email_normalizes`, `test_session_repo_persists_and_loads`, `test_optimistic_lock_user_concurrent_update`, `test_totp_encryptor_roundtrip`

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass — verify especially that `identity/domain` imports nothing from `identity/infra`.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Coverage ≥85% on `identity/domain/` and `identity/infra/`. (Identity domain is not on the 95% list — only transactions/ledger/custody/chains domains are per architecture Section 5.)
- [ ] OpenAPI: no change.
- [ ] Domain events declared in `identity/domain/events.py` but NOT yet registered — that happens in their emitting briefs. Document this in a module docstring.
- [ ] No new ADR.
- [ ] Migration `<date>_identity_initial.py` committed with downgrade tested.
- [ ] Single PR. Conventional commit: `feat(identity): domain + repositories + migration [phase1-identity-001]`.

---

## Implementation Notes

- `User`, `Session`, `MagicLink`, `TotpSecret` are *aggregate roots*. None has child entities in V1 — they are flat. This makes mappings 1:1 with rows; no association tables.
- The `Email` VO normalizes via `value.strip().lower()` and validates with a strict regex (RFC-5321 pragmatic subset, not RFC-5322 full). Reject obviously malformed; do not attempt MX validation. Store `email_hash = blake2b(email_normalized).digest()` for V2 search-without-decrypt scenarios; not used in V1 reads.
- `MagicLink.token_hash`: store SHA-256 of the raw token. The raw token is generated as `secrets.token_urlsafe(32)` in the use case (next brief), never persisted in plaintext.
- `Session.refresh_token_hash`: argon2id of the raw refresh token. The raw token also lives in an httpOnly cookie; verification compares argon2 hashes.
- `TotpSecret.backup_codes_hashed`: array of argon2id hashes. Use Postgres `BYTEA[]` for storage. Codes are 8 chars uppercase alphanum — generation in the enroll use case (next brief).
- `TotpSecret` encryptor uses an envelope pattern stub: encrypt the raw secret with AES-GCM using a key derived from `IDENTITY_TOTP_ENCRYPT_KEY` settings env var. The stub uses one static key for all secrets — the KMS brief (Phase 2) replaces with per-secret data keys. Mark the stub with a `# TODO(phase2-custody-kms-001): replace with KMS envelope` comment.
- `Email` VO lives in `identity/domain/value_objects.py`, not `shared/domain/`. It's identity-specific; only one context uses it. Resist the urge to promote.

---

## Risk / Friction

- This brief is at the M/L boundary. If Claude Code overflows, escalate by splitting `phase1-identity-001a (User+Email VO)` and `phase1-identity-001b (Session+MagicLink+TotpSecret)` rather than relaxing scope. Note in `BLOCKED.md` if it happens.
- The `StaticKeyTotpEncryptor` placeholder is a security smell. It is acceptable in V1 because (a) the project is testnet-only with no real money; (b) the KMS brief in Phase 2 replaces it before any real custody work touches it; (c) the placeholder is loud (config var name `STATIC_KEY` plus the TODO comment). If a reviewer asks why it isn't real KMS in Phase 1: explain the phasing decision; do not silently switch to KMS, that's Phase 2 work.
- `kyc_tier` column on `users` while KYC context isn't implemented yet: an integer with default 0 is a denormalization for read convenience. The KYC context, when delivered, will own write semantics; identity only reads. Document this in a comment on the column in the migration.
