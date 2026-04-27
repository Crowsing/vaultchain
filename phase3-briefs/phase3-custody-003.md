---
ac_count: 2
blocks:
- phase3-custody-004
- phase3-wallet-002
- phase3-admin-004
- phase3-admin-006
- phase3-admin-007
- phase3-admin-008
complexity: L
context: custody
depends_on:
- phase2-custody-001
- phase2-custody-002
estimated_hours: 4
id: phase3-custody-003
phase: 3
sdd_mode: strict
state: ready
title: Cold tier (dual KMS master keys + cold signing path + backfill)
touches_adrs:
- ADR-008
---

# Brief: phase3-custody-003 — Cold tier (dual KMS master keys + cold signing path + backfill)


## Context

Phase 2 introduced KMS-encrypted hot wallets (one address per user-chain pair, signed without admin approval). Phase 3 introduces a real cold tier: a **second address per user-chain pair**, encrypted under a **separate KMS master key** with a **separate IAM role**, and signable only via an admin-approved path. This is not theatre — it makes the architecture honest about what "cold" means in a custodial wallet:

1. **Two AWS KMS master keys.** `vaultchain-custody-master` (existing, hot) and `vaultchain-custody-cold-master` (new). Separate aliases. Separate IAM policies — the application's runtime IAM role can `kms:GenerateDataKey + kms:Decrypt` on the hot key but **only `kms:GenerateDataKey` on the cold key** (encrypt-only). A second IAM role `cold-signer` has `kms:Decrypt` on the cold key and is assumed transiently only during the admin-approved cold-sign path.
2. **Two address tables.** `custody.hot_wallets` (existing) and `custody.cold_wallets` (created empty in `phase2-custody-001`, populated here). Same shape; different role-based access.
3. **Backfill job.** Phase 2 users have hot wallets but no cold. A one-shot migration-driven backfill job (`backfill_cold_wallets`) iterates existing users, generates cold keypairs for each chain, encrypts under the cold KMS, inserts into `custody.cold_wallets`. Idempotent — if a cold wallet already exists for `(user, chain)`, skip.
4. **Cold signing path.** A new use case `SignColdTransaction` — invoked only from the admin-approved withdrawal flow (`phase3-admin-004`), never from user-facing send. The path: (a) admin approves a withdrawal in the queue (with their TOTP); (b) the approval triggers `ExecuteApprovedTransaction` which calls `SignColdTransaction(approved_withdrawal)`; (c) `SignColdTransaction` assumes the `cold-signer` IAM role via STS, decrypts the cold-wallet's encrypted private key, signs, **then immediately drops STS credentials**. The role-assumption is short-lived (15-minute STS session is the AWS default; the actual hold is sub-second).

The trade-off vs HSM-backed truly-physical-separation is documented in ADR-008 as a deliberate portfolio simplification: real exchange custody uses HSM appliances or hardware-segregated AWS accounts. VaultChain's IAM-role-segregation is the right pattern for the architectural shape — same code-side abstractions, weaker physical guarantee. Mainnet would use HSM; testnet portfolio uses IAM segregation. The ADR makes this trade explicit so reviewers see it as deliberate, not naive.

The user-facing wallet (the "receive" address shown in the dashboard) **stays the hot wallet**. Funds arriving go to hot. The rebalance worker (`phase3-custody-004`) periodically transfers excess from hot to cold. Cold balances never appear in the user dashboard — they appear in admin user-detail (`phase3-admin-007`). The split between user-visible (hot) and admin-visible (cold) is part of the security model.

---

## Architecture pointers

