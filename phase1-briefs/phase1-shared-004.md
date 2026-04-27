---
ac_count: 8
blocks: []
complexity: M
context: shared
depends_on:
- phase1-shared-003
estimated_hours: 4
id: phase1-shared-004
phase: 1
sdd_mode: strict
state: in_progress
title: Outbox publisher worker + EventBus implementation
touches_adrs: []
---

# Brief phase1-shared-004: Outbox publisher worker + EventBus implementation


## Context

The `shared.domain_events` outbox table is now populated atomically with aggregate writes (per `phase1-shared-003`). This brief delivers the consumer side: an arq-managed worker that polls the outbox for unpublished events, dispatches them to in-process subscribers via the `EventBus`, and marks `published_at` on success or increments `attempts` on failure with exponential backoff. It also delivers the concrete `EventBus` adapter that fronts the registry.

The outbox pattern is only as reliable as the consumer. This brief makes that consumer real: at-least-once delivery, idempotent re-delivery via the `event_handler_log` UNIQUE constraint, and observable via structlog with `event_id` correlation.

No subscriber is wired in this brief — the registry is empty until identity briefs register their handlers. The publisher loop must therefore be no-op-safe when no subscriber exists for an event type (log INFO and mark published).

---

## Architecture pointers

- **Layer(s):** `infra` (worker, EventBus adapter), `application` (handler invocation surface)
- **Affected packages:** `vaultchain.shared.events`, `backend/src/vaultchain/main.py` (worker entrypoint), Alembic versions/
- **Reads from:** `shared.domain_events`
- **Writes to:** `shared.domain_events` (`published_at`, `attempts`, `last_error`), `shared.event_handler_log` (new table)
- **Publishes events:** `none` (it's the publisher itself)
- **Subscribes to events:** `none` directly — fans events out to registered handlers
- **New ports introduced:** `none` (concretizes existing `EventBus` Protocol)
- **New adapters introduced:** `OutboxEventBus` (sync in-process implementation), `OutboxPublisherWorker` (arq job)
- **DB migrations required:** `yes` — new table `shared.event_handler_log` with `(event_id, handler_name) UNIQUE` per architecture-decisions Section 3
- **OpenAPI surface change:** `no`

---

## Acceptance Criteria

- **AC-phase1-shared-004-01:** Given the migration applied, when `\d shared.event_handler_log` is inspected, then the table exists with `(event_id UUID, handler_name TEXT, processed_at TIMESTAMPTZ, status TEXT)` and a `UNIQUE (event_id, handler_name)` constraint.
- **AC-phase1-shared-004-02:** Given an event row with `published_at IS NULL` and one registered handler, when the publisher polls, then the handler is invoked exactly once with the deserialized event payload.
- **AC-phase1-shared-004-03:** Given an event row whose handler invocation succeeds, when the worker tick completes, then `published_at` is set and `event_handler_log` has a row with `status='success'`.
- **AC-phase1-shared-004-04:** Given an event row whose handler raises, when the worker tick completes, then `published_at` remains NULL, `attempts` is incremented, `last_error` contains the exception message, and the row is eligible for retry on next tick (subject to backoff).
- **AC-phase1-shared-004-05:** Given an event delivered twice (re-poll on transient failure), when the second handler invocation begins, then it short-circuits via the `event_handler_log` UNIQUE on `(event_id, handler_name)` and the handler is NOT re-executed.
- **AC-phase1-shared-004-06:** Given an event with no registered handler, when the publisher polls, then the row is marked `published_at` (no-op-safe — events without subscribers are not retried forever).
- **AC-phase1-shared-004-07:** Given backoff config `base=1s, factor=2, max=60s`, when an event has `attempts=3`, then it is not eligible for poll until `occurred_at + 8s` has elapsed (backoff respected).
- **AC-phase1-shared-004-08:** Given the worker process is started via `arq worker`, when shut down via SIGTERM, then in-flight handler invocations complete before exit (graceful shutdown — the outbox is never left in a half-processed state).

---

## Out of Scope

- DLQ table after N failures: out of V1 (architecture-decisions Section 3 ADR-pin).
- Cross-process distributed coordination (multiple worker replicas): single-replica V1; ADR-stub if scale demands later. Use a Postgres advisory lock (`pg_advisory_lock(outbox_publisher_lock)`) on tick start to make the design forward-compatible without committing.
- HTTP-callable subscriber endpoints: V1 has only in-process subscribers.
- Subscriber registration: handlers are registered via decorator or registry append in their own context's bootstrap brief, not here.

---

## Dependencies

- **Code dependencies:** `vaultchain.shared.unit_of_work.SqlAlchemyUnitOfWork`, `vaultchain.shared.events.{base, registry, bus}`, `phase1-shared-003` migration applied.
- **Data dependencies:** `phase1-shared-003` migration must run first (FK from `event_handler_log.event_id` to `shared.domain_events.id`).
- **External dependencies:** `arq` (already in `pyproject.toml`), Redis (docker-compose).

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/shared/domain/test_event_bus_protocol.py`
  - covers AC-phase1-shared-004-02 (Protocol shape only)
  - test cases: `test_event_bus_publish_signature`, `test_event_bus_subscribe_signature`
- [ ] **Application tests:** `tests/shared/application/test_outbox_publisher_loop.py`
  - uses fake handlers + in-memory event store
  - covers AC-phase1-shared-004-02, -03, -04, -05, -06
  - test cases: `test_dispatch_to_registered_handler`, `test_handler_success_marks_published`, `test_handler_failure_increments_attempts_and_records_error`, `test_redelivery_short_circuits_via_handler_log`, `test_event_with_no_handler_marked_published`
- [ ] **Adapter tests:** `tests/shared/infra/test_outbox_publisher_worker.py`
  - testcontainers Postgres + Redis, real arq job
  - covers AC-phase1-shared-004-01, -07, -08
  - test cases: `test_event_handler_log_table_and_unique_constraint`, `test_backoff_skips_recently_failed`, `test_graceful_shutdown_drains_inflight`
- [ ] **Property tests:** `tests/shared/domain/test_outbox_idempotency_properties.py`
  - hypothesis-driven on `(event_id, handler_name)` re-delivery sequences
  - properties: `for any sequence of (deliver, redeliver, redeliver) on the same (event_id, handler_name), handler is invoked at most once` (verifies the must-have property test from architecture-decisions Section 5: idempotency replay).

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Coverage ≥85% on `shared/events/`.
- [ ] No new ADR.
- [ ] Migration `<date>_shared_event_handler_log.py` committed with downgrade tested.
- [ ] arq worker entry registered in `backend/src/vaultchain/main.py` and discoverable via `arq vaultchain.worker.WorkerSettings`.
- [ ] Structlog correlation: each handler invocation logs `{event_id, event_type, handler_name, attempt, status}` at INFO level.
- [ ] Single PR. Conventional commit: `feat(shared): outbox publisher worker + EventBus adapter [phase1-shared-004]`.
- [ ] PR description AC↔test map, ADRs (none).

---

## Implementation Notes

- The `OutboxEventBus.publish` method is unused at this stage (no synchronous publishers from the application side). Application code never calls `publish` directly — it adds events to the UoW via `add_event`, and the outbox+worker handle delivery. Document this in a module docstring so the next brief author doesn't reach for `publish`.
- Polling interval: 1 second by default, configurable via env var `OUTBOX_POLL_INTERVAL_S`. The poll query is `SELECT ... FROM shared.domain_events WHERE published_at IS NULL AND occurred_at + backoff(attempts) <= NOW() ORDER BY occurred_at LIMIT 100 FOR UPDATE SKIP LOCKED` — `SKIP LOCKED` makes the design forward-compatible to multi-replica without committing now.
- Handler invocation: the worker calls handlers via `await handler(event)`. Handlers are async coroutines. If a handler is sync, wrap with `asyncio.to_thread`.
- Idempotency: BEFORE invoking the handler, INSERT into `shared.event_handler_log` with `ON CONFLICT (event_id, handler_name) DO NOTHING`. If `rowcount == 0`, the handler already ran — skip and mark published.
- Event reconstruction: the registry maps `event_type` string → dataclass. The worker reads `payload` JSONB, looks up the class, calls `Event(**payload, aggregate_id=row.aggregate_id, ...)`. If `event_type` is unknown to the registry, log WARN and mark published (forward compatibility — events from a future deploy will be silently skipped on a rolled-back replica).

---

## Risk / Friction

- arq's interaction with testcontainers can be flaky if the Redis connection is closed before in-flight jobs drain. Use `WorkerSettings.on_shutdown` to drain explicitly. Document the pattern in the test fixture for future workers.
- The "no-op-safe on missing handler" semantics (AC-06) is a *design choice* — alternatively events without handlers could fail loudly. We pick no-op-safe for V1 because the alternative breaks rollbacks (a rolled-back deploy would crash on events from the newer code). If a reviewer pushes back, architecture-decisions Section 3 supports the choice ("only additive optional changes").
- Backoff math: `backoff_seconds = min(base * (factor ** attempts), max_backoff)`. Implement as a pure function in `shared/events/backoff.py` and unit-test exhaustively — easy to fence-post.
