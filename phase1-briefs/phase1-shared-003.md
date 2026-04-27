---
ac_count: 8
blocks:
- phase1-shared-004
- phase1-identity-001
- phase1-identity-002
- phase1-identity-003
- phase1-identity-004
complexity: L
context: shared
depends_on: []
estimated_hours: 4
id: phase1-shared-003
phase: 1
sdd_mode: strict
state: merged
title: Concrete UnitOfWork + DomainEvent outbox table
touches_adrs: []
---

# Brief phase1-shared-003: Concrete UnitOfWork + DomainEvent outbox table


## Context

Bootstrap delivered an `AbstractUnitOfWork` Protocol stub plus a `DomainEvent` base and an empty `event_registry`. Every subsequent application brief depends on a concrete UoW that wraps a SQLAlchemy `AsyncSession`, manages transaction boundaries, captures domain events on aggregates, and writes them to the `shared.domain_events` outbox table in the same DB transaction as the aggregate mutation. Without this brief, no application use case can be implemented without inventing its own transaction semantics — the exact drift Section 2 of architecture-decisions rules out.

This brief delivers two things at the infrastructure level: the `SqlAlchemyUnitOfWork` concrete implementation and the Alembic migration that creates the `shared.domain_events` table per the schema in architecture-decisions Section 3. Domain events are not yet *published* here — that responsibility belongs to `phase1-shared-004` (the outbox worker). What this brief guarantees is that events captured inside a UoW commit land atomically in the outbox alongside the aggregate write.

This is the foundation of the outbox pattern: writes-and-events-in-one-transaction. The reliability of every cross-context flow downstream rests on it.

---

## Architecture pointers

- **Layer(s):** `infra` (concrete UoW + repository base + Alembic), `domain` (no change — Protocol already exists in bootstrap)
- **Affected packages:** `vaultchain.shared.unit_of_work`, `vaultchain.shared.events`, `backend/alembic/versions/`
- **Reads from:** `none` (this brief introduces the substrate)
- **Writes to:** `shared.domain_events` (new table)
- **Publishes events:** `none` (capture-only — publication is `phase1-shared-004`)
- **Subscribes to events:** `none`
- **New ports introduced:** `none` (concretizes existing `AbstractUnitOfWork` Protocol)
- **New adapters introduced:** `SqlAlchemyUnitOfWork`
- **DB migrations required:** `yes` — new schema `shared`, new table `shared.domain_events` per architecture-decisions Section 3, plus the partial index `idx_events_unpublished` on `(published_at, occurred_at) WHERE published_at IS NULL`
- **OpenAPI surface change:** `no`

---

## Acceptance Criteria

- **AC-phase1-shared-003-01:** Given a fresh DB, when the migration runs, then schema `shared` exists with table `shared.domain_events` whose columns and types match architecture-decisions Section 3 exactly (id UUID PK, aggregate_id UUID NOT NULL, aggregate_type TEXT NOT NULL, event_type TEXT NOT NULL, payload JSONB NOT NULL, occurred_at TIMESTAMPTZ DEFAULT NOW(), published_at TIMESTAMPTZ NULL, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT NULL).
- **AC-phase1-shared-003-02:** Given the migration applied, when `\d shared.domain_events` is inspected, then the partial index `idx_events_unpublished` exists on `(published_at, occurred_at) WHERE published_at IS NULL`.
- **AC-phase1-shared-003-03:** Given the migration applied, when the migration is rolled back, then both the table and the schema are cleanly removed (downgrade leaves no orphan objects).
- **AC-phase1-shared-003-04:** Given a `SqlAlchemyUnitOfWork`, when `async with uow:` enters and the body raises, then no rows are committed (rollback semantics).
- **AC-phase1-shared-003-05:** Given a UoW with two aggregate-mutations and one captured `DomainEvent`, when the UoW commits, then both aggregate rows AND the corresponding `shared.domain_events` row are visible in a separate connection (atomicity verified).
- **AC-phase1-shared-003-06:** Given a UoW where the body calls `commit()` explicitly, when the body subsequently raises, then the prior commit persists (commit semantics — re-entrant rollback does not undo committed work). UoW exposes `commit()` and `rollback()` per the bootstrap Protocol.
- **AC-phase1-shared-003-07:** Given a `DomainEvent` instance with arbitrary payload that is JSON-serializable via `dataclasses.asdict`, when `uow.add_event(event)` is called and the UoW commits, then the row in `shared.domain_events` has `aggregate_id`, `aggregate_type`, `event_type` populated from event class metadata and `payload` containing the serialized dataclass minus those three fields.
- **AC-phase1-shared-003-08:** Given two concurrent UoW instances opened on the same aggregate row with optimistic-lock `version` checking, when both attempt UPDATE with the same version, then exactly one succeeds and the other raises `StaleAggregate` (validates the optimistic-lock foundation that Transactions/Custody downstream depend on).

---

## Out of Scope

- Outbox publisher worker (consumer side): covered by `phase1-shared-004`.
- Event handler idempotency log (`event_handler_log` table): covered by `phase1-shared-004`.
- Per-context repository implementations: each context-bootstrap brief delivers its own (e.g., `UserRepository` arrives in `phase1-identity-001`).
- DLQ table: explicitly out of V1 — architecture-decisions Section 3 marks it as ADR-pinned for V2.
- `payload_schema_version` column: deliberate omission per architecture-decisions Section 3 ("naive — only additive optional changes").

---

