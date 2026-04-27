---
ac_count: 7
blocks:
- phase2-custody-002
complexity: L
context: custody
depends_on:
- phase1-shared-003
- phase1-shared-005
estimated_hours: 4
id: phase2-custody-001
phase: 2
sdd_mode: strict
state: ready
title: Custody domain, KMS port, envelope encryption pattern
touches_adrs:
- ADR-004
---

# Brief: phase2-custody-001 — Custody domain, KMS port, envelope encryption pattern


## Context

The Custody context owns the system's most sensitive operation: holding private keys for user wallets, encrypting them at rest, and decrypting them only at the moment of signing. Per architecture Section 3 + Section 5 + the four product invariants, the implementation uses **envelope encryption**: each wallet's private key is encrypted with a unique data-encryption-key (DEK), and the DEK itself is encrypted with a master-key managed by AWS KMS. The plaintext DEK is never persisted; the KMS master-key is never exfiltrated. At signing time, Custody calls KMS `Decrypt` on the encrypted DEK, holds the plaintext DEK in memory only for the duration of the sign operation, signs, then zeros the DEK from memory.

This brief delivers the **domain layer + ports** for Custody. The KMS adapter and signing service are the next brief (`phase2-custody-002`). Specifically here: the `HotWallet` aggregate (one row per user-chain pair, holding `address`, `encrypted_private_key BYTEA`, `encrypted_dek BYTEA`, `key_version INT`, `kms_key_id TEXT`, `created_at`), the `KMSPort` Protocol (with methods `encrypt_dek`, `decrypt_dek`, `generate_data_key`), the `EnvelopeEncryptionService` (a domain service that orchestrates DEK lifecycle for an encrypt or decrypt operation), the migration creating `custody.hot_wallets`, `custody.audit_log`, `custody.cold_wallets` (cold table is created but unused in Phase 2 — populated in Phase 3), and the **ADR-004 draft** documenting the pattern.

The `audit_log` table per architecture Section 3 (line 342–365) stores: `event_id`, `request_id`, `actor_type`, `actor_id`, `operation` (`'sign' | 'encrypt' | 'decrypt' | 'address_generate' | ...`), `pre_hash` (SHA-256 of pre-state), `post_hash` (SHA-256 of post-state), `kms_key_id`, `result` (`'success' | 'failure'`), `failure_reason`, `created_at`. **Critically, the log never stores `signed_tx`, raw private key bytes, or KMS plaintext data keys.** Only hashes. Brief enforces this invariant at the type level: the audit-log writer accepts only `bytes` of length 32 (a SHA-256 hash) for `pre_hash` and `post_hash`, never raw payloads. A `tests/custody/domain/test_audit_log_invariant.py` asserts via property test that arbitrary plaintext input is rejected.

The hot/cold tier split is structural here, not behavioral: the `hot_wallets` table holds keys signable without admin approval (transactions ≤ threshold); the `cold_wallets` table will hold keys requiring admin approval (Phase 3). Phase 2 only writes to `hot_wallets`. The threshold is enforced by `Transactions` context, not Custody — Custody just signs whatever `ApprovedTx` it receives.

---

## Architecture pointers

- **Layer:** domain only in this brief (with the migration). Application + infra come in `phase2-custody-002`.
- **Packages touched:**
  - `custody/domain/entities/hot_wallet.py` (HotWallet aggregate)
  - `custody/domain/value_objects/encrypted_payload.py` (EncryptedPayload VO: `{ciphertext: bytes, encrypted_dek: bytes, key_version: int, kms_key_id: str}`)
  - `custody/domain/services/envelope_encryption.py` (orchestrates encrypt/decrypt via KMS port)
  - `custody/domain/services/audit_logger.py` (port + types)
  - `custody/domain/ports.py` (KMSPort, AuditLogPort, HotWalletRepository)
  - `custody/domain/errors.py` (`KMSUnavailable`, `WalletNotFound`, `KeyVersionMismatch`)
  - `custody/infra/migrations/<timestamp>_custody_initial.py` (Alembic migration)
