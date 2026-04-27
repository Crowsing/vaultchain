---
ac_count: 9
blocks:
- phase2-ledger-002
- phase2-balances-001
complexity: L
context: ledger
depends_on:
- phase1-shared-003
estimated_hours: 4
id: phase2-ledger-001
phase: 2
sdd_mode: strict
state: ready
title: Ledger domain (postings, entries, accounts) + double-entry invariant
touches_adrs:
- ADR-001
---

# Brief: phase2-ledger-001 — Ledger domain (postings, entries, accounts) + double-entry invariant


## Context

The Ledger context is the system's source of truth for money movements. Per architecture Section 3 (lines 258-298) and ADR-001, it implements **real double-entry accounting**: every money movement is a balanced posting consisting of debit and credit entries that sum to zero per asset-and-chain. Three tables form the model: `ledger.accounts` (one row per logical account — `external_chain`, `user_hot_wallet:<user_id>:<chain>:<asset>`, `user_pending_withdrawal:<user_id>:<chain>:<asset>`, `faucet_pool`), `ledger.postings` (one row per balanced posting group, headers carrying `posting_type`, `caused_by_event_id UNIQUE`), `ledger.entries` (one row per debit or credit, FK to posting).

The double-entry invariant is enforced at three levels per architecture Section 3 line 295:
1. **Application layer.** The posting service refuses to commit unless `Σ debits = Σ credits` per posting, asset-and-chain-quantized.
2. **DB level.** A deferred trigger constraint on `ledger.postings` verifies balance at transaction commit (CHECK that the sum of associated entries is zero per asset).
3. **Reconciliation job.** A daily job (introduced in this brief as a stub, populated in Phase 3) recomputes account balances and compares with on-chain RPC data — mismatch alerts.

This brief delivers: the domain entities (`Posting`, `Entry`, `Account`, `LedgerPostingService`), the `Money` arithmetic that already lives in shared kernel (this brief tightens its quantization rules), the migration creating the three tables + the deferred constraint trigger, and the `LedgerRepository`. **It does NOT yet wire the subscribers** — that's `phase2-ledger-002`. So Phase 2's first half ships a Ledger that is structurally correct but not yet receiving events.

The `caused_by_event_id UNIQUE` is per-posting, not per-entry. It guarantees outbox at-least-once semantics produce exactly-once postings: if the same event is delivered twice, the second insert collides on UNIQUE and the handler returns successfully without double-posting. Per architecture Section 3 line 297.

Critical invariants enforced as **property tests** (mandatory per architecture Section 5):
1. For any random posting, `Σ debits = Σ credits` per asset.
2. For any random posting sequence, `user_hot_wallet:<user>:*` balance never goes negative.

---

## Architecture pointers

- **Layer:** domain + application + infra. No delivery — Ledger has no public API.
- **Packages touched:**
  - `ledger/domain/entities/account.py` (Account aggregate; identifier = `account_key` like `user_hot_wallet:<uuid>:ethereum:ETH`)
  - `ledger/domain/entities/posting.py` (Posting aggregate with embedded Entries)
  - `ledger/domain/value_objects/entry.py` (Entry VO: `{account_key, asset, chain, amount: Money, side: 'debit' | 'credit'}`)
  - `ledger/domain/services/ledger_posting_service.py` (validates balance invariant + writes via repo + publishes domain event)
  - `ledger/domain/ports.py` (`LedgerRepository`)
  - `ledger/domain/errors.py` (`UnbalancedPosting`, `AccountNegativeBalance`, `DuplicatePosting`)
  - `ledger/application/use_cases/post.py` (the orchestration entry point)
  - `ledger/application/queries/get_account_balance.py` (read-only, sums entries for an account)
  - `ledger/infra/sqlalchemy_ledger_repo.py`
  - `ledger/infra/migrations/<timestamp>_ledger_initial.py`
- **Reads / writes:** `ledger.accounts`, `ledger.postings`, `ledger.entries`. Reads via repository for balance projection; writes only via `LedgerPostingService.post()`.
- **Publishes events:** `ledger.PostingCommitted{posting_id, posting_type, total_debit_per_asset, total_credit_per_asset, caused_by_event_id}` — registered.
- **Migrations:** three new tables + deferred trigger function.
- **OpenAPI:** none.

---

## Acceptance Criteria

- **AC-phase2-ledger-001-01:** Given the migration, when applied, then schema `ledger` contains:
  - `ledger.accounts(account_key TEXT PK, asset TEXT NOT NULL, chain TEXT NOT NULL, account_kind TEXT CHECK kind IN ('external_chain', 'user_hot_wallet', 'user_pending_withdrawal', 'faucet_pool'), created_at)` — `account_key` is a string identifier like `user_hot_wallet:<uuid>:ethereum:ETH`.
  - `ledger.postings(id UUID PK, posting_type TEXT NOT NULL CHECK type IN ('deposit', 'withdrawal_reserved', 'withdrawal_settled', 'withdrawal_unreserved', 'faucet_drip'), caused_by_event_id UUID UNIQUE, created_at, metadata JSONB)`.
  - `ledger.entries(id UUID PK, posting_id UUID NOT NULL FK, account_key TEXT NOT NULL FK, asset TEXT, chain TEXT, amount NUMERIC(78,0) NOT NULL CHECK amount > 0, side TEXT CHECK side IN ('debit', 'credit'), created_at)`.

