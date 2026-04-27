---
ac_count: 10
blocks: []
complexity: M
context: audit
depends_on:
- phase2-custody-002
- phase1-admin-002
- phase1-shared-003
estimated_hours: 4
id: phase2-audit-001
phase: 2
sdd_mode: strict
state: ready
title: Audit context (log table, subscribers, /admin/audit endpoint)
touches_adrs: []
---

# Brief: phase2-audit-001 — Audit context (log table, subscribers, /admin/audit endpoint)


## Context

Per architecture Section 2 line 60-62, Audit is a cross-cutting concern, but for clean read access and Phase 3's admin viewer it gets its own thin context layer. The `custody.audit_log` table is owned and written by Custody (per `phase2-custody-001`); this brief delivers:

1. A separate `audit.events` mirror table for non-custody operations (admin actions, KYC reviews when Phase 3 lands, withdrawal approvals when Phase 3 lands). Phase 2 populates it with admin login events from `phase1-admin-002`.
2. Subscribers that listen to outbox events from custody/identity/admin contexts and (a) for events already captured by `custody.audit_log` (signing, key generation), do nothing — Custody writes them in-context; (b) for non-custody events (admin login, admin action), insert into `audit.events`.
3. A `GET /admin/api/v1/audit` paginated read endpoint that UNIONs `custody.audit_log` and `audit.events`, returning a unified timeline.

The reasoning per architecture Section 3 + the privacy section: Custody's audit log holds operations involving keys (sign, encrypt, decrypt, generate). It needs the type-level invariant that nothing larger than a 32-byte hash leaks. Other audit needs (admin logged in, admin viewed user X) are non-key-related and can carry richer payloads — they belong in a different table with looser typing. UNIONing at read-time gives the admin a single timeline.