- **Reads / writes:** none yet (no use cases in this brief).
- **Events:** new event types registered (published by `custody-002`):
  - `custody.HotWalletCreated` (payload: `wallet_id, user_id, chain, address, key_version`)
  - `custody.SigningPerformed` (payload: `wallet_id, transaction_id, pre_hash, post_hash, request_id`)
  - `custody.SigningFailed` (payload: `wallet_id, transaction_id, pre_hash, failure_reason, request_id`)
  - All registered in `shared/events/registry.py`.
- **Migrations:** `custody.hot_wallets`, `custody.cold_wallets` (empty), `custody.audit_log`. Per-schema permissions: `audit_user` has SELECT on `custody.audit_log`, no SELECT on `custody.hot_wallets`.
- **OpenAPI:** none in this brief.

---

## Acceptance Criteria

- **AC-phase2-custody-001-01:** Given the migration runs, when applied, then schemas/tables exist: `custody.hot_wallets` with columns `id UUID PK, user_id UUID FK, chain TEXT NOT NULL CHECK chain IN ('ethereum', 'tron', 'solana'), address TEXT NOT NULL, encrypted_private_key BYTEA NOT NULL, encrypted_dek BYTEA NOT NULL, key_version INT NOT NULL, kms_key_id TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(user_id, chain)`. `custody.cold_wallets` has identical structure (Phase 3 populates). `custody.audit_log` with the columns enumerated in Context.

- **AC-phase2-custody-001-02:** Given the `HotWallet` aggregate, when constructed via factory `HotWallet.create(user_id, chain, address, encrypted_payload)`, then it validates: address matches the chain via `Address.parse(chain, address)` (using shared kernel from bootstrap), `encrypted_payload.ciphertext` is non-empty, `encrypted_payload.encrypted_dek` is non-empty, `key_version >= 1`. Returns the aggregate with a fresh UUID. Raises `InvalidWallet` (DomainError, mapped to 422) on validation failure.

- **AC-phase2-custody-001-03:** Given the `KMSPort` Protocol, when defined, then it has exactly these methods: `async generate_data_key(key_id: str) -> tuple[plaintext_dek: bytes, encrypted_dek: bytes]` (returns 32-byte AES-256 plaintext DEK + KMS-encrypted DEK), `async decrypt_dek(encrypted_dek: bytes, key_id: str) -> bytes` (returns plaintext DEK), `async encrypt_dek(plaintext_dek: bytes, key_id: str) -> bytes`. The Protocol carries the `kms_key_id` separately so multi-region or key-rotation scenarios can override.

- **AC-phase2-custody-001-04:** Given the `EnvelopeEncryptionService`, when `encrypt(plaintext: bytes, key_id: str) -> EncryptedPayload` is called, then it: (1) calls `kms.generate_data_key(key_id)` getting `plaintext_dek` + `encrypted_dek`, (2) AES-256-GCM encrypts `plaintext` with `plaintext_dek` (12-byte nonce randomly generated, prepended to ciphertext), (3) zeros `plaintext_dek` from memory using a `bytearray` + explicit overwrite, (4) returns `EncryptedPayload(ciphertext, encrypted_dek, key_version=1, kms_key_id=key_id)`. The plaintext_dek is NEVER stored, NEVER logged, NEVER returned out of this method.

- **AC-phase2-custody-001-05:** Given a valid `EncryptedPayload`, when `decrypt(payload, kms) -> bytes` is called, then it: (1) calls `kms.decrypt_dek(payload.encrypted_dek, payload.kms_key_id)` getting plaintext_dek, (2) AES-256-GCM decrypts `payload.ciphertext` using plaintext_dek, (3) zeros plaintext_dek from memory, (4) returns the decrypted plaintext. On AES-GCM authentication failure (tampered ciphertext), raises `KeyVersionMismatch` mapped to HTTP 500 (operationally a critical alert).