- **AC-phase2-ledger-001-02:** Given the migration, when applied, then a deferred constraint trigger function `ledger.assert_balanced_posting()` exists; it fires AFTER INSERT ON entries (DEFERRABLE INITIALLY DEFERRED), and at COMMIT time verifies that for the touched posting_id, `SUM(amount WHERE side='debit') == SUM(amount WHERE side='credit')` per (asset, chain). If violated, raises a Postgres exception. This is the second-line defense per architecture Section 3.

- **AC-phase2-ledger-001-03:** Given the `LedgerPostingService.post(posting_type, entries, caused_by_event_id, metadata)`, when invoked, then it: (1) validates input — at least 2 entries, `Σ debit = Σ credit` per (asset, chain); (2) refuses to commit if any `user_hot_wallet:*` account would go negative post-posting (queries current balance via repo); (3) within UoW, INSERTs the Posting + Entries, INSERTs/UPDATEs the corresponding `ledger.accounts` rows if not exists; (4) publishes `PostingCommitted` to the outbox; (5) returns the Posting aggregate. On UNIQUE violation on `caused_by_event_id`, returns the existing posting (idempotency).

- **AC-phase2-ledger-001-04:** Given a posting with **unbalanced entries** (e.g., 100 ETH debit + 99 ETH credit), when `LedgerPostingService.post()` validates, then raises `UnbalancedPosting` BEFORE attempting the DB write — application-layer enforcement is the first line of defense per architecture Section 3.

- **AC-phase2-ledger-001-05:** Given a posting that would make a `user_hot_wallet:<user>:*` account negative (e.g., user has 1 ETH, withdrawal of 2 ETH), when validated, then raises `AccountNegativeBalance` with details `{account_key, current_balance, requested_debit}`. **Property test:** for any random sequence of postings starting from zero, the user wallet balance never goes negative.

- **AC-phase2-ledger-001-06:** Given a posting with all debits/credits balanced (e.g., deposit posting: debit `external_chain` 1 ETH, credit `user_hot_wallet:alice:ethereum:ETH` 1 ETH), when validated, then `Σ debit_per_asset = Σ credit_per_asset` confirms balance. **Property test:** for any random valid posting (generated by Hypothesis with constraints), the application validation passes AND the DB constraint trigger does not fire.

- **AC-phase2-ledger-001-07:** Given two outbox deliveries of the same `caused_by_event_id`, when each invokes `LedgerPostingService.post()`, then the first commits the posting; the second hits UNIQUE violation on `caused_by_event_id`, the service catches the violation, looks up the existing posting, and returns it. No double-posting. **Property test:** for the same input event invoked N times, exactly one posting exists.

- **AC-phase2-ledger-001-08:** Given the `GetAccountBalance` query for `account_key='user_hot_wallet:<uuid>:ethereum:ETH'`, when invoked, then it returns `Money(amount=Σ_credits - Σ_debits, currency='ETH', chain='ethereum', decimals=18)`. The query is computed via SQL `SELECT SUM(CASE side='credit' THEN amount ELSE -amount END)`. Cached per-account-key for 5 seconds in Redis (Balances will use this; cache invalidates on `PostingCommitted` events touching the account).

- **AC-phase2-ledger-001-09:** Given the `Money` quantization rule, when an Entry is constructed with a non-integer amount (e.g., `Decimal('1.5')` for ETH), then it is rejected — chain-native units are integers (wei, sun, lamports). The shared kernel `Money` already enforces this; this brief adds a `Money.from_float()` constructor that quantizes via `Decimal` and raises on non-integer chain-native results.

- **AC-phase2-ledger-001-10:** Given the per-schema permissions per architecture Section 3 line 234, when set up in the migration, then: `app_user` has `INSERT, SELECT` on all `ledger.*` tables but NO UPDATE, NO DELETE (the ledger is append-only; corrections are reverse postings). `analytics_user` (created in this migration, even if unused in Phase 2) has SELECT-only on `ledger.entries` and `ledger.postings`. Documented in the migration's docstring.

- **AC-phase2-ledger-001-11:** Given the daily reconciliation job stub, when committed, then `ledger/application/jobs/reconcile_daily.py` exists with a stub that: (1) lists all `user_hot_wallet:*` accounts; (2) for each, computes Ledger balance via `GetAccountBalance`; (3) calls `ChainGateway.get_native_balance(address)` via Chains port to get on-chain balance; (4) compares; (5) on mismatch logs WARNING `ledger.reconciliation.mismatch` with details. The job is **registered** in arq's scheduler with cron `0 4 * * *` but is opt-in via env flag `RECONCILIATION_ENABLED=true`. Phase 2 leaves it disabled in prod (no real chain data flowing yet via this brief — `ledger-002` enables that). Stub returns "OK" with the count of accounts checked.

---

## Out of Scope

