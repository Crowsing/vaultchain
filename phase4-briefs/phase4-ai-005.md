---
ac_count: 14
blocks:
- phase4-ai-006
- phase4-ai-007
- phase4-evals-001
- phase4-web-008
complexity: L
context: ai
depends_on:
- phase4-ai-001
- phase4-ai-002
- phase4-ai-003
- phase2-transactions-002
- phase3-transactions-003
- phase1-identity-003
- phase1-shared-006
estimated_hours: 4
id: phase4-ai-005
phase: 4
sdd_mode: strict
state: ready
title: '`prepare_send_transaction` tool + `PreparedAction` aggregate + ADR-011'
touches_adrs:
- ADR-011
---

# Brief: phase4-ai-005 — `prepare_send_transaction` tool + `PreparedAction` aggregate + ADR-011


## Context

This brief realises invariant #1 from `architecture-decisions.md`: **"Never execute, only prepare. AI prepares `UnsignedTx`; only Policy converts to `ApprovedTx`; only Executor signs and broadcasts. AI cannot import custody/KMS modules."**

The persistent record of "AI has prepared something, awaiting user TOTP" is the `PreparedAction` aggregate. It exists for two reasons. First, the user confirms by TOTP — and TOTP confirmation needs *something* to point at on the server (an ID the frontend can submit alongside the TOTP code); the LLM cannot hold mutable server state, so a row in our DB is the only place that ID can live. Second, the architecture explicitly states "AI never sees `Transaction` — it sees `PreparedAction`" (line 163). A separate aggregate, with a separate state machine, with a separate table, is the architectural enforcement of that boundary. If a future bug accidentally let `ai.*` modules import `transactions.application.use_cases`, the import-linter contract from `phase4-ai-001` AC-02 catches that drift; the aggregate split makes the design intent explicit at the model layer.

The flow:

1. The LLM invokes `prepare_send_transaction(chain, asset, amount_human, to_address)` via the tool catalog from `phase4-ai-003`. The executor from `phase4-ai-004` validates input + dispatches.
2. The tool calls the existing `transactions.application.use_cases.PrepareSendTransaction` (from `phase2-transactions-002`) for the heavy lifting — chain-aware address validation, asset precision conversion, fee estimation via `ChainGateway`, USD valuation via `PricingPort`, and threshold-policy evaluation via `phase3-transactions-003`'s real `ChainAwareThresholdPolicy`. **Crucially, that use case persists nothing** (per `architecture-decisions.md` §"`/transactions/prepare` semantics"). The AI tool wraps it: takes its result, persists a `PreparedAction` row, returns the prepared_action_id + a human-readable summary to the LLM.
3. The LLM weaves the summary into its assistant message ("I prepared a send of 0.1 ETH to 0x1234… with fee ≈ $5.40. Confirm with your TOTP when ready.") The frontend receives a mid-stream `prepared_action` SSE event (specified in `phase4-ai-006`) carrying `prepared_action_id`, expiry timestamp, and the structured preview, and renders a confirmation card next to the assistant's text.
4. The user enters their TOTP into the card. The frontend POSTs `/api/v1/ai/prepared-actions/{id}/confirm` with `{totp_code, idempotency_key}`. The endpoint:
   1. Authorises (user owns the prepared action).
   2. Asserts `status == 'pending'` (404/409 otherwise — a stale card or a re-confirmation attempt).
   3. Verifies TOTP via `IdentityTotpVerifier` port. On failure: 403, prepared_action stays pending — user can retry within expiry.
   4. **Materialises a `Transaction` aggregate at `awaiting_totp`** from `prepared_action.payload`, then immediately calls the shared `Transaction.confirm_with_totp()` domain method (the same one used by `phase2-transactions-002`'s `ConfirmDraft` flow). This re-runs the threshold policy fresh — between prepare (T) and confirm (T+30s) the user's daily-spend window or KYC tier may have changed, so the binding decision is at confirm time, not prepare time.
   5. Transition: `awaiting_totp → broadcasting` (policy says pass) or `awaiting_totp → awaiting_admin` (policy says route_to_admin). Events published per the existing Phase 2 / Phase 3 contract.
   6. Marks `PreparedAction.status = 'confirmed'`, sets `confirmed_transaction_id`. Single UoW with the Transaction creation.
   7. Returns `{transaction_id, status, route: 'broadcasting' | 'awaiting_admin'}`.
5. **Supersession:** if the user changes their mind mid-conversation and asks for a different send, the new `prepare_send_transaction` tool call creates a new `PreparedAction` AND marks any prior pending action of the same `kind='send_transaction'` in the same conversation as `superseded`, with `superseded_by_id` pointing to the new one. The frontend's chat panel discards stale cards (the SSE protocol in `phase4-ai-006` will emit a corresponding `prepared_action_superseded` event). User can only confirm the latest.
6. **Expiry:** `expires_at = created_at + 5 minutes` (configurable). A small background sweeper job (registered in this brief) periodically (every 60s) marks `pending` actions whose `expires_at < NOW()` as `expired`. Expired actions cannot be confirmed; the confirm endpoint returns 409 `ai.prepared_action_expired`.

The state machine: `pending → confirmed | expired | superseded`. All three terminal states are sinks. Property test (AC-13) fuzzes random sequences of `(create, supersede, expire-sweep, confirm-attempt)` events and asserts no orphan states, confirmed-implies-transaction-id, expired/superseded-cannot-confirm.

---

## Architecture pointers

- `architecture-decisions.md` §"Non-negotiable invariants" #1 (the "prepare not execute" rule), §"Bounded contexts" (AI/Tools ──prepare──► Transactions returns PreparedAction), §"AI streaming via SSE" (`prepared_action` event mid-stream — emitted by `phase4-ai-006`, payload shaped here), §"`/transactions/prepare` semantics" (prepare doesn't persist; this brief adds the persistence layer SPECIFIC to the AI flow), §"Custody invariant enforcement" (the import-linter contract from `phase4-ai-001` AC-02).
- **Layer:** application (use cases + sweeper job) + domain (aggregate + state machine + VOs) + infra (repo + migration + composition) + delivery (one new endpoint).
- **Packages touched:**
  - `ai/shared/domain/prepared_action.py` (aggregate root — lives in `ai/shared/` because both `ai/tools/` (creates it) and the confirm endpoint (`ai/delivery/` or `ai/application/`) consume it)
  - `ai/shared/domain/value_objects/prepared_action_status.py` (enum)
  - `ai/shared/domain/value_objects/prepared_action_kind.py` (enum: `send_transaction` for V1; `swap`, `approve_token` deferred to V2)
  - `ai/shared/domain/value_objects/send_payload.py` (frozen dataclass: `chain, asset, to_address, amount_chain_units, unsigned_tx_json, fee_estimate_chain_units, value_usd_at_creation, policy_decision_at_prepare, policy_decision_reason_at_prepare`)
  - `ai/shared/domain/ports.py` (`PreparedActionRepository`)
  - `ai/shared/domain/errors.py` (`PreparedActionNotFound`, `PreparedActionExpired`, `PreparedActionSuperseded`, `PreparedActionAlreadyConfirmed`)
  - `ai/tools/infra/tools/prepare_send_transaction.py` (the `PrepareSendTransactionTool` — bound to executor via `phase4-ai-003`'s `extra_tools` extension point)
  - `ai/application/use_cases/confirm_prepared_action.py` (the confirmation use case; lives at `ai/application/` because it crosses sub-domains — uses `prepared_action` from `shared/`, calls into `transactions.application` and `identity.application`)
  - `ai/application/jobs/expire_prepared_actions.py` (arq sweeper, runs every 60s)
  - `ai/delivery/prepared_actions_router.py` (`POST /api/v1/ai/prepared-actions/{id}/confirm`)
  - `ai/shared/infra/sqlalchemy_prepared_action_repo.py`
  - `ai/shared/infra/migrations/004_prepared_actions.py` (Alembic; revision after `003_tool_calls`)
- **Reads:** `transactions.application.queries` (for verifying `confirmed_transaction_id` integrity in tests), `identity.application.use_cases.verify_totp` via port (for confirm flow).
- **Writes:** `ai.prepared_actions` (INSERT on create, UPDATE for status transitions including supersession), `transactions.transactions` (via `transactions.application.use_cases.MaterializeTransactionFromPreparedAction` — this is a NEW Phase 4 use case in the Transactions context; see Implementation Notes for the cross-context responsibility split).
- **Publishes events:**
  - `ai.PreparedActionCreated{prepared_action_id, conversation_id, user_id, kind, expires_at}` — V1 subscriber: `phase4-ai-006` SSE handler emits the mid-stream event (it subscribes via the in-memory event bus pattern from `phase1-shared-004`, not the cross-process outbox, because the event must reach the same SSE connection that triggered it).
  - `ai.PreparedActionSuperseded{prepared_action_id, superseded_by_id, conversation_id, user_id}` — same in-memory subscriber pattern.
  - `ai.PreparedActionExpired{prepared_action_id, user_id, expired_at}` — outbox-published; no V1 subscriber. Notifications could subscribe in V2.
  - `ai.PreparedActionConfirmed{prepared_action_id, transaction_id, user_id}` — outbox-published; no V1 subscriber.
- **Subscribes to events:** none (the sweeper is a scheduled job, not event-driven).
- **New ports introduced:** `PreparedActionRepository` (in `ai/shared/domain/ports.py`).
- **New adapters introduced:** `SqlAlchemyPreparedActionRepository`. Plus `FakePreparedActionRepository` in `tests/ai/fakes/`.
- **DB migrations required:** yes — `004_prepared_actions`.
- **OpenAPI surface change:** yes — one new endpoint `POST /api/v1/ai/prepared-actions/{id}/confirm`.

---

## Acceptance Criteria

- **AC-phase4-ai-005-01:** Given migration `004_prepared_actions`, when applied, then table `ai.prepared_actions(id UUID PK, user_id UUID NOT NULL REFERENCES identity.users(id), conversation_id UUID NOT NULL REFERENCES ai.conversations(id) ON DELETE RESTRICT, tool_call_id UUID NOT NULL REFERENCES ai.tool_calls(id) ON DELETE RESTRICT, kind TEXT NOT NULL CHECK (kind IN ('send_transaction')), payload JSONB NOT NULL, status TEXT NOT NULL CHECK (status IN ('pending','confirmed','expired','superseded')) DEFAULT 'pending', expires_at TIMESTAMPTZ NOT NULL, confirmed_transaction_id UUID NULL REFERENCES transactions.transactions(id), superseded_by_id UUID NULL REFERENCES ai.prepared_actions(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())` exists with three partial indexes: `idx_pa_pending_expiry ON (expires_at) WHERE status = 'pending'` (sweeper), `idx_pa_user_status ON (user_id, status, created_at DESC)` (list queries), `idx_pa_conv_kind_pending ON (conversation_id, kind) WHERE status = 'pending'` (supersession lookup). Migration is idempotent.

- **AC-phase4-ai-005-02:** Given the `PreparedAction` aggregate in `ai/shared/domain/prepared_action.py`, when constructed via `PreparedAction.create(user_id, conversation_id, tool_call_id, kind, payload, expires_at)`, then it returns a state-bearing dataclass with `id`, the constructor args, `status='pending'`, `confirmed_transaction_id=None`, `superseded_by_id=None`, `created_at` and `updated_at` set to now. A pending `ai.PreparedActionCreated` event is collected. **State transitions are domain methods** with strict guards: `confirm(transaction_id)` requires `status == 'pending'` else raises (`PreparedActionExpired` / `PreparedActionSuperseded` / `PreparedActionAlreadyConfirmed` based on current state); `expire()` requires `status == 'pending'` else is a silent no-op (sweeper safety — multiple sweeps are fine); `supersede(by_id)` requires `status == 'pending'` else raises `InvalidStateTransition`. Each transition collects the corresponding event and updates `updated_at`.

- **AC-phase4-ai-005-03:** Given the `SendPayload` value object, when constructed, then it freezes: `chain: ChainName`, `asset: AssetName`, `to_address: ChainAddress` (validated VO from `phase3-chains-*`), `amount_chain_units: Decimal` (whole integer in chain native units, NUMERIC(78,0)-shaped), `unsigned_tx_json: dict` (chain-specific blob), `fee_estimate_chain_units: Decimal`, `value_usd_at_creation: Decimal` (from `phase3-transactions-003` AC-14), `policy_decision_at_prepare: Literal['pass', 'route_to_admin']`, `policy_decision_reason_at_prepare: str | None`. Serialisation: `to_dict()` produces a JSONB-ready shape (Decimals → strings, addresses → string repr); `from_dict()` round-trips. **Property test** (`tests/ai/shared/domain/test_send_payload_properties.py`): for any randomly generated `SendPayload`, `from_dict(to_dict(p)) == p`.

- **AC-phase4-ai-005-04:** Given the `PrepareSendTransactionTool` in `ai/tools/infra/tools/prepare_send_transaction.py`, when constructed with `prepare_use_case: PrepareSendTransaction` (Phase 2 use case), `prepared_action_repo: PreparedActionRepository`, `clock`, then: (1) `name == "prepare_send_transaction"`; (2) `description == "Prepare a token send. Validates the destination address, estimates the fee, computes USD value, and creates a prepared action that the user confirms with TOTP. Returns a prepared_action_id, a human summary, and the policy decision (pass or route_to_admin). Use this when the user asks to send, transfer, withdraw, or move funds to an address."`; (3) `input_schema` requires `{chain: enum[ethereum,tron,solana], asset: enum[ETH,USDC,TRX,USDT,SOL,USDC-SPL], amount_human: string (decimal pattern), to_address: string (length 1..256)}` with `additionalProperties: False`.

- **AC-phase4-ai-005-05:** Given `PrepareSendTransactionTool.execute({chain, asset, amount_human, to_address}, user_id=u)`, when the happy path runs, then within a single UoW: (1) constructs `ChainAddress.parse(to_address, chain)` — raises `AddressInvalid` → `ToolResult.failure({code: 'address_invalid', message: 'The address is not a valid <chain> address.'})`; (2) parses `amount_human` to Decimal then converts to `amount_chain_units` via the asset catalog precision (from `phase3-wallet-002`) — invalid format → `amount_invalid`, below minimum → `amount_below_minimum`; (3) calls `PrepareSendTransaction.execute(user_id=u, chain, asset, amount_chain_units, to_address)` — returns `PreparedTxResult{unsigned_tx_json, fee_estimate_chain_units, value_usd_at_creation, policy_decision, policy_decision_reason}`; (4) supersedes any prior pending `PreparedAction` with same `(conversation_id, kind='send_transaction')` — single SQL `UPDATE ai.prepared_actions SET status='superseded', superseded_by_id = $newid, updated_at = NOW() WHERE conversation_id = $1 AND kind = 'send_transaction' AND status = 'pending'`; for each row affected, the repo loads it, calls `supersede(new_id)` to collect the event, persists; (5) constructs `PreparedAction.create(...)` with `expires_at = clock.now() + 5min`, persists; (6) returns `ToolResult.ok({prepared_action_id, summary: "<human readable: 'Send 0.1 ETH to 0x12...34 — fee ≈ 0.002 ETH ($5.40). Tap to confirm.'>", chain, asset, amount_human, value_usd, fee_usd, policy_decision, policy_decision_reason, expires_at: ISO-8601, requires_admin: bool})`. The `requires_admin` field equals `policy_decision == 'route_to_admin'` and is hoisted to a top-level field for LLM prominence.

- **AC-phase4-ai-005-06:** Given the conversation_id needs to be threaded into the tool, when `phase4-ai-004`'s executor invokes `tool.execute(input, user_id=user_id)`, then the tool needs `conversation_id` AND `tool_call_id` for the `PreparedAction` construction. **Resolution:** the executor in `phase4-ai-004` is extended (one-line change documented in this brief's PR) to also pass `*, conversation_id: UUID, tool_call_id: UUID` as kwargs to `tool.execute`. Read-only tools (`get_balances`, etc.) ignore them; the prepare tool consumes them. The `Tool` Protocol signature gains those kwargs as optional with default `None`; tools that need them assert non-`None` at execute entry (`assert conversation_id is not None`).

- **AC-phase4-ai-005-07:** Given the `ConfirmPreparedAction` use case in `ai/application/use_cases/confirm_prepared_action.py`, when invoked with `(prepared_action_id, totp_code, idempotency_key, *, requesting_user_id)`, then within a single UoW: (1) loads PA, asserts `pa.user_id == requesting_user_id` else raises `PreparedActionNotFound`; (2) asserts `pa.status == 'pending'` — on `expired` raises `PreparedActionExpired`, on `superseded` raises `PreparedActionSuperseded`, on `confirmed` raises `PreparedActionAlreadyConfirmed`; (3) calls `IdentityTotpVerifier.verify(user_id, totp_code)` via port — on False raises `TotpInvalid` (existing error from `phase1-identity-003`); (4) calls `transactions.application.use_cases.MaterializeTransactionFromPreparedAction(payload=pa.payload, user_id=requesting_user_id, idempotency_key=idempotency_key)` — this NEW Phase 4 use case in the Transactions context constructs a `Transaction` at `awaiting_totp`, runs `transaction.confirm_with_totp()` (re-running threshold policy fresh), persists, publishes the standard Phase 2/3 events; returns the transaction id and final status (`broadcasting` or `awaiting_admin`); (5) calls `pa.confirm(transaction_id)`, persists; (6) commits all collected events via outbox; (7) returns `{transaction_id, status, route: 'broadcasting' | 'awaiting_admin'}`. The shared-006 idempotency middleware caches the response by `idempotency_key` — repeating the same key returns the cached response (verified by AC-12).

- **AC-phase4-ai-005-08:** Given the new endpoint `POST /api/v1/ai/prepared-actions/{id}/confirm` with body `{totp_code: string, idempotency_key: UUIDv4}`, when called with valid auth (cookie session per `phase1-identity-004`), then: (1) idempotency middleware (`phase1-shared-006`) intercepts duplicate keys — replay returns cached response; (2) calls `ConfirmPreparedAction`; (3) maps errors per the architecture's error envelope: `PreparedActionNotFound` → 404 `ai.prepared_action_not_found`; `PreparedActionExpired` → 409 `ai.prepared_action_expired`; `PreparedActionSuperseded` → 409 `ai.prepared_action_superseded`; `PreparedActionAlreadyConfirmed` → 409 `ai.prepared_action_already_confirmed`; `TotpInvalid` → 403 `identity.totp_invalid`; (4) on success returns `202 Accepted` with `{transaction_id, status, route}`. OpenAPI example committed.

- **AC-phase4-ai-005-09:** Given the `expire_prepared_actions` arq job in `ai/application/jobs/expire_prepared_actions.py`, when scheduled (every 60 seconds via the cron registry from `phase1-shared-004`), then it: (1) runs a single SQL `SELECT id FROM ai.prepared_actions WHERE status = 'pending' AND expires_at < NOW() ORDER BY expires_at ASC LIMIT 500` (bounded batch); (2) for each id, loads the PA, calls `pa.expire()`, persists, commits events via outbox; (3) logs `{batch_size, oldest_age_seconds}` metric to structlog; (4) idempotent by construction — re-running on already-expired rows is a domain no-op (AC-02 silent-no-op semantics). Cron registered with `EXPIRE_PREPARED_ACTIONS_ENABLED=true` by default; `false` for local dev to avoid noisy log lines.

- **AC-phase4-ai-005-10:** Given a prepared action whose `expires_at < NOW()` is being concurrently confirmed and swept, when both run, then: (1) the sweeper takes a row-level lock via `SELECT ... FOR UPDATE SKIP LOCKED` per row; (2) the confirm path uses `SELECT ... FOR UPDATE` on the row before the status check; (3) whichever runs first wins — confirm-wins case: status becomes `confirmed`, sweeper SKIP LOCKED moves on; sweeper-wins case: status becomes `expired`, the confirm flow's status check raises `PreparedActionExpired`. No double-state, no lost update. Verified by adapter test running both concurrently with deterministic delays.

- **AC-phase4-ai-005-11:** Given the architecture import-linter contract "AI never imports Custody" from `phase4-ai-001` AC-02, when this brief introduces `ai/application/use_cases/confirm_prepared_action.py` which calls into `transactions.application.use_cases.MaterializeTransactionFromPreparedAction`, then the contract still passes — the call goes through `transactions.application.*`, never `custody.*`. A test confirms `lint-imports` passes for this brief's package layout. The `MaterializeTransactionFromPreparedAction` use case in Transactions, in turn, imports `custody.application.gateways` (the existing port from Phase 2) — that's allowed because Transactions is permitted to depend on Custody. The architecture is preserved: AI talks to Transactions; Transactions talks to Custody; AI never directly talks to Custody.

- **AC-phase4-ai-005-12:** Given the idempotency contract on the confirm endpoint, when the same `(prepared_action_id, idempotency_key)` is submitted twice in quick succession (the user's frontend retries due to a network blip), then: first call succeeds (200) with response cached by middleware; second call returns the same response from cache, **without** re-invoking the use case (verified by mock-counter on `MaterializeTransactionFromPreparedAction` in the test). If the user submits a SECOND confirm with a DIFFERENT idempotency_key against the same already-confirmed prepared_action, the use case path runs and returns 409 `ai.prepared_action_already_confirmed`. The combination of middleware-cache (handles network retries) + domain-status-check (handles deliberate replays) covers both attacks.

- **AC-phase4-ai-005-13:** Given the property test on **PreparedAction state machine no-orphan-states** (`tests/ai/shared/domain/test_prepared_action_state_machine_properties.py::test_no_orphan_states`), when fuzzed via Hypothesis over random sequences of events `[create, supersede, expire, confirm_attempt(totp_valid|totp_invalid)]` of varying lengths, then: (a) the final `status` is always one of `{pending, confirmed, expired, superseded}` (no other values possible); (b) `status == 'confirmed'` ⇒ `confirmed_transaction_id IS NOT NULL`; (c) `status == 'superseded'` ⇒ `superseded_by_id IS NOT NULL`; (d) once non-pending, no event mutates state again (terminal-sink invariant). **New mandatory property test for Phase 4** (alongside `phase4-ai-002` AC-12 authorization and `phase4-ai-004` AC-12 truncation).

- **AC-phase4-ai-005-14:** Given **ADR-011 — Prepare-not-execute boundary (PreparedAction aggregate)**, when committed, then `docs/decisions/ADR-011-prepared-action-boundary.md` exists with: **Context** (invariant #1 from architecture-decisions; the architectural need for AI to "have something to point at" during the TOTP-confirmation gap; the choice between extending Drafts vs introducing a third aggregate); **Decision** (PreparedAction is a separate aggregate from `Transaction` and `Draft`; lives in `ai/shared/domain`; has a four-state machine `pending→{confirmed,expired,superseded}` with terminal sinks; `confirmed` carries `confirmed_transaction_id` for forward link; supersession on conversation+kind enforces "one live prep card per chat"; expiry default 5 min — between TOTP rotation timing and "user wandered off"; the confirm endpoint runs threshold policy FRESH at confirm time, not relying on the prepare-time decision, because user state may have changed between prepare and confirm); **Consequences** — *acceptable*: aggregate split makes the architectural invariant explicit at the model layer (defence-in-depth alongside the import-linter contract); two materialisation paths (`ConfirmDraft` from Phase 2's wizard, `ConfirmPreparedAction` from this brief's AI flow) both call the shared `Transaction.confirm_with_totp` domain method — minimal code duplication; *concerning*: the supersession cascade is one extra UPDATE per prepare call — bounded (only pending rows in same conversation are touched), measured (the property test exercises this); *trade-off vs allowing many pending actions*: chosen supersession because the prep-card UI in `phase4-web-008` shows the latest one and stale cards confuse users; the `superseded_by_id` chain preserves auditability of "user changed mind 3 times before sending"; *trade-off* on expiry duration: 5 min, configurable via `PREPARED_ACTION_TTL_SECONDS`, documented as small enough to bound stale state and large enough for human reading-then-confirming time; *explicit non-decision*: per-tool retry policy at the executor level — deferred to V2, intentionally. The ADR explicitly addresses: "why not let `prepare_send_transaction` directly create a Draft?" → "Drafts have mutable shape and a different lifecycle (wizard-style, multi-step). PreparedAction is purpose-built: validated, frozen-payload, auto-expiring, with a clear terminal status. Conflating them would muddy both."; "why not skip the entire boundary and have AI directly call `ConfirmDraft` after asking for TOTP?" → "AI cannot prompt for TOTP — that's a security UI flow that lives in the frontend modal triggered by the prep card. The boundary makes the chain `LLM → tool → PA persisted → SSE event → UI prep card → TOTP modal → confirm endpoint → Transaction → Custody` visible and testable at each segment." Reviewer's first-30-second read should land on "this person understands defence-in-depth for AI-touching custodial systems."

---

## Out of Scope

- Other prepared-action kinds (`swap`, `approve_token`, etc.): V2 — the `kind` enum is extensible.
- Per-user / per-conversation rate limit on `prepare_send_transaction` calls: V2; covered indirectly by the architecture's 20-msg/hour AI chat cap.
- Auto-cancel a confirmed-but-failed transaction's PreparedAction: explicitly NOT done — `status='confirmed'` is a sink even if the downstream Transaction later fails. Auditability over consistency.
- A user-facing list of their prepared actions ("show me all my pending prep cards"): V2; the chat UI handles V1's case (one live card per conversation).
- Reading prepared actions across conversations for memory: explicit non-goal — `phase4-ai-007` memory writer indexes confirmed transactions, not prepared actions.
- A "cancel pending action" endpoint: implicit — supersession by a new prepare or expiry handles this. An explicit `DELETE /api/v1/ai/prepared-actions/{id}` is V2.
- Encryption-at-rest of `payload` JSONB: covered by the architecture's V2 PII pin (the payload contains addresses + amounts, no secrets, no TOTP, no signed tx — relatively low-sensitivity).

---

## Dependencies

- **Code dependencies:** `phase4-ai-001`, `phase4-ai-002`, `phase4-ai-003`, `phase4-ai-004` (Phase 4 lineage); `phase2-transactions-002` (`PrepareSendTransaction` use case + the existing `Transaction.confirm_with_totp` domain method); `phase3-transactions-003` (real ChainAwareThresholdPolicy that runs at prepare AND confirm); `phase3-wallet-002` (asset catalog for precision); `phase1-identity-003` (TOTP verifier port); `phase1-shared-003` (UoW + outbox); `phase1-shared-004` (arq cron registry for sweeper); `phase1-shared-006` (idempotency middleware on confirm endpoint).
- **Data dependencies:** migrations `001_ai_schema`, `002_chat_tables`, `003_tool_calls` applied. `transactions.transactions` table exists from Phase 2 (the `confirmed_transaction_id` FK target).
- **External dependencies:** none new beyond Phase 4 base.

---

## Test Coverage Required

- [ ] **Domain unit tests:** `tests/ai/shared/domain/test_prepared_action.py` — `create`, `confirm` (valid + each invalid prior state), `expire` (valid + idempotent no-op), `supersede` (valid + invalid), all events collected. Covers AC-02.
- [ ] **Domain unit tests:** `tests/ai/shared/domain/test_send_payload.py` — happy construction, invalid types raise. Covers AC-03.
- [ ] **Property tests:** `tests/ai/shared/domain/test_send_payload_properties.py` — round-trip. Covers AC-03 round-trip clause.
- [ ] **Property tests:** `tests/ai/shared/domain/test_prepared_action_state_machine_properties.py` — covers AC-13 (mandatory).
- [ ] **Application tests:** `tests/ai/tools/infra/tools/test_prepare_send_transaction_tool.py` — happy path (pass policy), happy path (route_to_admin), address invalid, amount invalid, amount below minimum, supersession of prior pending. Covers AC-04, AC-05.
- [ ] **Application tests:** `tests/ai/tools/application/test_executor_passes_conversation_id.py` — verifies executor extension from AC-06 (regression test on the executor signature change).
- [ ] **Application tests:** `tests/ai/application/test_confirm_prepared_action.py` — happy path → broadcasting; happy path → awaiting_admin (policy routes); TOTP invalid (PA stays pending); not found (wrong user); already confirmed; expired; superseded; idempotency replay (cached response). Covers AC-07, AC-12.
- [ ] **Contract tests:** `tests/api/test_ai_prepared_actions_routes.py` — happy 202; 403 on TOTP invalid; 404 on cross-user; 409 on each terminal state; OpenAPI example matches response. Covers AC-08.
- [ ] **Application tests:** `tests/ai/application/test_expire_prepared_actions_job.py` — sweeper marks expired rows, idempotency on re-run, batch-size cap. Covers AC-09.
- [ ] **Concurrency tests (testcontainers):** `tests/ai/application/test_confirm_vs_sweep_concurrent.py` — confirm + sweep race, both orderings, no double-state. Covers AC-10.
- [ ] **Architecture tests:** `tests/architecture/test_ai_005_imports.py` — verifies `lint-imports` passes; verifies `ai/application/use_cases/confirm_prepared_action.py` does not directly import `vaultchain.custody.*`. Covers AC-11.
- [ ] **Adapter tests (testcontainers):** `tests/ai/shared/infra/test_sqlalchemy_prepared_action_repo.py` — JSONB round-trip, partial index usage on the three indexes via EXPLAIN, FK integrity. Covers AC-01.
- [ ] **Migration tests:** `tests/ai/shared/infra/test_migration_004_prepared_actions.py` — apply + rollback, idempotency. Covers AC-01.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] `import-linter` contracts pass — including the new sub-check from AC-11 (no `ai.* → custody.*` imports).
- [ ] `mypy --strict` passes for `vaultchain.ai.*` and the touched modules in `vaultchain.transactions.application.use_cases.materialize_transaction_from_prepared_action`.
- [ ] `ruff check` and `ruff format` clean.
- [ ] Per-directory coverage gates pass (`ai/shared/domain/` ≥ 95%, `ai/application/` ≥ 90%, `ai/tools/infra/tools/` ≥ 90%).
- [ ] OpenAPI schema diff reviewed: one new endpoint `POST /api/v1/ai/prepared-actions/{id}/confirm` with full example.
- [ ] Four new error codes (`ai.prepared_action_not_found`, `ai.prepared_action_expired`, `ai.prepared_action_superseded`, `ai.prepared_action_already_confirmed`) registered + visible in `errors-reference.md`.
- [ ] One new port (`PreparedActionRepository`) declared with fake.
- [ ] One new Alembic revision (`004_prepared_actions`) committed + applied + rolled-back tested.
- [ ] Four new domain events registered (`ai.PreparedActionCreated`, `ai.PreparedActionSuperseded`, `ai.PreparedActionExpired`, `ai.PreparedActionConfirmed`).
- [ ] One new tool (`prepare_send_transaction`) wired into `ToolCatalog` via `phase4-ai-003`'s `extra_tools` extension.
- [ ] One new arq cron job (`expire_prepared_actions`) registered.
- [ ] **ADR-011 drafted and committed.**
- [ ] `docs/runbook.md` updated with: how to disable the sweeper in emergencies (`EXPIRE_PREPARED_ACTIONS_ENABLED=false`), how the confirm flow integrates with the existing TOTP path, the 5-minute TTL default and how to override (`PREPARED_ACTION_TTL_SECONDS`).
- [ ] Single PR. Conventional commit: `feat(ai): prepare_send_transaction tool + PreparedAction aggregate + ADR-011 [phase4-ai-005]`.
- [ ] PR description: a sequence diagram of the full flow (LLM → tool → executor → tool → PrepareSendTransaction → repo persist → ToolResult → SSE event → frontend prep card → user TOTP → confirm endpoint → MaterializeTransactionFromPreparedAction → Transaction.confirm_with_totp → policy → broadcasting/awaiting_admin → PA marked confirmed) plus a state diagram of the four PreparedAction states.

---

## Implementation Notes

- **Cross-context responsibility split.** The `MaterializeTransactionFromPreparedAction` use case lives in `transactions.application.use_cases/`, NOT in `ai.*`. Reason: it constructs a `Transaction` aggregate — that constructor is internal to the Transactions context. AI calls into it via the standard cross-context import pattern (Pragmatic reads + explicit application-use-case import for writes is the pattern Phase 3 uses for `phase3-transactions-003` ↔ `phase3-kyc-003`). The use case takes a `payload` dict (from `pa.payload.to_dict()`) and an `idempotency_key`, and internally calls `Transaction.confirm_with_totp` — the same domain method the Phase 2 `ConfirmDraft` flow uses. Code duplication is minimal: differences are pre-confirmation (Draft → Transaction vs. PreparedAction → Transaction), shared logic is post-confirmation (the state-machine method on the aggregate).
- **Why threshold policy at confirm, not just prepare.** Policy at prepare gives the LLM and user a heads-up. Policy at confirm is binding. The two could disagree if `daily_so_far_usd` changed between prepare (T) and confirm (T+30s) — e.g., the user just confirmed another withdrawal in another session, pushing them over the daily cap. Re-running ensures the binding decision reflects current state. This is documented in ADR-011 as a deliberate property.
- **Supersession SQL.** The supersession step is a single UPDATE bounded by the partial index `idx_pa_conv_kind_pending`. With one pending action per conversation+kind under normal flow, the update touches ~1 row. The repo wraps this: `SELECT ... FOR UPDATE` on candidate rows, then `pa.supersede(new_id)` per loaded row, then INSERT new row, all in one UoW. Don't shortcut by raw `UPDATE ... WHERE` — the domain events would be missed.
- **Expiry sweeper is opportunistic.** The `idx_pa_pending_expiry` partial index makes the candidate scan cheap. The 60-second cron is generous; expired rows can sit for up to 60s before being marked. The confirm endpoint's status check (AC-07 step 2) catches "expired but not yet swept" via the `expires_at < NOW()` condition — actually no, the domain check is purely `status == 'pending'`. Add a domain check: `if pa.status == 'pending' and pa.expires_at < clock.now(): raise PreparedActionExpired`. This makes confirmation safe even if sweeper is paused.
- **The `requires_admin` field in the tool's success response** is the LLM's hint to compose user-facing language differently. ("This is large enough that it'll need admin approval after you confirm — typically 1–2 hours during business hours.") The Tier-3 evals from `phase4-evals-001` exercise this branch.
- **Frontend prep card lifecycle** (out of scope for this brief but worth noting): the card is rendered when the SSE handler from `phase4-ai-006` emits `prepared_action`. It auto-disappears on `prepared_action_superseded` for that id, on `prepared_action_expired`, and on successful confirmation. Frontend implementation in `phase4-web-008`.
- **Don't extend the `Tool` Protocol's signature.** Adding kwargs is fine for current execute, but if too many tools accumulate "I need conversation_id, message_id, tool_call_id, request_id..." we'll regret it. The current pattern (kwargs with defaults, tools that don't need them ignore) is clean. If V2 needs richer context, introduce a `ToolContext` value object then.

---

## Risk / Friction

- **The most-architecturally-sensitive brief in Phase 4.** A reviewer's first read should land on ADR-011's clarity and the import-linter regression test (AC-11). If those don't sing, the rest doesn't matter.
- **`Transaction.confirm_with_totp` is shared between two callers.** A future change to that method's contract risks breaking either the Wizard flow or the AI flow. Both call sites have AC tests; CI catches breaks. Document at the top of the domain method's docstring: "Called by ConfirmDraft (Wizard) and ConfirmPreparedAction (AI). Both expect the same threshold-policy semantics."
- **Race between confirm and sweep is real, narrow.** AC-10 guards it; the test runs with deterministic delays. Production-grade reliability comes from PG row locking; the architecture's "no fancy locking" stance applies *outside* of explicit safety-critical paths like this one. Document in runbook.
- **`payload` JSONB grows unbounded with chain-specific shapes.** A Solana unsigned tx with 10 instructions can be ~5KB. Across many users this is fine; flag if a future chain's unsigned tx approaches 50KB (would interact with the `phase4-ai-004` truncation rule). For V1's three chains, comfortably under 5KB.
- **The 5-minute TTL is judgement.** A reviewer might want shorter (security argument: stale prepared state) or longer (UX argument: user reading + thinking time). 5 min is the median of TOTP rotation × 10 (security boundary) and a typical chat-message-read-time × 5 (UX boundary). Documented as configurable; the value never appears in code, always reads from `PREPARED_ACTION_TTL_SECONDS`.
- **Cross-context responsibility for `MaterializeTransactionFromPreparedAction`.** A reviewer may ask "why does Transactions know about a PreparedAction?" The answer: it knows about a *payload* (a frozen dict with chain/asset/amount/etc.), NOT about the AI aggregate that owns it. The use case's input is `dict`, not `PreparedAction`. AI's confirm orchestrator does the unwrapping. Documented in the use case docstring.
- **The `kind` enum is single-valued in V1.** A reviewer might ask "why an enum?" Forward extensibility for V2 swap/approve flows. The CHECK constraint catches drift; the property test ensures only `send_transaction` is exercised in V1.