- **AC-phase2-custody-001-06:** Given the `AuditLogPort`, when defined, then it has one method: `async record(event: AuditEvent) -> None` where `AuditEvent` is a frozen dataclass with fields `event_id, request_id, actor_type, actor_id, operation, pre_hash: bytes, post_hash: bytes, kms_key_id, result, failure_reason: str | None`. **The type system enforces `pre_hash` and `post_hash` are exactly 32 bytes (SHA-256)** via `__post_init__` assertions. Passing raw payloads (e.g., 100-byte signed_tx) raises `ValueError` at construction time. This is the type-level realization of invariant #4.

- **AC-phase2-custody-001-07:** Given the `HotWalletRepository` Protocol, when defined, then it has methods `async get_by_user_and_chain(user_id, chain) -> HotWallet | None`, `async list_by_user(user_id) -> list[HotWallet]`, `async insert(wallet: HotWallet) -> None`. No `update` method — hot wallets are immutable post-creation; key rotation in V2 will introduce a new aggregate `WalletKeyRotation`.

- **AC-phase2-custody-001-08:** Given ADR-004, when committed, then `docs/decisions/ADR-004-custody-envelope-encryption.md` exists with sections: Context, Decision, Consequences. The Decision section concretely names: AES-256-GCM for the symmetric layer, KMS-managed master key per environment (dev: LocalStack, prod: AWS KMS in `us-east-1`), one master key total in V1 (`vaultchain-custody-master`), data key per encryption (NOT cached, every encrypt generates a fresh DEK — KMS pricing comfortably absorbs this), `key_version` column for future rotation. Consequences acknowledge: KMS outage means no signing (acceptable — better than fallback to weaker key management), KMS pricing at $0.03 per 10k requests means signing cost is negligible at portfolio scale.

- **AC-phase2-custody-001-09:** Given the `custody/domain/` package, when scanned by import-linter, then it imports nothing outside `shared/domain/` (Money, Address, DomainError, DomainEvent base) and stdlib. No infra imports. No web3.py, no boto3, no SQLAlchemy. This is the strictest layer in the system.