The endpoint is admin-only (gated by `phase1-admin-002`'s admin session middleware). Filters: `actor_type` (`user|admin|system`), `actor_id`, `operation`, `from_date`, `to_date`. Pagination: cursor-based on `created_at, id` (audit logs grow large; offset-based pagination becomes slow). For Phase 2, no admin UI consumes this yet — the endpoint is built but the reader is Phase 3's admin audit viewer brief.

Per architecture line 363: "the log never stores `signed_tx`, raw private key bytes, or KMS plaintext data keys. Only SHA-256 pre/post hashes." This invariant lives in `custody.audit_log` (enforced in `custody-001` via type system). For `audit.events`, payloads are JSONB but with a different invariant: no PII (no email, phone, SSN, address). A "sanitization" helper in this brief enforces the rule for known PII fields; it's best-effort.

---

## Architecture pointers

- **Layer:** application + delivery + infra. No domain entities (audit is reporting, not a state machine).
- **Packages touched:**
  - `audit/application/handlers/on_admin_authenticated.py` (writes to `audit.events`)
  - `audit/application/handlers/on_admin_action_performed.py` (Phase 3 placeholder)
  - `audit/application/queries/list_audit_events.py` (UNION query, cursor pagination)
  - `audit/infra/sqlalchemy_audit_events_repo.py`
  - `audit/infra/sanitizer.py` (PII redaction helper)
  - `audit/infra/migrations/<timestamp>_audit_initial.py` (creates `audit.events` table)
  - `audit/delivery/router.py` (`GET /admin/api/v1/audit`)
- **Reads:** `custody.audit_log` (cross-schema SELECT — uses `audit_user` role declared in `custody-001` AC-10), `audit.events`.
- **Writes:** `audit.events` only. Custody writes its own audit log.
- **Subscribes to events:**
  - `identity.AdminAuthenticated` (from `phase1-admin-002`) → writes audit.events
  - `audit.AdminActionPerformed` (Phase 3 only — placeholder)
  - `custody.SigningPerformed` / `custody.SigningFailed` → **NOT subscribed**, Custody owns its log
- **Migrations:** `audit.events` schema and table.
- **OpenAPI:** new `GET /admin/api/v1/audit` endpoint.

---

## Acceptance Criteria

- **AC-phase2-audit-001-01:** Given the migration runs, when applied, then `audit.events` table exists with columns: `id UUID PK, event_id UUID UNIQUE NOT NULL, request_id TEXT, actor_type TEXT NOT NULL CHECK actor_type IN ('user', 'admin', 'system'), actor_id UUID NOT NULL, operation TEXT NOT NULL, target_type TEXT, target_id TEXT, payload JSONB NOT NULL DEFAULT '{}', result TEXT NOT NULL CHECK result IN ('success', 'failure'), failure_reason TEXT, created_at TIMESTAMPTZ DEFAULT NOW()`. Index on `(created_at DESC, id)` for cursor pagination. Index on `actor_id`, `operation` for filtered queries.

- **AC-phase2-audit-001-02:** Given the migration, when applied, then a database role `audit_reader` is created with `SELECT` only on `audit.events` and `custody.audit_log`. The `app_user` is granted `INSERT, SELECT` on `audit.events`. The endpoint connection uses the `app_user` (no separate connection pool yet); Phase 3 may introduce a dedicated `audit_reader` pool for the admin viewer.

- **AC-phase2-audit-001-03:** Given `identity.AdminAuthenticated{admin_id, ip_address, user_agent, success: bool}` arrives via outbox, when `on_admin_authenticated` fires, then it INSERTs into `audit.events`: `actor_type='admin', actor_id=admin_id, operation='admin.login', target_type=null, target_id=null, payload={'ip_address': '...', 'user_agent': '...'}, result='success' or 'failure'`. Idempotent on `event_id UNIQUE`.

- **AC-phase2-audit-001-04:** Given `GET /admin/api/v1/audit?limit=20&cursor=<base64>&actor_type=admin&from_date=2026-04-01`, when called by an authenticated admin, then it: (1) returns a cursor-paginated UNION of `custody.audit_log` and `audit.events` with the columns aligned to a common shape `{id, event_id, actor_type, actor_id, operation, target, payload_summary, result, failure_reason, created_at, source}` (where `source='custody'` or `'audit'`); (2) ordered by `created_at DESC, id DESC`; (3) applies filters; (4) `cursor` is base64-encoded `(created_at, id)` of the last row.

- **AC-phase2-audit-001-05:** Given the Custody audit_log row carries 32-byte `pre_hash` and `post_hash`, when transformed into the unified shape for the read endpoint, then the response includes them as hex strings: `payload_summary: {pre_hash: '0xabc...', post_hash: '0xdef...', kms_key_id: 'alias/...'}`. The full row data is preserved; the endpoint does not redact (it's admin-only). For `audit.events` rows with rich payloads, `payload_summary` is the full JSONB.

- **AC-phase2-audit-001-06:** Given the sanitizer helper `redact_pii(payload: dict) -> dict`, when invoked with a payload containing keys matching known PII patterns (`email`, `phone`, `ssn`, `address`), then those keys' values are replaced with `'[REDACTED]'`. The matcher is name-based (case-insensitive substring match) — not perfect but covers known fields. **Property test:** for any random payload with PII keys, the output has those keys redacted. Unknown keys pass through.

- **AC-phase2-audit-001-07:** Given a non-admin authenticated user, when they call `GET /admin/api/v1/audit`, then they receive `403 admin.unauthorized`. The endpoint's middleware (from `phase1-admin-002`) enforces admin-only access.

- **AC-phase2-audit-001-08:** Given an unauthenticated request to `GET /admin/api/v1/audit`, when received, then returns `401 auth.required`. The endpoint sits behind admin session middleware on the `/admin/api/v1/...` mount per architecture Section 4.

- **AC-phase2-audit-001-09:** Given the cursor encoding/decoding, when the cursor is malformed (truncated, wrong base64), then the endpoint returns `400 audit.cursor_invalid`. When the cursor decodes to fields outside the result set, returns an empty result (graceful — pagination beyond the end).

- **AC-phase2-audit-001-10:** Given the rate limit policy on the audit endpoint, when called more than 30 times per minute per admin, then 429. (Lower than user-facing endpoints because this is heavy reads.)

- **AC-phase2-audit-001-11:** Given the admin viewer (Phase 3) is not yet implemented, when an operator wants to inspect logs immediately, then the runbook documents: `curl https://api.vaultchain.app/admin/api/v1/audit -H 'Cookie: ...' | jq .events[]`. Adequate for Phase 2 ops needs.

---

## Out of Scope

- The admin audit viewer UI: Phase 3.
- Custody-side audit log writing: already in `custody-002`.
- KYC review audit events: Phase 3 (introduces `kyc.ReviewCompleted`).
- Withdrawal approval audit events: Phase 3.
- AI prep card audit events: Phase 4 (introduces `ai.PrepCardConfirmed`).
- Real-time audit streaming (WebSocket / SSE): V2.
- Cryptographic audit-log signing (tamper-evident chain): V2.
- Per-row encryption of audit payloads: V2.

---

## Dependencies

- **Code dependencies:** `phase2-custody-002` (custody.audit_log populated; cross-schema SELECT), `phase1-admin-002` (AdminAuthenticated event published; admin middleware available).
- **Data dependencies:** `custody.audit_log` schema applied. `identity.users` schema applied (admin sessions need it).
- **External dependencies:** none new.

---

## Test Coverage Required

- [ ] **Application tests:** `tests/audit/application/test_on_admin_authenticated.py` — happy path success, happy path failure, idempotent re-delivery. Covers AC-03.
- [ ] **Application tests:** `tests/audit/application/test_list_audit_events.py` — UNION query returns rows from both sources, ordering correct, cursor pagination round-trips, filters apply correctly. Uses Fakes. Covers AC-04, AC-05.
- [ ] **Property tests:** `tests/audit/infra/test_sanitizer_properties.py` — for any random payload, PII keys are redacted, non-PII keys pass through. Covers AC-06.
- [ ] **Adapter tests:** `tests/audit/infra/test_sqlalchemy_audit_events_repo.py` — testcontainer Postgres, INSERT, cursor pagination correctness, role permissions per AC-02.
- [ ] **Contract tests:** `tests/api/test_admin_audit_endpoint.py` — TestClient hits `GET /admin/api/v1/audit` as authenticated admin (asserts UNION results), as user (403), unauthenticated (401), with bad cursor (400), with rate limit exceeded (429). Covers AC-04, AC-07, AC-08, AC-09, AC-10.

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] OpenAPI schema diff: 1 new endpoint documented; `docs/api-contract.yaml` committed.
- [ ] No new domain events.
- [ ] One new port `AuditEventsRepository` declared with fake.
- [ ] Single PR. Conventional commit: `feat(audit): events table + subscribers + admin endpoint [phase2-audit-001]`.
- [ ] `docs/runbook.md` updated with the curl-based audit inspection procedure (AC-11).

---

## Implementation Notes

- The UNION query uses raw SQL with parameterized filters — SQLAlchemy's UNION is awkward; raw is clearer. Document the SQL template at the top of `list_audit_events.py`.
- The cursor decode validates: base64-decoded JSON `{ts: str, id: str}`. Anything else is malformed.
- The `payload_summary` field in the unified response comes verbatim from the source row's payload (or transformed for custody.audit_log into a fixed shape including hashes-as-hex). Don't aggregate / redact at read time — the admin needs the full picture.
- For `audit.events` writes, sanitize at write time (not read time) — once PII is in the table, re-reads might not re-sanitize. Audit log is the worst place for PII leaks.
- The audit event id (`event_id UUID UNIQUE`) maps to the outbox event id — provides traceability from outbox → audit row.

---

## Risk / Friction

- The cross-schema SELECT (audit endpoint reading `custody.audit_log`) is a small architecture-decisions deviation per Section 3 ("Each bounded context owns its own Postgres schema"). Document this as a deliberate exception for read-only audit access; the alternative (audit.events mirror of custody hashes) duplicates without value.
- The PII sanitizer is best-effort name-matching; reviewers may push back on its rigor. The defense: the sanitizer is for `audit.events`, which doesn't normally hold PII (admin operations don't expose user PII in their event payloads — the event is "admin viewed user X" with `target_id=user_id`, not `target_data={email, phone}`). Document the principle: "PII-bearing fields don't belong in audit payloads at all; the sanitizer is a defense-in-depth catch."
- Cursor pagination implementation has subtle bugs around tied `created_at` (multiple rows in the same millisecond). The `(created_at, id)` composite cursor handles ties. Test with a fixture that intentionally creates 100 rows with identical `created_at`.
- The 30 req/min rate limit on the audit endpoint is conservative. If Phase 3's admin UI polls heavily, raise to 120 req/min. Don't tune until use case demands.
- `audit.events` will grow forever in V1. Phase 4 adds a 90-day retention policy. For Phase 2 portfolio scope (a few hundred events total), no concern.