## Dependencies

- **Code dependencies:** `vaultchain.shared.events.base.DomainEvent`, `vaultchain.shared.events.registry`, `vaultchain.shared.unit_of_work.base.AbstractUnitOfWork`, `vaultchain.shared.domain.errors.ConflictError` — all delivered by bootstrap.
- **Data dependencies:** `none` — first migration this PR introduces.
- **External dependencies:** Alembic (configured in bootstrap), SQLAlchemy 2 async, asyncpg, testcontainers[postgres].

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/shared/domain/test_unit_of_work_protocol.py`
  - covers AC-phase1-shared-003-04 (semantic check on the Protocol shape — fakes-based)
  - test cases: `test_uow_protocol_has_commit_rollback_add_event`, `test_uow_aenter_aexit_signature`
- [ ] **Application tests:** `tests/shared/application/test_unit_of_work_capture.py`
  - uses fake UoW from `tests/shared/fakes/fake_uow.py`
  - covers AC-phase1-shared-003-04, AC-phase1-shared-003-06, AC-phase1-shared-003-07
  - test cases: `test_event_added_then_rollback_does_not_persist`, `test_event_added_after_explicit_commit_persists`, `test_event_serialization_roundtrip`
- [ ] **Adapter tests:** `tests/shared/infra/test_sqlalchemy_unit_of_work.py`
  - testcontainers Postgres, real migrations applied
  - covers AC-phase1-shared-003-01 through -05, -07, -08
  - test cases: `test_migration_creates_shared_schema`, `test_migration_creates_domain_events_table_with_columns`, `test_migration_creates_partial_index`, `test_downgrade_removes_table_and_schema`, `test_uow_rollback_on_exception`, `test_uow_atomic_aggregate_and_event_write`, `test_event_payload_serialization_in_db`, `test_optimistic_lock_concurrent_update_raises_stale`
- [ ] **Property tests:** `tests/shared/domain/test_domain_event_serialization_properties.py`
  - hypothesis-driven, only for the event-serialization roundtrip (deterministic, no DB)
  - properties: `for any DomainEvent dataclass with primitive fields, asdict→json→jsonb→dict→reconstructed_event preserves equality`

Contract and E2E layers do not apply — this brief introduces no API surface.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass (no architectural drift).
- [ ] `mypy --strict` passes for touched modules.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (≥85% on `shared/unit_of_work`, ≥85% global).
- [ ] OpenAPI schema diff: N/A (no API surface).
- [ ] No new domain events registered (this brief is substrate, not producer). The `event_registry` import path is touched only to verify it loads cleanly post-migration.
- [ ] No new ADR drafted (canonical pattern, no decision deviation).
- [ ] No new port introduced.
- [ ] Migration script committed at `backend/alembic/versions/<date>_shared_outbox_initial.py` with both `upgrade()` and `downgrade()`, downgrade tested in adapter test.
- [ ] Single PR. Conventional commit. Title format: `feat(shared): concrete UoW + domain events outbox table [phase1-shared-003]`.
- [ ] PR description references brief, lists AC↔test map, lists touched ADRs (none).

---

## Implementation Notes

- Use SQLAlchemy 2 async style (`AsyncSession`, `sessionmaker(class_=AsyncSession)`). Bind UoW lifetime to one session per `__aenter__`; close on `__aexit__`.
- `add_event` captures into an in-memory list on the UoW; the actual INSERT into `shared.domain_events` happens inside the commit path, *before* the SQL `COMMIT`, so atomicity is guaranteed by the single transaction. Do not flush events on `add_event` — that would split atomicity.
- Event serialization: use `dataclasses.asdict(event)` for the payload, but extract `aggregate_id`, `aggregate_type`, `event_type` to columns. The `DomainEvent` base class declares these as class-level attributes (or `__class_var__`-style); the concrete event subclasses set them.
- For optimistic locking: use a `version` column convention on aggregate tables (introduced per-aggregate by their bootstrap brief). The UoW does not own optimistic locking — it just propagates the `StaleAggregate` (subclass of `ConflictError` from `shared/domain/errors.py`) when `UPDATE ... WHERE version = ?` returns `rowcount == 0`. AC-08 verifies this contract on a test aggregate defined in the test module only.
- Schema-per-context naming: migration creates `CREATE SCHEMA shared`, then `CREATE TABLE shared.domain_events ...`. Follow the migration naming convention from setup-prompt: `<date>_shared_outbox_initial.py`.
- Apply `make-migration` skill discipline: write upgrade, write downgrade, write the test that applies-and-rolls-back.
- The `version` column is NOT added to `shared.domain_events` itself — events are append-only (Regime C per architecture-decisions Section 3). Only mutable aggregate tables get `version`.

---

## Risk / Friction

- The split between "UoW captures events" (here) and "outbox publisher dispatches" (`phase1-shared-004`) means this brief delivers a system where events accumulate in the table but nothing reads them. That is intentional but could surprise a reviewer skimming logs — make the absence visible by adding a one-line comment in the worker placeholder file pointing to brief -004.
- Optimistic-lock test (AC-08) needs a *test-only* aggregate table with a `version` column. Define this in the test module rather than introducing real schema, to avoid coupling this brief to any future aggregate's migration.
- Testcontainers Postgres image must be `postgres:16` with `pgvector` and (optionally) `pg_uuidv7` available. Bootstrap docker-compose pinned 16; the testcontainer base image must match — verify in `tests/shared/conftest.py`.
