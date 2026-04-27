---
ac_count: 8
blocks:
- phase2-web-006
- phase2-web-007
complexity: L
context: notifications
depends_on:
- phase1-identity-002
- phase2-transactions-002
- phase2-faucet-001
estimated_hours: 4
id: phase2-notifications-001
phase: 2
sdd_mode: strict
state: ready
title: Notifications context + SSE channel + Resend email adapter
touches_adrs:
- ADR-003
---

# Brief: phase2-notifications-001 — Notifications context + SSE channel + Resend email adapter


## Context

This brief delivers two related deliverables in one PR:

1. **Real Resend email adapter** replacing `ConsoleEmailSender` from `phase1-identity-002`. Same `EmailSender` Protocol; new adapter calls Resend's API. Templates: magic-link (already used by Phase 1), tx-confirmed (new), faucet-success (new). Replaces console-print-only behavior with real email delivery.

2. **Notifications context + SSE channel.** Per architecture Section 4 line 495-497: "A single `/api/v1/events` SSE channel multiplexes `transaction.status_changed`, `notification.created`, `kyc.tier_changed` events. The channel opens on login. TanStack Query polling is the graceful-degradation fallback." This brief delivers: the Notifications domain (Notification entity, `NotificationPreferences`), subscribers that translate domain events into Notifications + SSE pushes, the `/api/v1/events` SSE endpoint, and `/api/v1/notifications` REST endpoints (list, mark-read, preferences).

The SSE flow:
- Frontend connects on login: `EventSource('/api/v1/events?token=<session>')`.
- Backend uses an in-process pub/sub (Redis pub/sub for multi-instance correctness): on event publish, the handler `notify_user(user_id, event)` selects connected SSE channels for that user and writes the event.
- Heartbeat every 25s (`event: heartbeat\ndata: {}`) to keep the connection alive past load balancer idle timeouts.
- Reconnect strategy: client uses `Last-Event-ID` header to resume; backend stores last 50 events per user in Redis (TTL 5 minutes) for replay.

Event multiplexing: this brief subscribes to `transactions.Confirmed`, `transactions.Failed`, `transactions.Expired`, `chain.DepositDetected` (translated through Ledger to the user-facing event), `faucet.QuickFundCompleted`. For each, creates a Notification row and pushes the SSE event. The frontend's EventBus distributes to whichever components care.

Email triggers: `transactions.Confirmed` → optional email (off by default; per-user preference). Magic-link emails continue from Identity. Faucet-success emails are off by default (high-volume noise). Phase 4 polish may add more email templates.

---

## Architecture pointers

- **Layer:** domain + application + infra + delivery.
- **Packages touched:**
  - `notifications/domain/entities/notification.py`
  - `notifications/domain/value_objects/notification_kind.py` (`tx_confirmed | tx_failed | deposit_detected | faucet_success | system`)
  - `notifications/domain/value_objects/notification_preferences.py`
  - `notifications/domain/ports.py` (`NotificationRepository`, `SSEPublisher`, `EmailSender` reused)
  - `notifications/application/handlers/on_transaction_confirmed.py`, `on_transaction_failed.py`, `on_deposit_detected.py`, `on_faucet_completed.py`
  - `notifications/application/use_cases/list_notifications.py`, `mark_read.py`, `update_preferences.py`
  - `notifications/infra/sqlalchemy_notifications_repo.py`
  - `notifications/infra/redis_sse_publisher.py` (Redis pub/sub for cross-instance)
  - `notifications/infra/resend_email_adapter.py` (replaces ConsoleEmailSender)
  - `notifications/delivery/router.py` (REST endpoints + SSE endpoint)
  - `notifications/delivery/sse_handler.py` (the streaming response)
  - `notifications/infra/migrations/<timestamp>_notifications_initial.py`
  - `notifications/infra/email_templates/` (HTML templates: magic-link, tx-confirmed, faucet-success)