- **AC-phase2-custody-001-10:** Given the `audit_log` table, when inserted into via the (yet-to-be-built) infra adapter, then per-schema permissions enforce: `app_user` (the application's DB user) has INSERT permission only on `audit_log`; `audit_user` (a separate role for the future audit viewer) has SELECT only. Migration creates these roles and grants if they don't exist; idempotent.

---

## Out of Scope

- KMS adapter implementation (LocalStack + AWS KMS): `phase2-custody-002`.
- Signing service: `phase2-custody-002`.
- Cold wallet write path + admin approval queue: Phase 3.
- Key rotation: V2.
- Multi-region KMS: V2.
- Per-user data keys (column-level encryption for AI chat content): V2.
- The actual deposit/withdrawal posting handlers in Ledger: `phase2-ledger-002`.

---

## Dependencies

- **Code dependencies:** `phase1-shared-003` (UoW pattern, DomainEvent base), `phase1-shared-005` (error envelope).
- **Data dependencies:** none — this brief introduces the schema.
- **External dependencies:** `cryptography` library for AES-256-GCM, `boto3` deferred to next brief. ADR-004 draft is part of this PR.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/custody/domain/test_hot_wallet.py` — covers AC-02 (factory validation, address-chain match, fields). `tests/custody/domain/test_encrypted_payload.py` — covers VO equality and serialization.
- [ ] **Domain unit tests:** `tests/custody/domain/test_audit_log_invariant.py` — covers AC-06; asserts `AuditEvent(pre_hash=b"x"*100)` raises `ValueError`. **Property test:** for any random byte-string of length ≠ 32, AuditEvent construction raises.
- [ ] **Property tests:** `tests/custody/domain/test_kms_envelope_properties.py` — for any random plaintext bytes ∈ [0, 4096], `decrypt(encrypt(x)) == x`. Uses `FakeKMSPort` (in-memory). **This is the property test mandated by architecture Section 5 (line 6 in the property tests list).** Real KMS test via LocalStack lives in `phase2-custody-002`.
- [ ] **Domain unit tests:** `tests/custody/domain/test_envelope_encryption.py` — covers AC-04, AC-05; happy path, tampered ciphertext (modify a byte → expect `KeyVersionMismatch`), empty plaintext, large plaintext (4KB).
- [ ] **Migration test:** `tests/custody/infra/test_migration.py` — applies the migration on testcontainer Postgres, asserts table structure, asserts `audit_user` role has SELECT on `audit_log` and no SELECT on `hot_wallets`. Covers AC-01, AC-10.

> No application/contract/E2E tests in this brief — those come in subsequent custody briefs and downstream consumers.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contract added: `custody.domain` may not import `custody.infra`, `custody.application`, or any non-stdlib non-shared-domain package. Verified by AC-09.
- [ ] `mypy --strict` passes — particularly important for the AuditEvent type-level invariant.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gate passes (custody/domain target: 95% — strict mode).
- [ ] Three new domain events registered in `shared/events/registry.py` with payload schemas inline.
- [ ] Three new ports declared in `custody/domain/ports.py` with fakes in `tests/custody/fakes/` (`FakeKMSPort` keeps DEKs in a dict, `FakeAuditLogPort` collects events in a list, `FakeHotWalletRepository` is a dict).
- [ ] **ADR-004 drafted and committed** in `docs/decisions/ADR-004-custody-envelope-encryption.md`.
- [ ] Single PR. Conventional commit: `feat(custody): domain + KMS envelope encryption pattern + ADR-004 [phase2-custody-001]`.
- [ ] PR description includes a sequence diagram of the encrypt/decrypt flow.

---

## Implementation Notes

- AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`. The 12-byte nonce is generated fresh per encryption via `os.urandom(12)`, prepended to ciphertext: final ciphertext = `nonce || aesgcm_ciphertext_with_tag`. The decrypt method splits these back.
- "Zeroing" plaintext_dek in Python is best-effort — Python doesn't guarantee memory clearing. Use `bytearray` for the DEK (mutable), overwrite with `bytes(len(dek))` after use, then `del`. Document in code that this is best-effort given Python GC, and that the real defense is short-lived process + KMS-only key release.
- The `EncryptedPayload` is a frozen `@dataclass(frozen=True)` value object, equality by content, no methods that decrypt — decrypt is on the service, not the VO.
- The `AuditEvent.__post_init__` assertion is `if len(self.pre_hash) != 32 or len(self.post_hash) != 32: raise ValueError(...)`. Use `bytes` not `bytearray` for hashes (immutable).
- Migration: use raw SQL via Alembic's `op.execute(...)` for the role/grant statements — SQLAlchemy doesn't have first-class role primitives.
- ADR-004 should be ~200 lines; reviewers will read it. Cite the AWS Encryption SDK best-practices doc (link not in repo, just cite by name) as the reference pattern.

---

## Risk / Friction

- The "zero memory after use" is theater in Python; reviewers who know cryptography will note this. The honest answer in ADR-004: "Process isolation + short-lived signing scope + KMS as the source of trust is the real defense; in-process zeroing is hygiene, not a security boundary." Include this paragraph verbatim.
- LocalStack's KMS implementation has had bugs around `GenerateDataKey` over the years. Verify the exact LocalStack version pinned in `docker-compose-dev.yml` works for this flow before relying on it. Worst case: pin a known-good LocalStack version.
- The audit-log type-invariant (32-byte hash assertion) is the **kind of small detail that reviewers love** — it shows the engineer thought about misuse-resistance at the type system level, not just at the validator level. Don't skip the property test that exercises it.
- The cold_wallets table being created-empty-in-Phase-2 is deliberate. Resist adding "let's just leave it for Phase 3" in a comment — leaving a placeholder schema documents intent better than a TODO.