- **Layer:** application + infra. Domain reuses existing entities; cold path adds one new `ColdWallet` aggregate (mirror of HotWallet — separate to keep the type-system clear about which tier a wallet is in).
- **Packages touched:**
  - `custody/domain/entities/cold_wallet.py` (new ColdWallet aggregate, structurally identical to HotWallet but distinct type)
  - `custody/domain/ports.py` (new `ColdWalletRepository`, `ColdKMSPort`)
  - `custody/application/use_cases/generate_cold_wallet.py`
  - `custody/application/use_cases/sign_cold_transaction.py`
  - `custody/application/jobs/backfill_cold_wallets.py` (one-shot migration-driven backfill)
  - `custody/infra/sts_assumed_kms_adapter.py` (the cold-signer's `KMSPort` impl that assumes the `cold-signer` role transiently)
  - `custody/infra/sqlalchemy_cold_wallet_repo.py`
  - Composition root wires both KMS adapters
  - `docs/decisions/ADR-008-hot-cold-tier-separation.md` (drafted)
  - Terraform / runbook updates (separate IAM resources)
- **Reads / writes:** `custody.cold_wallets` (read by sign path, write by generate). `custody.audit_log` (extended with cold operations).
- **Publishes events:**
  - `custody.ColdWalletCreated{wallet_id, user_id, chain, address, key_version}` — registered.
  - `custody.ColdSigningPerformed{wallet_id, transaction_id, pre_hash, post_hash, request_id, admin_id}` — distinct from hot signing event for audit clarity.
  - `custody.ColdSigningFailed{...}` — distinct.
- **Migrations:** none new (cold_wallets table created in phase2-custody-001). The IAM resources are infra — Terraform/runbook only.
- **OpenAPI:** none — Custody has no public API.

---

## Acceptance Criteria

- **AC-phase3-custody-003-01:** Given the AWS KMS infrastructure, when configured for prod, then **two distinct master keys** exist with aliases `alias/vaultchain-custody-master` (hot) and `alias/vaultchain-custody-cold-master` (cold). Separate Terraform resources; separate `aws_kms_key` blocks. Per-key tags for cost-tracking (`Tier=hot` vs `Tier=cold`). LocalStack init script (development) creates both with the same aliases. Documented in `docs/runbook.md` deployment section.

- **AC-phase3-custody-003-02:** Given the IAM configuration, when applied, then **two IAM roles** exist: (a) `vaultchain-app` (the app's runtime role) with `kms:GenerateDataKey + kms:Decrypt` on the hot key and **only `kms:GenerateDataKey` on the cold key** (write-only — can encrypt, cannot decrypt); (b) `vaultchain-cold-signer` with `kms:Decrypt` on the cold key (read-only). The app's role can `sts:AssumeRole` into `vaultchain-cold-signer`. Cross-role assumption is logged in CloudTrail (free in AWS).

- **AC-phase3-custody-003-03:** Given the `GenerateColdWallet(user_id, chain)` use case, when invoked, then within a single UoW: (1) check repo for existing cold wallet → if exists, return it (idempotent); (2) generate fresh keypair (chain-appropriate — same paths as hot wallet generation); (3) call `EnvelopeEncryptionService.encrypt(private_key, kms_key_id='alias/vaultchain-custody-cold-master')` using the **app's runtime role** (which has GenerateDataKey on the cold key); (4) construct `ColdWallet.create(user_id, chain, address, encrypted_payload)`; (5) insert via repo; (6) record audit event with `operation='cold_address_generate'`; (7) publish `ColdWalletCreated`. The plaintext private key is zeroed from memory before the use case returns.

- **AC-phase3-custody-003-04:** Given the `SignColdTransaction(unsigned_tx, user_id, transaction_id, admin_id, request_id)` use case, when invoked, then: (1) load the `ColdWallet` for `(user_id, unsigned_tx.chain)` — raises `WalletNotFound` if missing; (2) **assume the `cold-signer` IAM role via STS** (`boto3.client('sts').assume_role(RoleArn='arn:aws:iam::...:role/vaultchain-cold-signer', RoleSessionName=f'cold-sign-{request_id}', DurationSeconds=900)`); (3) construct a transient KMS client with the temporary credentials; (4) decrypt the cold wallet's private key via `EnvelopeEncryptionService.decrypt`; (5) sign via `signer_registry[chain].sign(...)`; (6) zero plaintext key; (7) record audit event with `operation='cold_sign', actor_admin_id=admin_id, result='success'`; (8) publish `ColdSigningPerformed`; (9) **drop the STS-assumed credentials** (just let the temporary client go out of scope; STS credentials auto-expire). Returns `ApprovedTx`.

- **AC-phase3-custody-003-05:** Given any failure path in `SignColdTransaction` (KMS, STS, signing, repo), when caught, then audit event recorded with `operation='cold_sign', result='failure', failure_reason`, `ColdSigningFailed` published, error propagates. The audit event captures admin_id even on failure — admin's intent is recorded.

- **AC-phase3-custody-003-06:** Given the `backfill_cold_wallets` job, when executed (one-shot via deploy-time arq invocation), then: (1) query `custody.hot_wallets` for all distinct `(user_id, chain)` pairs; (2) for each, call `GenerateColdWallet(user_id, chain)` (idempotent — skips already-existing); (3) emit progress logs every 10 wallets generated; (4) on completion, log `custody.backfill.complete` with count. The job is registered as an admin-only HTTP endpoint `POST /admin/api/v1/custody/backfill-cold-wallets` (gated by admin auth from `phase1-admin-002`) AND as a one-time CLI invocation via `python -m custody.cli backfill-cold-wallets`. Both paths converge on the same use case.

- **AC-phase3-custody-003-07:** Given the property-test-style invariant on cold wallets, when `tests/custody/domain/test_cold_wallet_isolation.py` runs, then: (a) `ColdWallet` and `HotWallet` are NOT mutually constructible — passing a HotWallet to a function expecting ColdWallet is a `mypy --strict` error; (b) the database schemas have separate tables; (c) the `kms_key_id` field on cold wallets is `'alias/vaultchain-custody-cold-master'` (asserted in repo write); on hot wallets it's `'alias/vaultchain-custody-master'`. **Type-level separation** is the runtime defense; the repo-level assertion is the integrity check.

- **AC-phase3-custody-003-08:** Given the env-driven STS Role ARN for `vaultchain-cold-signer`, when running in dev/test (LocalStack), then the `STSAssumedKMSAdapter` short-circuits — LocalStack doesn't fully implement STS AssumeRole the same way, so the adapter detects `KMS_ENDPOINT_URL` is set (LocalStack mode) and skips role assumption, using the same boto3 client. **In dev/test, the cold-signer role is conceptual; in prod, it's enforced by AWS IAM.** Document the dev-vs-prod asymmetry inline. The contract test for the cold-sign path runs in dev mode and exercises the use case logic; the IAM segregation is verified manually post-deploy via a runbook step ("invoke cold-sign-debug endpoint, verify CloudTrail logs the assume-role event").

- **AC-phase3-custody-003-09:** Given the hot signing path from `phase2-custody-002`, when running, then **nothing changes for hot signing** — `SignTransaction` still uses the app's runtime role with the hot KMS. Reviewers checking that Phase 3 doesn't regress Phase 2 should find Phase 2's hot-signing tests untouched.

- **AC-phase3-custody-003-10:** Given ADR-008, when committed, then `docs/decisions/ADR-008-hot-cold-tier-separation.md` exists with: Context (why two tiers, what "cold" means in custodial), Decision (dual KMS master keys + IAM role separation + STS assume-role for cold sign + backfill job for Phase 2 users + the rebalance worker plan deferred to custody-004), Consequences (acceptable: AWS IAM is sufficient for portfolio scope; concerning: a compromised app role still has GenerateDataKey on cold and could DOS by generating data keys but cannot decrypt existing cold-encrypted material — document this is acceptable since DOS detection is straightforward via CloudWatch metrics; trade-off: not HSM-grade, mainnet would use HSM). The ADR explicitly names the threat model: "an attacker who exfiltrates the runtime IAM role's credentials can sign small hot withdrawals but cannot drain cold; an attacker who additionally compromises the cold-signer role can drain cold but the audit log preserves admin attribution." The portfolio reviewer's first-30-second read of this ADR should land on "this person has thought about threat models."

- **AC-phase3-custody-003-11:** Given the cold-tier audit log (`custody.audit_log` rows produced by `SignColdTransaction`), when fuzzed via `tests/custody/domain/test_no_cold_plaintext_leakage_properties.py`, then for any randomly generated `unsigned_tx` (chain ∈ {ethereum, tron, solana}, random payloads up to 10 KB), the resulting audit row contains: (1) `pre_hash` and `result_hash` as 32-byte SHA-256 digests; (2) NO byte sequence equal to the plaintext private key, the unsigned-tx bytes, the signed-tx bytes, or any KMS plaintext data key. Property holds across 1000 generated cases per Hypothesis run. **Architecture-mandated property test (PHASE3-SUMMARY property #4).**

---

## Out of Scope

- Hot↔cold rebalance worker: `phase3-custody-004` (separate brief).
- Multi-region KMS replication: V2.
- HSM adapter (real physical separation): V2 / mainnet.
- Cold wallet rotation / re-encryption: V2.
- Per-user cold KMS keys (column-level encryption): V2 — would scale to enterprise compliance.

---

## Dependencies

- **Code dependencies:** `phase2-custody-001` (domain primitives), `phase2-custody-002` (KMS adapter, signing service, signer registry).
- **Data dependencies:** `custody.cold_wallets` table created (in phase2-custody-001 migration as empty).
- **External dependencies:** AWS KMS (a second master key + alias), AWS IAM (a second role + assume-role policy). Operator provisions via Terraform; runbook step.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/custody/domain/test_cold_wallet.py` — factory, validation, type-isolation from HotWallet (mypy --strict catches mixing).
- [ ] **Application tests:** `tests/custody/application/test_generate_cold_wallet.py` — happy path, idempotency, KMS failure raises. Uses `FakeKMSPort` configured with the cold key id.
- [ ] **Application tests:** `tests/custody/application/test_sign_cold_transaction.py` — happy path (audit event with `actor_admin_id` recorded), wallet-not-found, KMS-decrypt-failure, signing exception (audit + event), no plaintext leakage. Uses Fakes.
- [ ] **Application tests:** `tests/custody/application/test_backfill_cold_wallets.py` — seeds 10 users with hot wallets, runs backfill, asserts 10 cold wallets exist; second run is no-op; partial-state (5 cold pre-existing, 5 missing) completes only the missing.
- [ ] **Adapter tests:** `tests/custody/infra/test_sts_assumed_kms_adapter.py` — LocalStack mode short-circuits (no real STS assume); the test asserts the adapter constructed correctly and decrypt works against LocalStack KMS via the cold key alias.
- [ ] **Adapter tests:** `tests/custody/infra/test_sqlalchemy_cold_wallet_repo.py` — testcontainer Postgres, asserts INSERT/SELECT, asserts UNIQUE(user_id, chain) constraint.
- [ ] **Property tests:** `tests/custody/domain/test_no_cold_plaintext_leakage_properties.py` — fuzz `unsigned_tx` for cold sign, assert audit_log row contains no plaintext beyond the standard 32-byte hashes.
- [ ] **Contract tests:** `tests/api/test_admin_backfill_endpoint.py` — admin auth required (401 without), backfill returns count.
- [ ] **E2E:** none — admin approval E2E lands in `phase3-admin-006`'s Playwright spec.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] Two KMS master keys provisioned in dev (LocalStack) AND in prod (AWS); runbook documents prod provisioning step-by-step.
- [ ] IAM roles (`vaultchain-app` and `vaultchain-cold-signer`) defined in Terraform; role separation validated in prod via a manual CloudTrail check (documented in runbook).
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes — particularly the type-isolation between HotWallet and ColdWallet.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] Three new domain events registered (ColdWalletCreated, ColdSigningPerformed, ColdSigningFailed).
- [ ] Two new ports declared (`ColdWalletRepository`, `ColdKMSPort`) with fakes.
- [ ] **ADR-008 drafted and committed.**
- [ ] Single PR. Conventional commit: `feat(custody): cold tier with dual KMS + signing path + backfill + ADR-008 [phase3-custody-003]`.
- [ ] PR description: a sequence diagram of the cold-sign flow (admin approve → assume role → decrypt → sign → drop credentials → audit) AND a deployment checklist for the operator (KMS keys, IAM roles, env vars).

---

## Implementation Notes

- The `ColdKMSPort` is a parallel Protocol to `KMSPort` — same shape, different identity. The reason for not reusing `KMSPort`: the type system makes "cold operations" visually distinct in code. A function that accepts `ColdKMSPort` cannot be accidentally invoked with the hot adapter and vice versa.
- The STS `assume_role` call is wrapped in `asyncio.to_thread()` like other boto3 calls. Sub-second latency in practice; assumes IAM trust policy is configured (the runtime role's principal is allowed to assume the cold-signer role).
- "Drop credentials" in AC-04 is naturally handled by Python scope — the `boto3.client('kms', aws_access_key_id=..., aws_secret_access_key=..., aws_session_token=...)` is local to the use case method. When the method returns, the client is GC'd. STS credentials expire at AWS in 15min anyway. Document the layered defense.
- For LocalStack development, **do not** try to fake STS AssumeRole — LocalStack's Pro tier supports it, free tier does not. The short-circuit in AC-08 (use the same boto3 client when `KMS_ENDPOINT_URL` is set) is the cleanest approach.
- Backfill job's idempotency relies on the `UNIQUE(user_id, chain)` constraint on `custody.cold_wallets`. The use case's "skip if exists" is belt-and-suspenders.
- The deployment runbook step for "validate IAM segregation" is: from a Fly machine post-deploy, run `aws kms decrypt --ciphertext-blob fileb://<cold-blob>` using the runtime role credentials and assert it fails with `AccessDeniedException`. This proves the runtime role cannot decrypt cold material.

---

## Risk / Friction

- The "AWS IAM is enough for portfolio scope" framing is honest but a sophisticated reviewer may probe: "what if IAM policies drift (e.g., someone adds Decrypt to the runtime role by accident)?" The defense: Terraform manages all IAM, drift detection via `terraform plan` in CI catches this. Document.
- The 15-minute STS session window is plenty for any individual sign operation but exposes a small attack window: if an attacker gets process-memory access to a Fly machine mid-cold-sign, they have ~15min of credentials. Mitigations: (a) the credentials can only sign one tx in the use case scope, then are GC'd; (b) the IAM role's policy can be tightened to require an `sts:ExternalId` matching `request_id`. Phase 3 ships without ExternalId; document as V2 hardening.
- LocalStack's STS short-circuit means the IAM segregation is **not validated by automated tests**. Manual runbook validation is required post-deploy. This is the kind of gap that sneaks bugs into production. Mitigate by: (a) explicit runbook checklist with the AWS CLI command to verify; (b) a one-time CI job that runs the validation on the staging environment after each deploy. Phase 3 documents the runbook step; the CI job is V2 ops.
- A user signing up in Phase 2 has only a hot wallet. After Phase 3 deploy, the backfill must run before the rebalance worker (`phase3-custody-004`) starts, otherwise rebalance has nowhere to send funds. Deploy procedure: (1) deploy code, (2) run backfill via CLI, (3) start rebalance worker. Encode the ordering in the runbook AND in arq scheduler config (rebalance job's first run is delayed by 60min after deploy to give backfill room).
