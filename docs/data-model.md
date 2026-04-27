# Data Model

> Phase 1 brief phase1-shared-003 fills this with the full ERD per `docs/architecture-decisions.md` §3.

## Tables (planned)

- `users`, `sessions`, `email_tokens`, `webauthn_credentials`
- `kyc_applicants`, `kyc_documents`, `kyc_decisions`, `kyc_webhook_events`
- `wallets`, `wallet_keys`, `chain_addresses`
- `accounts`, `entries`, `postings`
- `transactions`, `transaction_events`, `prepared_actions`
- `contacts`, `contact_groups`
- `ai_threads`, `ai_messages`, `ai_memory_chunks`
- `notifications`, `notification_targets`
- `prices`, `price_quotes`
- `outbox`, `idempotency_keys`

See ADR-001 (data model boundaries) and ADR-006 (ledger invariants).