- **Reads:** `notifications.notifications`, `notifications.preferences`, Redis (SSE channel registry, last-50-events).
- **Writes:** `notifications.notifications` insert, `notifications.preferences` upsert, Redis pub/sub publish, Resend API.
- **Subscribes to events:** `transactions.Confirmed`, `transactions.Failed`, `transactions.Expired`, `chain.DepositDetected`, `faucet.QuickFundCompleted`.
- **Migrations:** `notifications.notifications`, `notifications.preferences`.
- **OpenAPI:** new endpoints `/api/v1/events` (SSE), `/api/v1/notifications`, `/api/v1/notifications/{id}/read`, `/api/v1/notifications/preferences`.

---

## Acceptance Criteria

- **AC-phase2-notifications-001-01:** Given the migration runs, when applied, then `notifications.notifications` exists with columns `id UUID PK, user_id UUID NOT NULL, kind TEXT NOT NULL CHECK kind IN (...), title TEXT NOT NULL, body TEXT NOT NULL, payload JSONB NOT NULL DEFAULT '{}', read_at TIMESTAMPTZ NULL, created_at` indexed on `(user_id, created_at DESC)`. `notifications.preferences` exists with `user_id UUID PK, email_tx_confirmed BOOL DEFAULT false, email_tx_failed BOOL DEFAULT true, email_faucet_success BOOL DEFAULT false, email_deposit_detected BOOL DEFAULT false, sse_enabled BOOL DEFAULT true, updated_at`.