- Subscribers wiring deposits/withdrawals to postings: `phase2-ledger-002`.
- Reconciliation job actually firing on real data: enabled in Phase 3 once full chain coverage exists.
- Reverse postings UI / admin: V2.
- Multi-currency aggregation in Ledger: stays out — that's Balances' job.
- Tron and Solana asset coverage in postings: Phase 3 (the schema accommodates `chain` already).
- Per-user audit of postings: Phase 4 if AI assistant needs it.

---

## Dependencies

- **Code dependencies:** `phase1-shared-003` (UoW + DomainEvent base + outbox).
- **Data dependencies:** none — this brief introduces ledger schema.
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/ledger/domain/test_entry_vo.py`, `test_posting_entity.py` — VO equality, posting construction with entries.
- [ ] **Property tests:** `tests/ledger/domain/test_posting_balance_invariant.py` — for any random valid posting, `Σ debits = Σ credits` per asset (AC-06). **This is the architecture-mandated property test (Section 5 line 2).**
- [ ] **Property tests:** `tests/ledger/domain/test_user_account_never_negative.py` — for any random posting sequence starting from zero, `user_hot_wallet:*` balance stays ≥ 0 (AC-05). **Architecture-mandated property test (Section 5 line 3).**
- [ ] **Property tests:** `tests/ledger/domain/test_money_arithmetic_properties.py` — money associativity, quantization round-trip per architecture Section 5 line 1. (Architecture-mandated property test for money.)
- [ ] **Application tests:** `tests/ledger/application/test_post.py` — happy path (deposit, withdrawal_reserved, faucet_drip), UnbalancedPosting raised, AccountNegativeBalance raised, idempotency on duplicate caused_by_event_id. Covers AC-03, AC-04, AC-05, AC-07.
- [ ] **Application tests:** `tests/ledger/application/test_get_account_balance.py` — happy path, unknown account returns Money(0), cache behavior. Covers AC-08.
- [ ] **Adapter tests:** `tests/ledger/infra/test_sqlalchemy_ledger_repo.py` — testcontainer Postgres, asserts INSERT pathway, asserts the deferred constraint trigger fires correctly when a manually-crafted unbalanced posting is INSERTed (covering AC-02). Also asserts permissions per AC-10.
- [ ] **Reconciliation stub test:** `tests/ledger/application/test_reconcile_daily.py` — runs the stub against an empty ledger, asserts "OK" + count=0. Covers AC-11.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All test categories above implemented and passing locally.
- [ ] All four mandatory property tests (per architecture Section 5) implemented and seeded with at least 200 hypothesis runs each in CI.
- [ ] `import-linter` contracts pass: `ledger.domain` may not import other contexts; `ledger.application` may import `ledger.domain` only.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (ledger/domain 95%, ledger/application 90%, ledger/infra 80%).
- [ ] One new domain event registered.
- [ ] One new port (`LedgerRepository`) declared with fake.
- [ ] Single PR. Conventional commit: `feat(ledger): domain + double-entry + reconciliation stub [phase2-ledger-001]`.
- [ ] PR description: an example posting (deposit) with all three rows shown (one Posting, two Entries) — concrete walkthrough.

---

## Implementation Notes

- The `account_key` string format is `<kind>:<id_part>:<chain>:<asset>` for typed accounts and `<kind>:<chain>:<asset>` for system accounts (`external_chain:ethereum:ETH`, `faucet_pool:ethereum:ETH`). Centralize the formatting in `Account.make_key()` to avoid drift.
- The Postgres deferred trigger uses `CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED` so the assertion fires at COMMIT, allowing the application to insert all entries of a posting before validation. Use `op.execute()` in the migration with raw SQL.
- The reconciliation stub deliberately does nothing in Phase 2 — its purpose is to register the cron + the file structure so reviewers see the architectural commitment. Phase 3 fills it in.
- The `account_kind` enum stays narrow in V1; resist adding `pending_swap` or `fee_reserve` until the use case exists.
- Negative balance check (AC-05) needs to query the current balance under the same UoW transaction (with row-level lock on the account row, OR with serializable isolation level for the posting service). Use `SELECT ... FOR UPDATE` on the relevant account rows. Document why.

---

## Risk / Friction

- The deferred constraint trigger is the kind of feature that's easy to mis-implement (wrong NEW/OLD, wrong WHEN clause, wrong return value). Test it ruthlessly — manually craft a malicious unbalanced posting in a SQL transaction and assert COMMIT fails. Document the SQL in the migration's docstring.
- "User account never negative" via row-locking is correct but slow at high concurrency. For Phase 2 portfolio scale (1-10 concurrent operations), it's fine. If reviewers ask about scale, the answer is: "V2 introduces optimistic-locking with version columns + retry, but row-level lock is correct and simple for V1."
- The four property tests are the architecture-mandated ones. Skipping any of them is a process violation. Reviewers at an architecture-review level will check.
- `account_key` as a string PK feels old-school vs UUID. The tradeoff: the string is human-readable in DB inspection (you can see `user_hot_wallet:<uuid>:ethereum:ETH` in psql output), and the natural-key uniqueness eliminates a join when querying balances. Documented in ADR-001; cite if questioned.
