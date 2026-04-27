---
ac_count: 8
blocks:
- phase2-wallet-001
- phase2-chains-002
- phase2-transactions-002
- phase2-audit-001
- phase2-faucet-001
complexity: M
context: custody
depends_on:
- phase2-custody-001
- phase1-shared-003
estimated_hours: 4
id: phase2-custody-002
phase: 2
sdd_mode: strict
state: ready
title: KMS adapter (LocalStack/AWS) + signing service
touches_adrs: []
---

# Brief: phase2-custody-002 — KMS adapter (LocalStack/AWS) + signing service


## Context

This brief realizes the application + infra layers of Custody on top of the domain primitives from `custody-001`. It delivers: `BotoKMSAdapter` (a real AWS KMS client wired to LocalStack in dev/CI and AWS KMS in prod via env-driven endpoint), the `SqlAlchemyHotWalletRepository`, the `SqlAlchemyAuditLogAdapter`, and three core use cases — `GenerateHotWallet` (called by Wallet context when provisioning a user's chain wallet), `SignTransaction` (called by Transactions context when transitioning `awaiting_totp → broadcasting`), and `RecordAuditEvent` (called internally by signing + key-generation paths).

The signing service is chain-aware but lives in Custody, not Chains. This is intentional per architecture Section 2 — Custody owns the signing operation; Chains owns the RPC/broadcast operation. The split: `SignTransaction(unsigned_tx, user_id, transaction_id)` returns an `ApprovedTx(signed_bytes, hash, chain)`. The signing service decrypts the wallet's private key (in-memory, ephemeral), uses chain-appropriate signer (eth_account for Ethereum), produces signed bytes, computes the SHA-256 pre-hash (of the unsigned tx) and post-hash (of the signed tx), records the audit event, and returns `ApprovedTx`. The plaintext private key never leaves `SignTransaction`'s call frame.

The threshold check (hot vs cold tier) is NOT in this brief. Custody just signs whatever it's given. The Transactions context performs the threshold policy check before invoking `SignTransaction`. Phase 2 sees only hot-tier signing because the threshold check trivially passes for testnet small amounts; Phase 3 introduces the cold path.

---

## Architecture pointers

- **Layer:** application + infra.
- **Packages touched:**
  - `custody/application/use_cases/generate_hot_wallet.py` (called by Wallet provisioning)
  - `custody/application/use_cases/sign_transaction.py`
  - `custody/application/use_cases/record_audit.py`
  - `custody/infra/boto_kms_adapter.py`
  - `custody/infra/sqlalchemy_hot_wallet_repo.py`
  - `custody/infra/sqlalchemy_audit_log_adapter.py`
  - `custody/infra/signers/ethereum_signer.py` (single-chain in Phase 2)
  - `custody/infra/signers/signer_registry.py` (chain → signer map; Phase 3 adds Tron, Solana)
  - Composition root wiring in `backend/main.py`
- **Reads:** `custody.hot_wallets` by `user_id, chain`. KMS via boto3.
- **Writes:** Insert into `custody.hot_wallets` (on wallet generation), insert into `custody.audit_log` (on every KMS or signing operation).
- **Publishes events:** `custody.HotWalletCreated`, `custody.SigningPerformed`, `custody.SigningFailed` (registered in `custody-001`).
- **Ports / adapters:** new `BotoKMSAdapter` (implements `KMSPort`), new `EthereumSigner` (implements internal `Signer` Protocol).
- **Migrations:** none new; `custody-001`'s migration covers it.
- **OpenAPI:** none — Custody has no public endpoints.

---

## Acceptance Criteria

- **AC-phase2-custody-002-01:** Given the `BotoKMSAdapter` is configured with `KMS_ENDPOINT_URL` (LocalStack URL in dev/CI: `http://localstack:4566`; unset in prod uses AWS default), `KMS_REGION=us-east-1`, and `KMS_KEY_ID` (resolved at startup to a key alias `alias/vaultchain-custody-master`), when `generate_data_key(key_id)` is called, then it invokes `boto3.client('kms').generate_data_key(KeyId=..., KeySpec='AES_256')`, returns `(plaintext_dek_bytes, encrypted_dek_bytes)`. Wraps boto3 calls in `asyncio.to_thread()` because boto3 is sync.

- **AC-phase2-custody-002-02:** Given `decrypt_dek(encrypted_dek, key_id)` is called, when KMS responds successfully, then it returns the plaintext DEK. On `botocore.exceptions.ClientError` with `KMSInvalidStateException` or `AccessDeniedException`, raises `KMSUnavailable` (DomainError) — the use case maps this to a service-level failure that the caller handles. On network timeout (10s), raises `KMSUnavailable`.

- **AC-phase2-custody-002-03:** Given the `GenerateHotWallet` use case is invoked with `(user_id, chain)`, when executed, then within a single UoW: (1) generates a fresh chain-appropriate private key (eth_account.Account.create() for Ethereum — the resulting `0x...` 32-byte key); (2) derives the public address; (3) calls `EnvelopeEncryptionService.encrypt(private_key_bytes, kms_key_id)` to get an `EncryptedPayload`; (4) constructs `HotWallet.create(user_id, chain, address, payload)`; (5) inserts via repo; (6) records audit event with `operation='address_generate', pre_hash=SHA256(public_seed_or_zeroes), post_hash=SHA256(address)`; (7) publishes `HotWalletCreated` to outbox; (8) returns the new wallet (without the encrypted payload — repository accessor strips it). Idempotent on `(user_id, chain)` via UNIQUE constraint — duplicate call returns existing wallet.

- **AC-phase2-custody-002-04:** Given the `SignTransaction` use case is invoked with `(unsigned_tx: UnsignedTx, user_id: UUID, transaction_id: UUID, request_id: str)`, when executed, then: (1) loads the `HotWallet` for `(user_id, unsigned_tx.chain)` — raises `WalletNotFound` if missing; (2) decrypts the private key via `EnvelopeEncryptionService.decrypt`; (3) routes to chain-specific signer (`EthereumSigner.sign(unsigned_tx, private_key) → signed_bytes, tx_hash`); (4) computes `pre_hash = SHA256(canonical_serialize(unsigned_tx))`, `post_hash = SHA256(signed_bytes)`; (5) zeros `private_key` from memory; (6) records audit event with `operation='sign', result='success'`; (7) publishes `SigningPerformed`; (8) returns `ApprovedTx(signed_bytes, tx_hash, chain)`. **Critically: never logs `signed_bytes`, never logs `private_key`, never logs `unsigned_tx.value` in plaintext form** (the audit_log captures only hashes).

- **AC-phase2-custody-002-05:** Given any failure path in `SignTransaction` (KMS unavailable, signing exception, repository error), when caught, then: (1) audit event with `operation='sign', result='failure', failure_reason=<sanitized message>` is written within the same UoW (or the catch-block opens a new UoW just for the audit); (2) `SigningFailed` event published to outbox; (3) the error propagates as `KMSUnavailable` or `SigningFailed` DomainError to the caller. The audit log MUST capture failed signing attempts even when the operation cannot complete.

- **AC-phase2-custody-002-06:** Given the `EthereumSigner.sign(unsigned_tx, private_key)` is invoked with an EIP-1559 transaction, when called, then it uses `eth_account.Account.sign_transaction(tx_dict, private_key)` and returns `(rawTransaction, hash)` from the resulting `SignedTransaction`. The `tx_dict` is built from `unsigned_tx` fields (`to, value, gas, maxFeePerGas, maxPriorityFeePerGas, nonce, chainId, data`). Type-1 (EIP-2930) and Legacy txs are out of scope for this brief — only EIP-1559 (the modern default).

- **AC-phase2-custody-002-07:** Given the `SqlAlchemyAuditLogAdapter.record(event)`, when called, then it INSERTs into `custody.audit_log` with all enumerated columns. Schema permissions per `custody-001` enforce: even if a malicious code path tried to INSERT into `custody.hot_wallets` from outside Custody's domain layer, the role would lack the privilege. Per-schema permissions are the second line of defense.

- **AC-phase2-custody-002-08:** Given the boto3 KMS client, when configured for LocalStack, when running tests in CI, then `localstack/localstack:3.x` testcontainer fixture is used (session-scoped), `KMS_ENDPOINT_URL` is set to the testcontainer's exposed port, the master key `alias/vaultchain-custody-master` is created at fixture startup via a one-time `create_key + create_alias` boto call. Tests verify the round-trip: generate → encrypt → decrypt → match.

- **AC-phase2-custody-002-09:** Given an authenticated audit-event entry, when inspected, then it never contains: `signed_bytes`, `private_key`, `plaintext_dek`, `unsigned_tx.value` in plaintext, or any field longer than 64 bytes outside the SHA-256 hashes. **Property test:** generate random `unsigned_tx` instances, run `SignTransaction`, scan the resulting `audit_log` row for byte-strings exceeding 64 bytes outside the hash columns — should find none.

- **AC-phase2-custody-002-10:** Given the composition root, when `backend/main.py` boots in `prod` mode, then `BotoKMSAdapter` is wired with no `endpoint_url` (boto3 uses AWS defaults, region from env). In `dev` / `test`, `endpoint_url` resolves to the LocalStack URL. The wiring is centralized in a single function `wire_custody_adapters(env: Env) -> CustodyDeps` so no test bypasses it.

---

## Out of Scope

- Tron and Solana signers: Phase 3.
- Cold-tier signing path + admin approval orchestration: Phase 3.
- KMS key rotation / re-encrypt: V2.
- Hardware HSM adapter: V2.
- Multi-region KMS failover: V2.
- Per-chain fee estimation: that's Chains context (`phase2-chains-002`).

---

## Dependencies

- **Code dependencies:** `phase2-custody-001` (domain + ports + entities + ADR-004), `phase1-shared-003` (UoW pattern, outbox).
- **Data dependencies:** `custody.hot_wallets` and `custody.audit_log` migrations applied (`custody-001`).
- **External dependencies:** `boto3`, `eth_account` (already pulled by `web3.py` in `chains-001`), LocalStack 3.x for tests, AWS KMS access in prod (operator provisions an AWS account + key + IAM role for Fly with `kms:Encrypt, kms:Decrypt, kms:GenerateDataKey` on `alias/vaultchain-custody-master`).

---

## Test Coverage Required

- [ ] **Application tests:** `tests/custody/application/test_generate_hot_wallet.py` — happy path, idempotency on duplicate (user, chain), KMS failure raises `KMSUnavailable`. Uses `FakeKMSPort`. Covers AC-03.
- [ ] **Application tests:** `tests/custody/application/test_sign_transaction.py` — happy path, wallet-not-found, KMS-decrypt-failure (audit row recorded with `result='failure'`), signing exception (audit row + event), no plaintext leakage assertion. Covers AC-04, AC-05.
- [ ] **Property tests:** `tests/custody/application/test_audit_no_leakage_properties.py` — fuzz `unsigned_tx`, run signing, assert audit_log row contains no plaintext beyond hashes. Covers AC-09.
- [ ] **Adapter tests:** `tests/custody/infra/test_boto_kms_adapter.py` — uses LocalStack testcontainer, asserts `generate_data_key` round-trips, asserts `decrypt_dek` recovers plaintext, asserts unauthorized key-id raises `KMSUnavailable`. **Per architecture Section 5 line 6, this realizes the property test mandate against real KMS.** Covers AC-01, AC-02, AC-08.
- [ ] **Adapter tests:** `tests/custody/infra/test_ethereum_signer.py` — uses Anvil testcontainer (session-scoped, shared with chains-001), generates a fresh keypair, builds an EIP-1559 tx, signs, asserts `eth_account.Account.recover_transaction(rawTransaction) == address`. Covers AC-06.
- [ ] **Adapter tests:** `tests/custody/infra/test_sqlalchemy_audit_log_adapter.py` — testcontainer Postgres, asserts INSERTs persist correctly, asserts schema permissions block UPDATE/DELETE on audit_log even from `app_user`.
- [ ] **Contract tests:** none — Custody has no public API.
- [ ] **E2E:** none yet — full E2E comes when send flow lands (`transactions-002` + `web-007`).

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass: `custody.application` may not import `custody.infra`; cross-context import "Custody only sees `ApprovedTx`, not Transaction" is enforced (see `custody-001`'s contracts).
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (custody/application 90%, custody/infra 80%).
- [ ] No new domain events; reuses the three from `custody-001`.
- [ ] No new ports beyond what `custody-001` declared; the adapter implementations of those ports are this brief's deliverable.
- [ ] Single PR. Conventional commit: `feat(custody): KMS adapter, signing service, ethereum signer [phase2-custody-002]`.
- [ ] PR description: a sequence diagram of the SignTransaction call (caller → use case → KMS → signer → audit → outbox).
- [ ] `docs/runbook.md` updated with: KMS-key creation steps for prod (one-time AWS console steps + the alias setup), LocalStack init for dev (already automated in `docker-compose-dev.yml`).

---

## Implementation Notes

- The `Signer` Protocol (NOT a port — internal to Custody) has one method: `sign(unsigned_tx: UnsignedTx, private_key: bytes) -> SignedTx`. `SignedTx` is a dataclass `{signed_bytes: bytes, hash: str}`. The registry is a plain `dict[Chain, Signer]` populated at composition.
- `eth_account` is the canonical Python library for EVM signing in 2026. It's already pulled by `web3.py` (used in `chains-001`), so no extra dep.
- The `record_audit` call inside `SignTransaction` MUST happen even on failure — wrap the try-block in a structure that captures the partial state. A small `try / except / record_failure / re-raise` pattern. Don't merge audit-record into the UoW as the only mechanism — failures may abort the UoW; use a separate UoW or a SAVEPOINT for the audit row.
- The "no plaintext leakage" property test is one of the strongest signals to a reviewer; spend the time to make it bulletproof. Use Hypothesis to generate `UnsignedTx` instances with random byte fields and verify the audit_log columns by length-checking each row.
- LocalStack KMS sometimes returns base64-encoded blobs where AWS returns raw bytes. Normalize at adapter boundary; document the workaround in code comment.
- Don't forget to set `boto3` retry config: `Config(retries={'max_attempts': 2, 'mode': 'standard'})` — KMS is reliable but flaky network in Fly's connection to AWS deserves the retry.

---

## Risk / Friction

- AWS KMS pricing in prod: $1/key/month for the master key, $0.03 per 10k requests. At Phase-2-portfolio-traffic scale this is $1-2/month total. Document in the deploy runbook so the operator doesn't get surprised.
- The `sign_transaction` in-memory key handling looks like a sequential, single-coroutine operation but FastAPI runs requests concurrently. The DEK lifecycle is per-call-frame so concurrent signs each have their own DEK — verify with a load test (or at least a sanity test that fires 10 concurrent SignTransaction calls and asserts no cross-talk).
- LocalStack's KMS implementation has had subtle differences from real AWS (e.g., key-id format quirks). The adapter test against LocalStack catches most issues, but plan a manual smoke-test step in the runbook: "after first prod deploy, manually invoke `GenerateHotWallet` for a test user via `fly ssh` and verify the audit_log row + KMS CloudTrail entry."
- The property test for "no plaintext leakage" is the kind of test that can produce false greens if Hypothesis can't generate adversarial inputs. Seed it with at least: a 4KB plaintext, a UTF-8 plaintext containing potential PII patterns (`john@example.com`, phone numbers), and a JSON-like structure. Hand-curated hostile inputs > pure random.