- **AC-phase2-notifications-001-02:** Given `transactions.Confirmed{transaction_id, tx_hash, block_number}` arrives, when `on_transaction_confirmed` fires, then it: (1) loads Transaction view (read-only port from `ledger-002`'s pattern); (2) creates a Notification with `kind='tx_confirmed', title='Transaction confirmed', body='Your <amount> <asset> sent to <to_address[:8]>… is confirmed.', payload={transaction_id, tx_hash, block_number, amount, asset, to_address}`; (3) inserts into repo; (4) publishes to SSE via `SSEPublisher.publish(user_id, event)`; (5) IF `preferences.email_tx_confirmed=true`, calls `EmailSender.send(template='tx-confirmed', vars={...}, to=user.email)`. (Phase 1's preference defaults are off, so most users don't get emails.)

- **AC-phase2-notifications-001-03:** Given `chain.DepositDetected` arrives (via the Ledger flow — actually subscribed here too, listening directly to chain events), when `on_deposit_detected` fires, then creates Notification with `kind='deposit_detected', title='Deposit received', body='You received <amount> <asset>.', payload={amount, asset, tx_hash, block_number}`; SSE pushes; emails IF preference enabled.

- **AC-phase2-notifications-001-04:** Given `GET /api/v1/events?token=<session>`, when an authenticated user opens the SSE connection, then: (1) middleware validates session; (2) handler upgrades to SSE response; (3) subscribes to Redis pub/sub channel `notifications:user:<user_id>`; (4) writes any "missed" events (resume from `Last-Event-ID` header, querying last 50 from Redis), (5) sends `event: connected\ndata: {ts: ...}`; (6) writes new events as they arrive, format `event: <kind>\ndata: <json>\nid: <event_id>\n\n`; (7) heartbeat `event: heartbeat\ndata: {}` every 25s. Connection closes on client disconnect or auth expiry.

- **AC-phase2-notifications-001-05:** Given the SSE connection is active and a `transactions.Confirmed` event triggers the handler, when the SSE handler picks it up, then the event is written to the open connection within ~50ms (Redis pub/sub latency). Test asserts the event is delivered to a connected EventSource within 200ms.

- **AC-phase2-notifications-001-06:** Given the user's SSE connection drops mid-session (client disconnect, network blip), when reconnecting with `Last-Event-ID: <last_received_event_id>`, then the handler queries Redis `notifications:user:<user_id>:replay` (a sorted set of last 50 events keyed by event_id), replays events with id > Last-Event-ID, then continues with live events. Replay TTL is 5 minutes; if the gap is longer, the client falls back to TanStack Query polling. Frontend logic in web-006/web-007.

- **AC-phase2-notifications-001-07:** Given `GET /api/v1/notifications?limit=20&before=<cursor>`, when called by an authenticated user, then returns paginated list ordered by `created_at DESC`. Each row has `{id, kind, title, body, payload, read: bool, created_at}`. `unread_count` returned in the response envelope. Cache headers `Cache-Control: private, no-cache`.

- **AC-phase2-notifications-001-08:** Given `POST /api/v1/notifications/{id}/read`, when called, then sets `read_at = NOW()` for the notification (idempotent on already-read). Returns 204. `POST /api/v1/notifications/read-all` marks all unread as read in one call. `GET /api/v1/notifications/preferences` and `PATCH /api/v1/notifications/preferences` for per-user toggles.

- **AC-phase2-notifications-001-09:** Given the `ResendEmailAdapter`, when constructed with `RESEND_API_KEY` env var, when `send(template, vars, to)` is called, then it: (1) renders the Jinja2 template from `notifications/infra/email_templates/<template>.html` with `vars`; (2) constructs a Resend API request `POST https://api.resend.com/emails` with `from: 'VaultChain <noreply@vaultchain.app>'` (operator-configured `EMAIL_FROM` env), `to`, `subject` (rendered separately), `html` (the rendered template); (3) on 200, returns success; (4) on 4xx (invalid email, etc.), logs WARN and returns success (don't fail the calling use case for email failures); (5) on 5xx or timeout (5s), retries once with exponential backoff, then logs ERROR and returns success.

- **AC-phase2-notifications-001-10:** Given the development environment (`ENV=dev`), when `ResendEmailAdapter` is configured, then it falls back to `ConsoleEmailSender` behavior (prints to stdout, doesn't call Resend). Switch via `EMAIL_DELIVERY=console|resend` env var. Tests use the console adapter (or a `FakeEmailSender` that captures calls).

- **AC-phase2-notifications-001-11:** Given the magic-link email template (re-used from `phase1-identity-002` but now rendered via the new adapter), when sent, then it includes the same content/CTA as Phase 1 plus VaultChain branding (logo URL, footer with unsubscribe info — even though there's nothing to unsubscribe from in V1, the placeholder shows operational discipline). The template lives in `notifications/infra/email_templates/magic-link.html`.

- **AC-phase2-notifications-001-12:** Given the rate limit policy, when the SSE endpoint is connected by the same user from more than 3 simultaneous browser tabs, then the 4th connection receives `429 events.too_many_connections`. The Redis-tracked active-connection count enforces this. Reasonable per architecture Section 4.

---

## Out of Scope

- Push notifications (mobile / web push): V2.
- Slack / Discord webhooks: V2.
- Per-event-type SSE subscription filtering (frontend asks "only tx events"): V2 — Phase 2 sends all events to the channel, frontend filters.
- Email digest mode (one daily summary): V2.
- Localization (i18n) of notification text: V2 (English only).
- Read receipts / delivery confirmation: V2.
- Custom user notification rules: V2.

---

## Dependencies

- **Code dependencies:** `phase1-identity-002` (extracts EmailSender port; replaces adapter), `phase2-transactions-002`, `phase2-faucet-001`, all event publishers in Phase 2.
- **Data dependencies:** all prior migrations applied; Redis available.
- **External dependencies:** Resend account + API key (operator-provisioned, free tier 100 emails/day). Redis pub/sub.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/notifications/domain/test_notification_entity.py` — factory, serialization.
- [ ] **Application tests:** `tests/notifications/application/test_on_transaction_confirmed.py` — happy path creates notification + SSE push + (preference-on) email; preference-off skips email. Covers AC-02.
- [ ] **Application tests:** `tests/notifications/application/test_on_deposit_detected.py`, `test_on_faucet_completed.py`, `test_on_transaction_failed.py` — same pattern.
- [ ] **Application tests:** `tests/notifications/application/test_list_mark_read_preferences.py` — REST endpoints' use cases, ownership enforcement.
- [ ] **Adapter tests:** `tests/notifications/infra/test_resend_email_adapter.py` — uses `respx` to mock httpx; happy path, 4xx-suppressed, 5xx-retried-then-suppressed. Covers AC-09. Template rendering tested.
- [ ] **Adapter tests:** `tests/notifications/infra/test_redis_sse_publisher.py` — Redis testcontainer; pub/sub round-trip, replay queue, TTL. Covers AC-06.
- [ ] **Adapter tests:** `tests/notifications/infra/test_sqlalchemy_notifications_repo.py` — testcontainer Postgres; INSERT, list with pagination, mark_read.
- [ ] **Contract tests:** `tests/api/test_notifications_endpoints.py` — REST endpoints, ownership enforcement. Covers AC-07, AC-08.
- [ ] **Contract tests:** `tests/api/test_sse_endpoint.py` — uses `httpx.AsyncClient` with streaming response; opens connection, asserts initial `event: connected`, publishes a test event via Redis, asserts received within 200ms, asserts heartbeat, asserts disconnect on auth expiry. Covers AC-04, AC-05, AC-12. **This is the trickiest test in Phase 2** — see Implementation Notes.
- [ ] **E2E:** indirect via `phase2-web-007` (toast-on-confirmation Playwright spec).

---

## Done Definition

- [ ] All ACs verified by named test cases.
- [ ] All test categories above implemented and passing locally.
- [ ] `import-linter` contracts pass.
- [ ] `mypy --strict` passes.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass.
- [ ] OpenAPI schema diff: 4-5 new endpoints documented.
- [ ] No new domain events (subscribes only).
- [ ] Three new ports declared (`NotificationRepository`, `SSEPublisher`; `EmailSender` is reused from Phase 1).
- [ ] Single PR. Conventional commit: `feat(notifications): SSE channel + Resend adapter + notification entity [phase2-notifications-001]`.
- [ ] PR description: a sequence diagram showing event publish → handler → SSE delivery to browser.

---

## Implementation Notes

- The SSE endpoint uses FastAPI's `StreamingResponse` with `media_type='text/event-stream'`. The async generator yields formatted SSE strings. On client disconnect, `request.is_disconnected()` returns True (poll on each iteration).
- For Redis pub/sub, use `redis.asyncio.Redis.pubsub()`. Each SSE connection gets its own pubsub instance. Subscribe to `notifications:user:<user_id>`. The handler receives messages, formats as SSE, writes.
- The "last 50 events for replay" is implemented as a Redis sorted set (score=event_timestamp_ms, value=event_json) with `ZADD` + `ZREMRANGEBYRANK -1 -51` after each add. TTL 5min on the key.
- For SSE testing, the FastAPI TestClient doesn't support streaming. Use `httpx.AsyncClient(transport=ASGITransport(app=app))` with `response = await client.stream('GET', ...)` and iterate over `response.aiter_lines()`. Document the test pattern.
- The Resend API is straightforward — single endpoint, JSON request/response. Don't bring in their SDK; httpx + raw JSON is cleaner.
- Email templates use Jinja2 (already a Python dep via FastAPI's stack). Keep them simple HTML with inline styles (email clients hate stylesheets). Test rendering in unit tests with sample vars.

---

## Risk / Friction

- The SSE test (AC-04 contract test) is the trickiest piece of test infrastructure in Phase 2. Spend time getting it right; it'll prevent flaky failures later. Use `asyncio.wait_for` with a generous timeout (5s) on each assertion.
- Resend's free tier (100 emails/day) is fine for portfolio scope. If the operator's daily allotment runs out, magic-link emails fail — users can't log in. Consider a fallback to ConsoleEmailSender on Resend 5xx (logs the magic link to backend logs, operator can extract manually). Document.
- Multi-instance SSE correctness depends on Redis pub/sub. With one Fly app instance (the default for Phase 2 portfolio), single-instance SSE works without Redis pub/sub. The Redis layer is for future scale. Document that Phase 2 uses Redis pub/sub even at instance=1 to keep the code path consistent.
- The 3-tab SSE limit (AC-12) is a usability tradeoff. Most users have one tab; power users may have multiple devices. Tune if reviewers complain.
- The SSE channel sends ALL of a user's events including faucet, deposits, etc. If the user has notification preferences off for some, the SSE still fires (preferences gate emails, not SSE). Frontend may render or suppress based on preferences. Document this behavior.
